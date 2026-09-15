# Does the cross-encoder earn its place? (settled 2026-09-15)

A worked example of the level-6 method: a claim the README carried on faith,
the experiment that tested it, and what the numbers say.

## The claim

Through Phase 5 the pipeline was dense ∥ BM25 → RRF → cross-encoder, and the
eval said the last stage bought nothing: on 52 chunks it tied fusion on
hit@1/MRR and gained 0.001 nDCG@5. The README's honest line was "unproven at
this scale, not useless" — plus an anecdote that it changed one top hit on a
1,568-chunk PDF during Phase 4. An anecdote is not a result. The 90 MB model
and most of the query latency were riding on it.

## The experiment

- **Store**: the 144-page *Survey of Large Language Models* (arXiv
  2303.18223, 1,550 chunks) in the same collection as the 21 handbook docs
  (52 chunks). 1,602 chunks total; the handbook acts as distractor mass.
- **Labels**: one PDF is one document, so document-level grading would score
  every mode 1.0. `eval/golden-large.jsonl` labels **pages**; the harness
  grew `--store` (grade an existing directory read-only) and `--golden`, and
  grades `document#pN` units when a question carries `relevant_pages`.
- **Questions**: 32 — 10 exact-term (GPTQ, ALiBi, AdamW betas…), 11
  paraphrase (no shared vocabulary with the passage), 3 keyword, 3 multi-hop
  (table row + prose on another page), 5 unanswerable (sourdough, FIFA, the
  Calvin cycle — nothing in any of the 22 documents).
- **Decision rule, written before running**: keep the reranker if it gains
  ≥ 0.03 hit@1 or ≥ 0.02 nDCG@5, or if unanswerable rejection gets worse
  without it. Otherwise make it opt-in and drop it from the image.

## The numbers

| mode | hit@1 | recall@3 | recall@5 | MRR | nDCG@5 |
| --- | --- | --- | --- | --- | --- |
| dense | 0.815 | 0.907 | 0.926 | 0.889 | 0.875 |
| lexical | 0.815 | 0.926 | 0.944 | 0.889 | 0.889 |
| rrf | 0.889 | 0.926 | 0.926 | 0.930 | 0.904 |
| rerank | 0.926 | 0.907 | 0.963 | 0.954 | 0.931 |

Top score per question — the abstention signal:

| mode | answerable min / mean | unanswerable max / mean | gap |
| --- | --- | --- | --- |
| dense (cosine) | 0.373 / 0.579 | 0.258 / 0.218 | +0.115 |
| rrf (1/(k+rank)) | 0.030 / 0.033 | 0.027 / 0.020 | +0.003 |
| rerank (calibrated) | 0.062 / 0.951 | 0.000 / 0.000 | +0.062 |

Threshold sweep on rerank: `min_score = 0.01` loses 0/27 answerable and
blocks 5/5 unanswerable.

## Reading it honestly

1. **Ranking gain: real, small.** +0.037 hit@1 is one question in 27. Every
   metric but recall@3 moves the same direction, which is consistent, but 27
   questions cannot distinguish 0.03 from noise. The rule's first clause is
   met on paper; alone it would be a weak reason.
2. **Abstention: decisive.** The cross-encoder is the only stage whose score
   means anything. It puts 0.000 on every off-corpus question and ~0.95 on
   in-corpus ones. RRF's scores are rank reciprocals — a 0.003 gap is not a
   threshold, it is rounding. Dense cosine separates by 0.115 with overlap
   in the tails (min answerable 0.37 vs max unanswerable 0.26 — usable here,
   but it was 0.0001 vs 0.97 on the handbook set, so it does not travel).
   Remove the reranker and the system needs a new abstention mechanism;
   keep it and abstention is free.
3. **Why the 52-chunk result was different.** With 13 answer-bearing
   documents and 52 chunks, fusion already ranks correctly — the candidate
   set is small and clean and there is nothing to reorder. At 1,600 chunks
   with a single 144-page document, the top-30 from each retriever contains
   near-duplicates from adjacent pages and rows of tables; reading
   query+passage jointly is what separates them.
4. **The misses are informative.** Both are multi-hop where one hop is a
   table row ("PaLM · RoPE · SwiGLU"). The prose page is found, the table
   page is not: a table row embeds badly and its tokens are diluted among
   fifteen sibling rows in the same chunk. That is a chunking finding, not a
   reranking one — tables want their own chunk boundaries (or a row-per-chunk
   loader), which is a `learning/` §9 experiment for later.

**Decision: keep the cross-encoder in the default pipeline and image.**
Recorded in `eval/README.md`; results committed as `eval/baseline-large.json`.

## What would change the decision

- An embedder whose cosine is well-calibrated across corpora (bge/e5 with
  a fixed threshold) would take over the abstention job; then the reranker
  would have to justify itself on ranking alone, where its margin is one
  question.
- A cheaper abstention signal — e.g. BM25 hit count plus dense top-1 with
  per-corpus calibration — could be measured against the same two golden
  sets in an afternoon.

## Reproduce

```bash
./.venv/bin/sextant-eval --store ./chroma_db --golden eval/golden-large.jsonl
```

The survey must be in the store (`sextant-ingest path/to/2303.18223.pdf`);
the harness reads the directory in place and writes nothing.
