"""The two search models on ONNX Runtime, without torch.

Both default models -- the embedder and the cross-encoder -- are published by
their authors with an ONNX export beside the weights. Running that export
needs `onnxruntime` and `tokenizers`, which `chromadb` installs anyway; the
sentence-transformers path needs torch, which is two thirds of the install.

Each class reproduces the pipeline its model's own config declares, and
refuses a config it does not reproduce rather than guess: an embedder that
pools differently from the one that built a store returns vectors that look
fine and rank wrongly. `tests/test_onnx_models.py` compares both against the
torch path wherever that path is installed.
"""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any

from sextant import settings

logger = logging.getLogger(__name__)

# The name a store is stamped with, mapped to the repository holding the
# export. The short embedder name is what every existing store carries.
EMBEDDER_REPOS = {
    "all-MiniLM-L6-v2": "sentence-transformers/all-MiniLM-L6-v2",
    "sentence-transformers/all-MiniLM-L6-v2": "sentence-transformers/all-MiniLM-L6-v2",
}
RERANKER_REPOS = {
    "cross-encoder/ms-marco-MiniLM-L-6-v2": "cross-encoder/ms-marco-MiniLM-L6-v2",
    "cross-encoder/ms-marco-MiniLM-L6-v2": "cross-encoder/ms-marco-MiniLM-L6-v2",
}

ONNX_FILE = "onnx/model.onnx"
ENGINE_ENV = settings.env_name("ENGINE")

# Bounds memory on a large ingest; the vectors do not depend on it.
BATCH = 32


def engine() -> str:
    """`onnx` (the default) or `torch`, from `SEXTANT_ENGINE`."""
    return (settings.getenv("ENGINE") or "onnx").strip().lower()


def _fetch(repo: str, filename: str) -> Path:
    from huggingface_hub import hf_hub_download

    return Path(hf_hub_download(repo, filename))


def _session(path: Path) -> Any:
    import onnxruntime

    options = onnxruntime.SessionOptions()
    options.log_severity_level = 3  # errors only; its warnings are not ours to show
    # Idle worker threads otherwise busy-wait for the next job. With several
    # searches at once they took every core, and the server's own event loop
    # stalled for a third of a search (test_knowledge_base, TestConcurrency).
    options.add_session_config_entry("session.intra_op.allow_spinning", "0")
    return onnxruntime.InferenceSession(
        str(path), sess_options=options, providers=["CPUExecutionProvider"]
    )


def _feed(session: Any, encodings: list[Any]) -> dict[str, Any]:
    import numpy as np

    columns = {
        "input_ids": [e.ids for e in encodings],
        "attention_mask": [e.attention_mask for e in encodings],
        "token_type_ids": [e.type_ids for e in encodings],
    }
    wanted = [i.name for i in session.get_inputs()]
    unknown = set(wanted) - set(columns)
    if unknown:
        raise ValueError(f"the ONNX export asks for inputs this code does not supply: {unknown}")
    return {name: np.asarray(columns[name], dtype=np.int64) for name in wanted}


class OnnxEmbedder:
    """A sentence-transformers bi-encoder: transformer, mean pooling, L2 norm."""

    def __init__(self, model_name: str) -> None:
        from tokenizers import Tokenizer

        from sextant.vector_db.embeddings import QUERY_PREFIXES, EmbeddingsUnavailable

        repo = EMBEDDER_REPOS[model_name]
        try:
            modules = json.loads(_fetch(repo, "modules.json").read_text())
            pooling = json.loads(_fetch(repo, "1_Pooling/config.json").read_text())
            limits = json.loads(_fetch(repo, "sentence_bert_config.json").read_text())
            tokenizer_path = _fetch(repo, "tokenizer.json")
            self._session = _session(_fetch(repo, ONNX_FILE))
        except Exception as e:  # noqa: BLE001 - every failure here means "no embedder"
            raise EmbeddingsUnavailable(f"Could not load {model_name} for ONNX: {e}") from e

        kinds = [m.get("type", "").rsplit(".", 1)[-1] for m in modules]
        modes = {k for k, v in pooling.items() if k.startswith("pooling_mode_") and v}
        means = modes == {"pooling_mode_mean_tokens"}
        if kinds != ["Transformer", "Pooling", "Normalize"] or not means:
            raise EmbeddingsUnavailable(
                f"{model_name} declares {kinds} with pooling {pooling}; only mean "
                "pooling followed by normalisation is reproduced here."
            )

        self.name = model_name
        self.query_prefix = QUERY_PREFIXES.get(model_name, "")
        self.max_tokens = int(limits["max_seq_length"])
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))
        self._tokenizer.enable_truncation(max_length=self.max_tokens)
        self._tokenizer.enable_padding()
        # A second copy that never truncates: counting is how the chunker
        # learns a paragraph is too long, so it must see the whole of it.
        self._counter = Tokenizer.from_file(str(tokenizer_path))
        self._counter.no_truncation()
        self._counter.no_padding()

    def encode(self, texts: list[str]) -> list[list[float]]:
        import numpy as np

        vectors: list[list[float]] = []
        for start in range(0, len(texts), BATCH):
            encodings = self._tokenizer.encode_batch(texts[start : start + BATCH])
            feed = _feed(self._session, encodings)
            hidden = self._session.run(None, feed)[0]
            mask = feed["attention_mask"][..., None].astype(hidden.dtype)
            pooled = (hidden * mask).sum(axis=1) / np.clip(mask.sum(axis=1), 1e-9, None)
            norms = np.clip(np.linalg.norm(pooled, axis=1, keepdims=True), 1e-12, None)
            vectors.extend((pooled / norms).tolist())
        return vectors

    def encode_query(self, text: str) -> list[float]:
        return self.encode([self.query_prefix + text])[0]

    def count_tokens(self, text: str) -> int:
        return len(self._counter.encode(text, add_special_tokens=False).ids)


class OnnxReranker:
    """A cross-encoder with one output logit, squashed to 0-1 by a sigmoid."""

    def __init__(self, model_name: str) -> None:
        from tokenizers import Tokenizer

        repo = RERANKER_REPOS[model_name]
        config = json.loads(_fetch(repo, "config.json").read_text())
        if config.get("num_labels", len(config.get("id2label") or {0: 0})) != 1:
            raise ValueError(f"{model_name} does not have a single relevance output")
        self._session = _session(_fetch(repo, ONNX_FILE))
        self._tokenizer = Tokenizer.from_file(str(_fetch(repo, "tokenizer.json")))
        self._tokenizer.enable_truncation(
            max_length=int(config.get("max_position_embeddings", 512)),
            strategy="longest_first",
        )
        self._tokenizer.enable_padding()

    def predict(self, pairs: list[tuple[str, str]]) -> list[float]:
        scores: list[float] = []
        for start in range(0, len(pairs), BATCH):
            encodings = self._tokenizer.encode_batch(pairs[start : start + BATCH])
            logits = self._session.run(None, _feed(self._session, encodings))[0]
            scores.extend(1.0 / (1.0 + math.exp(-float(row[0]))) for row in logits)
        return scores
