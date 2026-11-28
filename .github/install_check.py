"""Install check: start the installed server the way an assistant does, and search.

Run inside the environment the wheel was installed into:

    python .github/install_check.py <folder>

It starts `sextant-kb` over stdio with the folder in SEXTANT_FOLDER, waits
for the folder to be indexed, asks one question whose answer is known, and
exits non-zero unless the right file comes back. Nothing here imports the
checkout: the server is the installed console script.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

QUESTION = "what does error TRK-118 mean"
EXPECTED_SOURCE = "error-codes.md"
INDEX_WAIT_SECONDS = 300


def _server_command() -> str:
    scripts = Path(sys.executable).parent
    name = "sextant-kb.exe" if os.name == "nt" else "sextant-kb"
    command = scripts / name
    if not command.is_file():
        raise SystemExit(f"the installed command is missing: {command}")
    return str(command)


async def _check(folder: Path, store: Path, wanted: int) -> None:
    params = StdioServerParameters(
        command=_server_command(),
        env={**os.environ, "SEXTANT_FOLDER": str(folder), "SEXTANT_CHROMA_DIR": str(store)},
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        tools = {t.name for t in (await session.list_tools()).tools}
        missing = {"kb_search", "kb_stats", "kb_list"} - tools
        if missing:
            raise SystemExit(f"the server is missing tools: {sorted(missing)}")

        stored = 0
        for _ in range(INDEX_WAIT_SECONDS):
            stats = json.loads((await session.call_tool("kb_stats", {})).content[0].text)
            stored = int(stats.get("document_count") or stats.get("documents") or 0)
            if stored >= wanted:
                break
            await asyncio.sleep(1)
        print(f"indexed {stored} of {wanted} documents")

        found = json.loads(
            (await session.call_tool("kb_search", {"query": QUESTION})).content[0].text
        )
        sources = [str(r.get("source", "")) for r in found.get("results", [])]
        print(f"top sources: {sources[:3]}")
        if not sources or not sources[0].endswith(EXPECTED_SOURCE):
            raise SystemExit(f"expected {EXPECTED_SOURCE} first, got {sources[:3]}")


def main() -> None:
    folder = Path(sys.argv[1]).resolve()
    wanted = sum(1 for p in folder.iterdir() if p.suffix in {".md", ".txt", ".pdf"})
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(_check(folder, Path(tmp) / "chroma_db", wanted))
    print("install check passed")


if __name__ == "__main__":
    main()
