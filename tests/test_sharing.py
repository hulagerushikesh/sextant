"""One library, more than one process (`sextant/vector_db/sharing.py`).

Claude Desktop runs two copies of this server for one extension. Two copies
writing one Chroma store left the owner's library unreadable on 2026-11-16.
These pin the three parts of the fix: one process has the store open and the
others ask it; two real servers over one folder index it once and answer as
one library; and a store Chroma cannot read is moved aside, not left to fail
every tool.
"""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any

import pytest

from sextant import settings
from sextant.vector_db.sharing import Library, owner_path

ROOT = Path(__file__).resolve().parents[1]


def _runner(name: str, calls: list[tuple[str, dict[str, Any]]]):
    async def run(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        calls.append((tool, args))
        if tool == "boom":
            raise ValueError("the owner could not do it")
        return {"answered_by": name, "tool": tool, "args": args}

    return run


class TestOneProcessHasTheStore:
    async def test_the_second_asks_the_first(self, tmp_path):
        store = tmp_path / "chroma_db"
        a_calls: list = []
        b_calls: list = []
        a = Library(store, _runner("a", a_calls))
        b = Library(store, _runner("b", b_calls))
        try:
            assert await a.try_own() is True
            assert await b.try_own() is False
            answer = await b.call("kb_search", {"query": "q", "limit": 3})
            assert answer == {"answered_by": "a", "tool": "kb_search",
                              "args": {"query": "q", "limit": 3}}
            assert b_calls == [] and a_calls == [("kb_search", {"query": "q", "limit": 3})]
        finally:
            await a.close()
            await b.close()

    async def test_when_the_first_exits_the_next_caller_takes_over(self, tmp_path):
        store = tmp_path / "chroma_db"
        started: list[str] = []
        a = Library(store, _runner("a", []))
        b = Library(store, _runner("b", []), on_owner=lambda: started.append("b"))
        try:
            await a.try_own()
            await a.close()
            assert not owner_path(store).exists()
            answer = await b.call("kb_stats", {})
            assert answer["answered_by"] == "b" and started == ["b"]
        finally:
            await b.close()

    async def test_an_owner_that_died_without_closing_is_taken_over(self, tmp_path):
        """A crash leaves the address file behind; the lock goes with the process."""
        store = tmp_path / "chroma_db"
        a = Library(store, _runner("a", []))
        b = Library(store, _runner("b", []))
        try:
            await a.try_own()
            assert a._server is not None
            a._server.close()
            await a._server.wait_closed()
            a._lock.release()  # what the operating system does when a process dies
            assert owner_path(store).exists()
            assert (await b.call("kb_stats", {}))["answered_by"] == "b"
        finally:
            await b.close()

    async def test_the_owners_error_reaches_the_caller(self, tmp_path):
        store = tmp_path / "chroma_db"
        a = Library(store, _runner("a", []))
        b = Library(store, _runner("b", []))
        try:
            await a.try_own()
            with pytest.raises(RuntimeError, match="the owner could not do it"):
                await b.call("boom", {})
        finally:
            await a.close()
            await b.close()

    async def test_a_request_without_the_token_is_refused(self, tmp_path):
        store = tmp_path / "chroma_db"
        calls: list = []
        a = Library(store, _runner("a", calls))
        try:
            await a.try_own()
            port = json.loads(owner_path(store).read_text())["port"]
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write(json.dumps({"token": "guess", "tool": "kb_list", "args": {}}).encode()
                         + b"\n")
            await writer.drain()
            reply = json.loads(await reader.readline())
            writer.close()
            assert "refused" in reply["error"] and calls == []
        finally:
            await a.close()

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")
    async def test_the_token_file_is_readable_by_this_user_only(self, tmp_path):
        store = tmp_path / "chroma_db"
        a = Library(store, _runner("a", []))
        try:
            await a.try_own()
            mode = stat.S_IMODE(owner_path(store).stat().st_mode)
            assert mode == 0o600
        finally:
            await a.close()

    async def test_a_large_answer_survives_the_trip(self, tmp_path):
        """A self-test sample or a long listing is megabytes on one line."""
        store = tmp_path / "chroma_db"
        big = "x" * (3 * 1024 * 1024)

        async def run(tool: str, args: dict[str, Any]) -> dict[str, Any]:
            return {"text": big}

        a = Library(store, run)
        b = Library(store, run)
        try:
            await a.try_own()
            assert (await b.call("kb_list", {}))["text"] == big
        finally:
            await a.close()
            await b.close()


def _json(result: Any) -> dict[str, Any]:
    from mcp.types import TextContent

    content = result.content[0]
    assert isinstance(content, TextContent), content
    found: dict[str, Any] = json.loads(content.text)
    return found


class TestTwoRealServersOneFolder:
    """Two `sextant-kb` processes on one folder and one store, as Claude
    Desktop starts them. Loads the real search models in each."""

    async def test_they_index_once_and_answer_as_one_library(self, tmp_path, corpus_dir):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        folder = tmp_path / "notes"
        folder.mkdir()
        for path in sorted(corpus_dir.glob("*.md")):
            (folder / path.name).write_text(path.read_text())
        store = tmp_path / "store"
        env = {k: v for k, v in os.environ.items() if not k.startswith("SEXTANT_")}
        env.update({
            settings.env_name("FOLDER"): str(folder),
            settings.env_name("CHROMA_DIR"): str(store),
            settings.SEALED: "1",
        })
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "sextant.vector_db.server"], env=env,
            cwd=str(ROOT),
        )
        logs = [tmp_path / "a.log", tmp_path / "b.log"]

        async def stats(session: ClientSession) -> dict[str, Any]:
            return _json(await session.call_tool("kb_stats", {}))

        async def ready(session: ClientSession) -> dict[str, Any]:
            for _ in range(240):
                found = await stats(session)
                if found.get("folder", {}).get("state") == "ready":
                    return found
                await asyncio.sleep(0.5)
            raise AssertionError(f"never indexed: {found}")

        with logs[0].open("w") as a_err, logs[1].open("w") as b_err:
            async with stdio_client(params, errlog=a_err) as (ar, aw), \
                    stdio_client(params, errlog=b_err) as (br, bw):
                async with ClientSession(ar, aw) as a, ClientSession(br, bw) as b:
                    await a.initialize()
                    await b.initialize()
                    from_a, from_b = await ready(a), await ready(b)
                    # One process answered both: the one with the store open.
                    assert from_a["server_process"] == from_b["server_process"]
                    assert from_a["folder"] == from_b["folder"]
                    assert from_a["folder"]["stored_this_run"] == len(list(folder.glob("*.md")))
                    for session in (a, b):
                        result = await session.call_tool(
                            "kb_search", {"query": "how does the Kalman filter predict"}
                        )
                        assert _json(result)["results"]

        # Exactly one of the two indexed the folder.
        passes = [log.read_text().count("not indexed") for log in logs]
        assert sorted(passes) == [0, 1], passes

        # And what they left behind opens.
        from sextant.vector_db.vector_search import KnowledgeBase

        os.environ[settings.env_name("CHROMA_DIR")] = str(store)
        try:
            reopened = KnowledgeBase()
            assert reopened.set_aside is None
            assert (await reopened.health_check())["documents"] == len(list(folder.glob("*.md")))
            reopened.client.close()
        finally:
            del os.environ[settings.env_name("CHROMA_DIR")]


class TestAnUnreadableStore:
    def test_it_is_moved_aside_and_a_new_one_opened(self, tmp_path, monkeypatch):
        import chromadb
        from chromadb.api.models.Collection import Collection

        store = tmp_path / "chroma_db"
        monkeypatch.setenv(settings.env_name("CHROMA_DIR"), str(store))
        from sextant.vector_db.vector_search import KnowledgeBase

        first = KnowledgeBase()
        first.client.close()
        (store / "folder_index.json").write_text("{}")

        real_count = Collection.count
        failures = ["Failed to apply logs to the hnsw segment writer"]

        def count(self: Any) -> int:
            if failures:
                raise chromadb.errors.InternalError(failures.pop())
            return real_count(self)

        monkeypatch.setattr(Collection, "count", count)
        kb = KnowledgeBase()
        try:
            assert kb.set_aside is not None
            moved = Path(kb.set_aside["moved_to"])
            assert moved.name.startswith("chroma_db.unreadable-") and moved.is_dir()
            assert (moved / "folder_index.json").exists()
            assert store.is_dir() and not (store / "folder_index.json").exists()
            report = asyncio.run(kb.health_check())
            assert "hnsw" in report["set_aside"]["reason"]
            assert "moved aside" in report["set_aside"]["note"]
        finally:
            kb.client.close()

    def test_a_readable_store_is_left_where_it_is(self, tmp_path, monkeypatch):
        store = tmp_path / "chroma_db"
        monkeypatch.setenv(settings.env_name("CHROMA_DIR"), str(store))
        from sextant.vector_db.vector_search import KnowledgeBase

        KnowledgeBase().client.close()
        kb = KnowledgeBase()
        try:
            assert kb.set_aside is None
            assert [p.name for p in tmp_path.iterdir()] == ["chroma_db"]
        finally:
            kb.client.close()


class TestTheCommandsWaitTheirTurn:
    """`sextant-ingest` and `sextant-forget` open the store themselves."""

    async def test_they_refuse_a_library_an_assistant_has_open(self, tmp_path, monkeypatch):
        from sextant.vector_db import forget_cli, ingest_cli

        store = tmp_path / "chroma_db"
        monkeypatch.setenv(settings.env_name("CHROMA_DIR"), str(store))
        note = tmp_path / "note.md"
        note.write_text("# A note\n\nSomething worth finding.\n")
        server = Library(store, _runner("server", []))
        try:
            await server.try_own()
            for module, argv in (
                (ingest_cli, ["sextant-ingest", str(note), "--no-summaries"]),
                (forget_cli, ["sextant-forget", "--list"]),
            ):
                monkeypatch.setattr(sys, "argv", argv)
                with pytest.raises(SystemExit) as stopped:
                    await asyncio.to_thread(module.main)
                assert "running in an assistant" in str(stopped.value)
            assert not store.exists(), "nothing may open the store while it is held"
        finally:
            await server.close()

    def test_they_run_when_nothing_has_it_open(self, tmp_path, monkeypatch):
        from sextant.vector_db import forget_cli

        monkeypatch.setenv(settings.env_name("CHROMA_DIR"), str(tmp_path / "chroma_db"))
        monkeypatch.setattr(sys, "argv", ["sextant-forget", "--list"])
        forget_cli.main()
