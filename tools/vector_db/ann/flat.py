"""
Exact search. The ground truth every other index is graded against.

There is no approximation here and that is the entire point: recall@k for HNSW
or IVF-PQ is defined as "how many of the k neighbours this index found are in
the k that *actually* are nearest", and something has to define "actually". This
is that something. It is also the honest memory-and-latency baseline -- the
thing the approximate indexes have to beat on something to justify their
approximation.

Brute force, but vectorised brute force. One matrix-vector product gives every
similarity at once, and `argpartition` finds the top k without sorting the whole
corpus. At a few thousand chunks this is genuinely fast -- fast enough that the
comparison's interesting finding may well be "you did not need an ANN index at
this scale", which is a finding worth being able to show rather than assume.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from tools.vector_db.ann.base import (
    AnnIndex,
    IndexStats,
    as_matrix,
    normalise,
)


class FlatIndex(AnnIndex):
    """Exact nearest-neighbour search by full scan."""

    name = "flat"

    def __init__(self) -> None:
        self.ids: list[str] = []
        self._matrix: np.ndarray | None = None
        self._build_seconds = 0.0

    def build(self, ids: list[str], vectors: Any) -> None:
        start = time.perf_counter()
        matrix = normalise(as_matrix(vectors))
        if len(ids) != matrix.shape[0]:
            raise ValueError(
                f"{len(ids)} ids for {matrix.shape[0]} vectors -- they must correspond"
            )
        self.ids = list(ids)
        self._matrix = matrix
        self._build_seconds = time.perf_counter() - start

    def search(self, query: Any, k: int) -> list[tuple[str, float]]:
        if self._matrix is None or not self.ids:
            return []

        vector = normalise(as_matrix(query))[0]
        # Cosine similarity for every chunk in one dot product. On unit vectors
        # this is the whole ranking; the squared-distance form is only needed
        # where a distance table is (IVF-PQ), so it is not reconstructed here.
        sims = self._matrix @ vector

        k = min(k, len(self.ids))
        if k <= 0:
            return []

        # argpartition finds the k largest in O(n), then only those k are sorted.
        # For k << n this is the difference between sorting 1,500 numbers and
        # sorting 5, on every query.
        top = np.argpartition(-sims, k - 1)[:k]
        top = top[np.argsort(-sims[top])]
        return [(self.ids[i], float(sims[i])) for i in top]

    def search_many(self, queries: Any, k: int) -> list[list[tuple[str, float]]]:
        """Exact neighbours for a batch of queries.

        The benchmark computes ground truth for hundreds of queries at once, and
        one (m, n) matrix product is dramatically faster than m separate ones.
        Kept beside `search` rather than in the harness because it is the same
        computation and should not drift from it.
        """
        if self._matrix is None or not self.ids:
            return [[] for _ in as_matrix(queries)]

        matrix = normalise(as_matrix(queries))
        sims = matrix @ self._matrix.T  # (m, n)
        k = min(k, len(self.ids))
        if k <= 0:
            return [[] for _ in range(sims.shape[0])]

        results: list[list[tuple[str, float]]] = []
        for row in sims:
            top = np.argpartition(-row, k - 1)[:k]
            top = top[np.argsort(-row[top])]
            results.append([(self.ids[i], float(row[i])) for i in top])
        return results

    def stats(self) -> IndexStats:
        matrix = self._matrix
        vectors, dim = matrix.shape if matrix is not None else (0, 0)
        return IndexStats(
            name=self.name,
            vectors=vectors,
            dim=dim,
            build_seconds=self._build_seconds,
            # The full float32 matrix, and nothing else. This is the number the
            # compressed indexes are trying to shrink.
            bytes=int(matrix.nbytes) if matrix is not None else 0,
            params={},
        )
