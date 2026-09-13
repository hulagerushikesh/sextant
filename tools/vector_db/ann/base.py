"""
What every index in this package agrees on.

Three indexes live here -- exact, HNSW, IVF-PQ -- and the only reason to have
three is to compare them. A comparison is worth nothing unless they are measured
on identical terms, so the shared terms are stated once, here, rather than
implied three times.

**Unit vectors, squared Euclidean distance.** Every vector is L2-normalised at
build time and every query is normalised at search time. On unit vectors

    ||q - x||^2 = 2 - 2 * (q . x)

so squared Euclidean distance and cosine similarity are the same ranking, and
`similarity()` converts one to the other exactly. This matters more than it
looks: IVF-PQ's asymmetric distance computation is naturally a squared-L2
calculation over residuals, HNSW's graph only needs *an* ordering, and the rest
of the system speaks cosine because that is what the Chroma collection was built
with. Normalising once at the boundary means no index has to carry a metric
flag, and no comparison is secretly between two different questions.

**Similarities out, not distances.** `search` returns the same numbers
`KnowledgeBase._dense` has always returned, on the same 0-1 scale, so an index
can be swapped underneath the retrieval pipeline without moving the score
threshold or rescaling anything downstream. This project has already shipped one
bug where a distance was labelled a similarity; the conversion lives in one
function to keep that from happening twice.

**Stats are part of the contract.** Build time, resident bytes and the parameters
in force are what the comparison is *about* -- an index that reports recall and
latency but not memory hides the entire reason IVF-PQ exists. Every index must
report them, so `stats()` is abstract rather than optional.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# float32 throughout. The embeddings arrive as float32 from sentence-transformers
# and doubling them to float64 would double the memory of the exact index -- the
# baseline the memory comparison is measured against -- for no accuracy that
# survives the cosine rounding at the other end.
DTYPE = np.float32


@dataclass(frozen=True)
class IndexStats:
    """What an index cost to build and what it costs to keep."""

    name: str
    vectors: int
    dim: int
    build_seconds: float
    # Resident bytes of the index's own arrays. Deliberately excludes the ids
    # and any Python object overhead: the question is how the *encoding*
    # compares, and 1,500 Python strings would swamp the difference between
    # 384 float32s and 48 PQ codes.
    bytes: int
    # Of `bytes`, the part that does NOT scale with the corpus: IVF-PQ's coarse
    # centroids and PQ codebooks are a fixed cost a large corpus amortises but a
    # tiny one does not. Splitting it out is the difference between "IVF-PQ uses
    # more memory than flat" (true at 52 vectors, false at 50,000) and the honest
    # per-vector figure. Flat and HNSW have no fixed overhead -- their memory is
    # all per-vector -- so this stays 0 for them.
    overhead_bytes: int = 0
    # The knobs this instance was built with, for the benchmark to label rows.
    params: dict[str, Any] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        per_vector = (self.bytes - self.overhead_bytes) / self.vectors if self.vectors else 0.0
        return {
            "name": self.name,
            "vectors": self.vectors,
            "dim": self.dim,
            "build_seconds": round(self.build_seconds, 4),
            "bytes": self.bytes,
            # Total over the corpus, including fixed overhead. What actually sits
            # in memory right now.
            "bytes_per_vector": round(self.bytes / self.vectors, 1) if self.vectors else 0.0,
            # The asymptotic per-vector cost -- what one more chunk adds -- with
            # the fixed codebooks factored out. This is the number that answers
            # "how does this scale".
            "amortised_bytes_per_vector": round(per_vector, 1),
            "overhead_bytes": self.overhead_bytes,
            "params": dict(self.params),
        }


def as_matrix(vectors: Any) -> np.ndarray:
    """A contiguous float32 (n, dim) array, whatever the caller passed."""
    matrix = np.asarray(vectors, dtype=DTYPE)
    if matrix.ndim == 1:
        matrix = matrix.reshape(1, -1)
    if matrix.ndim != 2:
        raise ValueError(f"expected a 2-D array of vectors, got shape {matrix.shape}")
    return np.ascontiguousarray(matrix)


def normalise(matrix: np.ndarray) -> np.ndarray:
    """Scale each row to unit length.

    A zero row would divide by zero and poison every distance computed against
    it with a NaN, which sorts unpredictably rather than last. Zero vectors are
    left alone instead: they stay at distance 2 from everything, which is the
    honest answer for a vector with no direction.
    """
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    np.copyto(norms, 1.0, where=norms == 0)
    return (matrix / norms).astype(DTYPE, copy=False)


def similarity(squared_distance: np.ndarray | float) -> np.ndarray | float:
    """Cosine similarity from squared Euclidean distance between unit vectors.

    Clipped to [-1, 1] because it is not: float32 accumulation over 384
    dimensions leaves a distance of 2.0000002 on an exactly-opposite pair, and
    IVF-PQ's reconstructed distances are approximations that can land slightly
    outside the range on their own. A similarity of 1.0000001 would be reported
    as a score above one, which is the kind of number that makes a reader
    distrust every other number on the page.
    """
    return np.clip(1.0 - np.asarray(squared_distance) / 2.0, -1.0, 1.0)


class AnnIndex(ABC):
    """A nearest-neighbour index over unit vectors.

    Built once from the whole corpus rather than updated incrementally. That is
    a real limitation and a deliberate one: incremental insertion is where ANN
    indexes get complicated (HNSW tolerates it, IVF-PQ needs its quantizer
    retrained as the distribution drifts), and this corpus is rebuilt on
    ingestion anyway. The knowledge base holds the authoritative vectors; an
    index here is a derived, disposable accelerator.
    """

    #: Short identifier used in API payloads and benchmark rows.
    name: str = "index"

    @abstractmethod
    def build(self, ids: list[str], vectors: Any) -> None:
        """Index `vectors`, whose rows correspond to `ids`. Normalises for you."""

    @abstractmethod
    def search(self, query: Any, k: int) -> list[tuple[str, float]]:
        """The `k` nearest ids to `query`, best first, with cosine similarities.

        Returns fewer than `k` when the index holds fewer vectors, and an empty
        list when it is empty. Never raises for an over-large `k` -- the caller
        asking for more neighbours than exist is normal at small corpus sizes.
        """

    @abstractmethod
    def stats(self) -> IndexStats:
        """Build cost, memory and parameters. Valid only after `build`."""

    def __len__(self) -> int:
        return len(getattr(self, "ids", ()))
