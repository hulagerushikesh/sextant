"""
IVF-PQ -- an inverted file over product-quantized codes, by hand.

Two independent ideas stacked, and it helps to keep them separate.

**IVF (the inverted file) is about *where to look*.** Run k-means over the corpus
to carve it into `nlist` cells, each with a centroid. To search, find the
`nprobe` centroids nearest the query and scan only the vectors in those cells --
not the whole corpus. nprobe is the knob: 1 cell is fast and misses neighbours
that fell across a cell boundary; all cells is exhaustive. That trade is the IVF
half of the recall/latency curve.

**PQ (product quantization) is about *how small each vector is*.** Split a 384-d
vector into `m` contiguous sub-vectors, run a separate k-means (256 centroids,
one byte) in each sub-space, and store each vector as `m` bytes -- the ids of its
nearest sub-centroids. A 384-d float32 vector (1536 bytes) becomes, at m=48, 48
bytes: a 32x compression. That is the entire reason IVF-PQ exists, and the number
the memory column on the frontend is there to show.

The clever part is scoring compressed codes without decompressing them. For a
given query, precompute a table of the squared distance from each query
sub-vector to all 256 sub-centroids in that sub-space -- an (m x 256) lookup
table. Then any stored code's distance is `m` table lookups summed, no
multiplies. This is *asymmetric* distance computation: the query stays full
precision, only the database is quantized, which keeps far more accuracy than
quantizing both. Distances are computed on the residual (vector minus its cell
centroid), because residuals are small and cluster tightly, so the quantizer
spends its bits where they matter.

Why implement rather than import faiss. The failure modes *are* the lesson.
Recall collapses if nprobe is too low for the query distribution; it collapses a
different way if m divides the dimension badly; a cell can empty out and the
k-means degenerates. Watching those happen -- and seeing them in the frontend as
a curve that bends where the parameter stops helping -- is the point of building
it. faiss appears in the benchmark as a reference column, not as the thing under
test.

Distances are squared Euclidean over unit vectors, ranking identically to cosine
(see base.py). The similarities returned are reconstructed from quantized
distances, so they are approximate -- close enough to order hits, not exact, and
labelled honestly as coming from the approximate index.
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
    similarity,
)


def _kmeans(
    data: np.ndarray, k: int, rng: np.random.Generator, iters: int = 25
) -> np.ndarray:
    """Lloyd's algorithm, k-means++ seeding. Returns (k, dim) centroids.

    Hand-rolled rather than pulled from scikit-learn: it is fifteen lines, it is
    the same routine the coarse quantizer and every PQ sub-space need, and it
    keeps this package's dependency footprint to numpy. Empty clusters are
    re-seeded onto the point furthest from its centroid, which is what stops a
    dead cell from silently shrinking the effective codebook.
    """
    n = data.shape[0]
    if n <= k:
        # Fewer points than centroids: each point is its own centroid, padded by
        # repeating the last so the codebook still has k rows to index into.
        pad = np.repeat(data[-1:], k - n, axis=0) if n < k else data[:0]
        return np.ascontiguousarray(np.vstack([data, pad]) if n < k else data[:k])

    # k-means++: spread the initial centroids out, so a cell is unlikely to start
    # empty and iterations are not wasted recovering from a bad seed.
    centroids = np.empty((k, data.shape[1]), dtype=data.dtype)
    centroids[0] = data[rng.integers(n)]
    closest = np.sum((data - centroids[0]) ** 2, axis=1)
    for i in range(1, k):
        probs = closest / closest.sum() if closest.sum() > 0 else None
        idx = rng.choice(n, p=probs) if probs is not None else rng.integers(n)
        centroids[i] = data[idx]
        closest = np.minimum(closest, np.sum((data - centroids[i]) ** 2, axis=1))

    for _ in range(iters):
        # Assign every point to its nearest centroid via the (n, k) distance
        # matrix, expanded as |x|^2 - 2 x.c + |c|^2 (the cross term is the only
        # matmul, which is what keeps this affordable).
        dots = data @ centroids.T
        norms = np.sum(centroids**2, axis=1)
        assign = np.argmin(norms - 2 * dots, axis=1)

        moved = False
        for c in range(k):
            members = data[assign == c]
            if len(members) == 0:
                # Re-seed the empty cell onto the worst-served point rather than
                # leaving a codebook entry that indexes nothing.
                far = int(np.argmax(np.min(norms - 2 * dots, axis=1)))
                centroids[c] = data[far]
                moved = True
            else:
                mean = members.mean(axis=0)
                if not np.allclose(mean, centroids[c]):
                    centroids[c] = mean
                    moved = True
        if not moved:
            break

    return centroids


class IvfPqIndex(AnnIndex):
    """Inverted lists over product-quantized residual codes."""

    name = "ivfpq"

    def __init__(
        self,
        nlist: int = 64,
        nprobe: int = 8,
        m: int = 16,
        nbits: int = 8,
        seed: int = 42,
    ) -> None:
        # nlist coarse cells; nprobe of them scanned per query.
        self.nlist = nlist
        self.nprobe = nprobe
        # m sub-quantizers, each with 2^nbits centroids. nbits=8 -> one byte per
        # sub-code, the standard and the only value where "one code is one byte"
        # holds exactly; it stays a parameter so the benchmark can show what
        # coarser codebooks cost.
        self.m = m
        self.nbits = nbits
        self.ksub = 2**nbits
        self.seed = seed

        self.ids: list[str] = []
        self._dim = 0
        self._dsub = 0
        self._coarse: np.ndarray | None = None  # (nlist, dim)
        self._codebooks: np.ndarray | None = None  # (m, ksub, dsub)
        self._codes: np.ndarray | None = None  # (n, m) uint8/uint16
        self._assign: np.ndarray | None = None  # (n,) cell of each vector
        self._lists: list[np.ndarray] = []  # cell -> row indices
        self._build_seconds = 0.0

    # -- build -------------------------------------------------------------

    def build(self, ids: list[str], vectors: Any) -> None:
        start = time.perf_counter()
        matrix = normalise(as_matrix(vectors))
        n, dim = matrix.shape
        if len(ids) != n:
            raise ValueError(f"{len(ids)} ids for {n} vectors -- they must correspond")
        if dim % self.m != 0:
            raise ValueError(
                f"m={self.m} must divide the dimension {dim}; "
                f"{dim} splits evenly by {[d for d in (8,12,16,24,32,48,64) if dim % d == 0]}"
            )

        self.ids = list(ids)
        self._dim = dim
        self._dsub = dim // self.m
        rng = np.random.default_rng(self.seed)

        if n == 0:
            # Nothing to quantize. Leave the index in its empty state so `search`
            # returns [] rather than k-means dividing by an empty corpus.
            self._coarse = None
            self._codes = None
            self._build_seconds = time.perf_counter() - start
            return

        # Coarse quantizer: nlist cells over the full vectors. Capped at n so a
        # tiny corpus does not ask k-means for more cells than points.
        nlist = min(self.nlist, n) if n else self.nlist
        self._coarse = _kmeans(matrix, nlist, rng)
        self._assign = self._nearest_coarse(matrix)  # (n,)

        # Residuals: each vector minus its cell centroid. PQ quantizes these,
        # not the raw vectors -- residuals are smaller and more alike across
        # cells, so a shared codebook fits them far better.
        residuals = matrix - self._coarse[self._assign]

        # One PQ codebook per sub-space, trained on that sub-space's residuals.
        self._codebooks = np.empty((self.m, self.ksub, self._dsub), dtype=np.float32)
        code_dtype = np.uint8 if self.ksub <= 256 else np.uint16
        self._codes = np.empty((n, self.m), dtype=code_dtype)
        for s in range(self.m):
            sub = residuals[:, s * self._dsub : (s + 1) * self._dsub]
            book = _kmeans(sub, self.ksub, rng, iters=25)
            self._codebooks[s] = book
            # Assign each residual sub-vector to its nearest sub-centroid.
            dots = sub @ book.T
            norms = np.sum(book**2, axis=1)
            self._codes[:, s] = np.argmin(norms - 2 * dots, axis=1).astype(code_dtype)

        # Invert the assignment: cell -> the rows that live in it, so a probe is
        # an array slice rather than a scan for membership.
        self._lists = [np.where(self._assign == c)[0] for c in range(len(self._coarse))]
        self._build_seconds = time.perf_counter() - start

    def _nearest_coarse(self, matrix: np.ndarray) -> np.ndarray:
        assert self._coarse is not None
        dots = matrix @ self._coarse.T
        norms = np.sum(self._coarse**2, axis=1)
        return np.argmin(norms - 2 * dots, axis=1)

    # -- query -------------------------------------------------------------

    def search(self, query: Any, k: int) -> list[tuple[str, float]]:
        if self._coarse is None or self._codes is None or not self.ids:
            return []
        assert self._codebooks is not None and self._assign is not None

        vector = normalise(as_matrix(query))[0]

        # Pick the nprobe nearest cells to scan.
        coarse_d = np.sum((self._coarse - vector) ** 2, axis=1)
        nprobe = min(self.nprobe, len(self._coarse))
        cells = np.argpartition(coarse_d, nprobe - 1)[:nprobe]

        candidates = (
            np.concatenate([self._lists[c] for c in cells])
            if len(cells)
            else np.array([], dtype=int)
        )
        if candidates.size == 0:
            return []

        # The asymmetric distance tables, one per probed cell. The residual is
        # query-minus-*that cell's* centroid, so a vector's approximate distance
        # is its per-sub-space table entries summed. Building one table per cell
        # and reusing it across every vector in the cell is the whole efficiency.
        cell_of = self._assign[candidates]
        approx = np.empty(candidates.shape[0], dtype=np.float32)
        for c in cells:
            residual = vector - self._coarse[c]
            table = self._distance_table(residual)  # (m, ksub)
            mask = cell_of == c
            rows = candidates[mask]
            codes = self._codes[rows]  # (len, m)
            # Sum the table entry each sub-code points at: take_along on each
            # sub-space, then add across the m columns.
            dist = np.zeros(rows.shape[0], dtype=np.float32)
            for s in range(self.m):
                dist += table[s, codes[:, s]]
            approx[mask] = dist

        k = min(k, candidates.shape[0])
        top = np.argpartition(approx, k - 1)[:k]
        top = top[np.argsort(approx[top])]
        return [(self.ids[candidates[i]], float(similarity(approx[i]))) for i in top]

    def _distance_table(self, residual: np.ndarray) -> np.ndarray:
        """(m, ksub) squared distances from each query sub-vector to each sub-centroid."""
        assert self._codebooks is not None
        table = np.empty((self.m, self.ksub), dtype=np.float32)
        for s in range(self.m):
            sub = residual[s * self._dsub : (s + 1) * self._dsub]
            book = self._codebooks[s]  # (ksub, dsub)
            diff = book - sub
            table[s] = np.einsum("ij,ij->i", diff, diff)
        return table

    # -- stats -------------------------------------------------------------

    def stats(self) -> IndexStats:
        n = len(self.ids)
        codes_bytes = int(self._codes.nbytes) if self._codes is not None else 0
        coarse_bytes = int(self._coarse.nbytes) if self._coarse is not None else 0
        book_bytes = int(self._codebooks.nbytes) if self._codebooks is not None else 0
        # The codes are the per-vector cost -- the number that scales with the
        # corpus. Coarse centroids and codebooks are a fixed overhead that a
        # large corpus amortises, but they are real, so they are counted.
        populated = sum(1 for lst in self._lists if len(lst) > 0)
        return IndexStats(
            name=self.name,
            vectors=n,
            dim=self._dim,
            build_seconds=self._build_seconds,
            bytes=codes_bytes + coarse_bytes + book_bytes,
            # Codes scale with the corpus; the coarse centroids and codebooks do
            # not. A large corpus makes the overhead negligible per vector, which
            # is exactly the regime IVF-PQ is for.
            overhead_bytes=coarse_bytes + book_bytes,
            params={
                "nlist": len(self._coarse) if self._coarse is not None else self.nlist,
                "nprobe": self.nprobe,
                "m": self.m,
                "nbits": self.nbits,
                "code_bytes_per_vector": self.m,
                "populated_cells": populated,
            },
        )
