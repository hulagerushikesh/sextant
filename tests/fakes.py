"""Scripted stand-ins for the Gemini client.

The agent loop is the hardest part of this system to test, because its input is
a model. Rather than mock the loop away, these replay real SDK objects through
it: the code under test does not know it is being tested, and the assertions are
about what the loop did with the turns, not about what was called.

Ported from the Anthropic fakes in Phase 8. The shape of the fake changed
completely -- streamed `Message` objects became `GenerateContentResponse` chunks
carrying `Candidate.content.parts` -- while every assertion in `test_agent.py`
stayed about behaviour, which is the point of testing the loop rather than the
client.
"""

from __future__ import annotations

from typing import Any, cast

from google.genai import types


def text_chunk(text: str, thought: bool = False) -> types.GenerateContentResponse:
    """One streamed text delta."""
    return _chunk([types.Part(text=text, thought=thought or None)])


def call_chunk(name: str, args: dict[str, Any], call_id: str = "call_1"):
    """A function call. Gemini delivers these whole, not as partial JSON."""
    return _chunk(
        [
            types.Part(
                function_call=types.FunctionCall(id=call_id, name=name, args=args),
                # Gemini 3 attaches this to the parts it returns and expects it
                # echoed back. The loop must not rebuild parts by hand.
                thought_signature=b"sig",
            )
        ]
    )


def final_chunk(
    finish: types.FinishReason = types.FinishReason.STOP,
    input_tokens: int = 100,
    output_tokens: int = 10,
    thinking_tokens: int = 0,
    cached_tokens: int = 0,
    grounding: types.GroundingMetadata | None = None,
) -> types.GenerateContentResponse:
    """The closing chunk: finish reason, cumulative usage, grounding if any."""
    return _chunk(
        [],
        finish_reason=finish,
        grounding_metadata=grounding,
        usage=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=input_tokens,
            cached_content_token_count=cached_tokens or None,
            candidates_token_count=output_tokens,
            thoughts_token_count=thinking_tokens or None,
        ),
    )


def grounding(
    *sites: tuple[str, str],
    supports: list[tuple[int, list[int]]] | None = None,
    queries: list[str] | None = None,
) -> types.GroundingMetadata:
    """Grounding metadata: web chunks, and byte-offset spans citing them.

    `supports` is (end_byte_offset, chunk_indices) -- the same shape the API
    returns, byte offsets and all, because that is the detail the loop has to
    get right.
    """
    return types.GroundingMetadata(
        web_search_queries=queries if queries is not None else ["a query"],
        grounding_chunks=[
            types.GroundingChunk(web=types.GroundingChunkWeb(title=title, uri=uri))
            for title, uri in sites
        ],
        grounding_supports=[
            types.GroundingSupport(
                segment=types.Segment(end_index=end),
                grounding_chunk_indices=indices,
            )
            for end, indices in (supports or [])
        ],
    )


def _chunk(
    parts: list[types.Part],
    finish_reason: types.FinishReason | None = None,
    grounding_metadata: types.GroundingMetadata | None = None,
    usage: types.GenerateContentResponseUsageMetadata | None = None,
) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                content=types.Content(role="model", parts=parts),
                finish_reason=finish_reason,
                grounding_metadata=grounding_metadata,
            )
        ],
        usage_metadata=usage,
    )


class FakeModels:
    def __init__(self, turns: list[list[types.GenerateContentResponse]]) -> None:
        self.turns = list(turns)
        self.requests: list[dict[str, Any]] = []

    async def generate_content_stream(self, **kwargs: Any):
        # Copy the contents list. The agent appends to the same list between
        # turns, so recording it by reference makes every recorded request show
        # the *final* conversation -- request 0 would appear to have carried
        # turns that had not happened yet.
        self.requests.append({**kwargs, "contents": list(kwargs.get("contents", []))})
        if not self.turns:
            raise AssertionError("the agent asked for more turns than the script provides")
        chunks = self.turns.pop(0)

        async def stream():
            for chunk in chunks:
                yield chunk

        return stream()


class FakeGemini:
    """Drop-in for `genai.Client(...).aio`, replaying a fixed list of turns."""

    def __init__(self, turns: list[list[types.GenerateContentResponse]]) -> None:
        self.models = FakeModels(turns)


class FakeHost:
    """An MCPHost that answers from a dict instead of a subprocess."""

    def __init__(self, results: dict[str, Any] | None = None, tools: list[str] | None = None):
        self.results = results or {}
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.error: str | None = None
        default = ["kb_search", "kb_ingest", "kb_stats", "kb_list"]
        self._names = tools if tools is not None else default

    @property
    def connected(self) -> bool:
        return True

    @property
    def tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "description": f"{name} description",
                "input_schema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }
            for name in self._names
        ]

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        if name not in self.results:
            from mcp_server.mcp_host import ToolUnavailable

            raise ToolUnavailable(f"no scripted result for {name}")
        return self.results[name]

    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None


def as_host(fake: FakeHost) -> Any:
    """Hand a FakeHost to code annotated for a real MCPHost.

    Declared once rather than cast at each call site. The alternative -- widening
    the production signature to a Protocol so a test double satisfies it -- would
    be changing shipped types to suit the tests.
    """
    return cast(Any, fake)


def kb_result(*hits: dict[str, Any]) -> dict[str, Any]:
    """A kb_search payload shaped like the real tool's."""
    return {
        "success": True,
        "results": list(hits),
        "total_found": len(hits),
        "scored_by": "cross-encoder",
        "collection_size": 100,
    }


def hit(chunk_id: str, title: str, content: str, **extra: Any) -> dict[str, Any]:
    return {
        "id": chunk_id,
        "document_id": chunk_id.split("#")[0],
        "title": title,
        "content": content,
        "source": extra.get("source", "notes.md"),
        "page": extra.get("page", 1),
        "section": extra.get("section"),
        "category": "general",
        "score": extra.get("score", 0.99),
        "scored_by": "cross-encoder",
        "dense_score": extra.get("dense_score", 0.6),
        "matched": extra.get("matched", ["dense", "lexical"]),
        "chunk_index": 0,
    }
