# IVF-PQ at 100k vectors — where memory turns into latency

*Learning path §9, item 5. 2026-09-19. Cost: ₹0 (~55 minutes of laptop
CPU, no key). Decision: nothing ships — flat stays the default; the note
records the crossover and the one dial that actually moves IVF-PQ's
recall at scale.*

## Hypothesis

[`ann-comparison.md`](ann-comparison.md) measured the three indexes at 2k
and 8k vectors and found flat fastest, exact and smallest-effort at that
size — IVF-PQ's win was memory (48 B/vector against 1,536) and nothing
else. The open question it left: at what size does the memory story become
a latency story too? Flat's cost is one `n × 384` matmul per query and
grows linearly; IVF-PQ's is `nprobe` cells of ~100 vectors regardless of
`n`. Claim, written before running: **at n = 100k the hand-written
IVF-PQ + rerank beats flat on p50 latency at recall@10 ≥ 0.9.** Rule:
record the crossover either way; no product change (the live corpus is
~2k chunks). HNSW is run last as the reference for the same question,
skipped if its build passes 40 minutes (it took 29).

## Setup

Same geometry as the earlier note — 384-d (the MiniLM shape), 40 Gaussian
clusters, spread 0.35, 200 held-out corpus vectors as queries, k = 10,
seed 42 — at n = 25k (a middle point) and n = 100k. IVF-PQ at
`nlist = 256` (25k) and `1024` (100k), so cells hold ~100 vectors at both
sizes; `m ∈ {48, 16}`; `nprobe` swept 1–64; rerank at `oversample = 8`.
HNSW at `M = 16, efConstruction = 200`, efSearch 10–160. Ground truth is
the exact flat index over the same normalised matrix. Everything is the
pure-NumPy implementation in `tools/vector_db/ann/`; `faiss` is not
installed on this machine, so there is no C++ reference row this time.
Machine: 8-core laptop, single process.

## Results

Flat, the bar to beat: **0.79 ms** at 25k, **3.72 ms** at 100k
(38 MB and 154 MB resident). Linear in n, as it should be.

**IVF-PQ, m = 48 (48 B/vector hot; 6.8 MB total at 100k, 23× smaller
than flat):**

| n | nprobe | ivfpq recall | ivfpq p50 | + rerank (×8) recall | rerank p50 |
| --- | --- | --- | --- | --- | --- |
| 25k | 4 | 0.369 | 1.49 ms | 0.772 | 1.75 ms |
| 25k | 8 | 0.385 | 2.82 ms | 0.858 | 2.97 ms |
| 25k | 16 | 0.385 *(ceiling)* | 5.28 ms | 0.859 *(ceiling)* | 5.56 ms |
| 100k | 4 | 0.256 | 1.68 ms | 0.424 | 1.93 ms |
| 100k | 8 | 0.295 | 3.20 ms | 0.582 | 3.27 ms |
| 100k | 16 | 0.324 | 6.01 ms | 0.708 | 5.94 ms |
| 100k | 32 | 0.329 *(ceiling)* | 11.5 ms | 0.727 *(ceiling)* | 11.2 ms |

Build: 50 s at 25k, 280 s at 100k (k-means over 1,024 cells plus 48 PQ
codebooks, in Python). `m = 16` (16 B/vector) was swept too and is not
worth a table: its rerank ceiling is 0.59 at 25k and 0.39 at 100k — at
384-d, 16 sub-quantizers of 24 dimensions each is too coarse for anything
but the cheapest first pass.

**HNSW, M = 16:**

| n | efSearch | recall | p50 | build | memory |
| --- | --- | --- | --- | --- | --- |
| 25k | 10 | 0.989 | 0.31 ms | 283 s | 42 MB |
| 25k | 40 | 1.000 | 0.62 ms | | |
| 25k | 80 | 1.000 | 0.91 ms | | |
| 100k | 10 | 0.890 | 0.38 ms | 1,723 s | 167 MB |
| 100k | 20 | 0.939 | 0.56 ms | | |
| 100k | 40 | 0.971 | 0.89 ms | | |
| 100k | 80 | 0.996 | 1.48 ms | | |
| 100k | 160 | 1.000 | 2.30 ms | | |

HNSW at 100k: recall 0.996 at 1.48 ms (ef 80) and 1.000 at 2.30 ms
(ef 160), both under flat's 3.72 ms — at ef 20 it is 7× faster than flat
at 0.94. Its build is the cost: 29 minutes in Python for 100k inserts,
against IVF-PQ's 5 and flat's half a second. Memory is flat's plus 8%
for the graph.

**The hypothesis fails.** At 100k, IVF-PQ + rerank does reach latency
parity with flat — nprobe 8, 3.27 ms against 3.72 — but at recall 0.58,
and turning nprobe up buys nothing past 0.73 at any latency. The latency
crossover for IVF-PQ is real and sits at ≈100k in pure Python; the recall
condition is what it cannot meet with this configuration.

**What moved instead: the recall ceiling fell with n.** Rerank's ceiling
went 1.00 (2k, 128-d) → 0.86 (25k) → 0.73 (100k) with nothing changed but
the corpus size. That is the finding of this run. Cells hold ~100 vectors
at both sizes, so it is not that the cells got bigger; it is that the
clusters got *denser*. With 2,500 points per Gaussian blob in 384-d the
true top-10 sit inside a shell of near-equidistant neighbours, and the
per-vector quantization error of PQ is larger than the gap between the
10th and the 80th neighbour. The PQ scan does gather the right cells; it
then hands the exact pass 80 candidates that mostly are not the ten it
needed. `nprobe` is the wrong dial for this — it widens *coverage*, and
coverage was already complete.

## Follow-up: is it coverage or ordering?

Pre-registered before running: if the ceiling is ordering, recall should
rise with `oversample` at fixed nprobe and reach ≥ 0.9 by 64, with only
the cheap exact pass growing. Same 100k index, nprobe fixed:

| nprobe | oversample | candidates | recall@10 |
| --- | --- | --- | --- |
| 16 | 8 | 80 | 0.708 |
| 16 | 16 | 160 | 0.825 |
| 16 | 32 | 320 | **0.911** |
| 16 | 64 | 640 | 0.951 |
| 16 | 128 | 1,280 | 0.959 |
| 32 | 32 | 320 | 0.947 |
| 32 | 64 | 640 | **0.990** |
| 32 | 128 | 1,280 | 0.999 |

Confirmed: it is ordering. Oversample 32 lifts recall 0.71 → 0.91 at
nprobe 16, and 64 at nprobe 32 reaches 0.99 — the coarse index is
gathering the right neighbourhood, it just cannot rank inside it. The
exact pass over 640 candidates is one (640 × 384) matmul, about a
millisecond. (This follow-up ran while the HNSW build occupied another
core, so its absolute latencies are ~40% above the main table's and are
not quoted; the recall column is what it was for.)

So the honest 100k configuration is **nprobe 16–32, oversample 32–64: recall
0.91–0.99 at roughly 7–13 ms, 48 B/vector hot.** Against flat's 3.7 ms that
is 2–3× slower, in Python. The C++ reference in the earlier note put
IVF-PQ's constant factor at ~50×, which would place the same configuration
well under a millisecond — and there the memory story and the latency
story are the same story. In pure NumPy they are not, at 100k.

## What this says

1. **IVF-PQ's recall dial at scale is `oversample`, not `nprobe`.** Both
   earlier notes swept nprobe and called the plateau a "PQ ceiling"; that
   was right about the cause and wrong about the fix. The ceiling is the
   quantized ordering, and the cure is to hand the exact pass a longer
   shortlist. A production IVF-PQ deployment sets `nprobe` for coverage
   and `k × oversample` for the reranker, and tunes the second on real
   queries.
2. **The pure-Python latency crossover for IVF-PQ is ≈100k vectors**, and
   only at recall ~0.6. For HNSW it is ≈25k at recall 1.0 (see the table)
   — which is why "large corpus, RAM is fine" → HNSW in the earlier
   decision table stands. IVF-PQ earns its place on memory alone.
3. **Synthetic blobs are a pessimistic case for PQ.** Isotropic Gaussians
   give sub-vectors nothing to exploit; real embeddings live on a lower-
   dimensional manifold with correlated sub-spaces, which is what the PQ
   codebooks (and OPQ's rotation) are built to capture. The ceilings
   here are lower bounds, not predictions for a real 100k-chunk store.
4. **None of it changes the product.** The live store is ~2k chunks; flat
   is exact at well under a millisecond and needs no tuning. The switch
   (`SEXTANT_ANN_INDEX=ivfpq_rerank`) exists for the day a corpus is
   fifty times larger, and this note is what to set when that day comes.

## Reproducing

`exp_ivfpq_100k.py` and `exp_ivfpq_oversample.py` (session scratchpad;
both are ~80 lines over `tools/vector_db/ann/` and are reproduced by the
setup above). Runtime: 25k ≈ 8 min, 100k ≈ 40 min including the HNSW
build (29 min of it), follow-up ≈ 5 min.
