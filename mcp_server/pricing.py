"""
What a query cost.

A per-query number is the difference between "the agent sometimes takes six
turns" being a curiosity and being a decision. The turn cap in `agent.py` exists
because of this file.

Rates are Google list prices for the Gemini API paid tier, in USD per million
tokens. They are hard-coded and dated on purpose: there is no pricing endpoint to
read, so a stale number should be visibly stale rather than quietly wrong.
Caching and batch pricing are not modelled -- nothing here uses either.

Two things differ from the Anthropic pricing this replaces, and both change what
the number means:

* **Thinking tokens are billed as output.** Gemini 3 thinks by default, and on a
  tool-use turn the thinking can outweigh the visible answer. `usage_metadata`
  reports them separately; they are added to the output count here rather than
  quietly dropped, because dropping them understates a six-turn loop badly.
* **Search is billed per request, not per token.** Anthropic's server-side web
  search came out of the same token budget. Google bills grounded requests
  separately, so a single web-backed answer can cost more than the tokens
  suggest. `GROUNDING_USD_PER_REQUEST` is the list rate *after* the monthly free
  allowance, which this file does not track -- it cannot know the account's
  month-to-date usage, so it prices every grounded request as though the
  allowance is gone. That overstates cost early in a month and is never wrong in
  the direction that matters.
"""

from __future__ import annotations

PRICING_AS_OF = "2026-08"

# gemini-3.1-flash-lite, the default in `agent.py`. A flat list rate, not an
# introductory one, so there is no expiry to track. This model thinks, and
# thinking bills as output (folded into the output count where it is read), so
# the output rate carries that. If AGENTICRAG_MODEL is bumped to a flash or pro
# model these numbers understate the bill -- update them to match whatever model
# is actually deployed (gemini-3.7-flash is $0.75/$3.75 on its introductory rate
# to 2026-12-31, then $1.50/$7.50).
INPUT_USD_PER_MTOK = 0.25
OUTPUT_USD_PER_MTOK = 1.50

# $14 per 1,000 grounded requests once the 5,000/month free allowance is used.
GROUNDING_USD_PER_REQUEST = 0.014


def estimate_cost(
    input_tokens: int, output_tokens: int, grounded_requests: int = 0
) -> float:
    """USD for one query's model usage, rounded to the nearest hundredth of a cent.

    `output_tokens` is expected to already include thinking tokens; the agent
    adds them at the point it reads `usage_metadata`, where the distinction is
    visible, rather than here, where it would be a silent assumption.
    """
    dollars = (
        input_tokens * INPUT_USD_PER_MTOK + output_tokens * OUTPUT_USD_PER_MTOK
    ) / 1_000_000
    return round(dollars + grounded_requests * GROUNDING_USD_PER_REQUEST, 6)
