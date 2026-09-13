"""
Hybrid retrieval: lexical, dense, fused, reranked.

Dense vectors and BM25 fail in opposite directions. An embedding matches meaning
and will happily return a passage about state estimation for a query about
Kalman filters -- but it also loses exact tokens, so a query for an error code, a
surname or a section number can miss the one chunk that literally contains it.
BM25 nails those and is helpless at paraphrase. Running both and fusing the
rankings costs one extra pass over a corpus already in memory.

Fusion is reciprocal rank fusion, which combines *ranks* rather than scores. That
matters here: a cosine similarity and a BM25 score have no common scale, and
anything that adds or averages them is inventing a relationship that does not
exist. RRF only asks "how near the top did each retriever put this?".

The cross-encoder then reranks the shortlist. Unlike the bi-encoder that produced
the vectors, it reads the query and the passage together with full attention, so
it can tell a passage that is *about* the topic from one that actually answers
the question -- which is exactly what chunking dilutes.
"""

from __future__ import annotations

import logging
import math
import re
from collections import Counter
from dataclasses import dataclass

logger = logging.getLogger(__name__)

RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Okapi BM25's usual defaults. k1 controls how fast term frequency saturates,
# b how hard document length is penalised.
BM25_K1 = 1.5
BM25_B = 0.75

# Standard RRF constant. Large enough that the top few ranks are not wildly
# more valuable than the ones just below them.
RRF_K = 60

_TOKEN = re.compile(r"[a-z0-9]+")

# Deliberately short. A long stoplist starts eating query terms that carry
# meaning in a technical corpus ("no", "all", "state").
_STOPWORDS = frozenset(
    "a an and are as at be but by for from has have how i if in into is it its of on or "
    "that the their then there these this to was were what when where which who will with".split()
)


def tokenize(text: str) -> list[str]:
    """Lowercase alphanumeric terms, minus the most common function words."""
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS and len(t) > 1]


class BM25Index:
    """An in-memory Okapi BM25 index.

    Built from the collection rather than persisted: the chunks already live in
    ChromaDB, and a second on-disk index would be one more thing that can fall
    out of step with the first. Rebuilt whenever ingestion changes the corpus.
    """

    def __init__(self, ids: list[str], texts: list[str]) -> None:
        self.ids = ids
        self.lengths = [0] * len(ids)
        self.frequencies: list[Counter[str]] = []
        document_frequency: Counter[str] = Counter()

        for i, text in enumerate(texts):
            terms = tokenize(text)
            counts = Counter(terms)
            self.frequencies.append(counts)
            self.lengths[i] = len(terms)
            document_frequency.update(counts.keys())

        total = len(ids)
        self.average_length = (sum(self.lengths) / total) if total else 0.0
        self.idf = {
            term: math.log(1 + (total - df + 0.5) / (df + 0.5))
            for term, df in document_frequency.items()
        }

    def __len__(self) -> int:
        return len(self.ids)

    def search(self, query: str, limit: int) -> list[tuple[str, float]]:
        """Top `limit` (id, score) pairs, best first. Zero-scoring docs omitted."""
        terms = tokenize(query)
        if not terms or not self.ids:
            return []

        scored: list[tuple[str, float]] = []
        for i, counts in enumerate(self.frequencies):
            score = 0.0
            for term in terms:
                frequency = counts.get(term)
                if not frequency:
                    continue
                norm = 1 - BM25_B + BM25_B * (self.lengths[i] / (self.average_length or 1))
                score += self.idf[term] * frequency * (BM25_K1 + 1) / (frequency + BM25_K1 * norm)
            if score > 0:
                scored.append((self.ids[i], score))

        scored.sort(key=lambda pair: pair[1], reverse=True)
        return scored[:limit]


@dataclass
class Fused:
    """One candidate after fusion, with the trail of how it got here."""

    id: str
    rrf_score: float
    dense_rank: int | None = None
    lexical_rank: int | None = None

    @property
    def matched(self) -> list[str]:
        found = []
        if self.dense_rank is not None:
            found.append("dense")
        if self.lexical_rank is not None:
            found.append("lexical")
        return found


def reciprocal_rank_fusion(
    dense: list[str], lexical: list[str], k: int = RRF_K
) -> list[Fused]:
    """Fuse two ranked id lists into one, best first.

    Combines ranks, never scores -- cosine similarity and BM25 have no shared
    scale, and averaging them would be arithmetic on incompatible units.
    """
    fused: dict[str, Fused] = {}

    for source, ranking in (("dense", dense), ("lexical", lexical)):
        for rank, doc_id in enumerate(ranking, start=1):
            entry = fused.get(doc_id)
            if entry is None:
                entry = fused[doc_id] = Fused(id=doc_id, rrf_score=0.0)
            entry.rrf_score += 1 / (k + rank)
            if source == "dense":
                entry.dense_rank = rank
            else:
                entry.lexical_rank = rank

    return sorted(fused.values(), key=lambda f: f.rrf_score, reverse=True)


class RerankerUnavailable(RuntimeError):
    """Raised when the cross-encoder cannot be loaded."""


class CrossEncoderReranker:
    """Scores (query, passage) pairs directly, on a 0-1 scale.

    Loaded on first use rather than at import: it is a ~90 MB download the first
    time, and a knowledge base that is only ever ingested into should not pay for
    it.
    """

    def __init__(self, model_name: str = RERANK_MODEL) -> None:
        self.model_name = model_name
        self._model = None

    def _load(self):
        if self._model is None:
            try:
                import torch
                from sentence_transformers import CrossEncoder
            except ImportError as e:
                raise RerankerUnavailable(f"sentence-transformers is not importable ({e})") from e
            try:
                # Sigmoid explicitly: the raw head emits an unbounded logit, and
                # this project has already been bitten once by reporting an
                # unbounded number as if it were a 0-1 score.
                self._model = CrossEncoder(model_name_or_path=self.model_name,
                                           activation_fn=torch.nn.Sigmoid())
            except Exception as e:
                raise RerankerUnavailable(f"Could not load {self.model_name}: {e}") from e
        return self._model

    def score(self, query: str, passages: list[str]) -> list[float]:
        """Relevance of each passage to the query, in [0, 1]."""
        if not passages:
            return []
        model = self._load()
        scores = model.predict([(query, passage) for passage in passages])
        return [float(s) for s in scores]
