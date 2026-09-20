# Prompt caching — implicit never fires, explicit saves 40% gross and 28% net

*Milestone 17, the "cheaper first turn" left open in
[`agent-loop.md`](agent-loop.md). 2026-09-20. Cost: $0.027 ≈ ₹2.3 (12
agent runs; the explicit cache lived 15 minutes, < $0.001 of storage).
Decision: **no knob** — the explicit cache clears the gross bar and misses
the pre-registered net one at the traffic this deployment sees;
`cached_tokens` now reaches the usage line and `pricing.py` bills it at the
cached rate, so the number is honest if a cache is ever turned on.*

## Hypothesis

Every turn of the loop re-sends the same prefix: the system prompt and the
three tool schemas. `agent-loop.md` measured the search turn at 60% of a
question's tokens for that reason and guessed caching would halve the
per-question cost. At ₹0 first: `count_tokens` puts the system prompt at
753 tokens and the tool schemas at ~685 as JSON text — about 1,440. Gemini
runs an implicit cache by default on 2.5+ models with a minimum prefix of
4,096 tokens for every 3.x Flash the docs list (3.1 Flash-Lite is not
listed), and bills cached input on 3.1 Flash-Lite at $0.025/M against
$0.25/M — a tenth — with explicit-cache storage at $1.00 per million tokens
per hour.

Pre-registered: **H1** implicit caching never fires on this prefix —
`cached_content_token_count` is 0 on every turn of four questions run twice
back to back. **H2** an explicit cache of the same system prompt and tools
is refused as under the minimum; if accepted, it cuts the search turn's
billed input by ≥ 40%. Rule: implicit fires → price it, build nothing;
explicit works and saves ≥ 30% per query *net of storage at 5 queries an
hour* → opt-in knob, not the default; neither → note only.

## Setup

q01, q10, q29, g04 (three paraphrase, one global) through the real loop on
the handbook store, web search off. Three passes: cold, warm (immediately
after, same prefix), explicit (`caches.create` with the agent's
`system_instruction`, `tools` and `tool_config`, `ttl` 15 min, then every
turn sent with `cached_content` in place of them). Each model call logged
its `usage_metadata`; the agent now carries `cached_content_token_count`
through to `usage.cached_tokens`.

## Results

The prefix is **1,410 tokens** — the explicit cache reports it exactly; the
question adds 11–21. Per turn, `prompt / cached`:

| pass | q01 | q10 | q29 | g04 |
| --- | --- | --- | --- | --- |
| cold | 1428/0 · 2606/0 | 1422/0 · 1935/0 | 1421/0 · 1584/0 · 3043/0 · 3552/0 | 1431/0 · 3612/0 |
| warm | 1428/0 · 2215/0 | 1422/0 · 1705/0 | 1421/0 … 3842/0 (6 turns) | 1431/0 · 2910/0 |
| explicit | 1428/**1410** · 2594/**1410** | 1422/1410 · 1922/1410 | 6 turns, 1410 each | 1431/1410 · 2906/1410 |

Cost per question, `pricing.py` rates, cached tokens at $0.025/M:

| pass | turns | q01 | q10 | q29 | g04 | total |
| --- | --- | --- | --- | --- | --- | --- |
| cold | 10 | $0.0018 | $0.0013 | $0.0031 | $0.0018 | $0.0080 |
| warm | 12 | $0.0015 | $0.0012 | $0.0055 | $0.0014 | $0.0097 |
| explicit, billed as uncached | 12 | $0.0017 | $0.0012 | $0.0051 | $0.0015 | $0.0095 |
| explicit, at the cached rate | 12 | $0.0011 (−38%) | $0.0006 (−52%) | $0.0032 (−37%) | $0.0009 (−42%) | **$0.0057 (−40%)** |

**H1 holds: implicit caching fired on none of 22 turns**, cold or warm.
1,410 tokens is under the minimum, whatever it is for Flash-Lite.

**H2's first half fails in the useful direction: the cache was accepted at
1,410 tokens**, so Flash-Lite's explicit minimum is at or below that, and
every subsequent turn — including the passage-laden second ones — served
the whole prefix from it. Gross saving 37–52% per question, 40% over the
pass, which clears the 40% bar for the search turn (its input goes from
1,428 billed to 18 + 1,410 at a tenth: −89% on that turn's input).

**The net clause fails, narrowly.** A turn saves 1,410 × ($0.25 − $0.025)/M
= $0.00032; the cache costs $0.0014 an hour to keep. At 5 questions an
hour, storage is $0.00028 a question against a mean saving of $0.00095:
net $0.00067 on a $0.0024 question — **28%**, against the 30% the rule
asked for; on the median two-turn question ($0.0015) it is 23%. Break-even
is about 1.5 questions an hour; the rule's 30% needs about 10.

Also seen: q29 took 4 turns cold and 6 warm and explicit — the loop
rephrasing on an empty search ([`floor-fallback.md`](floor-fallback.md)),
not the cache. Three passes, three different turn counts for the same
question.

## What this says

1. **The repeated prefix is real and cacheable, and at this deployment's
   traffic it is not worth managing.** The product runs on demand — the VM
   is stopped more than it is up — and an explicit cache burns storage for
   every idle hour it is alive, needs re-creating on every prompt or tool
   change (two tool sets: with and without `google_search`), and expires
   on its TTL. For a service answering ten questions an hour it is a third
   off the model bill; for one answering two, it is a wash with more
   moving parts.
2. **Implicit caching is a large-context feature.** A 1,400-token prefix is
   under every published minimum. It would fire for free once the
   conversation history plus passages crosses 4,096 tokens on a later turn
   — but that content is per-conversation, and a cache hit on it is the
   same request minus a few hundredths of a cent.
3. **The number is now honest either way.** `usage.cached_tokens` reaches
   the client and the log, and `estimate_cost` bills it at the cached rate.
   In the product it reads 0; if a cache is ever configured, the cost line
   falls with it instead of overstating.
4. **The search turn is 60% of a question because of the prefix, and the
   prefix is 1,410 tokens because the prompt is long.** The cheaper first
   turn the loop note asked for is a shorter system prompt as much as a
   cache — but the bullets in it were each measured in ([`kb-list.md`](kb-list.md),
   [`agent-loop.md`](agent-loop.md)), and cutting words to save $0.0001 a
   turn is not an experiment with a rule worth writing.

## Reproducing

`exp_prompt_cache.py OUT.json` (session scratchpad): wraps the SDK client
so every stream logs its usage, runs the three passes, creates and deletes
the cache. ~4 minutes, ~$0.03. `SEXTANT_JUDGE_MODEL` is not involved; no
answer is graded here.
