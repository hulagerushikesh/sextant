# Milestone 17 — What three experiments kept pointing at

*Closed 2026-09-23. Two shipped (per-document cap, `kb_list`), three
candidates measured and decided against ($0.43 in all), and the composer
fix deployed. Next: [`milestone-18.md`](milestone-18.md).*

Milestone 16 measured five changes and shipped two. Three of the five —
one-row table chunks, 150-token chunks, summary chunks — lost dense
recall@5 the same way: more chunks per document, the five graded slots
filled by siblings of the first hit. Each note ends "a per-document cap is
overdue". This milestone starts by paying that debt, then turns to the one
product change experiment 5 argued for. Same protocol as before: hypothesis
and rule first, both golden sets, a note in `learning/` either way, nothing
ships as default unless it wins on both sets with the CI gate green.

Nothing here touches the VM. Experiment 1 costs nothing; 2 needs a key.

## Experiments

### 1 · Per-document candidate cap — ₹0

**Hypothesis.** Dense recall@5 losses in M16 exps 1, 3 and 5 were crowding:
the second, third and fourth hit were more chunks of the document already
found, and the document that also mattered sat at rank six. Capping the
final list at *N* chunks per document — with the cut candidates backfilling
the remaining slots in score order, so a single-document corpus is
unchanged — should recover the lost recall without moving anything else.

**Change.** `vector_search.py`: `MAX_PER_DOCUMENT` (env
`SEXTANT_MAX_PER_DOCUMENT`, `0` = off) applied in `_search` after the
`min_score` floor. Two passes over the ranked candidates: take while a
document is under the cap, then fill from the skipped ones. Same for all
four modes; the cap is on the answer, not the shortlist.

**Setup.** Three stores kept from experiment 5, so the comparison is
against the numbers already in `learning/summary-chunks.md`:

| store | chunks | questions | why |
| --- | --- | --- | --- |
| handbook, no summaries | 58 | 65 | the CI store; must not regress |
| handbook, with summaries | 79 | 65 | the crowding case — dense r@5 0.970 → 0.900 in exp 5 |
| mixed (handbook + survey, summaries) | 1,688 | 65 + 39 | the survey set is page-labelled on one document; the cap must not push its pages out for handbook chunks |

Cap ∈ {off, 2, 3}, all four modes.

**Decision rule, written before the numbers.** Ship as the default if, at
some *N*:
- the with-summaries store recovers dense recall@5 to within 0.02 of the
  no-summaries store (0.970), and
- no metric on the CI store drops by more than the gate (0.01), and
- survey-set recall@5 drops by no more than 0.02 in any mode, and
- rerank hit@1 does not drop on any store.

If dense recovers but the survey set pays, the cap stays a knob at `0` and
the note says which questions moved and why. If nothing moves, crowding
was the wrong diagnosis and the three notes get a correction.

**Result (2026-09-17, cap 2).** Dense recall@5 recovered in full: 0.900 →
0.973 on the summaries store, 0.882 → 0.955 on the mixed store, +0.018 on
the CI store; rerank hit@1 unchanged everywhere. Survey set rerank
recall@5 0.985 → 0.956 — one question, L13, whose page sat at rank 5
scoring 0.013 and was displaced by two handbook chunks the cross-encoder
scored 0.000. Rule not met; the knob stays at 0. Cap 3: same loss, less
gain.

### 1b · Score-guarded cap — ₹0

**Hypothesis.** The loss in 1 is a hard cap treating a 0.000 chunk as a
document that deserves a slot. Dense siblings that crowd score within a
few percent of the chunk they crowd out; the handbook chunks that
displaced L13 scored a thirtieth of it. Let a capped document keep its
slot unless the next uncapped document scores at least half as much.

**Change.** `MIN_DISPLACE_RATIO = 0.5` in `_diversify`: a chunk over the
cap is skipped only when the next candidate from an uncapped document
scores ≥ ratio × its score; otherwise it is kept as if there were no cap.

**Rule.** Same four conditions as 1, at cap 2. If L13 comes back and dense
holds, ship at 2. If dense gives up its gain, the guard is too strict and
the answer is that the cap belongs to dense retrieval only — which is not
the production mode, so the knob stays at 0 either way.

**Result (2026-09-17).** L13 back: survey rerank 0.985 again, survey dense
0.912 → 0.941, every dense gain from 1 held, CI store and rerank hit@1
untouched. Still over the line in the two rank-scored ablation modes —
survey lexical 0.971 → 0.941 (L27), rrf 0.985 → 0.956 (L13) — because an
RRF score is a rank artefact: rank 25 scores 0.74 × rank 3, so the guard
never fires and the cap is hard again. This is the same fact that keeps
`min_score` off fusion ranks.

### 1c · Cap only where scores carry magnitude — ₹0

**Hypothesis.** The guard is a comparison of relevance, and only cosine
and cross-encoder scores are one. Under BM25 and RRF the cap should not
apply at all — not because those modes lose, but because there is no score
to guard it with.

**Change.** `_diversify` runs only when `scored_by` is `cosine` or
`cross-encoder`. Production is rerank, so this changes nothing about what
ships; it makes the ablation honest.

**Rule.** The four conditions from 1, at cap 2, guard 0.5. This is the
last variant: if it passes, ship at 2 and regenerate both baselines; if
not, knob stays 0 and the note records all three.

**Result (2026-09-17).** All four conditions met — summaries store dense
recall@5 0.973 (= CI store), CI store +0.018 and nothing down, survey set
nothing down (dense +0.029), rerank hit@1 identical on every store.
**Shipped as default 2**; `baseline.json` regenerated. Note:
[`../learning/candidate-cap.md`](../learning/candidate-cap.md).

### 2 · `kb_list` tool — shipped (built 2026-09-19, measured 2026-09-20, $0.034)

"What topics do my documents cover?" is a listing, not a retrieval;
experiment 5 showed no chunk answers it at any level of a summary tree.

**Built.** `KnowledgeBase.list_documents()` → per document: title,
category, chunk count, page count, the model-written overview when
`--summaries` was used, and the first 240 characters of its opening either
way. `kb_list` on the MCP server; offered to the agent beside `kb_search`
and `kb_stats`; rendered to the model as one block per document; one
prompt bullet says a question about the collection is a listing, answered
by title, with no labels to cite. Verified over real stdio against the
local store: 22 documents, pages and leads correct. The starter prompts
already ask exactly this and need no change.

**Measured** ([`../learning/kb-list.md`](../learning/kb-list.md)): the
agent harness on the five `global` questions plus the three starter
prompts. Pre-registered rule: ship the prompt bullet as is if ≥ 4 of 5
global questions call `kb_list` first, otherwise strengthen once and
re-run once. Run 1: 3/5 (the "which of my documents cover X" phrasing went
to search); one sentence added; run 2: **4/5** and 3/3 starters, every
listing answer naming 100% of the expected documents, and the one that
searched afterwards did so *inside* the documents it had named. The fifth
is a content comparison that should search. Shipped. The harness now
records the tool sequence and a `named` grade.

### 3 · Dense fallback under the floor — measured, not shipped ($0.12, 2026-09-20)

**Hypothesis.** When `kb_search` keeps nothing at or above 0.01, return the
dense pass's chunks in cosine order, marked `below_floor`, with a warning
line ahead of them; the four all-sub-floor answerable questions reach
recall@union 1.0 and are judged relevant, and at most one of the 15
unanswerable questions stops declining. Rule: both → ship as default.

**Measured.** Both arms, 20 questions, agent harness with `--judge` (added
for this, judge on flash-lite for budget). Abstention held outright,
15/15; the answerable half failed — the knob fired on two of the four
(the model's own phrasing cleared the floor on the rest), helped q29 and
handed q48 the wrong config chunks. Not shipped. The unregistered result —
the loop stops rephrasing on unanswerable questions, searches 2.9 → 1.2,
cost halved — is queued in `NEXT.md` with its own rule.
[`../learning/floor-fallback.md`](../learning/floor-fallback.md).

### 4 · Prompt caching — measured, no knob ($0.027, 2026-09-20)

**Hypothesis.** Implicit caching never fires on the ~1,400-token prefix;
an explicit cache is refused as under the minimum, or if accepted cuts
the search turn's billed input ≥ 40%. Rule: explicit saves ≥ 30% per
query net of storage at 5 queries/hour → opt-in knob.

**Measured.** 0 of 22 turns implicitly cached. Explicit cache accepted at
1,410 tokens and hit on every turn: −40% gross over four questions, −28%
net at 5/hour (break-even ~1.5/hour, the rule's 30% at ~10/hour). No knob
for an on-demand deployment; `cached_tokens` reported and priced.
[`../learning/prompt-caching.md`](../learning/prompt-caching.md).

### 5 · Floor fallback as a cost feature — measured, candidate closed ($0.25, 2026-09-23)

**Hypothesis.** Across all 55 answerable handbook questions, sub-floor
passages do not make the model decline what it would otherwise answer.
Clauses: false abstention up by at most one question; faithfulness and
relevance down by at most 0.02; **the fallback fires on at least 3 of the
55, or the run has measured nothing**; cost per question up by at most 5%.
Rule: all four → flip the default.

**Measured.** Three clauses held — false abstention 1 → 0 (q48, and it
flipped for phrasing reasons, not the knob), faithfulness 0.936 → 0.960,
cost 0.00151 → 0.00147. The exposure clause failed: the fallback fired on
**one** question (q29, six turns → two), and only two of 55 control-arm
questions asked anything that would have fired it. 40 of 55 questions
issued different queries between arms, which is where r@union +0.036 came
from. Candidate closed; the knob stays in the code, off.
[`../learning/floor-fallback-cost.md`](../learning/floor-fallback-cost.md).

## Also in this milestone

- ~~Ship the composer fix already on `main` the next time the VM is up
  (reattach IP, new key on the VM — asked for first).~~ Done 2026-09-23:
  IP re-reserved and reattached, DNS repointed, tree shipped and rebuilt,
  key and daily cap replaced on the box by hand. The VM had been serving a
  pre-`kb_list` image, so this deploy carried all of M17.
- Remove the `agenticrag-*` command aliases in 0.8.
