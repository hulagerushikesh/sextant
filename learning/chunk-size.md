# Experiment 3 — Chunk size without the 256 ceiling

*Milestone 16, 2026-09-16. Cost: ₹0 (about an hour of laptop CPU).
Decision: 200 stays the default; chunk size becomes a setting.*

## Hypothesis

The 200/40 chunking was chosen for MiniLM's 256-token window, not for the
content. With a 512-token embedder (bge-small, experiment 4) larger chunks
might help hit@1 — more context per hit — or hurt, through the dilution
measured in Phase 4 (0.94 → 0.44 when a sentence shares a chunk with three
neighbours). Rule, written first: keep 200 unless a size wins on **both**
golden sets by ≥ 0.03 hit@1.

## Setup

Target ∈ {150, 200, 300, 400} tokens, overlap a fifth of the target,
× {MiniLM, bge-small + query prefix}: eight stores, each the 21 handbook
documents plus the pinned survey (v19, PyMuPDF), both golden sets, all
four modes. Row chunks (experiment 1) are unaffected by the target and
identical across the sweep.

What a larger target means for MiniLM, measured before running anything:

| target | survey chunks | prose median tokens | chunks over 256 | prose tokens MiniLM cannot see |
| --- | --- | --- | --- | --- |
| 150 | 2,217 | 139 | 0% | 0% |
| 200 | 1,608 | 189 | 0% | 0% |
| 300 | 1,073 | 289 | 93% | 10.8% |
| 400 | 828 | 390 | 98% | 33.7% |

So for MiniLM, 300 and 400 are not "bigger chunks", they are chunks with
the tail cut off. bge's 512 window sees all of them. That asymmetry is the
point of running both.

## Results

Survey set, 38 questions:

| embedder | target | dense hit@1 | dense r@5 | rrf hit@1 | rrf r@5 | rerank hit@1 | rerank r@5 | rerank MRR | misses |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MiniLM | 150 | 0.758 | 0.909 | **0.939** | 0.985 | **0.939** | 0.985 | **0.962** | L25 |
| MiniLM | 200 | 0.727 | 0.909 | 0.879 | 0.985 | 0.909 | 0.985 | 0.946 | L25 |
| MiniLM | 300 | 0.636 | 0.909 | 0.879 | 0.985 | 0.909 | 0.985 | 0.955 | L25 |
| MiniLM | 400 | 0.606 | 0.773 | 0.758 | 0.955 | 0.879 | 1.000 | 0.927 | L13 |
| bge | 150 | 0.727 | 0.909 | 0.818 | 0.985 | **0.939** | 0.985 | **0.962** | L25 |
| bge | 200 | 0.758 | 0.909 | 0.818 | 0.955 | 0.909 | 0.985 | 0.946 | L25 |
| bge | 300 | **0.788** | 0.909 | 0.818 | 0.985 | 0.909 | 0.985 | 0.955 | L25 |
| bge | 400 | 0.727 | 0.909 | 0.849 | 0.985 | 0.879 | 1.000 | 0.927 | L13 |

Handbook set, 60 questions, same mixed store:

| embedder | target | dense hit@1 | dense r@5 | rrf hit@1 | rrf r@5 | rerank hit@1 | rerank r@5 | rerank MRR | misses |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MiniLM | 150 | 0.720 | 0.930 | 0.880 | 0.970 | **0.980** | 0.970 | **0.987** | q36 q47 q48 |
| MiniLM | 200 | **0.820** | **0.950** | 0.880 | 0.940 | 0.940 | 0.970 | 0.964 | q36 q47 q48 |
| MiniLM | 300 | 0.720 | 0.870 | 0.840 | 0.950 | 0.960 | 0.970 | 0.980 | q36 q47 q48 |
| MiniLM | 400 | 0.760 | 0.850 | 0.820 | 0.920 | 0.920 | 0.980 | 0.957 | q36 q48 |
| bge | 150 | 0.740 | 0.870 | 0.860 | 0.970 | 0.960 | 0.970 | 0.977 | q36 q47 q48 |
| bge | 200 | 0.740 | 0.840 | 0.840 | 0.940 | 0.940 | 0.950 | 0.960 | q29 q36 q47 q48 |
| bge | 300 | 0.680 | 0.830 | 0.840 | 0.950 | 0.940 | 0.950 | 0.960 | q29 q36 q47 q48 |
| bge | 400 | 0.740 | 0.830 | 0.840 | 0.930 | 0.900 | 0.960 | 0.937 | q29 q36 q48 |

Handbook alone (the store the CI gate grades), MiniLM, 150 against the
committed 200 baseline: rerank hit@1 **+0.04**, dense hit@1 **−0.06**,
RRF hit@1 −0.04, lexical +0.02.

## What the numbers say

**Bigger is not better, for either embedder.** The hypothesis was that 200
was an artefact of MiniLM's window and a 512-window model would like 300
or 400. bge does gain dense hit@1 at 300 on the survey (0.788, its best
number anywhere), but the reranked result is flat at 300 and down at 400
on both sets, for both models. Recall@5 *rises* with size (400 reaches
1.000 on the survey) because a page-sized chunk is an easy page-level hit
— and hit@1 falls, because the cross-encoder is ranking chunks that each
say five things. Dilution beats truncation as the explanation: MiniLM at
300 has lost 11% of every chunk and its rerank score is identical to
bge's, which lost nothing.

**MiniLM's cliff is real and mostly invisible through the pipeline.**
Dense hit@1 on the survey falls 0.727 → 0.636 → 0.606 as the window
truncates. Rerank does not move until 400, because BM25 and the
cross-encoder both read the whole chunk; only the dense leg is blind to
the tail. That is a good argument for hybrid retrieval and a bad argument
for ever running MiniLM past 256 — which the knob below now refuses.

**Smaller is better for the reranked pipeline, and worse for dense.** 150
wins rerank hit@1 on both sets and both embedders: +0.030 on the survey
(one question in 33), +0.040 on the handbook (two in 50). Each chunk says
one thing, so the cross-encoder's top pick is the right one more often.
But it costs 37% more chunks, and on the handbook dense hit@1 drops
0.82 → 0.72 in the mixed store and 0.86 → 0.80 alone: the crowding effect
from experiment 1 again, more chunks per document competing for five
slots that are graded per document.

## Decision

**200 stays.** The sweep rule was met — 150 clears ≥ 0.03 on both sets,
on the survey by exactly one question — and the milestone's definition of
done (the CI gate stays green, all modes) was not: dense and RRF regress
past the 0.02 tolerance on the handbook-alone store. When two
pre-registered criteria disagree the stricter one wins, and re-baselining
to make a regression disappear is not a result. This is the second
experiment in the milestone where the reranked pipeline improves while
the dense ablation degrades through crowding; that pattern is now the
thing to fix, not to route around (see below).

What ships: `SEXTANT_CHUNK_TOKENS` (overlap follows at a fifth), so a
corpus owner who runs the reranked pipeline on a large paper corpus can
re-ingest at 150 and take the +0.03; the knowledge base refuses a target
past the embedder's window at startup, since the table above says what
that costs. Changing it means re-ingesting; the store does not record
its chunk size (it could — a follow-up if the knob gets used).

## What would change the decision

- **A per-document cap on the candidate list** (diversification before
  the reranker, e.g. at most *n* chunks per document in the fused top-30).
  It would remove the crowding that has now cost two experiments their
  dense numbers, and if it does, 150 becomes the default on the evidence
  here. That is a retrieval change with its own hypothesis and belongs in
  its own note; it is the first candidate for Milestone 17.
- A golden set whose questions need more than one sentence of context per
  hit (procedures, derivations). None of the current 98 do.
- Sizes between 150 and 200, or below 150. The curve has four points; the
  rerank optimum is at or below the smallest one, and 100-token chunks
  would start to split sentences.

## Reproduce

```bash
SEXTANT_CHUNK_TOKENS=150 SEXTANT_CHROMA_DIR=/tmp/c150 \
  ./.venv/bin/sextant-ingest eval/corpus/*.md --category handbook
./.venv/bin/sextant-eval --store /tmp/c150
SEXTANT_CHUNK_TOKENS=400 ./.venv/bin/sextant-eval --store /tmp/c150   # refused: 400 > 256
```
