"""
Turning a client-supplied transcript into model input.

Phase 7 asked for chat history. There are two things that could mean, and only
one of them is worth building. The cheap one is a list of past answers rendered
in the browser: it looks like a conversation and behaves like a search box,
because every question still arrives at the model alone. Ask "and the second
one?" and it has no idea what you mean.

The other is this: prior turns go back to the model, so a follow-up is a
follow-up. That costs input tokens on every question and needs bounding, which
is what this module is.

What is replayed, and what is not
---------------------------------
Prose only -- the user's questions and the model's answers. The tool calls and
retrieved passages from earlier turns are dropped on purpose:

* Context. Replaying tool results means every passage ever retrieved is resent
  on every question. Ten turns into a conversation that is most of the request,
  and the user pays for it whether or not it is relevant.
* Correctness. `tool_use` and `tool_result` blocks are paired by id. Round-trip
  those through a browser and any dropped or reordered turn is a 400 from the
  API, not a slightly worse answer.

The cost is real and worth naming: the model cannot re-read a passage from two
turns ago, so if a follow-up depends on one, it searches again. That is a second
retrieval instead of a much larger prompt, and retrieval is the cheap half.

Citation labels are the exception -- they are not replayed as content but they
must still resolve, which is `SourceRegistry.restore`. Without it turn two starts
numbering at [1] again and the transcript has two different [1]s in it.
"""

from __future__ import annotations

from typing import Any

# Six exchanges. Long enough that a line of questioning survives; short enough
# that an afternoon's conversation does not silently become a 100k-token prompt.
MAX_TURNS = 12

# Total prose replayed. A single long answer can blow the turn budget's intent,
# so there is a character bound too, applied oldest-first.
MAX_CHARS = 24_000

# One turn's contribution. Longer turns are tail-truncated rather than dropped:
# the end of an answer is the part a follow-up usually refers to.
MAX_TURN_CHARS = 4_000

_ELLIPSIS = "… "


def _clip(text: str) -> str:
    """Keep the last MAX_TURN_CHARS of a turn, marking that it was cut."""
    if len(text) <= MAX_TURN_CHARS:
        return text
    return _ELLIPSIS + text[-MAX_TURN_CHARS:]


def replay(history: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Bound and normalise a client transcript into Messages API turns.

    Everything here is defensive because the input is whatever the browser sent.
    A transcript that does not alternate, or that ends on a user turn, is not an
    error the caller should see -- it is a stale tab, or an aborted request whose
    half-answer never arrived. Drop what does not fit and answer the question.

    Returns turns ready to precede the current question: alternating, starting
    with `user`, ending with `assistant`.
    """
    turns: list[dict[str, str]] = []
    expected = "user"
    for entry in history:
        role = entry.get("role")
        content = str(entry.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        if role != expected:
            # An unanswered question, or two answers in a row. Keep the newer of
            # the pair rather than dropping the rest of the conversation.
            if role == "user" and turns:
                turns.pop()
            else:
                continue
        turns.append({"role": role, "content": _clip(content)})
        expected = "assistant" if role == "user" else "user"

    # The current question is appended by the caller, so history must end on an
    # answer. A trailing question means the previous request never completed.
    if turns and turns[-1]["role"] == "user":
        turns.pop()

    if len(turns) > MAX_TURNS:
        turns = turns[-MAX_TURNS:]
    # Trim oldest-first, in pairs, so the remainder still starts with a question.
    while turns and sum(len(t["content"]) for t in turns) > MAX_CHARS:
        del turns[:2]

    return turns
