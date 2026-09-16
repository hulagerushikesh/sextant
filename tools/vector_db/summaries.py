"""
One model-written summary per document, stored as a chunk.

A flat chunk store answers local questions: the passage that says X is found
when you ask about X. It has no passage that says what a document *is*, so
"what does this collection cover" or "which document compares A and B"
retrieves whichever chunk happens to contain the word "cover". A summary
chunk is that missing passage. It competes in the same index as everything
else -- no second store, no tree -- which is the cheapest version of the
RAPTOR idea and enough to measure whether the full tree would be worth
building (`learning/summary-chunks.md`).

Opt-in (`sextant-ingest --summaries`) because it costs a model call per
document, and the model needs `GEMINI_API_KEY`. Everything else in ingestion
runs without a key and keeps doing so.
"""

from __future__ import annotations

import os
from typing import Any

from tools import settings

# Same model as the agent unless overridden: summarising is the cheapest kind
# of generation there is, and a document is read once.
MODEL = settings.getenv("MODEL", "gemini-3.1-flash-lite") or "gemini-3.1-flash-lite"

# Gemini's window is a million tokens; this is a quarter of that in characters
# and covers every document this project has met, including a 144-page
# survey (~800k chars). Past it the head is sent with a note, because a
# summary of the first half of a document is still a summary of it, and an
# API error is not.
MAX_INPUT_CHARS = 1_000_000

# Enough room for the summary and the model's thinking; the summary itself is
# capped by the prompt, not the budget.
MAX_OUTPUT_TOKENS = 2048

SUMMARY_PROMPT = """Write an overview of the document below for a search index. \
Someone will read it to decide whether this document is the one that answers \
their question, and it will be matched against questions like "which of my \
documents covers X" or "compare A and B".

Four to eight sentences, plain prose, no heading, no bullet list. Say what \
kind of document it is and what it is about, then the topics it covers in the \
order it covers them, naming the specific things -- methods, settings, error \
codes, models, datasets -- a reader might ask about. Use the document's own \
terms. Do not evaluate it, and do not add anything it does not say."""

SUMMARY_KIND = "summary"


class SummariesUnavailable(RuntimeError):
    """Raised when summaries were asked for and cannot be produced."""


def summary_chunk_id(doc_id: str) -> str:
    """The id a document's summary chunk is stored under. One per document."""
    return f"{doc_id}#{SUMMARY_KIND}"


def summary_text(title: str, summary: str) -> str:
    """What is embedded and shown: the overview, introduced as one."""
    return f"Overview of {title}.\n{summary.strip()}"


def _client() -> Any:
    try:
        from google import genai
    except ImportError as e:  # pragma: no cover - dependency is declared
        raise SummariesUnavailable(
            "The `google-genai` package is not installed. Run: pip install -e '.[dev]'"
        ) from e
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise SummariesUnavailable(
            "GEMINI_API_KEY is not set; summaries need a model. Ingest without "
            "--summaries, or add the key to .env."
        )
    return genai.Client(api_key=key).aio


async def summarise(text: str, title: str, client: Any = None) -> str:
    """One summary of `text`. `client` is injectable so tests need no key."""
    from google.genai import types

    client = client or _client()
    body = text
    if len(body) > MAX_INPUT_CHARS:
        body = body[:MAX_INPUT_CHARS] + "\n\n[document truncated here for summarising]"

    response = await client.models.generate_content(
        model=MODEL,
        contents=f"Title: {title}\n\nDocument:\n{body}",
        config=types.GenerateContentConfig(
            system_instruction=SUMMARY_PROMPT,
            max_output_tokens=MAX_OUTPUT_TOKENS,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
        ),
    )
    summary = (response.text or "").strip()
    if not summary:
        finish = response.candidates[0].finish_reason if response.candidates else "none"
        raise SummariesUnavailable(f"The model returned no summary for {title!r} ({finish}).")
    return summary
