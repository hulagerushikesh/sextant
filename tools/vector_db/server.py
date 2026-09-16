"""
Knowledge-base MCP server.

Exposes the ChromaDB store in `vector_search.py` as three MCP tools over stdio.
This is a standalone server: it has no dependency on the FastAPI app, and it is
meant to be mounted by any MCP client -- Claude Desktop, MCP Inspector, or the
agent in `mcp_server/main.py`.

Run it directly:

    python -m tools.vector_db.server

Or drive it interactively:

    mcp dev tools/vector_db/server.py

IMPORTANT: stdout is the JSON-RPC channel. Nothing in this process may print to
it. Logs go to stderr via the logging module; `print()` anywhere in this import
graph will corrupt the protocol stream.
"""

from __future__ import annotations

import logging
import sys
from typing import Annotated, Any, Literal

from mcp.server import MCPServer
from pydantic import Field

# Preload FAISS before the embedder import below pulls in PyTorch. faiss-cpu and
# torch each bundle an OpenMP runtime, and on macOS whichever initialises *second*
# can segfault the process -- so the ANN benchmark's FAISS reference column would
# otherwise crash this subprocess the first time a sweep runs. Importing faiss
# first makes it the stable base (verified: faiss-then-torch coexists, the reverse
# does not). A no-op when faiss is not installed; faiss_ref guards its own import.
from tools.vector_db.ann import faiss_ref as _faiss_preload  # noqa: F401
from tools.vector_db.vector_search import (
    DEFAULT_MIN_SCORE,
    DEFAULT_MODE,
    KnowledgeBase,
    KnowledgeBaseUnavailable,
)

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger(__name__)

mcp = MCPServer(
    name="knowledge-base",
    title="Knowledge Base",
    version="0.4.0",
    instructions=(
        "Hybrid search over a private document collection. Use kb_search to "
        "answer questions about material the user has ingested; it will not "
        "find anything about current events or public web content. Documents "
        "are split into overlapping chunks, so results are passages rather than "
        "whole files, and each one names the page or section it came from. Call "
        "kb_stats first if you need to know whether the collection has any "
        "documents in it at all."
    ),
)

_kb: KnowledgeBase | None = None


def _store() -> KnowledgeBase:
    """Open the collection on first use, then reuse it.

    Deferred rather than opened at import so that a broken embedding install
    surfaces as a tool error the client can read, not a crash during startup
    that leaves the client staring at a closed pipe.
    """
    global _kb
    if _kb is None:
        _kb = KnowledgeBase()
    return _kb


@mcp.tool(
    description=(
        "Search the user's private document collection for passages relevant to "
        "a question. Runs meaning-based and keyword-based retrieval together, so "
        "it handles both paraphrase and exact terms -- an error code, a surname, "
        "a section number -- but a full question still ranks better than one or "
        "two bare keywords. Returns passages with the source and page or section "
        "they came from, suitable for citation. Each result reports how it was "
        "scored: 'cross-encoder' scores are relevance in 0-1, where anything "
        "above about 0.5 is a genuine match. Returns an empty list when the "
        "collection holds nothing relevant, which means the answer is not in the "
        "knowledge base -- say so rather than guessing."
    )
)
async def kb_search(
    query: Annotated[str, Field(description="The question or descriptive phrase to search for.")],
    limit: Annotated[int, Field(description="Maximum passages to return.", ge=1, le=25)] = 5,
    min_score: Annotated[
        float,
        Field(
            description=(
                "Drop passages the reranker scores below this, 0.0-1.0. Leave at "
                "the default unless you are getting obvious noise; it is applied "
                "only when results are cross-encoder scored."
            ),
            ge=0.0,
            le=1.0,
        ),
    ] = DEFAULT_MIN_SCORE,
    mode: Annotated[
        Literal["dense", "lexical", "rrf", "rerank"],
        Field(
            description=(
                "Retrieval pipeline to run. Leave at 'rerank', the full one. The "
                "others are ablations for benchmarking: 'dense' is vectors only, "
                "'lexical' is BM25 only, 'rrf' fuses both without reranking and "
                "returns fusion ranks, which order results but do not measure "
                "relevance."
            )
        ),
    ] = DEFAULT_MODE,
) -> dict[str, Any]:
    """Hybrid search over the ingested corpus."""
    try:
        return await _store().search(query, limit=limit, min_score=min_score, mode=mode)
    except KnowledgeBaseUnavailable as e:
        return {"success": False, "error": str(e), "results": [], "total_found": 0}


@mcp.tool(
    description=(
        "Add documents to the knowledge base so they become searchable. Each "
        "document needs 'content'; 'title', 'source', 'page' and 'category' are "
        "optional but 'source' and 'page' are what citations point at, so supply "
        "them when known. A caller that has already parsed a file may send a "
        "'locators' list instead of 'page' -- entries of {kind, label, start, "
        "end} where kind is 'page', 'section' or 'table' -- and each chunk is "
        "then attributed to the region it starts in; a 'table' region is "
        "chunked one row at a time with its label (the header) prepended. "
        "Re-using an existing 'id' "
        "replaces that document. Long documents are split into overlapping "
        "chunks automatically. To index a file from disk, use the "
        "sextant-ingest command instead."
    )
)
async def kb_ingest(
    documents: Annotated[
        list[dict[str, Any]],
        Field(description="Documents to store. Each requires a 'content' field."),
    ],
) -> dict[str, Any]:
    """Embed and persist documents into the collection."""
    try:
        return await _store().add_documents(documents)
    except KnowledgeBaseUnavailable as e:
        return {"success": False, "error": str(e), "documents_added": 0, "chunks_added": 0}


@mcp.tool(
    description=(
        "Report the state of the knowledge base: how many documents and chunks "
        "it holds, which embedding and reranking models back it, and where it is "
        "stored. Use this to check whether the collection is empty before "
        "concluding that a search found nothing."
    )
)
async def kb_stats() -> dict[str, Any]:
    """Health and size of the collection."""
    try:
        return await _store().health_check()
    except KnowledgeBaseUnavailable as e:
        return {"status": "unavailable", "error": str(e)}


@mcp.tool(
    description=(
        "Benchmark approximate-nearest-neighbour indexes over the current "
        "corpus. Builds hand-written HNSW and IVF-PQ indexes across a parameter "
        "sweep and measures each against exact search: recall@k, query-latency "
        "percentiles, build time and memory. This is an analysis tool for "
        "comparing index tradeoffs, not part of answering a question -- it does "
        "not retrieve anything for the user."
    )
)
async def kb_ann_benchmark(
    k: Annotated[
        int, Field(description="Neighbours per query to score recall over.", ge=1, le=100)
    ] = 10,
    n_queries: Annotated[
        int, Field(description="How many corpus vectors to hold out as queries.", ge=1, le=1000)
    ] = 200,
    grid: Annotated[
        dict[str, Any] | None,
        Field(description="Optional sweep overrides: hnsw_ef_search, ivf_nprobe, ivf_m, etc."),
    ] = None,
) -> dict[str, Any]:
    """Sweep the ANN indexes against exact search over the live corpus."""
    try:
        return await _store().ann_benchmark(k=k, n_queries=n_queries, grid=grid)
    except KnowledgeBaseUnavailable as e:
        return {"error": str(e)}


@mcp.tool(
    description=(
        "Run one query through exact, HNSW and IVF-PQ search side by side and "
        "return each index's hits with its latency and which exact neighbours it "
        "missed. For inspecting how the approximate indexes behave on a specific "
        "question, not for answering one."
    )
)
async def kb_ann_compare(
    query: Annotated[str, Field(description="The question or phrase to search with.")],
    k: Annotated[
        int, Field(description="Neighbours to retrieve from each index.", ge=1, le=50)
    ] = 10,
    hnsw: Annotated[
        dict[str, Any] | None,
        Field(description="HNSW build/search params: m, ef_construction, ef_search."),
    ] = None,
    ivfpq: Annotated[
        dict[str, Any] | None,
        Field(description="IVF-PQ params: nlist, nprobe, m, nbits."),
    ] = None,
) -> dict[str, Any]:
    """Compare every index on one query against exact search."""
    try:
        return await _store().ann_compare(query, k=k, hnsw=hnsw, ivfpq=ivfpq)
    except KnowledgeBaseUnavailable as e:
        return {"error": str(e)}


def main() -> None:
    """Console-script entry point: `sextant-kb`.

    Installed by pyproject so MCP clients can name a single command with no
    flags -- some clients parse the argument list themselves and would eat a
    `-m`. Also what the Claude Desktop config points at.
    """
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
