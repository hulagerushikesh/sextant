# Evaluation

Retrieval quality is a number. A number that is not checked drifts.

```bash
./.venv/bin/sextant-eval                     # grade every configuration
./.venv/bin/sextant-eval --check             # fail on regression vs baseline
./.venv/bin/sextant-eval --modes rrf rerank  # just these two

# The larger, page-labelled set against an existing store (read-only):
./.venv/bin/sextant-eval --store ./chroma_db --golden eval/golden-large.jsonl
```

Each run rebuilds the index from `corpus/` into a throwaway directory, so
grading never touches whatever you have actually ingested.

## What is here

| Path | |
| --- | --- |
| `corpus/` | 21 committed Markdown documents, ~5,000 words |
| `golden.jsonl` | 65 labelled questions over `corpus/` |
| `golden-large.jsonl` | 39 questions over a 144-page PDF, 38 page-labelled (see below) |
| `metrics.py` | hit@1, recall@k, MRR, nDCG@k — pure functions, tested in `tests/` |
| `harness.py` | runs the golden set against each retrieval mode |
| `judge.py` | faithfulness, relevance and abstention, scored by the model |
| `baseline.json` | committed results; `--check` compares against it |

## The two splits

**55 answerable** questions, each labelled with the documents that contain the
answer. Graded on ranking. The kinds are mixed on purpose: paraphrase questions
that share no vocabulary with the source, exact-term questions naming an error
code or a parameter, short keyword queries, multi-hop questions needing two
documents, and five `global` questions about what a document or a pair of
documents is for (Milestone 16, experiment 5).

**10 unanswerable** questions the corpus provably cannot answer. Graded on
whether the system declines. This is the only split where the right answer is
nothing, and it is what `min_score` was set from.

Thirteen documents carry the answers; eight are distractors on adjacent topics
that no question points at. Without them recall saturates at 1.0 and the
harness cannot tell the configurations apart — which is exactly what the first
run of it did.

## Results

Measured on 60 questions, 21 documents, 52 chunks. Reproduce with
`sextant-eval`.

| mode | hit@1 | recall@3 | recall@5 | MRR | nDCG@5 |
| --- | --- | --- | --- | --- | --- |
| dense (vectors only) | 0.860 | 0.900 | 0.990 | 0.906 | 0.906 |
| lexical (BM25 only) | 0.820 | 0.910 | 0.950 | 0.892 | 0.888 |
| rrf (fused) | 0.940 | 0.950 | 0.970 | 0.970 | 0.949 |
| rerank (full pipeline) | 0.940 | 0.960 | 0.970 | 0.970 | 0.951 |

Retrieval is graded with `min_score=0.0`. The floor trades recall for
abstention, and leaving it on would make a mode look worse purely because its
scores sit on a scale the floor happens to bite into.

**Fusion is the win.** Hybrid beats either retriever alone by 8 points of hit@1
and 6 of MRR. Neither one is close on its own, and they fail on different
questions — which is the entire argument for running both.

**Reranking is not justified by this corpus.** It is identical to fusion on
hit@1 and MRR, and ahead by 0.001 on nDCG@5. On 52 chunks fusion already puts
the right passage first, so the cross-encoder has nothing left to fix. That
was the state of the evidence until the larger set below was written; it is
now settled the other way.

## Results at 1,602 chunks

`golden-large.jsonl`: 32 questions over *A Survey of Large Language Models*
(arXiv 2303.18223, 144 pages, 1,550 chunks at the time; the pinned file is
now v19, md5 `b0facc450634ab588d0cd82c8be15ace`, extracted with PyMuPDF —
see [`learning/pdf-extraction.md`](../learning/pdf-extraction.md)) sitting in a store beside the 21
handbook documents (52 chunks, acting as distractors). One PDF is one document,
so these questions label **pages** and the harness grades page hits; two
multi-hop questions label two pages each. Kinds: 10 exact-term, 11 paraphrase,
3 keyword, 3 multi-hop, 5 unanswerable (the six `table` questions came
later, see below). Measured 2026-09-15.

| mode | hit@1 | recall@3 | recall@5 | MRR | nDCG@5 |
| --- | --- | --- | --- | --- | --- |
| dense | 0.815 | 0.907 | 0.926 | 0.889 | 0.875 |
| lexical | 0.815 | 0.926 | 0.944 | 0.889 | 0.889 |
| rrf | 0.889 | 0.926 | 0.926 | 0.930 | 0.904 |
| rerank | **0.926** | 0.907 | **0.963** | **0.954** | **0.931** |

Top score per question, answerable (min / mean) vs unanswerable (max / mean):

| mode | answerable | unanswerable | gap |
| --- | --- | --- | --- |
| dense | 0.373 / 0.579 | 0.258 / 0.218 | +0.115 |
| rrf | 0.030 / 0.033 | 0.027 / 0.020 | +0.003 |
| rerank | 0.062 / 0.951 | 0.000 / 0.000 | +0.062 |

**Reranking earns its place here.** It leads every ranking metric but
recall@3, by 0.024–0.037 — one question in 27, so the ranking gain is
real but small. The decisive column is the second table: at `min_score`
0.01 the cross-encoder blocks 5 of 5 unanswerable questions and loses 0 of
27 answerable ones, because its scores are calibrated (0.95 mean on
answerable, 0.000 on every unanswerable). RRF scores are `1/(k+rank)` and
carry no such meaning — a gap of 0.003 is no threshold at all — and dense
cosine separates by only 0.115 with overlap. Without the reranker the system
would need a different abstention signal; with it, abstention is a free
by-product of ranking. **Decision: the cross-encoder stays in the default
pipeline and the default image.** The 52-chunk result stands as what it was:
a corpus too small for ranking to be hard.

**Fusion still helps at this scale** — +0.074 hit@1 over either retriever
alone — though lexical alone is a closer second than it was on the handbook
set, because the survey's questions name exact terms (GPTQ, ALiBi, PPO).

**Both misses are multi-hop across a table and its prose** (L25, L26): the
architecture table on p. 23 and the formula/description on p. 24–25. The
prose page is found, the table page is not — a table row is a poor embedding
target and its tokens ("PaLM RoPE SwiGLU") are diluted by 15 other rows.

**The remaining misses are all multi-hop.** Three questions need two documents
and retrieve one. A single embedding of a two-part question lands between its
two halves. The fix is not in the retriever: the agent can search twice, and
Phase 3 gave it the loop to do so.

## Results with table-aware chunking (Milestone 16, experiment 1)

Six table-row questions (L33–L38, kind `table`) were added to
`golden-large.jsonl`, making 38, and the loader now marks tables so the
chunker emits a few rows at a time under one copy of the header
(`tools/vector_db/tables.py`). Same mixed store, control against treatment,
rerank mode. Measured 2026-09-16; full sweep and the dense-crowding failure
of one-row-per-chunk in [`learning/table-chunking.md`](../learning/table-chunking.md).

| large set, 38 q | hit@1 | recall@3 | recall@5 | MRR | nDCG@5 | misses |
| --- | --- | --- | --- | --- | --- | --- |
| before | 0.818 | 0.864 | 0.909 | 0.881 | 0.861 | L25 L26 L33 L38 |
| after | **0.909** | **0.939** | **0.985** | **0.947** | **0.944** | L25 |
| after, v19 via PyMuPDF (`baseline-large.json`) | **0.909** | **0.955** | **0.985** | **0.946** | **0.952** | L25 |

The handbook set is unchanged on rerank (0.94 / 0.97) and within the 0.02
gate on every ablation. `baseline.json` and `baseline-large.json` are the
"after" numbers. L26 — the table-and-formula multi-hop — now hits; L25
still needs two searches, which is experiment 2.

## Per-document cap

The returned list holds each document to `SEXTANT_MAX_PER_DOCUMENT` (2)
chunks when a competitive document is waiting, under cosine and
cross-encoder scores only. `baseline.json` dense recall@5 0.955 → 0.973
from this; rerank unchanged. Three rounds and the survey-set question a
hard cap lost are in [`../learning/candidate-cap.md`](../learning/candidate-cap.md).
Re-run any experiment's control with `SEXTANT_MAX_PER_DOCUMENT=0`.

Under the 0.01 floor the cross-encoder's order is noise, and chunks there
are ordered by dense cosine instead (`SEXTANT_SUBFLOOR_ORDER`, default
`dense`; `none` for the old order). `baseline.json` rerank recall@5 0.964
→ 0.982 from this; nothing at or above the floor moves, so the agent's
results are unchanged. [`../learning/subfloor-order.md`](../learning/subfloor-order.md).

When nothing clears the floor the search returns an empty list
(`SEXTANT_FLOOR_FALLBACK`, default `none`). `dense` returns the dense
pass's chunks in cosine order instead, reported as `scored_by: cosine`
with `below_floor: true`, and the agent prefixes them with a warning. Not
the default: on the agent it halved the loop's cost on unanswerable
questions with abstention intact, but did not help the answerable ones it
was built for, and on all 55 answerable questions it is safe but fires on
one of them. [`../learning/floor-fallback.md`](../learning/floor-fallback.md),
[`../learning/floor-fallback-cost.md`](../learning/floor-fallback-cost.md).

## Setting min_score

The summary gap between splits says no threshold exists — answerable scores go
down to 0.0001 and unanswerable up to 0.9730. That is two outliers deciding a
statistic. The counts tell a different story:

| min_score | answerable lost | unanswerable blocked |
| --- | --- | --- |
| 0.01 | 2 / 50 | 8 / 10 |
| 0.10 | 3 / 50 | 8 / 10 |
| 0.30 | 8 / 50 | 8 / 10 |
| 0.50 | 9 / 50 | 9 / 10 |
| 0.90 | 14 / 50 | 9 / 10 |

`0.01` is the default: it blocks four fifths of unanswerable queries and costs
two answerable ones. Everything above it costs more and buys nothing.

The ceiling of 8 in 10 is not a tuning failure. The question it cannot catch is
*"what does error code TRK-150 mean?"*, which scores 0.9730 against the
error-code reference — a passage genuinely about error codes that simply does
not contain that one. No relevance score separates "this passage is on topic"
from "this passage contains the answer". Only reading it does, which is the
model's job, and why the agent prompt carries an explicit abstention rule.

## Generation metrics

```bash
./.venv/bin/sextant-judge -n 10 --out judged.json
```

Needs `GEMINI_API_KEY` twice over — once to produce answers and once to grade
them — so it is a pre-release check rather than a CI gate.

Citation validity is checked **without** a model: every `[n]` in an answer must
refer to a source that was actually returned. Using a model to decide whether a
number is in a list would make a mechanical check probabilistic for no reason.
Faithfulness, relevance and abstention are judged by Claude, which sees the
question, the retrieved passages and the answer — but never the expected answer.
Grading against a reference measures paraphrase distance, not support.

The harness has been run end to end with both model calls stubbed, so the
machinery is verified; the judge's actual opinions are not.

## Summary chunks (Milestone 16, experiment 5)

```bash
SEXTANT_CHROMA_DIR=/tmp/with-overviews \
  ./.venv/bin/sextant-ingest --summaries eval/corpus/*.md --category handbook
./.venv/bin/sextant-eval --store /tmp/with-overviews
```

Since 0.8 the flag is only for forcing it: overviews are on whenever
`GEMINI_API_KEY` resolves, and the control arm above is now the one that
needs a flag (`--no-summaries`). CI has no key, so the store it builds and
checks against `baseline.json` is still the one without them.

One model-written overview per document, stored as a chunk (`kind:
summary`) in the same index. Measured against the five `global` questions
and the rest: global hit@5 was already 1.0 without them — a short
document's first chunk is its overview — so the pre-registered bar could
not be met; what they buy is rank (global rerank hit@1 0.6 → 1.0, local
+0.02) at the cost of dense recall@5 (−0.07 alone, crowding). Opt-in; the
committed baseline is built without them. Full table in
[`learning/summary-chunks.md`](../learning/summary-chunks.md).

## Agent-level retrieval

```bash
./.venv/bin/sextant-eval-agent --kinds multihop --sample 20 --store chroma_db --out run.json
./.venv/bin/sextant-eval-agent --kinds multihop --dry-run   # list the questions, spend nothing
./.venv/bin/sextant-eval-agent --ids q48 u01 u02 --judge     # exact questions, answers judged too
```

Everything above is one `kb.search()` per question. The product lets the
model choose the query and search again, so `sextant-eval-agent` runs the
real loop (real model, real MCP subprocess, web search off) and grades
what every `kb_search` in it returned: **recall@first** (the model's own
first query) and **recall@union** (everything any search retrieved), plus
the tool sequence, searches, turns and cost per question. A question
answered from `kb_list` makes no search, so it also grades **named** — the
share of expected documents whose title appears in the answer
([`learning/kb-list.md`](../learning/kb-list.md)). `--unanswerable` adds the
whole unanswerable split and `--judge` sends every answer through
`eval.judge` as well (faithfulness, relevance, declined; a second model
call per question, `SEXTANT_JUDGE_MODEL` to grade on a cheaper model),
which is how abstention is measured end to end — an unanswerable row has
no retrieval grade and stays out of those means. Every search also records
`below_floor`, and the grade counts them: a `SEXTANT_FLOOR_FALLBACK=dense`
run whose count is 0 did not test the knob, whatever else its numbers did
([`learning/floor-fallback-cost.md`](../learning/floor-fallback-cost.md)). Multi-hop questions are the point:
under the shipped prompt the loop searched once and answered half, and one
prompt bullet is what changed that. Results and the two product findings it
surfaced are in [`learning/agent-loop.md`](../learning/agent-loop.md).
Costs about $0.04 for 29 questions, so it is not in the CI gate.

## What this does not measure

The corpus and the questions were written together. This grades the retrieval
pipeline, not the world: it will settle an ablation and catch a regression, and
it will not predict performance on someone else's documents. Sixty questions is
also small enough that a swing of one or two is noise — the tolerance in
`--check` is set to 0.02 for that reason.
