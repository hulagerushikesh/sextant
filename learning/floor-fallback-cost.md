# The fallback almost never fires — a cost feature that has nothing to charge for

*Milestone 17 follow-up to [`floor-fallback.md`](floor-fallback.md).
2026-09-23. Cost: $0.25 ≈ ₹21 (110 agent runs $0.164, 110 judge calls on
`gemini-3.1-flash-lite` ≈ $0.08). Decision: **not shipped and now closed** —
`SEXTANT_FLOOR_FALLBACK` stays `none`. The pre-registered mechanism clause
failed: across all 55 answerable questions the fallback fired **once**. The
set-level numbers all moved the right way and none of that movement is the
knob.*

## Hypothesis

[`floor-fallback.md`](floor-fallback.md) shipped the knob off. Its recall
claim failed, but two things it measured on 4 answerable + 15 unanswerable
questions looked like a product: abstention held 15/15, and the loop stopped
rephrasing into empty searches — searches per unanswerable question 2.90 →
1.20, turns 4.60 → 2.40, agent cost on that split halved. The open question
was the one four questions cannot answer: **does handing the model sub-floor
passages make it abandon answerable questions it would otherwise answer?**

Pre-registered (`exp_floor_cost.md`, written before any number was read):
**(a)** false abstention over the 55 answerable questions rises by at most
one question (≤ +0.018); **(b)** mean faithfulness and mean relevance each
fall by at most 0.02; **(c)** the mechanism fires — at least 3 of the 55
questions make a search that comes back `below_floor: true`, *otherwise the
run has measured nothing and neither (a) nor (b) means anything*; **(d)**
mean agent cost per answerable question does not rise by more than 5%.
Rule: all four hold → flip the default to `dense`. (c) fails → no decision
either way. (a) or (b) fails → the candidate is closed.

## Setup

`sextant-eval-agent --golden eval/golden.jsonl --judge`, all 55 answerable
handbook questions, one store built once and shared by both arms so only the
knob differs, web search off, judge on `gemini-3.1-flash-lite`. Two arms,
`none` and `dense`, one run each. The unanswerable split was left out: its
numbers are already measured and it is not what this claim is about.

## Results

| arm | hit@1 | r@first | r@union | faith | relev | f.abst | searches / q | 2+ | turns / q | agent $ / q |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| none | 0.891 | 0.855 | 0.873 | 0.936 | 1.000 | 0.018 (q48) | 1.07 | 3 | 2.16 | 0.00151 |
| dense | 0.909 | 0.900 | 0.909 | 0.960 | 0.991 | **0.000** | 0.98 | 1 | 2.07 | 0.00147 |

**(a), (b) and (d) hold. (c) fails, and (c) was the clause that gives the
other three meaning.** Replaying every query the two arms actually issued
against the store at the product floor: the fallback fired on **one** of 55
questions (q29) in the treatment arm, and only two questions (q29, q48) in
the control arm asked anything that would have fired it. Three was the bar,
and three was not a high bar.

1. **q29 is the whole of the effect, and it reproduces.** "Why was a newer
   combined metric introduced?" is sub-floor; control spent four searches
   and six turns getting to mot-metrics, the fallback handed it over at
   cosine rank 3 on the first search — one search, two turns. Identical in
   shape to the q29 result in the earlier note. That is the feature working,
   on 1/55 of the set.
2. **q48 changed arms and is still not evidence.** Under control it declined
   (four empty searches); under `dense` it answered with
   config-reference — and the replay says that query *cleared* the floor, so
   the fallback never ran. In the earlier experiment q48 went the other way,
   declining under `dense`. Two experiments, two directions, neither caused
   by the knob: the model's phrasing decides whether the answer chunk scores
   0.0129 or 0.0089, and 0.01 is in between.
3. **Everything else that moved is the loop, not the knob.** 40 of 55
   questions asked a *different query* in the two arms — same model, same
   prompt, same store, one run each. r@union +0.036 is g02 and g03; g03's
   query cleared the floor and g02 rephrased into its second document. g01
   faithfulness fell 1.0 → 0.8 and g05 relevance 1.0 → 0.5 for the same
   reason, in the other direction. None of those five questions ever saw a
   sub-floor result.

## What this says

1. **A feature needs an exposure count before it needs a decision rule.** The
   whole design was sound and the run was clean, but the thing being measured
   happens roughly twice in a hundred product queries. Clause (c) was written
   because the earlier note had already seen the model's phrasing clear the
   floor on 3 of 4 questions it was supposed to fail; it should have been the
   ₹0 pre-check instead of a clause in a ₹21 run. Replaying the *control
   arm's* recorded queries would have given the number for free.
2. **Set-level movement on a 55-question set is mostly noise.** Four of six
   changed grades here are single questions flipping under nondeterministic
   phrasing. A one-run-per-arm agent experiment can say "nothing broke"; it
   cannot say "+0.036 recall" unless the mechanism is shown to have touched
   the rows that moved. It did not touch any of them.
3. **The safety question is answered, for what it is worth.** Sub-floor
   passages, labelled as nearest-by-embedding, did not make the model
   abandon anything: false abstention 1 → 0, faithfulness up, citations
   valid 55/55 in both arms. If the exposure were ever large — a corpus
   whose cross-encoder scores sit lower, or a `min_score` raised above
   0.01 — the knob is safe to turn on. It stays in the code, off, with that
   sentence attached.
4. **The candidate is closed.** Not because it failed, but because its
   benefit is one question in fifty-five and its cost is a flag, a branch in
   `_search`, a paragraph of prompt and a mode the agent has to reason
   about. `learning/` now has two notes on this knob and neither found a
   reason to ship it.

## Reproducing

`SEXTANT_FLOOR_FALLBACK=none|dense SEXTANT_JUDGE_MODEL=gemini-3.1-flash-lite
./.venv/bin/sextant-eval-agent --golden eval/golden.jsonl --store STORE
--judge --out OUT.json`, ~7 minutes per arm. The harness now records
`below_floor` on every search and counts it in the grade, so the exposure
number this run needed a replay script for comes out of the record.
