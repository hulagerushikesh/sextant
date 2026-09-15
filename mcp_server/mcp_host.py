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
from typing import Any

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

# Variables the subprocess needs but MCP's stdio client would otherwise strip.
# Both spellings of each: a `.env` written before the rename still says
# AGENTICRAG_*, and the subprocess resolves the same fallback order.
_FORWARDED_ENV = settings.env_names("CHROMA_DIR") + settings.env_names("ANN_INDEX")


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
