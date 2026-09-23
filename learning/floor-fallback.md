# Dense fallback under the floor — the model stops flailing, but cannot use what it is handed

*Milestone 17 follow-up to [`subfloor-order.md`](subfloor-order.md).
2026-09-20. Cost: $0.12 ≈ ₹10 (40 agent runs $0.087, 40 judge calls on
`gemini-3.1-flash-lite` ≈ $0.03). Decision: **not shipped** —
`SEXTANT_FLOOR_FALLBACK` stays `none`. The pre-registered rule needed the
answerable questions to benefit, and they do not; what the run found instead
is queued with its own rule — and measured in [`floor-fallback-cost.md`](floor-fallback-cost.md),
which closed the candidate.*

## Hypothesis

`subfloor-order.md` left the product question: `kb_search` filters at
`DEFAULT_MIN_SCORE` (0.01), so a question the cross-encoder cannot place
comes back empty and the model rephrases — up to four times on an
unanswerable question. Ordering the sub-floor chunks by dense cosine gave
q47 and q48 their second document in the harness, but the agent never sees
it. The candidate: when nothing clears the floor, return the dense pass's
chunks in cosine order, reported as `scored_by: cosine` with the cosine as
the score and `below_floor: true`, and tell the model in words that these
are nearest-by-embedding, not judged relevant.

Diagnosis first, at ₹0 (`floor_diag.py`): at the product floor the verbatim
golden questions that come back **empty** are handbook q29, q48, g03 and 8
of its 10 unanswerable (u03 and u07 have on-topic passages above the
floor); survey L39 and all 5 unanswerable. For the four answerable ones the
dense-ordered top-5 has recall 1.0. The cosines are not calibrated across
questions: u01's nearest chunk (detector-architectures, for "learning rate
schedule to fine-tune the detector") is 0.487; g03's second expected
document is 0.399. No threshold separates the two; only reading does. So the
unanswerable split is the risk and had to be in the run.

Pre-registered: **(a)** the four answerable questions reach recall@union 1.0
under the fallback and at least three of them are judged relevant and
faithful ≥ 0.5; **(b)** at most one of the 15 unanswerable questions that
declined under control answers under the fallback; **(c)** searches per
answerable question fall. Rule: (a) and (b) → flip the default and ship. (b)
fails → knob stays off, the floor is worth more than two questions. (a)
fails with (b) holding → knob stays off; the passages reach the model but
it cannot use them.

## Setup

Both arms through `sextant-eval-agent`, which gained `--unanswerable` and
`--judge` for this: every answer goes to `eval.judge.grade_one`
(faithfulness, relevance, declined) so one run grades retrieval and
abstention together. Handbook: q29 q47 q48 g03 + u01–u10 on a fresh store;
survey: L39 + L28–L32 on `./chroma_db` read-only. Web search off. The
judge ran on `gemini-3.1-flash-lite` (`SEXTANT_JUDGE_MODEL`, added for
this) rather than the default `gemini-3.7-flash`, on budget — the grades
below are from the weaker model, and one row shows what that costs. One
run per arm: the loop is not deterministic, and a per-question difference
between arms can be phrasing luck. Two are.

## Results

| set | knob | answerable r@union | declined (unans.) | searches / unans. q | turns / unans. q | agent $ (unans.) |
| --- | --- | --- | --- | --- | --- | --- |
| handbook | none | q29 1.0, q47 0.5, q48 0.5, g03 0.0 | **10 / 10** | 2.90 | 4.60 | 0.036 |
| handbook | dense | q29 1.0, q47 0.5, q48 0.5, g03 0.0 | **10 / 10** | **1.20** | **2.40** | **0.017** |
| survey | none | L39 1.0 | **5 / 5** | 1.20 | 2.40 | 0.007 |
| survey | dense | L39 1.0 | **5 / 5** | 0.80 | 1.80 | 0.006 |

Judge on the answerable four: control q29 1.0/1.0, q47 1.0/1.0, q48
1.0/1.0, g03 f 0.0; fallback q29 1.0/1.0, q47 1.0/1.0, **q48 declined**,
g03 f 0.0. False abstention on the answerable set 0 → 0.25 (one question).

**(b) holds outright; (a) fails; (c) holds where the knob fired.** In
detail, because the table hides which questions the fallback even reached:

1. **The fallback fired on two of the four answerable questions.** q47, g03
   and L39 never saw it: the model's own phrasing cleared the floor (g03's
   "How do I run the pipeline in production, observe it, and feed it video
   streams?" scores video-decoding 0.0143, just over), or the answer came
   from `kb_list`. The golden question being all-sub-floor says nothing
   about the query the model writes.
2. **q29 is the case for it.** Control needed two searches and a listing
   (four turns, $0.0031) to land on mot-metrics; the fallback handed it
   mot-metrics at cosine rank 3 on the first search, the model cited it,
   judged 1.0/1.0, two turns, $0.0014.
3. **q48 is the case against it, and it is not the fallback's fault.**
   Control's query "settings that interact badly when raised" scored
   config-reference#8 ("Notes on tuning" — the paragraph that names
   `process_noise_scale` and `max_age`) at **0.0129**: over the floor by
   0.003, and the model answered correctly. The fallback arm's query
   "which settings interact badly when both are raised" scored everything
   under the floor, and the dense order put config-reference#0 (the title
   chunk) and #7 (the detection table) on top, not #8. The model read
   them, was told they were below the floor, and declined — correctly, for
   what it was given. It also ran the identical query a second time, which
   returned the identical list; the loop has no memory that a repeated
   query is a wasted turn. Between arms this row is the floor sitting at
   0.0129 vs 0.01, not the knob.
4. **On the unanswerable split the fallback is a different feature than the
   one pre-registered.** Every one of the 15 declined under both arms, and
   the judge's reasons under the fallback name the passages as not
   containing the answer — the model read them and said no. What changed is
   how long it took: with an empty result the loop rephrases, lists, and
   rephrases again (u01: four searches and a listing, six turns); with
   nearest-by-embedding passages in hand it reads them once and stops.
   Searches per unanswerable question 2.9 → 1.2, turns 4.6 → 2.4, cost
   halved, abstention intact. The u03/u07 rows (on-topic passages above the
   floor) are unchanged, as they should be.
5. **The judge does not see a listing answer's sources.** g03 is answered
   from `kb_list` titles under both arms and grades faithfulness 0.0 with
   the reason "hallucinated the existence of specific documents": the
   judge is handed `kb_search` passages only, and a correct listing answer
   cites none. That is the harness's gap, not the model's; `named` (1.0
   both arms) is the grade that means something for g03.

## What this says

1. **A sub-floor passage is not a weaker relevance; it is a different
   signal, and the model treats it as one when told.** The fear in the
   pre-registration — that a cosine of 0.49 would read as an answer — did
   not happen once in 15 questions. The warning line ahead of the passages
   did its job. What the model gains is something to *read and reject*
   instead of an absence to *retry against*, and rejecting is cheaper.
2. **It cannot help an answerable question unless the dense order finds the
   right chunk for the model's phrasing**, and q48 shows the dense order
   picking a document's title chunk over its answer paragraph. Dense cosine
   under the floor is a judge of documents more than of chunks — the
   `subfloor-order.md` gain was at the document level too.
3. **The floor at 0.01 is a coin toss for q48.** 0.0129 clears it; the next
   phrasing does not. Nothing in this milestone moves that; a calibrated
   floor per corpus would, and is not on the list.
4. **The efficiency result is worth its own rule.** "Halves the loop's cost on
   unanswerable questions with abstention intact" was not the hypothesis, so
   it does not ship on this run. The risk it carries is the q48 shape at
   scale: on the 55 answerable handbook questions, how often does the
   model's phrasing go sub-floor, and does it then decline where control
   would have rephrased into a hit? That is false abstention across the
   whole answerable set, under both arms, judged — and it is the next
   pre-registration, not a footnote here.

## Reproducing

`SEXTANT_FLOOR_FALLBACK=dense SEXTANT_JUDGE_MODEL=gemini-3.1-flash-lite
sextant-eval-agent --golden eval/golden.jsonl --ids q29 q47 q48 g03 u01 …
u10 --judge`; survey with `--golden eval/golden-large.jsonl --store
./chroma_db --ids L39 L28 L29 L30 L31 L32`. `none` for the control. ~3
minutes and ~$0.03 per arm and set. `floor_diag.py` (session scratchpad)
lists the questions empty at the floor for ₹0.
