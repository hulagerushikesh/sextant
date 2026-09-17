# Experiment 1 — Per-document candidate cap

*Milestone 17, 2026-09-17. Cost: ₹0 (twelve local eval runs, ~15 minutes
of laptop CPU). Decision: shipped, `MAX_PER_DOCUMENT = 2`, guarded, dense
and rerank only.*

## Hypothesis

Three Milestone 16 experiments — one-row table chunks, 150-token chunks,
summary chunks — lost dense recall@5 the same way: more chunks per
document, and the five graded slots filled by siblings of the document
already found while the second relevant document sat at rank six. Each
note ended "a per-document cap is overdue". The claim to test: cap the
returned list at *N* chunks per document, backfill the cut ones in score
order so nothing is ever lost, and dense recall@5 comes back without
anything else moving. Rule, written first: ship as default if at some *N*
the with-summaries store recovers dense recall@5 to within 0.02 of the
no-summaries store, no CI-store metric drops past the 0.01 gate, survey-set
recall@5 drops by no more than 0.02 in any mode, and rerank hit@1 does not
drop anywhere.

## Setup

Three stores kept from experiment 5, so the control numbers are the ones
already in `summary-chunks.md`: the CI store (58 chunks, 65 questions),
the same handbook with summaries (79 chunks — the crowding case, dense
recall@5 0.970 → 0.900 in exp 5), and the mixed store (handbook + 144-page
survey + summaries, 1,688 chunks; 65 handbook questions graded by document,
39 survey questions graded by page). Cap ∈ {off, 2, 3}, all four modes,
`min_score = 0`.

## Results, in three rounds

**Round 1, hard cap.** Dense recovered exactly as predicted: summaries
store 0.900 → 0.973, mixed store 0.882 → 0.955, CI store 0.955 → 0.973.
Rerank hit@1 unchanged on every store. And the survey set lost — rerank
recall@5 0.985 → 0.956, one question.

| store · mode | off | cap 2 | cap 3 |
| --- | --- | --- | --- |
| summaries · dense r@5 | 0.900 | **0.973** | 0.909 |
| mixed, handbook q · dense r@5 | 0.882 | **0.955** | 0.900 |
| CI store · dense r@5 | 0.955 | **0.973** | 0.964 |
| mixed, survey q · rerank r@5 | 0.985 | 0.956 | 0.956 |
| mixed, survey q · rrf r@5 | 0.985 | 0.956 | 0.956 |

The question was L13, "how does a language model pick each next word if it
always takes the single most probable option" — greedy decoding, page 26.
Uncapped, the cross-encoder had it at rank 5 scoring 0.013 behind four
other survey pages. With two survey chunks allowed, slots 3 and 4 went to
`kalman-filter` and `mot-metrics` — the next documents in the list, scored
0.000 — and page 26 backfilled to rank 6. Cap 3 gave the same loss for a
third of the gain. Rule not met.

**Round 2, score-guarded cap.** The failure is a hard cap treating a chunk
scoring nothing as a document that deserves a slot. Dense siblings that
crowd score within a few percent of the chunk they push out (0.526 vs
0.507 on L13's dense list); the handbook chunks that took L13's slot
scored a thirtieth of it. So: a chunk over the cap is skipped only when
the next uncapped document scores at least half of it
(`MIN_DISPLACE_RATIO = 0.5`). L13 came back — survey rerank 0.985 again —
and survey dense went *up*, 0.912 → 0.941, with every dense gain from
round 1 held. Two ablation modes still lost: survey lexical 0.971 → 0.941
(L27) and rrf 0.985 → 0.956 (L13 again). An RRF score is a rank artefact:
rank 25 scores 0.74 × rank 3, so the guard never fires and under fusion
the cap is hard again. This is the same fact that keeps `min_score` off
fusion ranks.

**Round 3, cap only where a score is a relevance.** `_diversify` runs when
`scored_by` is `cosine` or `cross-encoder`; under BM25 and RRF the list is
returned as ranked. Production is rerank, so nothing about what ships
changed between rounds 2 and 3 — the ablation became honest.

| store | mode | off r@5 | shipped r@5 | Δ | hit@1 |
| --- | --- | --- | --- | --- | --- |
| CI store (58) | dense | 0.955 | 0.973 | +0.018 | 0.873 = |
| CI store (58) | rerank | 0.964 | 0.964 | 0 | 0.909 = |
| summaries (79) | dense | 0.900 | 0.973 | **+0.073** | 0.873 = |
| summaries (79) | rerank | 0.964 | 0.964 | 0 | 0.964 = |
| mixed, handbook q | dense | 0.882 | 0.955 | **+0.073** | 0.836 = |
| mixed, handbook q | rerank | 0.955 | 0.955 | 0 | 0.946 = |
| mixed, survey q | dense | 0.912 | 0.941 | +0.029 | 0.735 = |
| mixed, survey q | rerank | 0.985 | 0.985 | 0 | 0.912 = |
| any store | lexical, rrf | — | unchanged | 0 | = |

All four conditions met. The with-summaries store now scores what the
no-summaries store does on dense; the argument against `--summaries` as a
default is down to "needs a key at ingest time".

## What the numbers say

**Crowding was the right diagnosis, and only for dense.** The reranker was
never hurt by siblings in M16 because it reads the passage and scores the
sibling that does not answer the question near zero; the bi-encoder scores
every sibling near the one that does. A cap is a dense-retrieval fix, and
it is right that it changes nothing under the cross-encoder except the
rare list where two documents genuinely tie.

**Diversity without a score is noise.** The round-1 loss was not bad luck;
it is what a hard cap does whenever the corpus has one long document and
several short ones — the short ones always have "a chunk waiting". The
guard is the whole idea: a document takes a slot when it is competitive,
not because it exists.

**Why 2, not 3.** Multi-hop questions need two documents in five slots;
global questions need up to five. At 3, one document can hold three of
five and the second relevant document has two chances; at 2 it has three.
The measured difference on the summaries store was 0.973 vs 0.909.

## Decision

**Shipped as the default, `SEXTANT_MAX_PER_DOCUMENT=2`, `0` turns it off.**
`baseline.json` regenerated (dense recall@5 0.955 → 0.973); `baseline-large.json` is unchanged — the survey-set dense gain is on the store with summaries, and the CI store for that set has none. Guard and mode restriction are constants, not
knobs; neither has a second value worth exposing.

## What would change the decision

- A corpus of many long documents where a question's two relevant pages
  are usually in one document: the cap could push the second page to
  rank 3 in favour of a competitive chunk from a neighbouring paper. The
  survey set has one such document and gained; ten would be the test.
- A future embedder whose cosines are compressed (bge's are — see
  `embedder-swap.md`) could make the 0.5 guard pass more often than it
  should. Re-run this note's table when the embedder changes.

## Reproduce

```bash
SEXTANT_MAX_PER_DOCUMENT=0 ./.venv/bin/sextant-eval --out /tmp/off.json
SEXTANT_MAX_PER_DOCUMENT=2 ./.venv/bin/sextant-eval --out /tmp/cap.json
./.venv/bin/sextant-eval --store ./chroma_db --golden eval/golden-large.jsonl
```

The summaries and mixed stores need `sextant-ingest --summaries`, which
needs a key (`summary-chunks.md`, Reproduce).
