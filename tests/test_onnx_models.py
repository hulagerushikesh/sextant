"""The ONNX path gives the same vectors and scores as the torch path.

The ONNX embedder keeps the store stamp `all-MiniLM-L6-v2`, so every store
built with torch opens under it. That is only honest if the two produce the
same vectors; these tests are where that claim is checked, model against
model, rather than assumed from the export's name.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest

from sextant import settings
from sextant.vector_db import embeddings, onnx_models
from sextant.vector_db.embeddings import EmbeddingsUnavailable
from sextant.vector_db.retrieval import RERANK_MODEL

LONG = " ".join(f"Paragraph {i} explains how the lamp wick is trimmed at dusk." for i in range(60))
TEXTS = [
    "The lighthouse keeper on duty in March is Priya Raman.",
    "Kalman filters estimate state from noisy measurements.",
    "Error code E-4012 means the boiler pressure is low.",
    LONG,
]
QUERY = "who keeps the lighthouse in March"


@pytest.fixture(scope="module")
def onnx_embedder():
    return onnx_models.OnnxEmbedder(embeddings.LOCAL_MODEL)


@pytest.fixture(scope="module")
def torch_embedder():
    pytest.importorskip("sentence_transformers")
    return embeddings.LocalEmbedder(embeddings.LOCAL_MODEL)


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


class TestTheEmbedderMatchesTorch:
    def test_the_vectors_are_the_same(self, onnx_embedder, torch_embedder):
        for text, a, b in zip(
            TEXTS, onnx_embedder.encode(TEXTS), torch_embedder.encode(TEXTS), strict=True
        ):
            assert _cosine(a, b) > 0.9999, f"vectors differ for {text[:40]!r}"

    def test_a_batch_does_not_change_a_vector(self, onnx_embedder):
        """Padding to the longest text in a batch must not leak into the mean."""
        alone = onnx_embedder.encode([TEXTS[0]])[0]
        batched = onnx_embedder.encode(TEXTS)[0]
        assert _cosine(alone, batched) > 0.99999

    def test_the_token_budget_and_counts_are_the_same(self, onnx_embedder, torch_embedder):
        assert onnx_embedder.max_tokens == torch_embedder.max_tokens == 256
        for text in TEXTS:
            assert onnx_embedder.count_tokens(text) == torch_embedder.count_tokens(text)
        assert onnx_embedder.count_tokens(LONG) > 256, "counting must not truncate"

    def test_vectors_are_unit_length(self, onnx_embedder):
        for vector in onnx_embedder.encode(TEXTS):
            assert abs(math.sqrt(sum(x * x for x in vector)) - 1) < 1e-5


class TestTheRerankerMatchesTorch:
    def test_the_scores_are_the_same(self):
        pytest.importorskip("sentence_transformers")
        import torch
        from sentence_transformers import CrossEncoder

        pairs = [(QUERY, text) for text in TEXTS]
        mine = onnx_models.OnnxReranker(RERANK_MODEL).predict(pairs)
        theirs = CrossEncoder(RERANK_MODEL, activation_fn=torch.nn.Sigmoid()).predict(pairs)
        for a, b in zip(mine, theirs, strict=True):
            assert abs(a - float(b)) < 1e-4
        assert mine[0] == max(mine), "the passage that answers should score highest"


class TestWhichEngineRuns:
    def test_the_default_models_run_on_onnx(self, monkeypatch):
        monkeypatch.delenv(onnx_models.ENGINE_ENV, raising=False)
        monkeypatch.delenv(embeddings.EMBEDDER_ENV, raising=False)
        assert isinstance(embeddings.get_embedder(), onnx_models.OnnxEmbedder)

    def test_torch_is_used_when_asked_for(self, monkeypatch):
        pytest.importorskip("sentence_transformers")
        monkeypatch.setenv(onnx_models.ENGINE_ENV, "torch")
        assert isinstance(embeddings.get_embedder(), embeddings.LocalEmbedder)

    def test_the_engine_setting_reaches_the_subprocess(self, monkeypatch):
        """Set on the agent server, it must also choose the child's engine."""
        from sextant.mcp_server import mcp_host

        monkeypatch.setenv(onnx_models.ENGINE_ENV, "torch")
        assert (mcp_host.kb_server().env or {}).get(onnx_models.ENGINE_ENV) == "torch"

    def test_the_base_install_never_imports_torch(self, tmp_path):
        """The point of the item: search works with torch absent."""
        code = (
            "import sys\n"
            "from sextant.vector_db.embeddings import get_embedder\n"
            "from sextant.vector_db.retrieval import CrossEncoderReranker\n"
            "get_embedder().encode(['a'])\n"
            "CrossEncoderReranker().score('a', ['b'])\n"
            "print('torch' in sys.modules)\n"
        )
        env = {k: v for k, v in __import__("os").environ.items() if not k.startswith("SEXTANT_")}
        env[settings.SEALED] = "1"
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
        )
        assert out.stdout.strip().splitlines()[-1] == "False"


class TestAConfigItCannotReproduceIsRefused:
    def test_cls_pooling_is_refused_not_guessed(self, monkeypatch, tmp_path):
        files = {
            "modules.json": [
                {"type": "sentence_transformers.models.Transformer"},
                {"type": "sentence_transformers.models.Pooling"},
                {"type": "sentence_transformers.models.Normalize"},
            ],
            "1_Pooling/config.json": {
                "pooling_mode_mean_tokens": False,
                "pooling_mode_cls_token": True,
            },
            "sentence_bert_config.json": {"max_seq_length": 256},
        }

        def fetch(repo: str, filename: str) -> Path:
            path = tmp_path / filename.replace("/", "_")
            if filename in files:
                path.write_text(json.dumps(files[filename]))
            else:
                path.write_text("")
            return path

        monkeypatch.setattr(onnx_models, "_fetch", fetch)
        monkeypatch.setattr(onnx_models, "_session", lambda path: object())
        with pytest.raises(EmbeddingsUnavailable, match="mean"):
            onnx_models.OnnxEmbedder(embeddings.LOCAL_MODEL)
