# IVF with an HNSW coarse quantizer at 1M vectors — when finding the cells is itself a search

*Learning path §9, item 6. 2026-09-19. Cost: ₹0 (~50 minutes of laptop
CPU, no key). Decision: nothing ships — flat stays the default; the note
records where the graph-over-centroids trick pays, by how much, and the
half of the hypothesis it does not confirm.*

## Hypothesis

[`ivfpq-100k.md`](ivfpq-100k.md) left HNSW and IVF-PQ as rivals: HNSW wins
recall and latency at every size measured, IVF-PQ wins memory. The
planning note that followed decided against routing *between* them per
query. This run is the other combination — the one FAISS calls
`IVF65536_HNSW32,PQ48`: HNSW is not an alternative to the inverted file,
it is the inverted file's *coarse quantizer*. Every IVF query starts by
finding the `nprobe` nearest centroids, and at `nlist = 4,096` that is a
6 MB matmul nobody notices. At `nlist = 65,536` the centroid matrix is
100 MB and the "find the cells" step reads all of it, per query; a graph
over the centroids reads a few hundred rows instead.

Claim, written before running: **at nlist = 65,536 the brute-force
coarse step dominates the query, and the HNSW coarse quantizer finds
≥ 90% of the same nprobe cells and cuts p50 by ≥ 2× at equal (within
0.02) recall@10. At nlist = 4,096 HNSW buys nothing measurable
(control).** Rule: note only; nothing ships, the live corpus is ~2k
chunks.

One bug is on the record: the first attempt dropped the per-cell
`‖q − c_p‖²` term from the ADC tables, so distances from different cells
were not comparable and recall *fell* as `nprobe` rose. It was killed,
fixed, and re-run from scratch at 22:00; no number below predates the fix.

## Setup

1M × 384-d unit vectors in **1,000** Gaussian clusters of ~1,000 points
each (spread 0.35, seed 42) — not the 40 blobs of the earlier notes,
because 25,000 points per blob is exactly the density where the 100k note
showed PQ ordering collapses, and this run is about coarse *routing*, not
PQ ordering. 200 held-out corpus vectors as queries, k = 10, ground truth
exact. IVF-PQ at `m = 48`, `oversample = 32`, exact rerank of the 320
candidates from the raw matrix. Two coarse sizes: `nlist = 4,096` (~244
vectors per cell, the FAISS `4√n` rule — the control) and `nlist = 65,536`
(~15 per cell, the regime the trick exists for). Coarse assignment two
ways per query: brute (one BLAS matvec against every centroid,
`argpartition` for the top nprobe) and the repo's `HnswIndex`
(`M = 16, efConstruction = 200`) built over the centroids, at
`efSearch = 2×nprobe` and `4×nprobe` (floor 32). Cell overlap is the
fraction of brute's nprobe cells the graph also returned. Coarse k-means is
a batched, one-hot-CSR implementation (the repo's `_kmeans` holds an
`n × k` distance matrix and is unusable at k = 65k); PQ codebooks from
`_kmeans` on 100k residuals. Machine: 8-core, 8 GB laptop; single
process; 20-query warm-up before each configuration.

## Results

**Build:**

| nlist | coarse k-means | PQ train + encode | HNSW over centroids | total |
| --- | --- | --- | --- | --- |
| 4,096 | 28 s | 216 s | 47 s | ~5 min |
| 65,536 | 1,516 s | 310 s | 722 s | ~42 min |

At 65,536 the cells are lopsided — median 4 vectors, max 843, none empty
— because 1,000 blobs cannot fill 65k cells evenly however k-means tries.
The HNSW over 65k centroids costs 12 minutes in Python: it is a 65k-vector
HNSW build, same as any other.

**Control, nlist = 4,096** (centroids 6.3 MB; recall 0.986 for every row):

| coarse | nprobe | ef | p50 | coarse p50 | cell overlap |
| --- | --- | --- | --- | --- | --- |
| brute | 8 | — | 10.28 ms *(page-in, see below)* | 0.15 ms | 1.00 |
| hnsw | 8 | 32 | 1.63 ms | 0.51 ms | 0.91 |
| brute | 16 | — | 2.31 ms | 0.07 ms | 1.00 |
| hnsw | 16 | 32 | 2.69 ms | 0.56 ms | 0.89 |
| brute | 32 | — | 4.51 ms | 0.08 ms | 1.00 |
| hnsw | 32 | 64 | 5.13 ms | 0.95 ms | 0.89 |
| brute | 64 | — | 8.80 ms | 0.10 ms | 1.00 |
| hnsw | 64 | 128 | 10.67 ms | 1.80 ms | 0.90 |

The control comes out as predicted: brute coarse assignment over 4,096
centroids is 0.07–0.15 ms, the graph walk is 0.5–1.8 ms, and HNSW makes
every row *slower* by that difference while missing ~10% of the cells.
At `4√n` cells there is nothing to save.

**nlist = 65,536** (centroids 100.7 MB):

| coarse | nprobe | ef | recall | p50 | coarse p50 | cell overlap |
| --- | --- | --- | --- | --- | --- | --- |
| brute | 8 | — | 0.787 | 21.13 ms *(page-in)* | 2.53 ms | 1.00 |
| hnsw | 8 | 32 | 0.786 | 1.39 ms | 0.52 ms | 0.99 |
| brute | 16 | — | 0.899 | 5.76 ms | 2.59 ms | 1.00 |
| hnsw | 16 | 32 | 0.895 | 4.94 ms | 0.77 ms | 1.00 |
| hnsw | 16 | 64 | 0.898 | **3.24 ms** | 0.95 ms | 1.00 |
| brute | 32 | — | 0.939 | 5.11 ms | 2.22 ms | 1.00 |
| hnsw | 32 | 64 | 0.939 | **3.27 ms** | 0.83 ms | 1.00 |
| hnsw | 32 | 128 | 0.939 | 4.04 ms | 1.43 ms | 1.00 |
| brute | 64 | — | 0.939 | 6.87 ms | 2.21 ms | 1.00 |
| hnsw | 64 | 128 | 0.939 | 7.10 ms | 1.62 ms | 0.92 |
| hnsw | 64 | 256 | 0.939 | 8.59 ms | 2.83 ms | 0.94 |

Two rows are not clean and are marked: the first configuration after
each build (brute, nprobe 8) pays for paging the 1.5 GB data matrix back
in after 4–12 minutes of training on an 8 GB machine — the 20-query
warm-up was not enough — and its p50 is a page-in cost, not a search
cost. The same shows in the p90s of the next two rows at 65k (9–15 ms
against 3–6 ms p50); by nprobe 32 the numbers are steady. The nprobe 8
HNSW row is listed once (both ef formulas floor to 32).

**The hypothesis half-holds.** Cell overlap is 0.99–1.00 at nprobe 8–32
and 0.92–0.94 at 64 — the graph finds brute's cells, comfortably past the
90% bar, and recall matches within 0.004 everywhere. The coarse step
itself is cut 2.7–4.9× at nprobe 8–32 (2.2–2.6 ms → 0.5–0.95 ms) and
1.4× at 64. But **the whole query is cut 1.6–1.8×, not 2×**: 5.76 →
3.24 ms at nprobe 16, 5.11 → 3.27 ms at nprobe 32, and nothing at
nprobe 64. The premise that the brute coarse
step *dominates* was wrong — it was 43–45% of the query, not most of it.
The other half is building 32 × 48 × 256 ADC table entries per probed
cell and scanning 32 cells' codes plus a 320 × 384 rerank, and the graph
does nothing for that. Amdahl: a 3–5× cut on 45% of the work is a 1.6–1.8×
cut on the whole. At nprobe 64, `efSearch = 128` walks enough of the
graph that its cost approaches the matmul it replaces, and the win closes.

**The regime itself is the more useful finding.** At nprobe 32 the two
coarse sizes cost about the same — 4.51 ms (4,096, brute) against
3.27 ms (65,536, HNSW) — but the 4,096-cell index is at recall 0.986 and
the 65,536-cell one tops out at **0.939** and stays there from nprobe 32
to 64. A 1,000-point blob split across ~65 cells of median size 4 means a
query's true top-10 are scattered over more cells than nprobe reaches;
the coarse quantizer is now the recall bottleneck, not PQ. The FAISS
guideline is `4√n`–`16√n` cells: 4k–16k at 1M, where brute assignment is
a 6–25 MB read and `IVF_HNSW` has no problem to solve. The same guideline
shelves `IVF65536_HNSW32` for 1M–10M and `IVF1048576_HNSW32` for
100M–1B — at 10M, 65k cells is inside the band with ~150 vectors per
cell, ten times the density here, where this ceiling should ease (not
measured; 10M × 384 floats is twice this laptop's RAM). At 1M it is 4× past
the top of the band; oversizing `nlist` to make the trick show up costs
0.05 recall on this data, and the trick then buys back a third of the
latency. That is the honest shape of it.

## What this says

1. **Graph and clusters do stack — at the coarse layer, and only where
   the coarse layer is big.** The graph over centroids returns the same
   cells brute force does (overlap 0.99+) at a quarter of the cost. It is
   a clean substitution with no recall price. Its worth is bounded by the
   share of the query the coarse step takes, and that share is under half
   even at 65k cells.
2. **`nlist` is a recall dial, not just a speed dial.** More cells means
   a neighbourhood spread over more of them; at fixed `nprobe` recall
   falls. The 0.986 → 0.939 drop from 4,096 to 65,536 cells at 1M points
   is the coarse quantizer fragmenting the blobs. `4√n` is where the two
   effects balance on this data; the 65k regime belongs to corpora 10×
   larger and up.
3. **The Python build is the real cost of the big-nlist regime:** 42
   minutes at 65k cells against 5 at 4k, and 12 of those minutes are
   HNSW over the centroids. In FAISS these are seconds; the ratio between
   the two `nlist` values is what transfers.
4. **The ADC bug is worth remembering.** With one residual per query the
   `‖r‖²` term is a constant and can be dropped; with a residual per
   probed cell it is not, and dropping it silently ranks cells against
   each other by the wrong number. The symptom — recall going *down* as
   `nprobe` goes up — is the tell.
5. **None of it changes the product.** The live store is ~2k chunks on a
   flat index. The per-query routing idea stays decided against; the
   request-level tier stays a candidate for a 25k+ corpus; `IVF_HNSW` is
   a note for a corpus three orders of magnitude larger than that.

## Reproducing

`exp_ivf_hnsw_1m.py OUT.json 1000000 4096,65536` (session scratchpad;
~150 lines over `tools/vector_db/ann/hnsw.py` and the `_kmeans` in
`ivfpq.py`, plus a batched k-means and an ADC scan of its own). Runtime
≈ 50 min, 1.1 GB resident; the run writes its JSON after every row.
