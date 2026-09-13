"""
FAISS reference indexes -- the same algorithms, in C++, as a yardstick.

The hand-written HNSW and IVF-PQ in this package exist to make the *algorithms*
legible, and they succeed at that. What they cannot be is fast: they are pure
Python, per-node and per-cell, where the whole reason libraries like FAISS exist
is to do that same work in vectorised C++. So a benchmark of the Python indexes
alone leaves one honest question hanging -- "yes, but how slow is slow?" -- and
answers it only with a paragraph of caveat.

This file answers it with a column. `FaissHnswIndex` and `FaissIvfPqIndex` wrap
FAISS's own HNSW and IVF-PQ behind the same `AnnIndex` interface, so the harness
measures them on identical terms: same normalised vectors, same recall-against-
exact, same latency clock. On the frontend they are drawn as *dashed reference
lines*, deliberately set apart -- they are not the thing under test, they are the
speed the tested algorithms would run at once compiled. The gap between a solid
line and its dashed twin is the constant factor the caveat was describing, made
visible.

They are the same algorithms, so their recall curves track the Python versions
closely (small differences come from FAISS's neighbour-selection and training
details, not a different method). What differs by one to two orders of magnitude
is latency, and that is the entire point of showing them.

FAISS is an optional dependency (`pip install faiss-cpu`, the `bench` extra). When
it is absent `HAVE_FAISS` is False and the benchmark simply notes the reference
was skipped rather than failing -- the hand-written indexes are the product; the
reference is a bonus that not every environment needs to carry.

Distances are squared Euclidean over unit vectors (METRIC_L2), which ranks
identically to cosine (see base.py), so `similarity()` converts FAISS's returned
L2 distances to the same 0-1 scale every other index reports.
"""

from __future__ import annotations

import os
import time
from typing import Any

from tools.vector_db.ann.base import (
    AnnIndex,
    IndexStats,
    as_matrix,
    normalise,
    similarity,
)

# faiss-cpu and PyTorch (sentence-transformers, always loaded in the server) each
# bundle their own OpenMP runtime. On macOS the second one to initialise aborts
# the process ("OMP: Error #15 ... libiomp5 already initialized") unless this flag
# is set. faiss is only ever imported through this module, and this runs before
# `import faiss`, so setting it here covers whichever library loads second --
# without it, clicking "Run benchmark sweep" would hard-crash the running server.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

try:
    import faiss

    HAVE_FAISS = True
except ImportError:  # pragma: no cover - exercised only where faiss is absent
    faiss = None  # type: ignore[assignment]
    HAVE_FAISS = False


def _require_faiss() -> None:
    if not HAVE_FAISS:
        raise RuntimeError(
            "faiss is not installed; install the 'bench' extra (pip install faiss-cpu) "
            "to build the FAISS reference indexes"
        )


class FaissHnswIndex(AnnIndex):
    """FAISS's IndexHNSWFlat, wrapped as the C++ reference for our HNSW."""

    name = "faiss_hnsw"

    def __init__(
        self, m: int = 16, ef_construction: int = 200, ef_search: int = 50
    ) -> None:
        self.m = m
        self.ef_construction = ef_construction
        self.ef_search = ef_search
        self.ids: list[str] = []
        self._index: Any = None
        self._dim = 0
        self._build_seconds = 0.0

    def build(self, ids: list[str], vectors: Any) -> None:
        _require_faiss()
        start = time.perf_counter()
        matrix = normalise(as_matrix(vectors))
        n, dim = matrix.shape
        if len(ids) != n:
            raise ValueError(f"{len(ids)} ids for {n} vectors -- they must correspond")

        index = faiss.IndexHNSWFlat(dim, self.m)  # METRIC_L2 by default
        index.hnsw.efConstruction = self.ef_construction
        if n:
            index.add(matrix)

        self.ids = list(ids)
        self._dim = dim
        self._index = index
        self._build_seconds = time.perf_counter() - start

    def search(self, query: Any, k: int) -> list[tuple[str, float]]:
        if self._index is None or not self.ids:
            return []
        k = min(k, len(self.ids))
        if k <= 0:
            return []
        self._index.hnsw.efSearch = max(self.ef_search, k)
        vector = normalise(as_matrix(query))
        distances, indices = self._index.search(vector, k)
        hits = []
        for dist, idx in zip(distances[0], indices[0], strict=True):
            if idx < 0:  # FAISS pads with -1 when fewer than k are found
                continue
            hits.append((self.ids[int(idx)], float(similarity(float(dist)))))
        return hits

    def stats(self) -> IndexStats:
        n = len(self.ids)
        return IndexStats(
            name=self.name,
            vectors=n,
            dim=self._dim,
            build_seconds=self._build_seconds,
            bytes=_serialized_bytes(self._index),
            params={
                "M": self.m,
                "efConstruction": self.ef_construction,
                "efSearch": self.ef_search,
                "impl": "faiss",
            },
        )


class FaissIvfPqIndex(AnnIndex):
    """FAISS's IndexIVFPQ, wrapped as the C++ reference for our IVF-PQ."""

    name = "faiss_ivfpq"

    def __init__(
        self, nlist: int = 64, nprobe: int = 8, m: int = 16, nbits: int = 8
    ) -> None:
        self.nlist = nlist
        self.nprobe = nprobe
        self.m = m
        self.nbits = nbits
        self.ids: list[str] = []
        self._index: Any = None
        self._dim = 0
        self._nlist_built = nlist
        self._build_seconds = 0.0

    def build(self, ids: list[str], vectors: Any) -> None:
        _require_faiss()
        start = time.perf_counter()
        matrix = normalise(as_matrix(vectors))
        n, dim = matrix.shape
        if len(ids) != n:
            raise ValueError(f"{len(ids)} ids for {n} vectors -- they must correspond")
        if dim % self.m != 0:
            raise ValueError(f"m={self.m} must divide the dimension {dim}")

        self.ids = list(ids)
        self._dim = dim

        if n == 0:
            self._index = None
            self._build_seconds = time.perf_counter() - start
            return

        # FAISS trains nlist cells and needs at least nlist points to do it, so
        # cap nlist at n exactly as the hand-written index does.
        nlist = min(self.nlist, n)
        self._nlist_built = nlist
        quantizer = faiss.IndexFlatL2(dim)
        index = faiss.IndexIVFPQ(quantizer, dim, nlist, self.m, self.nbits)
        index.train(matrix)
        index.add(matrix)
        index.nprobe = self.nprobe

        self._index = index
        self._build_seconds = time.perf_counter() - start

    def search(self, query: Any, k: int) -> list[tuple[str, float]]:
        if self._index is None or not self.ids:
            return []
        k = min(k, len(self.ids))
        if k <= 0:
            return []
        self._index.nprobe = min(self.nprobe, self._nlist_built)
        vector = normalise(as_matrix(query))
        distances, indices = self._index.search(vector, k)
        hits = []
        for dist, idx in zip(distances[0], indices[0], strict=True):
            if idx < 0:
                continue
            hits.append((self.ids[int(idx)], float(similarity(float(dist)))))
        return hits

    def stats(self) -> IndexStats:
        n = len(self.ids)
        return IndexStats(
            name=self.name,
            vectors=n,
            dim=self._dim,
            build_seconds=self._build_seconds,
            bytes=_serialized_bytes(self._index),
            params={
                "nlist": self._nlist_built,
                "nprobe": self.nprobe,
                "m": self.m,
                "nbits": self.nbits,
                "impl": "faiss",
            },
        )


def _serialized_bytes(index: Any) -> int:
    """Resident size via FAISS's own serialization -- a real number, not a model.

    FAISS does not expose an in-memory byte count, but serializing the index and
    measuring the buffer is close: it is the encoding FAISS actually holds, codes
    and graph and codebooks included. Zero for an unbuilt index.
    """
    if index is None or not HAVE_FAISS:
        return 0
    return int(faiss.serialize_index(index).nbytes)
