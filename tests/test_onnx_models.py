"""The ONNX path gives the same vectors and scores as the torch path.

The ONNX embedder keeps the store stamp `all-MiniLM-L6-v2`, so every store
built with torch opens under it. That is only honest if the two produce the
same vectors; these tests are where that claim is checked, model against
model, rather than assumed from the export's name.
"""

from __future__ import annotations

import json
import logging
import math
import os
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

    def test_vectors_come_back_in_the_order_given(self, onnx_embedder):
        """Batches run shortest first; the answer must not come back that way."""
        texts = [LONG, *TEXTS[:3], *(f"Short note {i}." for i in range(40))]
        together = onnx_embedder.encode(texts)
        for text, vector in zip(texts, together, strict=True):
            assert _cosine(onnx_embedder.encode([text])[0], vector) > 0.99999

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


class TestAFirstRunIsQuiet:
    """Nothing a new user reads should look like an error (milestone 27, item 4)."""

    def test_the_hub_token_notice_is_dropped(self, monkeypatch, caplog, capfd):
        from huggingface_hub.utils import LocalEntryNotFoundError

        hub = logging.getLogger(onnx_models._HUB_LOGGER)
        calls: list[bool] = []

        def download(repo: str, filename: str, local_files_only: bool = False) -> str:
            calls.append(local_files_only)
            if local_files_only:
                raise LocalEntryNotFoundError("not cached")
            hub.warning("Warning: You are sending unauthenticated requests to the HF Hub. "
                        "Please set a HF_TOKEN to enable higher rate limits.")
            hub.warning("HTTP Error 500 thrown while requesting GET x")
            return "/cache/model.onnx"

        monkeypatch.setattr("huggingface_hub.hf_hub_download", download)
        with caplog.at_level(logging.WARNING):
            assert onnx_models._fetch("r", "f") == Path("/cache/model.onnx")
        assert calls == [True, False], "the cache is asked first, then the network"
        messages = [r.getMessage() for r in caplog.records]
        assert not any("HF_TOKEN" in m for m in messages)
        assert any("HTTP Error 500" in m for m in messages), "real hub warnings still show"
        assert "HF_TOKEN" not in capfd.readouterr().err

    def test_a_cached_model_works_offline(self, onnx_embedder, tmp_path):
        """With the models cached, search starts with the hub unreachable.

        The hub library would also fall back to its cache here on its own;
        that the cache is asked *first*, so no request is made at all, is
        the test above.
        """
        code = (
            "from sextant.vector_db.embeddings import get_embedder\n"
            "from sextant.vector_db.retrieval import CrossEncoderReranker\n"
            "get_embedder().encode(['a'])\n"
            "CrossEncoderReranker().score('a', ['b'])\n"
            "print('ok')\n"
        )
        env = {k: v for k, v in os.environ.items() if not k.startswith(("SEXTANT_", "HF_HUB_"))}
        env[settings.SEALED] = "1"
        env["HF_ENDPOINT"] = "http://127.0.0.1:9"  # nothing listens; any request fails
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=120
        )
        assert out.returncode == 0, out.stderr
        assert out.stdout.strip().splitlines()[-1] == "ok"
        assert "127.0.0.1:9" not in out.stderr

    def test_the_server_does_not_log_each_request(self):
        """In a fresh process: other tests' imports set this logger too."""
        code = (
            "import logging, sextant.vector_db.server\n"
            "print(logging.getLogger('httpx').getEffectiveLevel())\n"
        )
        env = {k: v for k, v in os.environ.items() if not k.startswith("SEXTANT_")}
        env[settings.SEALED] = "1"
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, env=env, check=True
        )
        assert int(out.stdout.strip().splitlines()[-1]) >= logging.WARNING
