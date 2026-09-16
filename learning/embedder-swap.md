# Experiment 4 — Embedder swap: MiniLM → bge-small-en-v1.5

*Milestone 16, 2026-09-16. Cost: ₹0 and one 128 MB model download.
Decision: not switched. The knob, the query prefix and the store guard
ship; the default stays `all-MiniLM-L6-v2`.*

## Hypothesis

`all-MiniLM-L6-v2` (2021, 256-token window) is the weakest link on
paraphrase questions: dense hit@1 on the survey set equals lexical, which
should not happen on questions written to avoid the document's words.
`BAAI/bge-small-en-v1.5` — same 384 dimensions, 512-token window, a much
higher MTEB retrieval score — should lift dense hit@1 by ≥ 0.03 on both
golden sets, and its cosine scale might be calibrated enough that an
abstention threshold travels between corpora (MiniLM's did not: 0.36/0.26
on one set, 0.26/0.58 on the other).

## What was built

- `SEXTANT_EMBEDDER` names the sentence-transformers model
  (`embeddings.py`); forwarded to the knowledge-base subprocess like the
  other knobs.
- A per-model **query prefix**. bge was trained with an instruction in
  front of the query and nothing in front of the passage; `encode_query()`
  applies it, `encode()` does not. Measured below — it is not optional.
- A **store guard**. The collection is stamped with the model that first
  wrote to it and refuses to open under a different one. This matters
  more than it sounds: MiniLM and bge-small are both 384-d, so mixing
  them raises no error anywhere — every query just scores against vectors
  from another space and retrieval quietly degrades. A store from before
  the stamp is taken to be MiniLM, the only model there was.

Chunking was left at 200/40 tokens so the embedder is the only variable;
experiment 3 sweeps chunk size with both models.

## Measurement

Same layout as experiments 1 and the reranker decision: 21 handbook
documents plus the survey in one store, both golden sets, all four modes.
MiniLM store = `chroma_db` after experiment 1 (1,679 chunks); bge store
rebuilt from the same text (1,685 — bge's tokenizer counts a few tables
differently).

**Dense mode** — the mode the swap targets:

| set | embedder | hit@1 | recall@3 | recall@5 | MRR | nDCG@5 |
| --- | --- | --- | --- | --- | --- | --- |
| large, 38 q | MiniLM | 0.697 | 0.864 | 0.879 | 0.802 | 0.800 |
| large, 38 q | **bge + prefix** | **0.788** | 0.833 | **0.924** | **0.850** | **0.844** |
| large, 38 q | bge, no prefix | 0.758 | 0.803 | 0.833 | 0.808 | 0.789 |
| handbook, 60 q | **MiniLM** | **0.800** | **0.850** | **0.940** | **0.856** | **0.853** |
| handbook, 60 q | bge + prefix | 0.760 | 0.850 | 0.890 | 0.822 | 0.820 |
| handbook, 60 q | bge, no prefix | 0.740 | 0.800 | 0.850 | 0.793 | 0.786 |

**The shipped pipeline** (rerank) and fusion:

| set | embedder | rrf hit@1 | rrf recall@5 | rerank hit@1 | rerank recall@5 | rerank MRR |
| --- | --- | --- | --- | --- | --- | --- |
| large | MiniLM | 0.788 | 0.939 | 0.909 | 0.985 | 0.947 |
| large | bge + prefix | 0.818 | 0.970 | 0.909 | 0.985 | 0.947 |
| handbook | MiniLM | 0.880 | 0.920 | 0.920 | 0.970 | 0.955 |
| handbook | bge + prefix | 0.880 | 0.950 | 0.940 | 0.950 | 0.960 |

**Dense separation**, top cosine per question, answerable (min / mean)
vs unanswerable (max / mean):

| set | embedder | answerable | unanswerable | gap |
| --- | --- | --- | --- | --- |
| large | MiniLM | 0.358 / 0.568 | 0.258 / 0.218 | +0.100 |
| large | bge + prefix | 0.670 / 0.780 | 0.585 / 0.560 | +0.085 |
| handbook | MiniLM | 0.256 / 0.490 | 0.581 / 0.406 | −0.326 |
| handbook | bge + prefix | 0.590 / 0.722 | 0.777 / 0.670 | −0.187 |

## What the numbers say

**The paraphrase gain is real, on one corpus.** +0.091 dense hit@1 and
+0.045 recall@5 on the survey — the questions written to avoid the
paper's vocabulary are exactly where bge pulls ahead (L11, L13 recovered).
On the handbook it loses 0.04 hit@1 and 0.05 recall@5 (q15, q29, q30, q50
lost; q29 now retrieves the survey ahead of the handbook document). Sixty
questions make 0.04 two questions, so this is not a large effect either
way, but the rule was written before the numbers and it says both sets.

**The prefix is part of the model.** Without it bge drops 0.03–0.09
recall@5 on every set and every mode that uses dense. Anyone swapping in a
model has to know its instruction string, which is why it lives in a
table in `embeddings.py` rather than in a config file.

**Calibration did not travel.** bge's cosines are compressed into
0.56–0.78 (a known property of the model), and the same failure shape
appears: on the survey a threshold near 0.6 would separate the two
classes; on the handbook the highest unanswerable score (0.78) sits above
the lowest answerable (0.59). The gap moved from −0.33 to −0.19, which is
"less wrong", not "usable". The cross-encoder's 0.000 on every unanswerable
question is still the only abstention signal in the system;
[`reranker-decision.md`](reranker-decision.md) stands.

**The reranker absorbs the difference.** Rerank hit@1 and recall@5 are
identical on the survey under both embedders and within one question on
the handbook. The candidate set changes at the margin (fusion recall@5
moved +0.03 on both sets), the final ranking barely does. For the shipped
pipeline the embedder is not where the next gain is.

## Decision

**Not switched.** The rule — dense hit@1 up ≥ 0.03 on *both* sets, rerank
not regressed — fails on the handbook. Switching would also mean a
41 MB larger image and every existing store re-ingested, for a gain the
reranker mostly erases. The code stays: `SEXTANT_EMBEDDER=BAAI/bge-small-en-v1.5`
is a one-line opt-in for a corpus like the survey, and the guard makes
it safe to try on a scratch store without touching the default one.

## What would change the decision

- Experiment 3. bge has a 512-token window and was measured here at
  200-token chunks chosen for MiniLM's 256. If it wins on both sets at
  300–400 tokens, that is a different experiment with a different
  answer.
- A corpus that is all paraphrase questions over long technical prose —
  the survey's profile. The handbook loss is on short factual pages where
  MiniLM's training data (Q&A pairs, forum text) is a closer fit.
- A larger model (`bge-base`, 110M parameters, ~440 MB) is a different
  cost class and would need to earn it on rerank, not dense.

## Reproduce

```bash
SEXTANT_EMBEDDER=BAAI/bge-small-en-v1.5 SEXTANT_CHROMA_DIR=/tmp/bge \
  ./.venv/bin/sextant-ingest eval/corpus/*.md --category handbook
SEXTANT_EMBEDDER=BAAI/bge-small-en-v1.5 ./.venv/bin/sextant-eval --store /tmp/bge
```

Opening `/tmp/bge` without `SEXTANT_EMBEDDER` set is refused, by design.
