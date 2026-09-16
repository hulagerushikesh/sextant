# Experiment 2 — Grade the agent, not just the retriever

*Milestone 16, 2026-09-16. Cost: $0.14 (six runs of the loop on
`gemini-3.1-flash-lite`). Decision: the loop did **not** already resolve
multi-hop questions; a one-bullet prompt change ships because it recovers
the one recoverable miss without adding turns anywhere else.*

## Hypothesis

Every retrieval number in this repository is one `kb.search()` per golden
question. The product searches as many times as the model chooses. So the
three multi-hop misses on the survey set and the three on the handbook set
might be a harness artefact: the agent reads the passages, notices half the
question is unanswered, searches again, and the union covers both. Rule,
written first: if multi-hop recall over the union of every search ≥ 0.9,
record that the loop does the job and stop. If not, one prompt change — a
decomposition nudge — and re-run; ship only if it moves recall without
adding turns to questions that did not need them.

## What was built

`eval/agent_harness.py` (`sextant-eval-agent`). Runs each question through
the real `mcp_server.agent.run` — real model, real MCP subprocess, web search
forced off — behind a host wrapper that records what every `kb_search`
returned. Grades two things from the record:

- **recall@first** — the model's first query, at the depth the tool
  returned. Measures phrasing: `sextant-eval` sends the golden question
  verbatim, the model sends whatever it decides to.
- **recall@union** — everything any search in the loop retrieved. Measures
  the loop.

Plus searches, turns, tokens and cost per question. Deterministic selection
(`--kinds multihop --sample 20`, seeded) so a re-run after a prompt change
grades the same questions. Tested end to end against the scripted model in
`tests/fakes.py`; the real run is not part of the CI gate because it costs
money.

## Setup

All 9 multi-hop questions plus a seeded sample of 20 others (10 per set),
against the mixed store from experiments 1, 3 and 4 (21 handbook documents
plus the survey, 1,660 chunks). Default `kb_search` behaviour throughout,
including the `min_score = 0.01` floor the product applies and the harness
does not. Multi-hop was then re-run twice more per arm, so every multi-hop
number below is three runs of the same nine questions.

## Results

Control is the shipped prompt; treatment adds one bullet (below).

**Multi-hop, 9 questions, three runs each:**

| arm | run | recall@first | recall@union | searches / q | searched 2+ | turns / q | $ |
| --- | --- | --- | --- | --- | --- | --- | --- |
| control | 1 | 0.722 | 0.722 | 1.33 | 1 | 2.33 | 0.013 |
| control | 2 | 0.722 | 0.722 | 1.22 | 1 | 2.22 | 0.013 |
| control | 3 | 0.722 | 0.722 | 1.44 | 1 | 2.44 | 0.014 |
| **nudge** | 1 | **0.778** | **0.778** | 1.44 | 4 | 2.11 | 0.014 |
| **nudge** | 2 | 0.722 | **0.778** | 2.00 | 5 | 2.44 | 0.015 |
| **nudge** | 3 | **0.778** | **0.778** | 1.56 | 4 | 2.33 | 0.015 |

**The other 20 questions** (exact, keyword, paraphrase, table), one run each:

| arm | recall@union | searches / q | turns / q | 6-turn cap hit | $ |
| --- | --- | --- | --- | --- | --- |
| control | 1.000 | 1.20 | 2.20 | 1 (q29) | 0.027 |
| nudge | 1.000 | 1.10 | 2.10 | 0 | 0.026 |

Exact, keyword and table questions took exactly one search and two turns
under both prompts; the only movement is one paraphrase question (q29,
below) that looped less.

## What the numbers say

**The loop does not search twice on its own.** Under the shipped prompt, one
of nine multi-hop questions got a second search in any run, and that one
(q48) was four rephrasings of the whole question, not a search for its
other half. The model reads the first page of passages, answers what they
cover, and stops; the prompt's "search again if the passages do not answer"
did not fire on a half-answered question. Recall@union equals
recall@first: the union added nothing, in any run. Hypothesis refuted.

**The nudge does what it says, and it fixes the query, not just the loop.**
With the bullet, four or five of nine multi-hop questions were split into two
searches — usually both in a single turn, as parallel calls, which is why
turns did not rise. L25 ("which position embedding does PaLM use, and how
does that method encode relative position") is recovered in every run:
`What position embedding does PaLM use?` ranks the PaLM table row first,
where the compound question ranked it tenth behind three RoPE prose pages.
That is the same dilution measured in experiment 3, in the query rather
than the chunk: a query that names two things lands between them. The
answer now says RoPE and explains the rotation; under the control prompt it
said the documents do not specify.

**The remaining three are not the kind the nudge can reach.** q36 ("why
freeze the appearance model while an object is partly hidden") and q47
("hit the maximum track count — underlying cause") are labelled as needing
two documents, and in every run the model answered from one — and the
answer matches the golden `expect` field both times. The occlusion page
says why you freeze and what goes wrong if you do not; the error-code page
names `max_age` and the noisy detector. The label says both documents are
relevant, which is true; it does not follow that both are needed. These are
retriever misses that are not product misses, and the union metric cannot
see that. q48 ("which two settings interact badly when both are raised") is
a miss at every level: the cross-encoder scores every chunk in the store
below 0.002 for any phrasing the model tried, there is no vocabulary shared
between the question and the answer (`process_noise_scale` widens the gate
that `max_age` keeps open), and no amount of rephrasing found it in 3, 4, 5
or 6 searches. That question needs a different retriever — query expansion
or HyDE, research question 2 in `learning/README.md` — not a better loop.

**Two product findings the harness surfaced, neither in the hypothesis.**

- *The `min_score` floor changes the loop's behaviour.* `sextant-eval`
  grades unfiltered; the product drops passages the reranker scores under
  0.01. q29 and q48 come back **empty** to the model — every chunk scores
  0.0001 — and the model then rephrases three to six times. q29 reached
  the six-turn cap once under the control prompt and still answered
  correctly on the last turn; the harness counts it as a hit because a
  0.0001-scored chunk of the right document sits at rank 5. The floor is
  doing its job — those scores are the reranker saying "nothing here" —
  but it means a question the harness passes can be a five-search loop in
  the product.
- *At the turn cap, the answer can be empty.* One treatment run of q48 spent
  all six turns searching; the loop ended with function calls in the last
  turn and no text, and the user would have seen nothing. `truncated` was
  set, but the interface has no answer to attach it to. Fixed alongside
  this experiment: before the final permitted turn the runner adds a user
  message saying the search budget is spent, and the model answers from
  what it has (`LAST_TURN_NOTE`). The obvious fix — the last turn with
  `FunctionCallingConfigMode.NONE` — was tried first and does not work on
  this model: it attempts the call anyway and the turn ends
  `MALFORMED_FUNCTION_CALL` with no text, the same empty answer by another
  route. Checked against the real API, cap forced to two turns: the
  answer is "The documents do not cover which two settings interact
  badly when both are raised."

## Decision

**The prompt bullet ships:**

> A question with two parts — "which X does A use, and how does X work" —
> is two searches. Run one for each part before answering, rather than one
> query that names both … If the passages you have cover only part of the
> question, search for the missing part before saying the documents do not
> cover it.

Multi-hop recall@union 0.722 → 0.778 in three of three paired runs;
non-multi-hop questions unchanged at one search and two turns; multi-hop
cost +8%. The pre-registered bar for the loop (≥ 0.9) was not met and will
not be met by prompting: of the three questions left, two are answered
correctly from one document and one is unreachable by this retriever.
Recorded as such rather than relabelled — the retrieval labels are correct
as retrieval labels; they over-specify what an answer needs, which is a
thing this harness can now show and `sextant-eval` cannot.

`sextant-eval-agent` stays in the repo as the way to re-run this after any
prompt change. $0.04 for 29 questions.

## What would change the decision

- A judge pass (`sextant-judge`) over the multi-hop set would settle whether
  q36/q47 answers are as complete as the `expect` field suggests, and could
  replace recall@union with an answer-level number for this class. ~$0.05.
- Query expansion or HyDE for q48-shaped questions: no shared vocabulary
  between question and passage, reranker at zero. That is research question
  2, and this harness is how it would be graded end to end.
- A cheaper first turn. Every question costs two turns minimum — one to
  search, one to answer — and the search turn is 60% of the tokens because
  the system prompt is re-sent. Prompt caching would halve the per-question
  cost; it is not modelled in `pricing.py` and was not measured here.

## Reproduce

```bash
./.venv/bin/sextant-eval-agent --kinds multihop --sample 20 --store chroma_db --out run.json
./.venv/bin/sextant-eval-agent --kinds multihop --dry-run     # list without spending
```

Needs `GEMINI_API_KEY`. Without `--store` it builds the handbook corpus in a
temporary directory, like `sextant-eval`.
