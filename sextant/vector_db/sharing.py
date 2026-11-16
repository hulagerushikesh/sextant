"""One library, opened by one process, used by any number of them.

Claude Desktop starts this server twice for one extension -- two launch paths
in its own log, both alive, either of which may be sent a tool call -- and two
Claude Code windows, or Claude Code beside Claude Desktop, do the same. Chroma's
on-disk store is not safe to open from two processes at once. On 2026-11-15 the
owner's two Desktop processes both indexed the same Downloads folder into one
store; on 2026-11-16 the store would not open ("Failed to apply logs to the
hnsw segment writer") and every tool failed. Reproduced here with two
processes replacing the same documents (`learning/two-processes.md`). Locking
each write is not enough: with a lock around every document, a store still
ended up refusing to open, because each process keeps its own copy of the
vector index in memory and writes it back.

So exactly one process opens the store: whichever takes the lock beside it
first, for as long as it lives. It serves its own tool calls and answers the
others' over a local socket. Every other process forwards each tool call to it
and returns the answer unchanged, so a person sees one library whichever
process their client happens to ask. When the owner exits, the operating
system drops its lock, and the next process to need the library takes over.

The socket listens on 127.0.0.1 only, and a request must carry a random token
that the owner writes to a file only this user can read.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import os
import secrets
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from filelock import FileLock, Timeout

logger = logging.getLogger(__name__)

# Answers can be whole listings and self-test samples: far past asyncio's 64 KB
# default line limit.
LINE_LIMIT = 64 * 1024 * 1024
# How long a process that cannot take the lock waits for the owner to start
# answering. Both processes start within milliseconds of each other, and the
# owner binds its socket before it loads any model.
OWNER_START_SECONDS = 20.0

RunLocal = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]


class LibraryBusy(RuntimeError):
    """Another process holds the library and is not answering."""


def lock_path(store: Path) -> Path:
    return store.parent / f"{store.name}.owner.lock"


def owner_path(store: Path) -> Path:
    return store.parent / f"{store.name}.owner.json"


class Library:
    """Routes a tool call to the one process that has the store open."""

    def __init__(
        self,
        store: Path,
        run_local: RunLocal,
        on_owner: Callable[[], None] | None = None,
    ) -> None:
        self.store = store
        self._run_local = run_local
        self._on_owner = on_owner
        self._lock = FileLock(str(lock_path(store)), thread_local=False)
        self._token = secrets.token_hex(32)
        self._server: asyncio.Server | None = None
        self._claim = asyncio.Lock()

    @property
    def owner(self) -> bool:
        return self._lock.is_locked

    # -- taking the library ------------------------------------------------

    async def try_own(self) -> bool:
        """Take the lock if nobody holds it; on success, start answering others."""
        async with self._claim:
            if self.owner:
                return True
            self.store.parent.mkdir(parents=True, exist_ok=True)
            try:
                self._lock.acquire(timeout=0)
            except Timeout:
                return False
            try:
                await self._serve()
            except BaseException:
                self._lock.release()
                raise
            logger.info("this process has the library at %s open", self.store)
            if self._on_owner is not None:
                self._on_owner()
            return True

    async def _serve(self) -> None:
        self._server = await asyncio.start_server(
            self._answer, host="127.0.0.1", port=0, limit=LINE_LIMIT
        )
        port = self._server.sockets[0].getsockname()[1]
        record = json.dumps({"port": port, "token": self._token, "pid": os.getpid()})
        path = owner_path(self.store)
        tmp = path.with_suffix(".tmp")
        # 0600 from the start: the token is the only thing between another
        # local user and this person's documents.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(record)
        os.replace(tmp, path)

    async def close(self) -> None:
        if self._server is not None:
            self._server.close()
            self._server = None
        if self.owner:
            try:
                owner_path(self.store).unlink()
            except OSError:
                pass
            self._lock.release()

    # -- answering ---------------------------------------------------------

    async def _answer(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request = json.loads(await reader.readline())
            if not hmac.compare_digest(str(request.get("token", "")), self._token):
                reply: dict[str, Any] = {"error": "refused: wrong token"}
            else:
                try:
                    reply = {"result": await self._run_local(request["tool"], request["args"])}
                except Exception as e:  # noqa: BLE001 - goes back to the caller, not lost
                    logger.exception("forwarded %s failed", request.get("tool"))
                    reply = {"error": f"{type(e).__name__}: {e}"}
            writer.write(json.dumps(reply, default=str).encode() + b"\n")
            await writer.drain()
        except (ValueError, ConnectionError) as e:
            logger.warning("dropped a malformed request from another sextant process: %s", e)
        finally:
            writer.close()

    # -- calling -----------------------------------------------------------

    async def call(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if self.owner or await self.try_own():
            return await self._run_local(tool, args)
        deadline = asyncio.get_running_loop().time() + OWNER_START_SECONDS
        while True:
            try:
                return await self._forward(tool, args)
            except (OSError, ValueError) as e:
                # The owner exited (its lock is free now) or has not written
                # its address yet.
                if await self.try_own():
                    return await self._run_local(tool, args)
                if asyncio.get_running_loop().time() > deadline:
                    raise LibraryBusy(
                        f"Another sextant process has the library at {self.store} open "
                        f"and is not answering ({e}). Quit the other assistant window "
                        "using sextant, or restart this one."
                    ) from e
                await asyncio.sleep(0.25)

    async def _forward(self, tool: str, args: dict[str, Any]) -> dict[str, Any]:
        record = json.loads(owner_path(self.store).read_text())
        reader, writer = await asyncio.open_connection(
            "127.0.0.1", int(record["port"]), limit=LINE_LIMIT
        )
        try:
            request = {"token": record["token"], "tool": tool, "args": args}
            writer.write(json.dumps(request).encode() + b"\n")
            await writer.drain()
            line = await reader.readline()
        finally:
            writer.close()
        if not line:
            raise ConnectionResetError("the owner closed the connection without answering")
        reply = json.loads(line)
        if "error" in reply:
            raise RuntimeError(reply["error"])
        result: dict[str, Any] = reply["result"]
        return result


@contextmanager
def exclusive(store: Path) -> Iterator[None]:
    """Hold the library for a command that opens the store itself.

    `sextant-ingest` and `sextant-forget` write the store directly. Run while
    an assistant has it open, that is two processes writing one store -- the
    thing this module exists to prevent -- so they refuse instead.
    """
    store.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(lock_path(store)), thread_local=False)
    try:
        lock.acquire(timeout=0)
    except Timeout as e:
        raise LibraryBusy(
            f"sextant is running in an assistant and has the library at {store} open. "
            "Quit that assistant (or remove sextant from it), then run this again."
        ) from e
    try:
        yield
    finally:
        lock.release()
