"""
MCP host: the client half of the protocol.

Owns a live connection to the knowledge-base MCP server, which runs as a
separate process speaking JSON-RPC over stdio -- the same way Claude Desktop
would run it. Tools are *discovered* at startup via `tools/list` rather than
hard-coded here, so adding a tool to the server requires no change to this file.

The discovered schemas go straight to Claude's tool-use API -- MCP and the
Messages API agree on the shape, so `agent.declare_tools` is a filter, not a
translation.
"""

from __future__ import annotations

import logging
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Protocol

from mcp import Client, StdioServerParameters
from mcp.client.stdio import stdio_client

from tools import settings

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Duplicated from tools.vector_db.vector_search rather than imported: importing
# it here would pull chromadb and torch into the agent server's import graph,
# and keeping the knowledge base out of this process is the whole point of
# speaking to it over a protocol.
PERSIST_DIR_ENV = settings.env_name("CHROMA_DIR")
# Which dense index the knowledge base uses. Forwarded like the store override:
# it changes what retrieval does, so dropping it would silently run the default.
ANN_BACKEND_ENV = settings.env_name("ANN_INDEX")

class ToolHost(Protocol):
    """What the agent actually needs: the schemas, and a way to call one.

    Narrower than `MCPHost` on purpose. `scope.ScopedHost` wraps the real host
    to trim another owner's documents out of every result, and the agent must
    accept either without knowing which it has -- the whole point being that
    nothing above this line can tell, and nothing below it is asked.
    """

    @property
    def tools(self) -> list[dict[str, Any]]: ...

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


# --- What the subprocess inherits --------------------------------------------
#
# MCP's stdio client does not hand its child this process's environment. It
# builds `get_default_environment() | params.env`, and on POSIX that default is
# HOME, LOGNAME, PATH, SHELL, TERM, USER. So a variable not named below does
# not exist for the subprocess, whatever the container sets -- and the failure
# is silent, because everything the subprocess reads has a default.
#
# Two kinds of name cross. These are ours, read through `tools.settings`, so
# they arrive with the SEXTANT_ prefix. Each one changes what retrieval does,
# which is why dropping one is worse than not starting: the server would open
# the default collection with the default index and answer anyway.
_FORWARDED_SETTINGS = (
    "CHROMA_DIR",
    "ANN_INDEX",
    "EMBEDDER",
    "CHUNK_TOKENS",
    "MAX_PER_DOCUMENT",
    "SUBFLOOR_ORDER",
    "FLOOR_FALLBACK",
)

# And these are other people's, read by the libraries only the subprocess
# imports. The embedder and the cross-encoder load *here*; the image bakes them
# into HF_HOME=/opt/models and sets HF_HUB_OFFLINE=1 so the first query does
# not download 180 MB and appear to hang. Until 2026-10-10 neither name
# crossed, so the child resolved $HOME/.cache/huggingface, found it empty, and
# downloaded the weights into a path that dies with the container -- see
# `TestTheSubprocessGetsTheModelCache`.
#
# Every name here is one the loader actually reads, not a guess:
#   huggingface_hub/constants.py   HF_HOME, HF_HUB_CACHE, XDG_CACHE_HOME,
#                                  HF_HUB_OFFLINE, TRANSFORMERS_OFFLINE
#   sentence_transformers/base/model.py   SENTENCE_TRANSFORMERS_HOME
_FORWARDED_VERBATIM = (
    "HF_HOME",
    "HF_HUB_CACHE",
    "XDG_CACHE_HOME",
    "HF_HUB_OFFLINE",
    "TRANSFORMERS_OFFLINE",
    "SENTENCE_TRANSFORMERS_HOME",
)

# Names the deploy sets, or the subprocess's own modules read, that deliberately
# do not cross -- each with the reason, so an entry is a claim somebody can
# check rather than an omission nobody can see. Pinned both ways: nothing here
# may also be forwarded, and nothing may name a variable no scan still finds.
_NOT_FORWARDED = {
    settings.env_name("MODEL"): (
        "summaries.py reads it at import, for summarise(), which only runs in "
        "sextant-ingest in the operator's shell. The subprocess imports that "
        "module for its chunk-id helpers and never calls it."
    ),
    "GEMINI_API_KEY": (
        "the same path: nothing the subprocess can be asked to do generates "
        "text. A key that does not cross cannot leak from here."
    ),
    settings.env_name("LOG_FORMAT"): (
        "the subprocess calls logging.basicConfig itself and never reads it; "
        "its stderr is text by design and the container collects it either way."
    ),
    settings.env_name("ALLOWED_ORIGINS"): (
        "CORS belongs to the HTTP layer, two processes above this one."
    ),
}

_FORWARDED_ENV = (
    tuple(settings.env_name(key) for key in _FORWARDED_SETTINGS) + _FORWARDED_VERBATIM
)


def kb_server() -> StdioServerParameters:
    """How to launch the knowledge-base server as a subprocess.

    sys.executable keeps it on the same interpreter as this process, so it
    inherits the venv without the caller needing to activate anything.

    The environment needs forwarding by hand: MCP's stdio client passes only an
    allowlist of variables it considers safe to inherit, so a store override or a
    dense-backend choice set in this process would otherwise be dropped and the
    server would quietly open the default collection with the default index.
    Silently reading the wrong corpus, or the wrong index, is a much worse failure
    than not starting.
    """
    forwarded = {
        name: value
        for name in _FORWARDED_ENV
        if (value := os.getenv(name)) is not None
    }
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "tools.vector_db.server"],
        cwd=str(REPO_ROOT),
        env=forwarded or None,
    )


def _text(result: Any) -> str:
    """Join the text blocks of a tool result.

    Content is a union -- text, image, audio, resource -- so the attribute is
    read defensively rather than assumed. A tool that starts returning images
    should degrade to an empty string, not an AttributeError.
    """
    return " ".join(
        getattr(block, "text", "")
        for block in result.content
        if getattr(block, "type", None) == "text"
    )


class ToolUnavailable(RuntimeError):
    """Raised when a tool call cannot be made -- no connection, or no such tool."""


class MCPHost:
    """A connection to one or more MCP servers, held open for the app's lifetime."""

    def __init__(self) -> None:
        self._stack: AsyncExitStack | None = None
        self._client: Client | None = None
        self._tools: list[dict[str, Any]] = []
        self.error: str | None = None

    @property
    def connected(self) -> bool:
        return self._client is not None

    @property
    def tools(self) -> list[dict[str, Any]]:
        """Schemas discovered from the server, in MCP's own shape."""
        return self._tools

    async def connect(self) -> None:
        """Start the tool server and discover what it offers.

        A failure here is recorded rather than raised: the API should still come
        up and be able to explain itself, instead of dying at import time.
        """
        stack = AsyncExitStack()
        try:
            client = await stack.enter_async_context(Client(stdio_client(kb_server())))
            listing = await client.list_tools()
        except Exception as e:
            await stack.aclose()
            self.error = f"Could not start the knowledge-base MCP server: {e}"
            logger.exception("MCP connection failed")
            return

        self._stack = stack
        self._client = client
        self._tools = [
            {
                "name": t.name,
                "description": t.description or "",
                "input_schema": t.input_schema or {},
            }
            for t in listing.tools
        ]
        self.error = None

        info = client.server_info
        logger.info(
            "MCP connected: %s v%s (protocol %s) -- tools: %s",
            getattr(info, "name", "unknown"),
            getattr(info, "version", "unknown"),
            client.protocol_version,
            ", ".join(t["name"] for t in self._tools) or "(none)",
        )

    async def close(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._client = None

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Invoke a discovered tool and return its structured result."""
        if self._client is None:
            raise ToolUnavailable(self.error or "Not connected to any MCP server.")
        if name not in {t["name"] for t in self._tools}:
            available = ", ".join(t["name"] for t in self._tools) or "(none)"
            raise ToolUnavailable(f"Server does not expose a tool named {name!r}. Has: {available}")

        result = await self._client.call_tool(name, arguments)

        if result.is_error:
            raise ToolUnavailable(f"{name} failed: {_text(result) or 'no detail returned'}")

        # Every tool on the kb server declares a dict return type, so MCP gives
        # us structured content. Fall back to the text block only if that
        # changes, so a schema-less tool doesn't crash the caller.
        if result.structured_content is not None:
            return result.structured_content
        return {"success": True, "text": _text(result)}
