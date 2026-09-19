# HNSW vs IVF-PQ: when to reach for which

This system ships three vector indexes, hand-written in NumPy, so their tradeoffs
can be **measured on your own corpus** rather than taken on faith from a library
benchmark. The Index Lab in the UI runs them live; this note records what the
numbers say and, more importantly, what they *mean*.

- **Flat** — exact search by full scan. The ground truth every recall number is
  measured against, and the honest baseline the approximate indexes must beat on
  *something* to justify themselves.
- **HNSW** — a navigable small-world graph. Fast and accurate; pays in memory.
- **IVF-PQ** — inverted lists over product-quantized codes. Tiny in memory and
  tunable; pays in recall.
- **IVF-PQ + rerank** — the same IVF-PQ candidates, re-scored exactly. Recovers
  the recall the quantization lost while keeping IVF-PQ's tiny hot footprint.

The code is in [`tools/vector_db/ann/`](../tools/vector_db/ann/). Each file opens
with the algorithm explained in prose — the point of writing them by hand was to
make the behaviour legible, so start there if you want the *why* behind a curve.

## What the sweep measures

For each index, across a grid of its parameters:

- **recall@k** against exact search — the fraction of the true nearest neighbours
  the index actually found. This is set overlap, not rank order: for retrieval
  feeding a reranker, whether the right chunk is in the shortlist is what counts.
- **query latency** — p50 / p90 / p99, in milliseconds.
- **build time** and **memory** — resident bytes, split into the per-vector cost
  (what one more chunk adds) and fixed overhead (IVF-PQ's codebooks, which a large
  corpus amortises).

Each index's query-time dial is what the sweep varies: **efSearch** for HNSW (how
wide the search beam is), **nprobe** for IVF-PQ (how many cells it scans). Bigger
values buy recall and cost latency — that pair *is* the tradeoff curve.

## Measured results (synthetic, 384-d, clustered)

Two corpus sizes, the same 384-d MiniLM geometry the real embedder produces,
40 clusters, 200 held-out queries, k=10:

| n | index | recall@10 | latency (p50) | build | memory | per-vector |
|---|-------|-----------|---------------|-------|--------|------------|
| 2,000 | flat | **1.000** | **0.079 ms** | 0.01 s | 3.1 MB | 1536 B |
| 2,000 | hnsw (ef=64) | 0.925 | 0.547 ms | 17 s | 3.3 MB | 1664 B |
| 2,000 | ivfpq (nprobe=16, m=48) | 0.590 | 5.49 ms | 5.4 s | **0.6 MB** | **48 B** |
| 8,000 | flat | **1.000** | **0.168 ms** | 0.00 s | 12.3 MB | 1536 B |
| 8,000 | hnsw (ef=64) | 0.711 | 0.563 ms | 64 s | 13.3 MB | 1664 B |
| 8,000 | ivfpq (nprobe=16, m=48) | 0.402 | 5.09 ms | 19 s | **1.1 MB** | **48 B** |

Three things fall out of this, and the third is the one that matters for this
project.

**1. IVF-PQ's win is memory, and it grows with scale.** 48 bytes per vector
against flat's 1536 — a **32× compression** — because each vector becomes 48
one-byte codes instead of 384 floats. At 2k the fixed codebooks make the *total*
only 5× smaller; at 8k it is 11×; at a million vectors it approaches the full 32×.
That is exactly the regime IVF-PQ is built for: when the corpus will not fit in
RAM as raw floats, this is how you shrink it. The cost is recall (0.59, then 0.40
as the same nprobe spreads over more cells) and, here, latency.

**2. HNSW's recall falls as the corpus grows at fixed efSearch** (0.925 → 0.711).
That is not a defect — it is the efSearch dial telling you a bigger graph needs a
wider beam. Push efSearch up and recall climbs back toward 1.0, at proportional
latency. HNSW's memory tracks flat's (it stores the full vectors *plus* the
graph), so it is the choice when you want near-exact recall at low latency and
can spend the RAM.

**3. At a few thousand chunks, you do not need an approximate index at all.**
Flat search is faster than both here (0.08–0.17 ms), exact by definition, builds
instantly, and its memory (3–12 MB) is nothing. A personal RAG corpus — a few
hundred PDF pages is a few thousand chunks — sits squarely in this regime. The
approximate indexes are a *pessimisation* at this scale.

## The caveat that reframes the latency column

These indexes are pure Python. FAISS and hnswlib are vectorised C++, and the
constant-factor gap is enormous — often 100×. So the **absolute latencies above
are not what production hardware would show**, and in two specific ways:

- HNSW's per-node graph walk and IVF-PQ's per-cell table construction are
  interpreted here, which is why they lose to flat's single BLAS matmul. In C++,
  HNSW queries in ~10 µs and overtakes a linear scan somewhere around 10k–100k
  vectors; IVF-PQ's table lookups are microseconds.
- Flat's advantage at small n is real regardless of language — a matmul over a few
  thousand vectors is genuinely fast — but the crossover point where ANN wins
  moves *down* with a compiled implementation.

What the hand-written version measures **correctly** is the shape that does not
depend on constant factors: the **memory ratios** (IVF-PQ codes are 32× smaller,
full stop) and the **recall/parameter curves** (recall vs efSearch, recall vs
nprobe, recall vs m). Those are algorithmic, and they transfer. Read the latency
column as *ordering within one language*, not as production numbers.

## The reference column: what C++ actually costs

Rather than leave that caveat as prose, the sweep can draw it. With `faiss-cpu`
installed (the `bench` extra), the benchmark adds two **reference** rows —
`faiss_hnsw` and `faiss_ivfpq`, the *same* algorithms from FAISS's compiled
library, swept over the same dials. On the chart they are **dashed lines**,
deliberately set apart: not the thing under test, just the speed the tested
algorithms run at once compiled. The gap between a solid line and its dashed twin
*is* the constant factor.

Measured, 2,000 × 128-d, at matched parameters:

| algorithm | impl | recall | latency (p50) | build |
|-----------|------|--------|---------------|-------|
| HNSW (ef=160) | hand-written Python | 1.000 | 0.95 ms | 12.0 s |
| HNSW (ef=160) | **FAISS (C++)** | 1.000 | **0.10 ms** | **0.06 s** |
| IVF-PQ (nprobe=32) | hand-written Python | 0.701 | 3.53 ms | 1.5 s |
| IVF-PQ (nprobe=32) | **FAISS (C++)** | 0.66 | **0.07 ms** | **0.14 s** |

The recall lines track each other — same algorithm — while **query latency is
~10× (HNSW) to ~50× (IVF-PQ) lower in C++, and build time up to ~200× lower**.
That is the entire content of the "these are Python constant factors" caveat, now
a number you can point at. Two honest details: FAISS's IVF-PQ recall sits a little
below the hand-written one here (different training and neighbour-selection
defaults, not a better or worse method), and FAISS's own latencies are so low they
brush up against flat's — which only sharpens the real conclusion: **the crossover
where any ANN index beats a linear scan moves down substantially once you leave
pure Python**, but at a personal-corpus scale flat still wins even against C++.

## Recovering IVF-PQ's recall: coarse-retrieve, then exact-rerank

IVF-PQ has a recall *ceiling*. Its quantized codes are too coarse to order
neighbours correctly, so past a certain point raising `nprobe` stops helping — it
scans more cells but still can't rank what it finds. In the sweep below the
ceiling is **0.701**, and nprobe 4, 8, 16, 32 all sit on it.

The fix is the pattern production systems actually ship. The approximate index
does not have to *rank* the neighbours, only *gather* them, and gathering a
correct oversized shortlist is the easy half. So ask IVF-PQ for `k × oversample`
candidates instead of `k`, then re-score just those candidates with the exact
full-precision vectors and keep the true top-k. A handful of exact dot products —
`k × oversample`, not the whole corpus — undoes the mis-ranking.

Synthetic sweep, 2,000 × 128-d, 40 clusters, k=10, oversample=8, cells holding
~31 vectors each (so there is a shortlist to reorder):

| index | nprobe | recall@10 | latency (p50) | hot B/vec | amortised B/vec |
|-------|--------|-----------|---------------|-----------|-----------------|
| ivfpq | 4 | 0.701 | 0.48 ms | 16 | 16 |
| ivfpq | 32 | 0.701 *(ceiling)* | 3.47 ms | 16 | 16 |
| ivfpq + rerank | 1 | 0.853 | 0.29 ms | **16** | 528 |
| ivfpq + rerank | 4 | **1.000** | 0.75 ms | **16** | 528 |

Two things to read off this:

**1. Rerank breaks the ceiling for almost nothing.** 0.701 → 1.000 at nprobe 4,
for ~0.27 ms of extra work. Even at nprobe 1 it beats bare IVF-PQ at *any* nprobe
(0.853 vs 0.701). This is why real IVF-PQ deployments are nearly always IVF-PQ
*plus* a rerank pass.

**2. The memory win survives — in the tier that counts.** Rerank needs the full
vectors reachable to re-score. In production they live on disk/SSD as a *cold*
tier and only the few candidate rows are fetched, so the *hot* RAM footprint stays
the 16-byte PQ codes — the `hot B/vec` column, unchanged. This in-memory harness
has no disk tier, so it keeps the full vectors resident and reports that honestly
in `amortised B/vec` (528 = 16 codes + 512 for the 128-d floats). The number that
transfers to a real deployment is the hot one.

**At the other end of the scale** the shortlist becomes the whole story: at
100k vectors the rerank ceiling under `nprobe` alone falls to 0.73, and it is
`oversample` — a longer shortlist, not more cells — that lifts it back to 0.99.
Measured in [`ivfpq-100k.md`](ivfpq-100k.md).

**The scale caveat, again.** Rerank only helps when the shortlist holds more than
`k` good-but-mis-ordered candidates. On a *tiny* corpus it doesn't: at 52 chunks
the coarse quantizer makes ~52 near-singleton cells, so `nprobe` alone fixes the
candidate set and there is nothing for the exact pass to reorder — on the live
52-chunk corpus, `ivfpq` and `ivfpq_rerank` score identically. Like everything
else here, rerank earns its keep at scale, not on a personal corpus.

## When to use which — the short version

| Situation | Index | Why |
|-----------|-------|-----|
| A few thousand chunks (a personal corpus) | **Flat** | Exact, fastest at this scale, trivial memory, zero tuning. |
| Large corpus, RAM is plentiful, recall matters most | **HNSW** | Near-exact recall at low latency; costs memory (vectors + graph). |
| Large corpus, memory is the binding constraint | **IVF-PQ** | 32× smaller codes; accept a recall hit, tune it back with nprobe and m. |
| Large corpus, memory-bound but recall must stay high | **IVF-PQ + rerank** | PQ's tiny hot footprint *and* near-exact recall; full vectors sit cold on disk, fetched only for the shortlist. |
| Millions of vectors, on-device or edge | **IVF-PQ** | The only one of the three whose footprint stays small at scale. |

For *this* project as it stands, the answer is **flat**. The value of having HNSW
and IVF-PQ built and measured is knowing the exact conditions under which that
answer changes — and being able to re-run the sweep on a real corpus the day it
does, from the Index Lab, without guessing.

## Using an index in live retrieval, not just the benchmark

The comparison stops being academic when you can *switch* the running pipeline to
the index you chose. The dense half of retrieval — the vector-search step, before
BM25 fusion and reranking — is backed by a configurable index:

```bash
AGENTICRAG_ANN_INDEX=hnsw   # chroma (default) | flat | hnsw | ivfpq | ivfpq_rerank
```

- `chroma` (default) — ChromaDB's own vector search, exactly as before. Nothing
  changes unless you opt in.
- `flat` / `hnsw` / `ivfpq` / `ivfpq_rerank` — the hand-written index answers the
  dense half instead. It is built once from the stored embeddings, cached, and
  rebuilt whenever you ingest. Lexical retrieval, fusion and reranking are
  untouched; only the dense candidate source moves.

The active backend is reported at `GET /stats` as `dense_backend`, and the health
log line names it at startup. Because the indexes return the same ids on the same
cosine scale as Chroma, nothing downstream can tell the difference except in
recall and latency — which is the whole point. At personal-corpus scale the honest
choice remains `chroma`/`flat` (exact, instant); the switch exists so that when a
corpus grows into the regime where HNSW or IVF-PQ earns its keep, changing to it
is one environment variable, not a rewrite.

## Reproducing

- **In the UI**: open **Index Lab → Benchmark sweep** and click *Run benchmark
  sweep*. It sweeps the live corpus and plots recall against latency.
- **From the API**: `POST /ann/benchmark` (sweep) and `POST /ann/compare` (one
  query through every index side by side).
- **The crossover table above**: a synthetic sweep at fixed geometry; the harness
  is `tools/vector_db/ann/benchmark.py`, and the numbers here were produced by
  sweeping n ∈ {2000, 8000} at 384-d.
