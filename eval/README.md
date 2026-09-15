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
| `golden.jsonl` | 60 labelled questions over `corpus/` |
| `golden-large.jsonl` | 32 page-labelled questions over a 144-page PDF (see below) |
| `metrics.py` | hit@1, recall@k, MRR, nDCG@k — pure functions, tested in `tests/` |
| `harness.py` | runs the golden set against each retrieval mode |
| `judge.py` | faithfulness, relevance and abstention, scored by the model |
| `baseline.json` | committed results; `--check` compares against it |

## The two splits

**50 answerable** questions, each labelled with the documents that contain the
answer. Graded on ranking. The kinds are mixed on purpose: paraphrase questions
that share no vocabulary with the source, exact-term questions naming an error
code or a parameter, short keyword queries, and multi-hop questions needing two
documents.

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
(arXiv 2303.18223, 144 pages, 1,550 chunks) sitting in a store beside the 21
handbook documents (52 chunks, acting as distractors). One PDF is one document,
so these questions label **pages** and the harness grades page hits; two
multi-hop questions label two pages each. Kinds: 10 exact-term, 11 paraphrase,
3 keyword, 3 multi-hop, 5 unanswerable. Measured 2026-09-15.

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

## What this does not measure

The corpus and the questions were written together. This grades the retrieval
pipeline, not the world: it will settle an ablation and catch a regression, and
it will not predict performance on someone else's documents. Sixty questions is
also small enough that a swing of one or two is noise — the tolerance in
`--check` is set to 0.02 for that reason.
