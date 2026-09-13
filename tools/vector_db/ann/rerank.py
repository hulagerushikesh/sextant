"""
Two-stage retrieval: cheap approximate recall, then exact re-scoring.

This is the pattern production vector search actually ships, and it exists to
fix one specific weakness. IVF-PQ is tiny in memory because it stores each vector
as a handful of quantized bytes -- but those bytes are too coarse to *order*
neighbours correctly, which is why its recall tops out below 1.0 no matter how
high nprobe goes. The insight that rescues it: the approximate index does not
have to rank the neighbours, only to gather them. Getting the right chunks into
an oversized shortlist is far easier than ordering them, and PQ is good enough
at the former even when it is bad at the latter.

So: ask the base index for `k * oversample` candidates instead of `k`, then
re-score just those candidates with the exact full-precision vectors and keep the
true top-k. A handful of exact dot products -- `k * oversample` of them, not the
whole corpus -- recovers almost all the recall the quantization lost, at almost
none of the cost of an exact scan.

The honest catch, stated plainly because it is the whole tradeoff: re-scoring
needs the full-precision vectors reachable. In a real deployment they live on
disk or SSD as a *cold* tier and only the few candidate rows are fetched, so the
*hot* RAM footprint stays the small PQ codes. This in-memory teaching harness has
no cold tier -- it keeps the full matrix in RAM -- so `stats()` reports the full
resident cost honestly, and breaks out `hot_bytes_per_vector` (the base index's
per-vector code cost) as the number that survives when the full vectors are cold.
The memory win IVF-PQ buys is in that hot tier, and rerank does not spend it.

Generic over any base `AnnIndex`. IVF-PQ is the one it transforms most, because
IVF-PQ is the one with a recall ceiling to lift; wrapping HNSW mostly just adds
an exact-ordering guarantee on top of an already-high-recall shortlist.
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


class RerankIndex(AnnIndex):
    """Wrap an approximate index with an exact full-precision re-scoring pass."""

    def __init__(self, base: AnnIndex, oversample: int = 4) -> None:
        if oversample < 1:
            raise ValueError(f"oversample must be >= 1, got {oversample}")
        self.base = base
        self.oversample = oversample
        # Machine name uses an underscore, not '+', so it is a valid CSS class
        # and React key on the frontend without escaping.
        self.name = f"{base.name}_rerank"

        self.ids: list[str] = []
        self._matrix: np.ndarray | None = None  # full precision, for rescoring
        self._row: dict[str, int] = {}
        self._build_seconds = 0.0

    # -- build -------------------------------------------------------------

    def build(self, ids: list[str], vectors: Any) -> None:
        start = time.perf_counter()
        matrix = normalise(as_matrix(vectors))
        if len(ids) != matrix.shape[0]:
            raise ValueError(
                f"{len(ids)} ids for {matrix.shape[0]} vectors -- they must correspond"
            )
        # The base builds from the *same* normalised matrix, so stage one and
        # stage two are searching one space, not two.
        self.base.build(ids, matrix)
        self.ids = list(ids)
        self._matrix = matrix
        self._row = {cid: i for i, cid in enumerate(ids)}
        self._build_seconds = time.perf_counter() - start

    # -- query -------------------------------------------------------------

    def search(self, query: Any, k: int) -> list[tuple[str, float]]:
        if self._matrix is None or not self.ids:
            return []

        vector = normalise(as_matrix(query))[0]

        # Stage one: gather an oversized candidate set from the cheap index. Its
        # own scores are discarded -- all it has to get right is *which* chunks
        # make the shortlist, not their order.
        fetch = min(k * self.oversample, len(self.ids))
        candidates = self.base.search(vector, fetch)
        rows = [self._row[cid] for cid, _ in candidates if cid in self._row]
        if not rows:
            return []

        # Stage two: exact cosine over just those candidate rows. On unit vectors
        # a dot product is the cosine, so this is one small (c, dim) x (dim,)
        # product -- c = k*oversample, not the whole corpus.
        block = self._matrix[rows]
        sims = block @ vector

        top = min(k, len(rows))
        order = np.argsort(-sims)[:top]
        return [(self.ids[rows[i]], float(sims[i])) for i in order]

    # -- stats -------------------------------------------------------------

    def stats(self) -> IndexStats:
        base = self.base.stats()
        n = len(self.ids)
        full_bytes = int(self._matrix.nbytes) if self._matrix is not None else 0
        dim = int(self._matrix.shape[1]) if self._matrix is not None else 0

        # Hot tier: the base index's own per-vector arrays (IVF-PQ's codes) --
        # the number that determines whether the index fits in RAM, and the one
        # rerank leaves untouched. Cold tier: the full vectors, counted in
        # `bytes` for honesty but broken out below because production keeps them
        # on disk.
        hot_per_vector = round((base.bytes - base.overhead_bytes) / n, 1) if n else 0.0

        params: dict[str, Any] = dict(base.params)
        params.update(
            {
                "base": self.base.name,
                "oversample": self.oversample,
                "hot_bytes_per_vector": hot_per_vector,
            }
        )
        return IndexStats(
            name=self.name,
            vectors=n,
            dim=dim,
            build_seconds=self._build_seconds,
            # Full resident cost of this harness: base structure + full vectors.
            bytes=base.bytes + full_bytes,
            # The base's fixed codebooks remain the only corpus-independent cost;
            # the full vectors are per-vector, so they stay out of overhead.
            overhead_bytes=base.overhead_bytes,
            params=params,
        )
