# Evaluation

Retrieval quality is a number. A number that is not checked drifts.

```bash
./.venv/bin/agenticrag-eval                     # grade every configuration
./.venv/bin/agenticrag-eval --check             # fail on regression vs baseline
./.venv/bin/agenticrag-eval --modes rrf rerank  # just these two
```

Each run rebuilds the index from `corpus/` into a throwaway directory, so
grading never touches whatever you have actually ingested.

## What is here

| Path | |
| --- | --- |
| `corpus/` | 21 committed Markdown documents, ~5,000 words |
| `golden.jsonl` | 60 labelled questions |
| `metrics.py` | hit@1, recall@k, MRR, nDCG@k — pure functions, tested in `tests/` |
| `harness.py` | runs the golden set against each retrieval mode |
| `judge.py` | faithfulness, relevance and abstention, scored by Claude |
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
`agenticrag-eval`.

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
the right passage first, so the cross-encoder has nothing left to fix. It did
change the top hit on a 1,568-chunk corpus during Phase 4, so the honest
statement is that it is *unproven at this scale*, not useless — and proving it
either way needs a corpus large enough for ranking to be hard.

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
./.venv/bin/agenticrag-judge -n 10 --out judged.json
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
