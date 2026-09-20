# HyDE on a technical personal corpus — the model writes the wrong document

*Learning path §9, item 2. 2026-09-20. Cost: $0.010 ≈ ₹1 (104 short
`gemini-3.1-flash-lite` calls). Decision: nothing ships — HyDE hurts the
dense stage on both sets, is erased by the reranker, and breaks abstention
when it replaces the question; the note records why a personal corpus is
the wrong place for it.*

## Hypothesis

[`agent-loop.md`](agent-loop.md) left one question the loop could not
reach by any rephrasing: q48, "which two settings interact badly when
both are raised" — the answer (`process_noise_scale` widens the gate that
`max_age` keeps open) shares no vocabulary with the question, and the
cross-encoder scored every chunk in the store below 0.002 for every
phrasing the model tried. HyDE (Gao et al. 2022) is the standard answer to
that shape: have the model write the passage it *expects* to find, embed
that instead of the question, and let the hypothetical's vocabulary do the
matching.

Pre-registered before any number was read: **embedding a hypothetical
passage for the dense half lifts rerank recall@5 on the handbook set by
≥ +0.03 (q48 moves off 0) and does not lower it on the large set, with
the abstention signal intact — unanswerable top-score mean rises by
< 0.05.** Rule: wins on both sets with the signal intact → ship as an
opt-in knob, not the default (it adds a model call to every query); one
set only, or the signal breaks → note only.

## Setup

Both golden sets and both stores: handbook (65 questions, 21 pages,
fresh store) and large (39 questions, the survey PDF plus the handbook as
distractors, `./chroma_db` read-only). For every question — answerable
and unanswerable alike, because a fabricated passage for a question the
corpus cannot answer is HyDE's known failure — `gemini-3.1-flash-lite`
wrote one 60–90 word passage "as it might appear in a technical document"
that answers it. No hint about the corpus: the model does not know the
documents, which is the situation a personal corpus is in. Three arms:
**control** (the question everywhere; must reproduce `baseline.json`),
**hyde_dense** (the passage is embedded for the dense half; BM25 and the
cross-encoder still see the question), **hyde_full** (the passage replaces
the question everywhere). Each in `dense`, `rrf` and `rerank`; product
defaults otherwise (cap 2; `min_score` 0 as the harness grades). Cost of
the 104 passages: 7,204 tokens in, 24,070 out including thinking, $0.0103.

## Results

Control reproduces both committed baselines to the third decimal.

**Handbook set** (`abst.` = mean top score on the 10 unanswerable
questions; higher is worse):

| arm | mode | hit@1 | recall@3 | recall@5 | mrr | abst. | q48 r@5 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| control | dense | 0.873 | 0.885 | 0.973 | 0.915 | 0.356 | 1.00 |
| hyde_dense | dense | 0.800 | 0.900 | 0.936 | 0.868 | 0.380 | 0.50 |
| control | rrf | 0.909 | 0.921 | 0.973 | 0.950 | — | 0.50 |
| hyde_dense | rrf | 0.927 | 0.930 | 0.964 | 0.953 | — | 0.50 |
| control | rerank | 0.909 | 0.949 | 0.964 | 0.955 | 0.135 | 0.50 |
| hyde_dense | rerank | 0.909 | 0.949 | 0.964 | 0.955 | 0.135 | 0.50 |
| hyde_full | rerank | 0.909 | 0.903 | 0.964 | 0.942 | 0.053 | 0.50 |

**Large set** (5 unanswerable):

| arm | mode | hit@1 | recall@3 | recall@5 | mrr | abst. mean | abst. max |
| --- | --- | --- | --- | --- | --- | --- | --- |
| control | dense | 0.735 | 0.912 | 0.912 | 0.842 | 0.224 | 0.273 |
| hyde_dense | dense | 0.706 | 0.853 | 0.912 | 0.810 | 0.212 | 0.301 |
| control | rrf | 0.882 | 0.956 | 0.985 | 0.934 | — | — |
| hyde_dense | rrf | 0.794 | 0.897 | 0.926 | 0.861 | — | — |
| control | rerank | 0.912 | 0.956 | 0.985 | 0.947 | 0.000 | 0.000 |
| hyde_dense | rerank | 0.912 | 0.956 | 0.985 | 0.947 | 0.000 | 0.000 |
| hyde_full | rerank | 0.735 | 0.882 | 0.956 | 0.831 | 0.145 | **0.697** |

**The hypothesis fails on every clause.**

1. *Dense gets worse, not better.* hit@1 0.873 → 0.800 on the handbook,
   0.735 → 0.706 on the survey; recall@3 down 0.06 on the survey. Two
   handbook questions the question-embedding found, the passage-embedding
   lost (q29, q48). Fusion inherits the loss on the survey (rrf hit@1
   0.882 → 0.794).
2. *The reranker erases it.* `hyde_dense/rerank` is identical to control
   on both sets — same metrics, same four failures (g02, q36, q47, q48
   handbook; L25 survey), same top scores. The fused pool is 25 deep; the
   relevant chunks are in it whichever text the dense half embedded, and
   the cross-encoder, still reading the question, ranks the pool the same
   way. At this corpus size HyDE cannot reach the stage that decides.
3. *Replacing the question breaks abstention.* `hyde_full/rerank` on the
   survey: hit@1 0.912 → 0.735, and the reranker's maximum score on an
   unanswerable question goes from **0.000 to 0.697** — the model wrote a
   confident paragraph about ONNX export, the cross-encoder scored a real
   passage against that paragraph, and the floor that keeps the product
   from answering "how do I export to ONNX?" from a corpus with no such
   page is gone. On the handbook the scores fall across the board instead
   (answerable mean 0.777 → 0.572): passage-to-passage is not what the
   cross-encoder was trained on.
4. *q48 was never the case for it.* Under `dense`, control already
   retrieves both of q48's documents (recall@5 1.00); it is the reranker
   that drops one. And the passage HyDE wrote for q48 is about *buffer
   size and polling frequency* — with no domain cue in the question, the
   model wrote a plausible systems paragraph about the wrong system. That
   is the finding: on a personal corpus the model does not know the
   documents, so the hypothetical answer is drawn from the wrong
   distribution, and a wrong-domain passage embeds further from the right
   chunk than the bare question did.

## What this says

1. **HyDE assumes the generator knows the corpus's world.** It was
   measured on web-scale QA where the model's prior *is* the corpus. On a
   corpus of one person's handbook and one survey, a question stripped of
   vocabulary is stripped for the model too, and what it writes is a
   confident guess about a different topic. The technique's premise fails
   exactly on the question it was brought in for.
2. **The reranker is the stage that decides, and HyDE never reaches it.**
   Any dense-side change that leaves the relevant chunk inside the 25-deep
   fused pool is invisible after the cross-encoder. That was also the
   shape of the embedder-swap and chunk-size results; three experiments
   now say the same thing about where this pipeline's answer is made.
3. **A fabricated passage defeats calibrated abstention.** The product's
   `min_score` floor works because a question with no answer in the
   corpus scores near zero against every chunk. A hypothetical answer is
   built to score well against *something*, and on the survey it found a
   0.70. Any query-expansion scheme has to be graded on the unanswerable
   split first.
4. **q48 stays open, and the note now says what would move it:** not a
   better query but a different candidate cut — the reranker demotes a
   chunk that dense retrieval already found. A `rerank` variant that keeps
   the dense top-1 from each of two documents is a candidate-side idea,
   ₹0, and the next thing to pre-register for it.

## Reproducing

`exp_hyde.py OUT.json` (session scratchpad; ~120 lines over
`eval.harness.grade` with a `KnowledgeBase` subclass whose `_dense`
embeds a substituted text). Passages are cached beside the output so a
re-grade is free. ~8 minutes; ~$0.01 the first time.
