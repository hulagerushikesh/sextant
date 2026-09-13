"""
The embedding backend.

Small on purpose, but it earns its place: the chunker needs to know how many
tokens a piece of text will cost *in the model that will embed it*, and that
answer is different for every backend. Splitting text on a token budget borrowed
from some other tokenizer is how you end up with chunks that quietly overflow.

Which is not a hypothetical here. `all-MiniLM-L6-v2` has a hard 256 word-piece
limit and truncates silently past it -- a 622-token document embeds to exactly
the same vector as its first 256 tokens, so a sentence at the end contributes
nothing at all. Before Phase 4 documents were stored whole, which meant anything
longer than about two paragraphs was unreachable no matter how it was queried.
"""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)

LOCAL_MODEL = "all-MiniLM-L6-v2"


class EmbeddingsUnavailable(RuntimeError):
    """Raised when no embedding backend can be opened."""


class Embedder(Protocol):
    """What the knowledge base needs from an embedding model."""

    name: str
    max_tokens: int

    def encode(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts."""

    def count_tokens(self, text: str) -> int:
        """Tokens this text will cost when embedded."""


class LocalEmbedder:
    """sentence-transformers, running in this process.

    Costs ~900 MB of torch in the virtualenv and a few seconds of load time on
    first use, and buys offline operation with no third API key.
    """

    def __init__(self, model_name: str = LOCAL_MODEL) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise EmbeddingsUnavailable(
                f"sentence-transformers is not importable ({e}). Run: pip install -e '.[dev]'"
            ) from e

        self._model = SentenceTransformer(model_name)
        self.name = model_name
        # The model's own limit, not a number picked by hand. Everything past it
        # is discarded without warning, so the chunker treats it as a hard wall.
        limit = self._model.max_seq_length
        if limit is None:
            # Refuse rather than guess: a wrong budget here means chunks that
            # overflow and lose their tails with nothing in the output saying so.
            raise EmbeddingsUnavailable(
                f"{model_name} does not report a max_seq_length, so the chunker has no "
                "token budget to work to."
            )
        self.max_tokens = int(limit)

    def encode(self, texts: list[str]) -> list[list[float]]:
        return self._model.encode(texts, show_progress_bar=False).tolist()

    def count_tokens(self, text: str) -> int:
        # add_special_tokens=False: [CLS]/[SEP] are the chunker's headroom, not
        # part of the content it is packing.
        #
        # verbose=False silences transformers' "sequence longer than the maximum
        # ... will result in indexing errors" warning. Counting tokens on a long
        # paragraph is exactly the point here -- that is how the chunker learns
        # the paragraph needs splitting -- and nothing is being run through the
        # model, so the warning is alarming and wrong in this context.
        return len(
            self._model.tokenizer.encode(text, add_special_tokens=False, verbose=False)
        )


def get_embedder() -> Embedder:
    """The embedder for this process.

    One backend today. The roadmap called for moving to an API embedding model
    (Voyage or OpenAI) to drop torch and ~900 MB of virtualenv, and this is the
    seam where that would go -- but it would save nothing yet, because the
    cross-encoder reranker in `retrieval.py` pulls torch in regardless. Phase 5's
    golden set is what should decide whether an API model retrieves better;
    adding a second, unmeasured backend before then is how you get a fallback
    nobody can justify. See the difflib path this repo used to have.
    """
    return LocalEmbedder()
