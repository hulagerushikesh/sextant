"""
Agent server.

Retrieval runs over MCP; the knowledge base is a separate process speaking
JSON-RPC over stdio and is never imported here (see `mcp_host.py`). The model
chooses which of its discovered tools to call, and when to stop (see `agent.py`).

This file is now thin on purpose. It holds the HTTP surface -- request shapes,
the SSE encoding, the MCP connection's lifetime -- and delegates every decision
about what to retrieve to the agent loop. Before Phase 3 the interesting logic
was a `_retrieve()` helper right here that called `kb_search` once, unconditionally.
"""

from __future__ import annotations

import json
import logging
import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Literal

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from mcp_server.agent import AgentUnavailable, declare_tools, web_search_default
from mcp_server.agent import run as run_agent
from mcp_server.conversation import MAX_TURNS as MAX_HISTORY_TURNS
from mcp_server.mcp_host import MCPHost, ToolUnavailable
from mcp_server.observability import (
    REQUEST_ID_HEADER,
    DailyBudget,
    RateLimiter,
    configure_logging,
    new_request_id,
    request_id,
)
from mcp_server.sources import MAX_RESTORED
from mcp_server.uploads import MAX_FILES, SUPPORTED_SUFFIXES, to_document
from tools import settings
from tools.vector_db.loaders import UnsupportedDocument

configure_logging()
logger = logging.getLogger(__name__)

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

host = MCPHost()
limiter = RateLimiter()
budget = DailyBudget()

# Bounds at the edge. None of these are tuning knobs -- they are the difference
# between a malformed request being rejected and it becoming a large bill or an
# out-of-memory kill deep inside the model call.
MAX_QUERY_CHARS = 2000
MAX_DOCUMENTS = 100
MAX_DOCUMENT_CHARS = 1_000_000

# Raw transcript entries accepted per request. `conversation.replay` decides how
# many are actually sent to the model; this only stops an unbounded POST body.
# Twice the replay budget, so a client that sends its whole transcript is
# trimmed rather than rejected.
MAX_HISTORY_ENTRIES = MAX_HISTORY_TURNS * 2
MAX_HISTORY_TURN_CHARS = 20_000


# -- models ----------------------------------------------------------------

class HistoryTurn(BaseModel):
    """One earlier turn of this conversation, as the client remembers it."""

    role: Literal["user", "assistant"]
    content: str = Field(max_length=MAX_HISTORY_TURN_CHARS)


class SourceRef(BaseModel):
    """A label already handed out, sent back so [3] keeps meaning [3].

    Deliberately thin: the passage text is not replayed to the model, so the
    client only returns what identifies a source and what the UI would show if
    an old citation is clicked. See `sources.SourceRegistry.restore`.
    """

    n: int = Field(ge=1)
    key: str = Field(max_length=500)
    origin: Literal["knowledge_base", "web"]
    title: str | None = Field(default=None, max_length=500)
    url: str | None = Field(default=None, max_length=2000)
    location: str | None = Field(default=None, max_length=300)
    score: float | None = None


class QueryRequest(BaseModel):
    # Constraints live on the model so they appear in /docs and are enforced
    # before any handler runs.
    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    timestamp: str | None = None
    client_id: str | None = Field(default=None, max_length=100)
    # Both default to empty, so a single-shot POST is unchanged by Phase 7.
    history: list[HistoryTurn] = Field(default_factory=list, max_length=MAX_HISTORY_ENTRIES)
    sources: list[SourceRef] = Field(default_factory=list, max_length=MAX_RESTORED)
    # None means "whatever the server is configured for", which is off. Sent per
    # request rather than only as server config so the UI can offer the web tier
    # as a deliberate, visible choice on the question that needs it.
    web_search: bool | None = None

    def prior(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """The two things the agent needs from the transcript."""
        return (
            [turn.model_dump() for turn in self.history],
            [source.model_dump() for source in self.sources],
        )

    @field_validator("query")
    @classmethod
    def not_only_whitespace(cls, value: str) -> str:
        """Reject a blank query in the schema rather than in the handler.

        Otherwise "" fails validation with a 422 and "   " fails a hand-written
        check with a 400 -- two status codes for one condition, and only one of
        them visible in the OpenAPI document.
        """
        stripped = value.strip()
        if not stripped:
            raise ValueError("Query cannot be empty")
        return stripped


class QueryResponse(BaseModel):
    success: bool
    response: str
    sources_used: list[str]
    tool_calls: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    abstained: bool = False
    turns: int = 0
    truncated: bool = False
    usage: dict[str, float] = {}
    request_id: str = "-"
    processing_time: float
    query_received: str
    timestamp: str
    error: str | None = None


class DocumentRequest(BaseModel):
    documents: list[dict[str, Any]] = Field(min_length=1, max_length=MAX_DOCUMENTS)
    client_id: str | None = Field(default=None, max_length=100)


class DocumentResponse(BaseModel):
    success: bool
    message: str
    documents_added: int
    collection_size: int
    error: str | None = None


# -- app -------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Hold the MCP connection open for the process lifetime."""
    await host.connect()
    try:
        yield
    finally:
        await host.close()


app = FastAPI(
    title="sextant - agent server",
    description="Retrieval over MCP, tool selection by the model",
    version="0.3.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

def _allowed_origins() -> list[str]:
    """Browser origins permitted to call this API, from the environment.

    Comma-separated in `SEXTANT_ALLOWED_ORIGINS`; defaults to the dev
    frontend. In the single-subdomain production layout the UI and the API are
    served from the same origin, so CORS never fires there -- but keeping this
    env-driven means a split-origin deploy (a separate `app.` and `api.` host)
    is a config change, not a code change, and the origin is never hardcoded to
    localhost in a shipped image.
    """
    raw = settings.getenv("ALLOWED_ORIGINS", "http://localhost:3000") or ""
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[REQUEST_ID_HEADER],
)


@app.middleware("http")
async def tag_request(request: Request, call_next):
    """Give every request an id, and put it on every log line it causes.

    A caller-supplied id is honoured so a trace can span the browser, this
    server and whatever sits in front of it.
    """
    incoming = request.headers.get(REQUEST_ID_HEADER)
    token = request_id.set(incoming or new_request_id())
    try:
        response = await call_next(request)
        response.headers[REQUEST_ID_HEADER] = request_id.get()
        return response
    finally:
        request_id.reset(token)


def _rate_limit(request: Request) -> None:
    """Reject a client that is asking too often. Raises 429 with Retry-After."""
    client = request.client.host if request.client else "unknown"
    allowed, retry_after = limiter.check(client)
    if not allowed:
        logger.warning("rate limited %s", client)
        raise HTTPException(
            status_code=429,
            detail=f"Too many requests. Try again in {retry_after}s.",
            headers={"Retry-After": str(retry_after)},
        )


def _budget_gate() -> None:
    """Refuse a query once the day's model spend has hit the cap.

    A hard ceiling, not a rate limit: it counts dollars, not requests, and
    resets at UTC midnight rather than on a rolling window. Off unless
    SEXTANT_DAILY_BUDGET_USD is set. 429 (not 402) so a browser's fetch
    retry/backoff treats it like the rate limiter it sits next to.
    """
    allowed, spent, retry_after = budget.check()
    if not allowed:
        logger.warning("daily budget reached: $%.4f of $%.2f", spent, budget.budget)
        raise HTTPException(
            status_code=429,
            detail=(
                f"Daily spend cap of ${budget.budget:.2f} reached. "
                "Answering is paused until 00:00 UTC."
            ),
            headers={"Retry-After": str(retry_after)},
        )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """A bad argument is the caller's problem, not a 500."""
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.get("/")
async def root():
    return {
        "message": "Agent server is running",
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "query": "/query (POST)",
            "query_stream": "/query/stream (POST)",
            "ingest": "/ingest (POST)",
            "upload": "/upload (POST, multipart)",
            "stats": "/stats (GET)",
            "tools": "/tools (GET)",
            "health": "/health (GET)",
            "docs": "/docs",
        },
    }


@app.get("/health")
async def health_check():
    """Health of this server, the MCP connection, and the model behind it."""
    model_ready = bool(os.getenv("GEMINI_API_KEY"))
    return {
        "status": "healthy" if host.connected and model_ready else "degraded",
        "mcp_connected": host.connected,
        # Retrieval works without a key; answering does not. Reported separately
        # so "the corpus is reachable" is never mistaken for "this can answer".
        "model_configured": model_ready,
        "supported_uploads": SUPPORTED_SUFFIXES,
        # Off by default and reported, because a tier that silently is not there
        # looks exactly like a model that chose not to use it.
        "web_search_enabled": web_search_default(),
        # The day's model spend against the cap, so the UI can show how much is
        # left and warn before answering stops. {"enabled": false} when unset.
        "budget": budget.status(),
        "mcp_error": host.error,
        "tools_discovered": [t["name"] for t in host.tools],
        "tools_offered_to_model": [t.get("name") for t in declare_tools(host)],
        "timestamp": datetime.now().isoformat(),
    }


@app.get("/tools")
async def list_tools():
    """The tool schemas discovered over MCP, exactly as the server declared them.

    Nothing here is written by hand -- this is `tools/list` output, and the same
    schemas go to the model. `kb_ingest` is discovered but withheld from the
    agent; see READABLE_TOOLS in `agent.py`.
    """
    if not host.connected:
        raise HTTPException(status_code=503, detail=host.error or "MCP server not connected")
    return {
        "count": len(host.tools),
        "tools": host.tools,
        "offered_to_model": [t.get("name") for t in declare_tools(host)],
    }


@app.get("/stats")
async def collection_stats():
    """Size and backing models of the knowledge base, via the MCP `kb_stats` tool.

    Separate from /health because they answer different questions: /health is
    "is the pipe open", this is "is there anything in the collection". A UI that
    cannot tell an empty corpus from a failed search will blame the search.
    """
    try:
        return await host.call("kb_stats", {})
    except ToolUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


class BenchmarkRequest(BaseModel):
    """A parameter sweep over the ANN indexes. All fields have working defaults."""

    k: int = Field(default=10, ge=1, le=100)
    n_queries: int = Field(default=200, ge=1, le=1000)
    # Passed through to benchmark.Grid. Left loose on purpose: the grid's own
    # fields are the contract, and duplicating them here as a rigid schema would
    # mean editing two files every time a knob is added to the sweep.
    grid: dict[str, Any] | None = None


class CompareRequest(BaseModel):
    """One query through every index, for the side-by-side view."""

    query: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)
    k: int = Field(default=10, ge=1, le=50)
    hnsw: dict[str, Any] | None = None
    ivfpq: dict[str, Any] | None = None


@app.post("/ann/benchmark")
async def ann_benchmark(request: BenchmarkRequest):
    """Sweep HNSW and IVF-PQ against exact search over the live corpus.

    Heavy and synchronous under the hood -- it builds real indexes -- so it is a
    deliberate, on-demand call the UI makes when the benchmark view is opened,
    never part of answering a question. The model is never offered these tools;
    READABLE_TOOLS in agent.py sees to that.
    """
    try:
        return await host.call(
            "kb_ann_benchmark",
            {"k": request.k, "n_queries": request.n_queries, "grid": request.grid},
        )
    except ToolUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.post("/ann/compare")
async def ann_compare(request: CompareRequest):
    """Run one query through exact, HNSW and IVF-PQ and return them side by side."""
    try:
        return await host.call(
            "kb_ann_compare",
            {"query": request.query, "k": request.k, "hnsw": request.hnsw, "ivfpq": request.ivfpq},
        )
    except ToolUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@app.post("/ingest", response_model=DocumentResponse)
async def ingest_documents(request: DocumentRequest, http_request: Request):
    """Store documents in the knowledge base, via the MCP `kb_ingest` tool.

    Writes live here rather than in the agent's tool list: answering a question
    must not be able to change the corpus it is answering from.
    """
    _rate_limit(http_request)

    oversized = sum(len(str(doc.get("content", ""))) for doc in request.documents)
    if oversized > MAX_DOCUMENT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=(
                f"Payload is {oversized} characters, over the {MAX_DOCUMENT_CHARS} limit. "
                "Use the sextant-ingest command for large files."
            ),
        )

    try:
        result = await host.call("kb_ingest", {"documents": request.documents})
    except ToolUnavailable as e:
        return DocumentResponse(
            success=False, message="", documents_added=0, collection_size=0, error=str(e)
        )

    return DocumentResponse(
        success=result.get("success", False),
        message=result.get("message", ""),
        documents_added=result.get("documents_added", 0),
        collection_size=result.get("collection_size", 0),
        error=result.get("error"),
    )


@app.post("/upload", response_model=DocumentResponse)
async def upload_files(
    http_request: Request, files: Annotated[list[UploadFile], File()]
):
    """Index uploaded files, parsing them here and storing them over MCP.

    Separate from /ingest, which takes documents a caller has already turned into
    text. This one takes bytes and runs the loaders, so a PDF keeps its page
    numbers and a citation can say "p. 14" -- the thing the old browser upload
    could not do, and the reason it only accepted text files.
    """
    _rate_limit(http_request)
    if len(files) > MAX_FILES:
        raise HTTPException(
            status_code=413,
            detail=f"{len(files)} files at once, over the {MAX_FILES} limit.",
        )

    documents: list[dict[str, Any]] = []
    skipped: list[str] = []
    for upload in files:
        try:
            documents.append(to_document(upload.filename or "upload", await upload.read()))
        except UnsupportedDocument as e:
            # One unreadable file should not lose the others in the same drop.
            skipped.append(str(e))
        finally:
            await upload.close()

    if not documents:
        return DocumentResponse(
            success=False,
            message="",
            documents_added=0,
            collection_size=0,
            error=" ".join(skipped) or "No readable files in the upload.",
        )

    try:
        result = await host.call("kb_ingest", {"documents": documents})
    except ToolUnavailable as e:
        return DocumentResponse(
            success=False, message="", documents_added=0, collection_size=0, error=str(e)
        )

    message = result.get("message", "")
    if skipped:
        message = f"{message} Skipped: {' '.join(skipped)}".strip()
    return DocumentResponse(
        success=result.get("success", False),
        message=message,
        documents_added=result.get("documents_added", 0),
        collection_size=result.get("collection_size", 0),
        error=result.get("error"),
    )


@app.post("/query", response_model=QueryResponse)
async def process_query(request: QueryRequest, http_request: Request):
    """Run the agent to completion and return the whole answer at once."""
    start = time.time()
    _rate_limit(http_request)
    _budget_gate()
    logger.info("query received (%d chars)", len(request.query))

    answer: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    usage: dict[str, float] = {}
    turns = 0
    truncated = False
    history, prior_sources = request.prior()

    try:
        async for event in run_agent(
            request.query, host, history, prior_sources, request.web_search
        ):
            kind = event["type"]
            if kind == "token":
                answer.append(event["text"])
            elif kind == "citation":
                # Web citations arrive as their own event so the streaming client
                # can render a link. Here there is nowhere to hang one, so the
                # label goes inline and matches the knowledge base's `[n]`.
                answer.append(f"[{event['n']}]")
            elif kind == "tool_call":
                tool_calls.append({"name": event["name"], "where": event["where"]})
            elif kind == "tool_result":
                # Attach to the most recent call of that tool rather than adding
                # a second entry: one call, one row, now with its outcome.
                for call in reversed(tool_calls):
                    if call["name"] == event["name"] and "summary" not in call:
                        call["summary"] = event["summary"]
                        break
            elif kind == "sources":
                sources = event["sources"]
            elif kind == "done":
                sources = event["sources"]
                usage = event["usage"]
                turns = event["turns"]
                truncated = event["truncated"]
    except (AgentUnavailable, ToolUnavailable) as e:
        return QueryResponse(
            success=False,
            response="",
            sources_used=[],
            processing_time=time.time() - start,
            query_received=request.query,
            timestamp=datetime.now().isoformat(),
            error=str(e),
        )
    except Exception as e:
        logger.exception("Query failed")
        return QueryResponse(
            success=False,
            response="",
            sources_used=[],
            processing_time=time.time() - start,
            query_received=request.query,
            timestamp=datetime.now().isoformat(),
            error=f"Server error: {e}",
        )

    # Charge the day's budget with what this query actually cost. Done here, on
    # the success path, because a failed query that never reached the model
    # should not spend the cap.
    budget.record(float(usage.get("cost_usd", 0.0)))

    return QueryResponse(
        success=True,
        response="".join(answer).strip(),
        # Which tools the model actually chose -- not a fixed list any more.
        sources_used=sorted({call["name"] for call in tool_calls}),
        tool_calls=tool_calls,
        sources=sources,
        abstained=not sources,
        turns=turns,
        truncated=truncated,
        usage=usage,
        request_id=request_id.get(),
        processing_time=time.time() - start,
        query_received=request.query,
        timestamp=datetime.now().isoformat(),
    )


@app.post("/query/stream")
async def process_query_stream(request: QueryRequest, http_request: Request):
    """Same as /query, streamed as Server-Sent Events.

    Event sequence, in the order the agent produces them:
      tool_call   : the model chose a tool
      tool_result : that tool came back -- hit count, how it was scored, and how
                    long it took, so an empty search is legible as one
      sources     : the numbered source list grew -- may arrive more than once,
                    and now arrives *during* the answer rather than before it,
                    because the model decides what to retrieve as it goes
      token       : one text delta
      citation    : a web citation closed; `n` matches an entry in `sources`
      done        : end of stream, with the final source list and usage
      error       : something failed; the message is human-readable
    """
    _rate_limit(http_request)
    _budget_gate()
    history, prior_sources = request.prior()

    # The context var is read inside the generator, which runs after the
    # middleware's `finally` has reset it -- so capture the value here.
    current = request_id.get()

    async def events():
        token = request_id.set(current)
        try:
            async for event in run_agent(
                request.query, host, history, prior_sources, request.web_search
            ):
                # Charge the cap as the closing event goes past, so a streamed
                # query counts against the day exactly like a non-streamed one.
                if event["type"] == "done":
                    budget.record(float(event.get("usage", {}).get("cost_usd", 0.0)))
                yield _sse(event["type"], event)
        except (AgentUnavailable, ToolUnavailable) as e:
            yield _sse("error", {"message": str(e)})
        except Exception as e:
            logger.exception("Streaming query failed")
            yield _sse("error", {"message": f"Server error: {e}"})
        finally:
            request_id.reset(token)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            REQUEST_ID_HEADER: current,
        },
    )


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


if __name__ == "__main__":
    uvicorn.run("mcp_server.main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
