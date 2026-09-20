# Under the floor, order by dense — the reranker's zeros are not a ranking

*Milestone 17 follow-up to [`hyde.md`](hyde.md). 2026-09-20. Cost: ₹0
(local models only). Decision: shipped as the default —
`SEXTANT_SUBFLOOR_ORDER=dense`; handbook rerank recall@5 0.964 → 0.982
and hit@1 0.909 → 0.927, survey set unchanged, nothing above the
product's floor moves.*

## Hypothesis

The HyDE note ended with a diagnosis instead of a query trick: for q48
dense retrieval already had both documents in its top seven, and it was
the cross-encoder that dropped one. Reading the pool before writing
anything down (no metric was looked at): the cross-encoder scores
config-reference 0.004 and *every other chunk in the 25-deep pool
0.000* — kalman-filter included. Among chunks scored 0.000 the order is
whatever the stable sort inherited from fusion, and RRF puts a chunk
that is rank 30 on dense and rank 8 on BM25 above one that is rank 7 on
dense and absent from BM25. q47 has the same shape (track-lifecycle at
dense 2/4/7, cross-encoder 0.000, behind mot-metrics at 0.004). q36's
reid is also a 0.000 — but the five above it are real scores, so a
sub-floor change should not reach it. g02's benchmark-datasets is dense
rank 18: not this problem.

The product already treats scores under `DEFAULT_MIN_SCORE` (0.01) as
"nothing here" and drops them. The claim is that the reranker's
*order* under that floor is noise too, and that dense similarity is the
signal left. Pre-registered: **ordering sub-floor chunks by dense cosine
raises handbook rerank recall@5 by ≥ +0.015 (q47 and q48 to 1.0; q36 and
g02 unchanged), leaves hit@1 unchanged on both sets (top-1 sits above the
floor wherever anything does), does not lower the survey set, and leaves
the unanswerable top scores identical (reported scores are untouched).**
Rule: wins both sets → flip the default and ship, saying plainly that the
product floor removes these chunks so the agent's answers do not change;
handbook only or survey lower → knob stays off, note only.

## Change

One knob in `vector_search.py`. `_search` now sorts and diversifies on
`keys`, which equal the cross-encoder scores at and above the floor and
`floor × cosine` below it (0 for a chunk the dense pass did not return);
`scores` — what a hit reports and what `min_score` tests — are
unchanged. Forwarded across the MCP boundary like the other knobs;
`test_every_retrieval_knob_crosses_the_process_boundary` pins it.

## Results

Same harness, both sets, `none` against `dense`:

| set | knob | hit@1 | recall@3 | recall@5 | mrr | ndcg@5 | failures |
| --- | --- | --- | --- | --- | --- | --- | --- |
| handbook | none | 0.909 | 0.949 | 0.964 | 0.955 | 0.938 | q36 q47 q48 g02 |
| handbook | dense | **0.927** | **0.967** | **0.982** | 0.961 | 0.952 | q36 g02 |
| survey | none | 0.912 | 0.956 | 0.985 | 0.947 | 0.953 | L25 |
| survey | dense | 0.912 | 0.956 | 0.985 | 0.947 | 0.953 | L25 |

Abstention: handbook unanswerable max 0.973 / mean 0.135 → 0.973 /
0.134; survey 0.0001 / 0.0000 → 0.0000 / 0.0000. Dense, lexical and rrf
modes are untouched by construction and reproduce their baselines.

**Three of four clauses hold; one was wrong in a good direction.** q47
and q48 both reach 1.0: track-lifecycle now sits at rank 2 for q47 and
kalman-filter at rank 3 for q48, where the dense pass had them. q36 and
g02 are unchanged, as predicted. The survey set does not move — every one
of its 34 answerable questions has real scores in the top five, so the
sub-floor order never reaches the cut. The clause that failed is hit@1
"unchanged": it rose. g03 ("what does the operations side of my documents
cover") is a question the cross-encoder scores 0.0025 at best — all under
the floor — and under `none` its top-1 was video-decoding (a fusion
artefact), under `dense` deployment-threading, one of the three expected.
The pre-registration assumed nothing is all-sub-floor; g03 is (so are
q29 and q48), and a listing question with no passage that answers it is
the natural case. The top scores moved by a ten-thousandth for the same reason: when every
chunk is under the floor, the reported top-1 is a different sub-floor
chunk. Both stay under the floor.

Per-question diff, all 65: 51 rows changed somewhere in their top five,
every change below 0.01; no row's above-floor prefix changed.

## What this says

1. **A calibrated floor also says where the reranker's ranking stops.**
   The cross-encoder's scores are meaningful as relevances above ~0.01 and
   as "no" below it; treating the "no"s as ranked was the bug. Dense
   cosine is a weaker judge than the cross-encoder but it is a judge, and
   below the floor it is the only one left. Two of the four remaining
   handbook failures were this, at zero cost.
2. **The agent sees none of it — yet.** `kb_search` filters at 0.01 by
   default, so q47 and q48 still come back empty to the model and it
   still rephrases ([`agent-loop.md`](agent-loop.md)). The gain is real
   for `min_score=0` callers and for the number the harness reports; for
   the product it moves the question to the floor itself: whether a
   search that finds nothing above 0.01 should return the dense order
   with the scores it has, marked as such, instead of nothing. That is a
   different trade — the unanswerable split would get passages too — and
   it needs the agent harness and the judge, not this one. Queued.
3. **The multi-hop failures were never one thing.** q36 (reid at dense
   6, real scores above it), g02 (benchmark-datasets at dense 18), L25
   (two pages, one search) each need something else. Four experiments
   have now each moved one of them.
4. **An all-sub-floor question has no retrieval answer, only a listing.**
   g03's best chunk scores 0.0025 for the same reason `kb_list` exists: a
   question about what the documents cover has no passage. Its hit@1 here
   is an artefact under either order; `named` in the agent harness is the
   grade that means something for it.

## Reproducing

`SEXTANT_SUBFLOOR_ORDER=none ./.venv/bin/sextant-eval` for the control;
default for the treatment. Survey: `--store ./chroma_db --golden
eval/golden-large.jsonl`. ~2 minutes each; both baselines regenerated
under the default.
