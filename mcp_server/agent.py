"""
The agent loop.

The model drives. Tools discovered over MCP at startup are declared to the Gemini
API alongside Google's built-in search, and the loop runs until the model stops
asking for tools. Two tiers, two very different execution paths: `kb_search`
round-trips through our own MCP subprocess, while `google_search` runs on
Google's servers and never reaches this process.

Ported from the Anthropic Messages API in Phase 8. Four things had to change, and
each one is a real difference rather than a rename:

1. **Citations are spans, not events.** Anthropic streamed a citation the moment
   it closed, so `[n]` could be appended mid-answer. Gemini attaches
   `grounding_metadata` to the *last* chunk of a turn, describing byte ranges
   over the finished text. Labels are therefore placed once, when the turn ends,
   and the client is sent the relabelled answer. See `_label_grounded`.
2. **Built-in tools and function declarations do not mix by default.** Sending
   both without `include_server_side_tool_invocations` is a 400. The API says so
   plainly, which is better than the silent degradation it could have been.
3. **Thinking is billed as output and spends `max_output_tokens`.** A generous
   answer allowance is not generous if the model thinks through most of it; the
   first port truncated a three-sentence answer at 42 characters for exactly
   this reason.
4. **History must be echoed back verbatim.** Gemini 3 attaches a
   `thought_signature` to the parts it returns, and rebuilding those parts by
   hand drops it. The model's own `Content` objects are appended unmodified.

Why a manual loop rather than the SDK's automatic function calling: the runner
owns the loop, and this phase needs three things from inside it -- text deltas
forwarded to the browser as they arrive, knowledge-base passages numbered before
the model sees them so its citations line up with the UI's, and a turn cap that
is visible in the response rather than buried in a config object.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import AsyncIterator
from typing import Any

from mcp_server.conversation import replay
from mcp_server.mcp_host import MCPHost, ToolUnavailable
from mcp_server.pricing import estimate_cost
from mcp_server.sources import Source, SourceRegistry
from tools import settings

logger = logging.getLogger(__name__)

# Flash-Lite, the cheapest tier that still runs this agent: $0.25/$1.50 per Mtok,
# roughly a third of gemini-3.7-flash. It has to be the *3.x* Flash-Lite, not
# 2.5: the loop is multi-turn tool use with thought signatures echoed back
# between turns ("tool call context circulation"), which 2.5-flash-lite rejects
# with a 400 -- only the Gemini-3 thinking models support it. Chosen as the
# default because for grounded RAG retrieval does the heavy lifting and the model
# only writes over passages it is handed. Overridable because model choice is a
# deployment decision, not a tuning knob: set SEXTANT_MODEL=gemini-3.7-flash
# for stronger synthesis (~3x the token price), or a pro model for the hardest
# multi-hop questions.
MODEL = settings.getenv("MODEL", "gemini-3.1-flash-lite") or "gemini-3.1-flash-lite"

# Thinking tokens come out of this budget, so it is the answer allowance *plus*
# room to reason. 4096 was enough for the answer alone and truncated in
# practice; the thinking level below is what keeps the reasoning share bounded.
MAX_OUTPUT_TOKENS = 8192

# `low` rather than off: tool selection across two tiers is exactly the decision
# thinking helps with, and off is not an option on every Gemini 3 model anyway.
THINKING_LEVEL = "low"  # types.ThinkingLevel.LOW; a str keeps this module SDK-free

# One model call per turn. Six is room for a search, a rephrase, a web fallback
# and an answer; past that the model is looping rather than working, and the
# user is paying for it either way.
MAX_TURNS = 6

# Only read tools are offered to the model. `kb_ingest` exists on the MCP server
# and is deliberately withheld here: answering a question must not be able to
# write to the corpus. The /ingest and /upload endpoints own that path, where a
# human asked for it.
READABLE_TOOLS = {"kb_search", "kb_list", "kb_stats"}

# Web search is off unless asked for. It is the one tier billed per request
# rather than per token -- $14 per 1,000 grounded requests once the monthly
# allowance is gone, which is several times what a corpus answer costs -- and
# the point of this system is the private corpus. The tool is not removed:
# every path that formats a grounded citation, prices it and shows it in the
# trace stays live, so turning it back on is one flag and not a re-port.
#
#   export SEXTANT_WEB_SEARCH=on        # for the whole server
#   {"query": "...", "web_search": true}  # for one request
WEB_SEARCH_ENV = settings.env_name("WEB_SEARCH")
_TRUTHY = {"1", "true", "yes", "on"}


def web_search_default() -> bool:
    """Whether web search is offered when a request does not say."""
    return (settings.getenv("WEB_SEARCH", "") or "").strip().lower() in _TRUTHY

SYSTEM_PROMPT = """You answer questions for a user who keeps a private document \
collection. You have tools; use them before answering.

Choosing a tool:
- Try the knowledge base first for anything that could plausibly be in the \
user's own documents. Phrase the query as a full question or a descriptive \
sentence, not two keywords -- matching is on meaning, and short queries rank \
badly.
- A question with two parts -- "which X does A use, and how does X work" -- \
is two searches. Run one for each part before answering, rather than one query \
that names both: the passage that answers the first half is rarely the one that \
answers the second. If the passages you have cover only part of the question, \
search for the missing part before saying the documents do not cover it.
- If it comes back empty, or the passages do not actually answer what was \
asked, decide what to do next rather than giving up: search again with \
different wording if the first phrasing was poor, or use web search if the \
question is about public, current, or general knowledge.
- A question about the collection itself -- what the documents cover, which \
documents there are, which to read first, how they relate -- is a listing, not \
a search. Use kb_list and answer from the titles and overviews it returns, \
naming documents by title; a listing has no passage labels to cite. "Which \
of my documents cover X" is a listing even though it names a topic: list \
first, and search inside the named documents only if the question also asks \
what they say. Use kb_search when the question is about something *inside* \
a document.
- Do not use web search for a question that is clearly about the user's own \
material. An answer from the open web is not an answer about their documents.

Citing:
- Knowledge-base passages arrive labelled, like [3]. Every claim you take from \
one must end with that label. Passages are excerpts, not whole documents, so \
cite the passage you actually used rather than the first one returned.
- Web results are cited for you; write those sentences normally.
- Never cite a label you were not given.
- Write each label in its own brackets -- [1][4], not [1, 4].
- Labels are stable for the whole conversation. A number you used in an earlier \
answer still points at the same passage, so reuse it rather than renumbering, \
and do not invent a label for something you have not retrieved in this session.

Answering:
- Use only what the tools returned. Do not add facts from your own knowledge, \
even if you are confident they are correct.
- If nothing you found answers the question, say so plainly in a sentence or \
two and stop. Do not pad the answer with adjacent information, and do not \
speculate.
- If sources disagree, say so and cite each side.
- Answer in prose, at the length the question needs. No preamble like "Based on \
the sources provided".
- Plain text only. The interface renders paragraphs, bullet lists, headings, \
bold and inline code, and nothing else -- LaTeX, tables and block equations \
reach the reader as raw source. Write an equation as inline code, like \
`P = F P F^T + Q`, or describe it in words."""

NO_WEB_NOTE = """

Web search is switched off in this session, so the knowledge base is all you \
have. If the passages you retrieve do not answer the question, say that the \
documents do not cover it -- do not answer from your own knowledge, and do not \
tell the user to search the web themselves as though that were part of the \
answer."""

LAST_TURN_NOTE = """That was the last search available for this question. Answer \
now from the passages you already have; if none of them answer it, say the \
documents do not cover it."""

NO_KB_NOTE = """

The knowledge base is unavailable in this session, so you have web search only. \
If the question is about the user's own documents, say the collection could not \
be reached -- do not quietly answer from the web instead."""


class AgentUnavailable(RuntimeError):
    """Raised when the agent cannot run at all (missing key, SDK not installed)."""


def _sdk():
    """Import the Google SDK, or explain why we can't."""
    try:
        from google import genai
        from google.genai import types
    except ImportError as e:  # pragma: no cover - dependency is declared
        raise AgentUnavailable(
            "The `google-genai` package is not installed. Run: pip install -e '.[dev]'"
        ) from e
    return genai, types


def _client():
    """Build an async Gemini client, or explain why we can't."""
    genai, _ = _sdk()
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        raise AgentUnavailable(
            "GEMINI_API_KEY is not set. Add it to the .env file at the repo root "
            "(see .env.example) and restart the server."
        )
    return genai.Client(api_key=key).aio


def declare_tools(host: MCPHost, web_search: bool | None = None) -> list[dict[str, Any]]:
    """Turn discovered MCP schemas into Gemini tool declarations.

    Still a filter and a rename. `parameters_json_schema` takes the MCP server's
    JSON Schema verbatim -- titles, defaults, bounds and enums included -- so no
    schema translation layer is needed here. That was the main risk in the port
    and it evaporated; the older `parameters` field takes a restricted subset and
    would have needed one.

    Returns plain dicts, and the SDK objects are built in `_tool_config`. Keeping
    this SDK-free is what lets `/tools` and `/health` report what the model was
    offered without importing the client.
    """
    tools = [
        {
            "name": tool["name"],
            "description": tool["description"],
            "input_schema": tool["input_schema"],
        }
        for tool in host.tools
        if tool["name"] in READABLE_TOOLS
    ]
    if web_search_default() if web_search is None else web_search:
        tools.append({"name": "google_search", "description": "Google Search, run by Google."})
    return tools


def _tool_config(declared: list[dict[str, Any]]):
    """Build the SDK tool objects and the config that lets them coexist.

    Function declarations and a built-in tool in one request are rejected with a
    400 unless `include_server_side_tool_invocations` is set. Nothing infers it.
    """
    _, types = _sdk()
    functions = [
        types.FunctionDeclaration(
            name=tool["name"],
            description=tool["description"],
            parameters_json_schema=tool["input_schema"],
        )
        for tool in declared
        if "input_schema" in tool
    ]

    tools = []
    if functions:
        tools.append(types.Tool(function_declarations=functions))
    if any(tool["name"] == "google_search" for tool in declared):
        tools.append(types.Tool(google_search=types.GoogleSearch()))
    return tools, types.ToolConfig(include_server_side_tool_invocations=True)


def _format_kb_result(result: dict[str, Any], registry: SourceRegistry) -> str:
    """Render `kb_search` output for the model, numbering each passage.

    The label written here is the same one the browser will print, which is what
    lets the model's `[3]` mean anything to a reader.
    """
    if not result.get("success", True):
        return f"The knowledge base could not be searched: {result.get('error', 'unknown error')}"

    hits = result.get("results") or []
    if not hits:
        size = result.get("collection_size")
        if size == 0:
            return "The knowledge base is empty -- no documents have been ingested yet."
        return (
            f"No passages matched that query. The collection holds {size} document(s), "
            "so a different phrasing may still find something."
        )

    # Naming the scorer matters: a cross-encoder relevance and a fusion rank are
    # different quantities, and the model should not read one as the other.
    scored_by = result.get("scored_by", "unknown")
    blocks = []
    for hit in hits:
        source = registry.add_kb(hit)
        header = f"[{source.n}] {source.title}"
        if source.location:
            header += f" ({source.location})"
        if source.score is not None:
            header += f" -- {scored_by} score {source.score}"
        blocks.append(f"{header}\n{source.content}")
    return "\n\n".join(blocks)


def _format_kb_list(result: dict[str, Any]) -> str:
    """Render `kb_list` output for the model: one block per document.

    Plain text rather than the JSON, so the model reads titles and overviews
    the way it reads passages, and so an empty collection says so in words.
    """
    if result.get("status") == "unavailable":
        return f"The knowledge base could not be listed: {result.get('error', 'unknown error')}"
    documents = result.get("documents") or []
    if not documents:
        return "The knowledge base is empty -- no documents have been ingested yet."
    blocks = [f"{len(documents)} document(s):"]
    for doc in documents:
        size = f"{doc.get('chunks', 0)} chunk(s)"
        if doc.get("pages"):
            size = f"{doc['pages']} page(s), {size}"
        title = doc.get("title", "Untitled document")
        header = f"- {title} [{doc.get('category', 'general')}; {size}]"
        about = doc.get("overview") or doc.get("lead")
        blocks.append(f"{header}\n  {about}" if about else header)
    return "\n".join(blocks)


def _summarise(name: str, result: dict[str, Any], is_error: bool) -> dict[str, Any]:
    """One line about what a tool gave back, for the trace panel.

    The trace used to show only what the model asked for. That makes the most
    interesting behaviour in the system invisible: a search returning nothing and
    the model rephrasing looks identical to a search returning ten passages, and
    "the model searched twice" reads as a bug rather than as the loop working.
    """
    if is_error:
        return {"status": "error"}
    if name == "kb_search":
        hits = result.get("results") or []
        summary: dict[str, Any] = {
            "status": "ok" if hits else "empty",
            "hits": len(hits),
            "scored_by": result.get("scored_by"),
        }
        if hits and hits[0].get("score") is not None:
            summary["top_score"] = hits[0]["score"]
        return summary
    if name == "kb_list":
        count = result.get("count", len(result.get("documents") or []))
        return {"status": "ok", "documents": count}
    if name == "kb_stats":
        # `collection_size` counts chunks, not documents -- the two diverged in
        # Phase 4 and the field kept its pre-chunking name.
        return {
            "status": "ok",
            "documents": result.get("documents"),
            "chunks": result.get("collection_size"),
        }
    return {"status": "ok"}


async def _execute(name: str, arguments: dict[str, Any], host: MCPHost, registry: SourceRegistry):
    """Run one MCP tool. Returns (text for the model, is_error, trace summary).

    A tool failure is reported back to the model as a tool result rather than
    raised: it can try a different query, and a knowledge base that is down
    should not take the whole answer with it.
    """
    try:
        result = await host.call(name, arguments)
    except ToolUnavailable as e:
        return str(e), True, {"status": "error", "error": str(e)}

    summary = _summarise(name, result, is_error=False)
    if name == "kb_search":
        return _format_kb_result(result, registry), False, summary
    if name == "kb_list":
        return _format_kb_list(result), False, summary
    return json.dumps(result, default=str), False, summary


def _register_grounding(metadata: Any, registry: SourceRegistry) -> list[Source | None]:
    """Register this turn's web results, in the order Gemini indexed them.

    Returns a list positionally aligned with `grounding_chunks`, because
    `grounding_supports` refers to sources by index into that list and nothing
    else. A chunk that is not a web result becomes None rather than shifting
    every index after it.

    Two fidelity losses worth naming, both Google's shape rather than ours. The
    URI is a `vertexaisearch.cloud.google.com` redirect, not the page's own
    address -- Google requires that link be the one displayed. And `title` is the
    site's domain, so the source list reads "wikipedia.org" where the Anthropic
    tier gave a page title.
    """
    registered: list[Source | None] = []
    for chunk in getattr(metadata, "grounding_chunks", None) or []:
        web = getattr(chunk, "web", None)
        if web is None or not getattr(web, "uri", None):
            registered.append(None)
            continue
        registered.append(registry.add_web(web.title or web.domain or web.uri, web.uri))
    return registered


def _label_grounded(text: str, metadata: Any, registered: list[Source | None]) -> str:
    """Insert `[n]` into a grounded answer at the spans Gemini attributed.

    `segment.end_index` is a **UTF-8 byte** offset, not a character offset. On
    ASCII the two agree, which is exactly why this is worth stating: an em dash
    or an accent silently shifts every later label by a character or two, and the
    bug would only appear on some answers.

    Insertions run back-to-front so earlier offsets stay valid.
    """
    supports = getattr(metadata, "grounding_supports", None) or []
    if not supports:
        return text

    raw = text.encode("utf-8")
    insertions: list[tuple[int, str]] = []
    for support in supports:
        segment = getattr(support, "segment", None)
        end = getattr(segment, "end_index", None) if segment else None
        if end is None:
            continue
        numbers = sorted(
            {
                registered[i].n
                for i in (getattr(support, "grounding_chunk_indices", None) or [])
                if 0 <= i < len(registered) and registered[i] is not None
            }
        )
        if numbers:
            insertions.append((min(end, len(raw)), "".join(f"[{n}]" for n in numbers)))

    for offset, label in sorted(insertions, reverse=True):
        raw = raw[:offset] + label.encode("utf-8") + raw[offset:]
    return raw.decode("utf-8", errors="replace")


async def run(
    query: str,
    host: MCPHost,
    history: list[dict[str, Any]] | None = None,
    prior_sources: list[dict[str, Any]] | None = None,
    web_search: bool | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Answer `query`, yielding events as the agent works.

    `web_search` overrides the server default for this one question; None
    means whatever `SEXTANT_WEB_SEARCH` says, which is off.

    `history` is the conversation so far and `prior_sources` the labels already
    handed out in it. Both come from the client -- this process keeps no session
    state, so a second browser tab is a second conversation and a server restart
    loses nothing. See `conversation.py` for what is and is not replayed.

    Event types:
      tool_call   : the model chose a tool. `where` is "mcp" or "google".
      tool_result : that tool came back. Carries a short summary and how long it
                    took, so an empty search is visible as an empty search.
      sources     : the numbered source list grew. Sent whenever it does, so the
                    UI can show citations before the sentence citing them lands.
      token       : one text delta of the answer.
      answer      : the finished text of a turn, relabelled with web citations.
                    Only sent when grounding attributed something; the client
                    replaces the streamed text with it. Gemini reports citations
                    as spans over completed text, so there is no honest way to
                    place them while the text is still arriving.
      done        : finished. Carries the final source list, usage and turn count.

    Both API endpoints consume this: the streaming one forwards events as they
    arrive, the plain one accumulates them.
    """
    client = _client()
    _, types = _sdk()

    declared = declare_tools(host, web_search)
    tools, tool_config = _tool_config(declared)
    offered = {tool["name"] for tool in declared}
    system = SYSTEM_PROMPT
    if "kb_search" not in offered:
        system += NO_KB_NOTE
    if "google_search" not in offered:
        system += NO_WEB_NOTE
    config = types.GenerateContentConfig(
        system_instruction=system,
        tools=tools,
        tool_config=tool_config,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        thinking_config=types.ThinkingConfig(
            thinking_level=types.ThinkingLevel(THINKING_LEVEL.upper())
        ),
        # This loop is the point of the file. The SDK's own runner would swallow
        # it, and with it the streamed deltas and the pre-numbered passages.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    registry = SourceRegistry()
    if prior_sources:
        registry.restore(prior_sources)

    contents: list[Any] = [
        types.Content(role=turn["role"] if turn["role"] == "user" else "model",
                      parts=[types.Part(text=turn["content"])])
        for turn in replay(history or [])
    ]
    contents.append(types.Content(role="user", parts=[types.Part(text=query)]))

    input_tokens = output_tokens = 0
    grounded_requests = 0
    turns = 0
    known_sources = len(registry)  # restored labels are already on the client
    truncated = True  # until the model ends a turn of its own accord

    while turns < MAX_TURNS:
        turns += 1
        calls: list[Any] = []
        parts: list[Any] = []
        spoken = ""
        grounding = None
        finish_reason = None
        turn_input = turn_output = 0

        stream = await client.models.generate_content_stream(
            model=MODEL,
            contents=contents,
            config=config,
        )
        async for chunk in stream:
            candidate = (chunk.candidates or [None])[0]
            if candidate is None:
                continue
            if candidate.finish_reason is not None:
                finish_reason = candidate.finish_reason
            # Attached to the closing chunk, describing the whole turn.
            if candidate.grounding_metadata is not None:
                grounding = candidate.grounding_metadata

            content = candidate.content
            for part in (content.parts or []) if content else []:
                # Appended unmodified: `thought_signature` rides on the part, and
                # rebuilding it would drop the model's reasoning continuity.
                parts.append(part)
                if part.function_call is not None:
                    calls.append(part.function_call)
                elif part.text and not part.thought:
                    spoken += part.text
                    yield {"type": "token", "text": part.text}

            usage = chunk.usage_metadata
            if usage is not None:
                # Reported cumulatively per turn, so the last chunk wins rather
                # than the sum of every chunk seen.
                turn_input = usage.prompt_token_count or 0
                # Thinking is billed as output; folding it in here, where the
                # split is visible, keeps `pricing.py` from having to assume it.
                turn_output = (usage.candidates_token_count or 0) + (
                    usage.thoughts_token_count or 0
                )

        input_tokens += turn_input
        output_tokens += turn_output

        if grounding is not None:
            grounded_requests += 1
            registered = _register_grounding(grounding, registry)
            # The web tier leaves no function_call to build a trace row from --
            # it ran on Google's servers. The queries it chose are the only
            # evidence it happened, and without them the trace shows an answer
            # appearing from nowhere.
            for search in getattr(grounding, "web_search_queries", None) or []:
                yield {
                    "type": "tool_call",
                    "where": "google",
                    "name": "google_search",
                    "input": {"query": search},
                }
            if grounding.web_search_queries:
                found = sum(1 for source in registered if source is not None)
                yield {
                    "type": "tool_result",
                    "where": "google",
                    "name": "google_search",
                    # No duration: the search ran on Google's servers and its
                    # timing is not ours to report.
                    "summary": {"status": "ok" if found else "empty", "hits": found},
                }
            if spoken:
                labelled = _label_grounded(spoken, grounding, registered)
                if labelled != spoken:
                    yield {"type": "answer", "text": labelled}

        if len(registry) > known_sources:
            known_sources = len(registry)
            yield {"type": "sources", "sources": registry.as_json()}

        if parts:
            contents.append(types.Content(role="model", parts=parts))

        if not calls:
            truncated = finish_reason == types.FinishReason.MAX_TOKENS
            if finish_reason not in (None, types.FinishReason.STOP,
                                     types.FinishReason.MAX_TOKENS):
                # SAFETY, RECITATION, MALFORMED_FUNCTION_CALL and friends. The
                # answer stops either way; saying which is the difference between
                # a bug report and a shrug.
                logger.warning("turn ended on %s", finish_reason)
            break

        results = []
        for call in calls:
            logger.info("calling %s", call.name, extra={"agent_tool": call.name})
            yield {
                "type": "tool_call",
                "where": "mcp",
                "name": call.name,
                "input": dict(call.args or {}),
            }
            started = time.perf_counter()
            text, is_error, summary = await _execute(
                call.name, dict(call.args or {}), host, registry
            )
            yield {
                "type": "tool_result",
                "where": "mcp",
                "name": call.name,
                "summary": summary,
                "duration_ms": round((time.perf_counter() - started) * 1000),
            }
            results.append(
                types.Part.from_function_response(
                    name=call.name,
                    # A dict, not a string: the API rejects a bare scalar here,
                    # and `is_error` travels alongside so the model can tell a
                    # failed search from an empty one.
                    response={"result": text, "error": is_error},
                )
            )

        contents.append(types.Content(role="user", parts=results))
        if turns == MAX_TURNS - 1:
            # The next turn is the last one allowed. Told as a user message,
            # because that is what it is: the runner reporting that the budget
            # is spent. Without it a model still searching at the cap ends the
            # loop with function calls and no text, and the user sees an empty
            # answer -- seen once in six runs of the multi-hop set
            # (`learning/agent-loop.md`). Forbidding calls through
            # `FunctionCallingConfigMode.NONE` was tried first: on
            # gemini-3.1-flash-lite the model attempts the call anyway and the
            # turn ends MALFORMED_FUNCTION_CALL with no text, which is the same
            # empty answer by another route.
            contents.append(types.Content(role="user", parts=[types.Part(text=LAST_TURN_NOTE)]))
        if len(registry) > known_sources:
            known_sources = len(registry)
            yield {"type": "sources", "sources": registry.as_json()}

    cost = estimate_cost(input_tokens, output_tokens, grounded_requests)
    logger.info(
        "agent finished in %d turn(s), %d source(s)",
        turns,
        len(registry),
        extra={
            "agent_turns": turns,
            "agent_truncated": truncated,
            "agent_input_tokens": input_tokens,
            "agent_output_tokens": output_tokens,
            "agent_grounded_requests": grounded_requests,
            "agent_cost_usd": cost,
            "agent_sources": len(registry),
        },
    )
    yield {
        "type": "done",
        "sources": registry.as_json(),
        "turns": turns,
        "truncated": truncated,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "grounded_requests": grounded_requests,
            # Reported per query rather than aggregated somewhere: the cost of a
            # six-turn loop is only actionable if you see it next to the answer.
            "cost_usd": cost,
        },
    }
