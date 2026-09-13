"""
Measure the indexes against each other on identical terms.

The whole package exists to answer one question -- when do you reach for HNSW and
when for IVF-PQ -- and this file is where that question becomes numbers. It does
two things, matching the two frontend views:

* `sweep()` builds each index across a grid of its parameters and, for every
  configuration, reports recall@k, query-latency percentiles, build time and
  resident bytes. That is the tradeoff curve: recall against latency, coloured
  by index, annotated with memory. It is the "which algorithm, and tuned how"
  view.

* `compare_query()` runs one query through every index at a fixed configuration
  and returns each index's hits beside the exact answer, so a specific question
  can be seen going right or wrong. It is the "what did this cost me on *this*
  question" view.

Two rules keep the comparison honest. Ground truth is always the exact `FlatIndex`
over the same vectors -- recall is measured against the real neighbours, never
against another approximation. And every index is built from one shared,
already-normalised matrix, so no index is quietly answering an easier question
than another.

Nothing here is random without a seed. The query sample and every k-means start
from fixed seeds, so two runs of the same grid are comparable rather than merely
similar -- a benchmark whose numbers move on their own teaches nothing.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import numpy as np

from tools.vector_db.ann.base import as_matrix, normalise
from tools.vector_db.ann.faiss_ref import (
    HAVE_FAISS,
    FaissHnswIndex,
    FaissIvfPqIndex,
)
from tools.vector_db.ann.flat import FlatIndex
from tools.vector_db.ann.hnsw import HnswIndex
from tools.vector_db.ann.ivfpq import IvfPqIndex
from tools.vector_db.ann.rerank import RerankIndex


def recall_at_k(
    found: list[list[tuple[str, float]]],
    truth: list[list[tuple[str, float]]],
    k: int,
) -> float:
    """Mean fraction of the true top-k that each result actually recovered.

    Set overlap, not rank correlation: for retrieval feeding a reranker, whether
    the right chunk is in the shortlist is what matters, not the order it arrived
    in -- the cross-encoder reorders it anyway. Averaged over queries.
    """
    if not truth:
        return 0.0
    total = 0.0
    for got, want in zip(found, truth, strict=False):
        want_ids = {i for i, _ in want[:k]}
        if not want_ids:
            continue
        got_ids = {i for i, _ in got[:k]}
        total += len(got_ids & want_ids) / len(want_ids)
    return total / len(truth)


def _percentiles(latencies_ms: list[float]) -> dict[str, float]:
    if not latencies_ms:
        return {"p50": 0.0, "p90": 0.0, "p99": 0.0, "mean": 0.0}
    arr = np.array(latencies_ms)
    return {
        "p50": round(float(np.percentile(arr, 50)), 4),
        "p90": round(float(np.percentile(arr, 90)), 4),
        "p99": round(float(np.percentile(arr, 99)), 4),
        "mean": round(float(arr.mean()), 4),
    }


@dataclass
class BenchRow:
    """One index at one configuration, measured."""

    index: str
    params: dict[str, Any]
    recall: float
    latency_ms: dict[str, float]
    build_seconds: float
    bytes: int
    bytes_per_vector: float
    amortised_bytes_per_vector: float
    overhead_bytes: int
    queries: int
    k: int

    def as_json(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "params": self.params,
            "recall": round(self.recall, 4),
            "latency_ms": self.latency_ms,
            "build_seconds": round(self.build_seconds, 4),
            "bytes": self.bytes,
            "bytes_per_vector": self.bytes_per_vector,
            "amortised_bytes_per_vector": self.amortised_bytes_per_vector,
            "overhead_bytes": self.overhead_bytes,
            "queries": self.queries,
            "k": self.k,
        }


@dataclass
class Grid:
    """The parameter sweep. Sensible defaults; every field is overridable.

    HNSW is swept over efSearch at a fixed build (M, efConstruction), because
    efSearch is the query-time recall/latency dial and re-searching an existing
    graph is cheap -- rebuilding per point would make the sweep unaffordable for
    no extra insight. IVF-PQ is swept over nprobe at a fixed (nlist, m): nprobe
    is its query-time dial, m its memory dial, and holding m lets one curve mean
    one memory budget.
    """

    hnsw_m: int = 16
    hnsw_ef_construction: int = 200
    hnsw_ef_search: tuple[int, ...] = (10, 20, 40, 80, 160)

    ivf_nlist: int = 64
    ivf_m: int = 16
    ivf_nbits: int = 8
    ivf_nprobe: tuple[int, ...] = (1, 2, 4, 8, 16, 32)

    # IVF-PQ + exact rerank, swept over the same nprobe dial as bare IVF-PQ so
    # the two curves are directly comparable: same candidate generator, one with
    # an exact re-scoring pass and one without. `rerank_oversample` is how many
    # times k candidates the base index gathers before the exact pass keeps k.
    include_rerank: bool = True
    rerank_oversample: int = 4

    # FAISS reference: the same HNSW and IVF-PQ in C++, swept over the same dials,
    # drawn as dashed reference lines. Skipped with a note if faiss is not
    # installed. This is what turns the "pure Python is slow" caveat into a
    # measured latency gap instead of a paragraph.
    include_faiss: bool = True

    include_flat: bool = True
    seed: int = 42


def _sample_queries(
    vectors: np.ndarray, n_queries: int, seed: int
) -> np.ndarray:
    """Hold out `n_queries` corpus vectors as the query set.

    Querying with real corpus vectors rather than fresh random ones keeps the
    benchmark on-distribution: the recall numbers describe how the index behaves
    on questions shaped like the data it holds, which is the situation that
    actually obtains. Each query's nearest neighbour is itself, so recall is
    measured on the *rest* of the top-k, and k is not thrown off by the freebie.
    """
    rng = np.random.default_rng(seed)
    n = vectors.shape[0]
    count = min(n_queries, n)
    idx = rng.choice(n, size=count, replace=False)
    return vectors[idx]


def sweep(
    ids: list[str],
    vectors: Any,
    k: int = 10,
    n_queries: int = 200,
    grid: Grid | None = None,
) -> dict[str, Any]:
    """Build every index across the grid and measure it. Returns JSON-ready rows.

    The vectors are normalised once here and every index is built from that same
    matrix, so the comparison is like-for-like. Ground truth is the exact index
    over those vectors; recall for everything else is measured against it.
    """
    grid = grid or Grid()
    matrix = normalise(as_matrix(vectors))
    n, dim = matrix.shape
    if len(ids) != n:
        raise ValueError(f"{len(ids)} ids for {n} vectors")

    queries = _sample_queries(matrix, n_queries, grid.seed)

    truth_index = FlatIndex()
    truth_index.build(ids, matrix)
    truth = truth_index.search_many(queries, k)

    rows: list[BenchRow] = []

    def measure(index: Any, name: str, params: dict[str, Any]) -> BenchRow:
        latencies: list[float] = []
        found: list[list[tuple[str, float]]] = []
        for q in queries:
            start = time.perf_counter()
            hits = index.search(q, k)
            latencies.append((time.perf_counter() - start) * 1000)
            found.append(hits)
        stats = index.stats().as_json()
        return BenchRow(
            index=name,
            params=params,
            recall=recall_at_k(found, truth, k),
            latency_ms=_percentiles(latencies),
            build_seconds=stats["build_seconds"],
            bytes=stats["bytes"],
            bytes_per_vector=stats["bytes_per_vector"],
            amortised_bytes_per_vector=stats["amortised_bytes_per_vector"],
            overhead_bytes=stats["overhead_bytes"],
            queries=len(queries),
            k=k,
        )

    if grid.include_flat:
        rows.append(measure(truth_index, "flat", {}))

    # HNSW: one build, swept over efSearch. Recall against the exact top-k will
    # climb with efSearch and so will latency -- that pair is the curve.
    hnsw = HnswIndex(
        m=grid.hnsw_m, ef_construction=grid.hnsw_ef_construction, seed=grid.seed
    )
    hnsw.build(ids, matrix)
    for ef in grid.hnsw_ef_search:
        hnsw.ef_search = ef
        rows.append(
            measure(
                hnsw,
                "hnsw",
                {"M": grid.hnsw_m, "efConstruction": grid.hnsw_ef_construction, "efSearch": ef},
            )
        )

    # FAISS HNSW reference: the same graph in C++, swept over the same efSearch.
    # Its recall tracks the Python line; its latency is the C++ constant factor.
    if grid.include_faiss and HAVE_FAISS:
        fhnsw = FaissHnswIndex(m=grid.hnsw_m, ef_construction=grid.hnsw_ef_construction)
        fhnsw.build(ids, matrix)
        for ef in grid.hnsw_ef_search:
            fhnsw.ef_search = ef
            rows.append(
                measure(
                    fhnsw,
                    "faiss_hnsw",
                    {
                        "M": grid.hnsw_m,
                        "efConstruction": grid.hnsw_ef_construction,
                        "efSearch": ef,
                        "impl": "faiss",
                    },
                )
            )

    # IVF-PQ: one build at fixed (nlist, m), swept over nprobe. Recall climbs
    # with nprobe until it hits the PQ quantization ceiling, which is the finding
    # -- nprobe buys recall only up to what the code precision allows.
    if dim % grid.ivf_m == 0:
        ivf = IvfPqIndex(
            nlist=grid.ivf_nlist, m=grid.ivf_m, nbits=grid.ivf_nbits, seed=grid.seed
        )
        ivf.build(ids, matrix)
        for nprobe in grid.ivf_nprobe:
            ivf.nprobe = nprobe
            rows.append(
                measure(
                    ivf,
                    "ivfpq",
                    {
                        "nlist": grid.ivf_nlist,
                        "nprobe": nprobe,
                        "m": grid.ivf_m,
                        "nbits": grid.ivf_nbits,
                    },
                )
            )

        # IVF-PQ + exact rerank: the same candidate generator, swept over the
        # same nprobe, with an exact re-scoring pass over k*oversample
        # candidates. Its curve should sit above bare IVF-PQ's -- more recall at
        # each nprobe -- which is the whole reason to add it. Built once; only
        # the wrapped base's nprobe moves.
        if grid.include_rerank:
            rer = RerankIndex(
                IvfPqIndex(
                    nlist=grid.ivf_nlist,
                    m=grid.ivf_m,
                    nbits=grid.ivf_nbits,
                    seed=grid.seed,
                ),
                oversample=grid.rerank_oversample,
            )
            rer.build(ids, matrix)
            # The hot (RAM-resident in production) per-vector cost is the base's
            # code size and does not change with nprobe, so read it once.
            hot = rer.stats().params.get("hot_bytes_per_vector")
            for nprobe in grid.ivf_nprobe:
                rer.base.nprobe = nprobe  # type: ignore[attr-defined]
                rows.append(
                    measure(
                        rer,
                        "ivfpq_rerank",
                        {
                            "nlist": grid.ivf_nlist,
                            "nprobe": nprobe,
                            "m": grid.ivf_m,
                            "nbits": grid.ivf_nbits,
                            "oversample": grid.rerank_oversample,
                            "hot_bytes_per_vector": hot,
                        },
                    )
                )

        # FAISS IVF-PQ reference: the same inverted-file + product-quantized
        # index in C++, swept over the same nprobe.
        if grid.include_faiss and HAVE_FAISS:
            fivf = FaissIvfPqIndex(
                nlist=grid.ivf_nlist, m=grid.ivf_m, nbits=grid.ivf_nbits
            )
            fivf.build(ids, matrix)
            for nprobe in grid.ivf_nprobe:
                fivf.nprobe = nprobe
                rows.append(
                    measure(
                        fivf,
                        "faiss_ivfpq",
                        {
                            "nlist": grid.ivf_nlist,
                            "nprobe": nprobe,
                            "m": grid.ivf_m,
                            "nbits": grid.ivf_nbits,
                            "impl": "faiss",
                        },
                    )
                )
        ivf_skipped = None
    else:
        # Not silent: an m that does not divide the dimension is a real
        # constraint the reader should see, not a missing curve to puzzle over.
        ivf_skipped = (
            f"IVF-PQ skipped: m={grid.ivf_m} does not divide dimension {dim}"
        )

    rerank_note = None
    if grid.include_rerank and dim % grid.ivf_m == 0:
        rerank_note = (
            "ivfpq_rerank memory is reported with the full vectors resident (this "
            "harness has no disk tier); production keeps them cold and only the PQ "
            "codes hot -- see hot_bytes_per_vector in its params."
        )

    faiss_note = None
    if grid.include_faiss and HAVE_FAISS:
        faiss_note = (
            "faiss_* rows are the same algorithms in C++, shown as a reference for "
            "latency only -- the gap to the Python lines at equal recall is the "
            "constant factor, not a better method."
        )
    elif grid.include_faiss and not HAVE_FAISS:
        faiss_note = (
            "FAISS reference skipped: faiss is not installed (pip install faiss-cpu, "
            "the 'bench' extra)."
        )

    return {
        "corpus": {"vectors": n, "dim": dim},
        "k": k,
        "queries": len(queries),
        "seed": grid.seed,
        "rows": [row.as_json() for row in rows],
        "notes": [note for note in (ivf_skipped, rerank_note, faiss_note) if note],
    }


def compare_query(
    ids: list[str],
    vectors: Any,
    query_vector: Any,
    k: int = 10,
    hnsw: dict[str, Any] | None = None,
    ivfpq: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one query through flat, HNSW and IVF-PQ and line the answers up.

    For the per-query view: the exact hits, each approximate index's hits with
    its latency, and -- the useful part -- which of the exact neighbours each
    index *missed*, so a wrong answer on a real question is legible as a specific
    set of dropped chunks rather than a recall number.
    """
    matrix = normalise(as_matrix(vectors))
    query = as_matrix(query_vector)

    flat = FlatIndex()
    flat.build(ids, matrix)

    hnsw_index = HnswIndex(**(hnsw or {"m": 16, "ef_construction": 200, "ef_search": 50}))
    hnsw_index.build(ids, matrix)

    built = {"flat": flat, "hnsw": hnsw_index}
    dim = matrix.shape[1]
    ivf_params = ivfpq or {"nlist": 64, "nprobe": 8, "m": 16}
    if dim % ivf_params.get("m", 16) == 0:
        ivf_index = IvfPqIndex(**ivf_params)
        ivf_index.build(ids, matrix)
        built["ivfpq"] = ivf_index

        # The same IVF-PQ candidates, re-scored exactly. On a single question the
        # payoff is legible as a shorter "missed vs exact" list than bare IVF-PQ.
        rerank_index = RerankIndex(IvfPqIndex(**ivf_params), oversample=4)
        rerank_index.build(ids, matrix)
        built["ivfpq_rerank"] = rerank_index

    exact = flat.search(query, k)
    exact_ids = [i for i, _ in exact]
    exact_set = set(exact_ids)

    results = {}
    for name, index in built.items():
        start = time.perf_counter()
        hits = index.search(query, k)
        latency = (time.perf_counter() - start) * 1000
        hit_ids = [i for i, _ in hits]
        results[name] = {
            "hits": [{"id": i, "score": round(s, 4)} for i, s in hits],
            "latency_ms": round(latency, 4),
            "stats": index.stats().as_json(),
            # Against exact. Empty for flat itself, which is the point of
            # showing it: the yardstick has zero misses by definition.
            "missed": [i for i in exact_ids if i not in set(hit_ids)],
            "recall": round(len(set(hit_ids) & exact_set) / len(exact_set), 4)
            if exact_set
            else 0.0,
        }

    return {"k": k, "exact": exact_ids, "results": results}
