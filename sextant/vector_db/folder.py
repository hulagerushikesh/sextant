"""The folder a launcher chose: index it when the server starts.

`ingest_cli` explains why file loading is a command and not an MCP tool: a
`kb_ingest_file` tool would hand every client that mounts this server, and the
model behind it, the ability to read arbitrary paths. That reasoning is about
*who names the path*, and it still holds here. This module reads one folder,
named by `SEXTANT_FOLDER` in the environment the launcher gave this process --
which in a Claude Desktop bundle is the folder a person picked in the install
dialog. The model never names a path, and no tool takes one.

It exists because the quickstart's second step was a terminal command, and a
person who installed with a double-click has no terminal open. The bundle sets
the variable; a config that does not set it gets exactly the server it had.

What it does, each time the server starts:

- walks the folder for the suffixes the loaders read;
- stores every file that is new or has changed since it was last stored, and
  leaves the rest alone -- a 400-file folder is not re-embedded on every launch;
- records what it could not store, and why, and says so through `kb_stats`
  and the self-test's report, because a file that silently is not in the
  corpus reads as "the answer is not there".

What it does not do: remove a document whose file was deleted, or watch for
changes while running. Both are "keep a folder in sync", which is a later
milestone's decision, not a side effect of this one.

Nothing here prints. stdout is the JSON-RPC channel.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sextant import settings
from sextant.vector_db.loaders import (
    MARKDOWN_SUFFIXES,
    PDF_SUFFIXES,
    TEXT_SUFFIXES,
    UnsupportedDocument,
    unreadable_line,
)
from sextant.vector_db.retrieval import RerankerUnavailable

logger = logging.getLogger(__name__)

SUPPORTED = PDF_SUFFIXES | MARKDOWN_SUFFIXES | TEXT_SUFFIXES

# Beside the collection, so it is thrown away with it: an emptied store must
# not be remembered as "already indexed".
LEDGER_NAME = "folder_index.json"

# Reported, not unbounded: a folder with nine hundred unreadable files should
# not turn `kb_stats` into nine hundred lines the model has to read.
MAX_REPORTED = 20


def configured() -> Path | None:
    """The folder the launcher chose, or `None`.

    An empty value, or a placeholder a client failed to substitute, is "not
    set" rather than a path: `${user_config.folder}` arriving literally would
    otherwise be reported as a missing folder of that name.
    """
    raw = (settings.getenv("FOLDER") or "").strip()
    if not raw or raw.startswith("${"):
        return None
    return Path(raw).expanduser()


def no_text_reason(path: Path) -> str:
    """Why a file that loaded but held no words is not searchable, in plain words.

    A PDF with no text at all is nearly always a scan: pictures of pages, with
    no text layer for search to read.
    """
    if path.suffix.lower() in PDF_SUFFIXES:
        return (
            "has no text that can be read, so it is probably a scanned PDF; it "
            "needs text recognition (OCR) before it can be searched"
        )
    return "is empty"


def _signature(path: Path) -> list[int]:
    stat = path.stat()
    return [stat.st_mtime_ns, stat.st_size]


def find_files(folder: Path) -> list[Path]:
    """Every loadable file under `folder`, hidden directories excluded.

    Hidden directories are skipped because the folder a person picks is often
    a notes vault or a checkout, and `.git`, `.obsidian` and `.venv` hold text
    files nobody means to search.
    """
    found: list[Path] = []
    for path in sorted(folder.rglob("*")):
        if any(part.startswith(".") for part in path.relative_to(folder).parts):
            continue
        if path.suffix.lower() in SUPPORTED and path.is_file():
            found.append(path)
    return found


class FolderSync:
    """One pass over the chosen folder, and what it is able to say about itself.

    `status()` is read by `kb_stats` and `kb_search` while `run()` is still
    going, so every field is updated as the pass proceeds rather than at the
    end: "indexing, 12 of 40" is the honest answer to a question asked ten
    seconds after install.
    """

    def __init__(self, folder: Path, ledger_dir: Path) -> None:
        self.folder = folder
        self.ledger_path = ledger_dir / LEDGER_NAME
        self.state = "waiting"
        self.found = 0
        self.done = 0
        self.stored = 0
        self.unchanged = 0
        self.skipped: list[dict[str, str]] = []
        self.warnings: list[str] = []
        self.error: str | None = None

    # -- what it says ------------------------------------------------------

    def status(self) -> dict[str, Any]:
        report: dict[str, Any] = {
            "path": str(self.folder),
            "state": self.state,
            "files_found": self.found,
            "files_checked": self.done,
            "stored_this_run": self.stored,
            "unchanged": self.unchanged,
            "not_indexed": len(self.skipped),
        }
        if self.skipped:
            report["not_indexed_files"] = self.skipped[:MAX_REPORTED]
            if len(self.skipped) > MAX_REPORTED:
                report["not_indexed_more"] = len(self.skipped) - MAX_REPORTED
        if self.warnings:
            report["warnings"] = self.warnings[:MAX_REPORTED]
        if self.error:
            report["error"] = self.error
        return report

    def note(self) -> str | None:
        """One sentence for a search result, or `None` when there is nothing to add.

        A search that runs while the folder is half indexed returns a correct
        answer about half a library. Without this line the model has no way to
        tell that from "the answer is not in your documents".
        """
        if self.state in ("waiting", "indexing"):
            return (
                f"The folder {self.folder} is still being indexed "
                f"({self.done} of {self.found} files checked), so these results "
                "cover only part of it. Ask again shortly for the full library."
            )
        if self.state == "missing":
            return (
                f"The chosen folder {self.folder} could not be found, "
                "so nothing from it is indexed."
            )
        if self.state == "failed":
            return f"Indexing the folder {self.folder} failed: {self.error}"
        return None

    # -- the ledger --------------------------------------------------------

    def _read_ledger(self) -> dict[str, Any]:
        try:
            ledger = json.loads(self.ledger_path.read_text())
        except (OSError, ValueError):
            return {}
        return ledger if isinstance(ledger, dict) else {}

    def _write_ledger(self, ledger: dict[str, Any]) -> None:
        try:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            self.ledger_path.write_text(json.dumps(ledger, indent=0, sort_keys=True))
        except OSError as e:
            # Costs a re-index next launch, nothing else; worth a line, not a failure.
            logger.warning("could not record the folder index at %s: %s", self.ledger_path, e)

    # -- the pass ----------------------------------------------------------

    async def run(self, open_store: Callable[[], Any]) -> None:
        """Index what is new or changed. Never raises: the server must keep serving."""
        try:
            await self._run(open_store)
        except Exception as e:  # noqa: BLE001 - a background task has nobody to raise to
            self.state = "failed"
            self.error = f"{type(e).__name__}: {e}"
            logger.exception("indexing %s failed", self.folder)

    async def _run(self, open_store: Callable[[], Any]) -> None:
        if not self.folder.is_dir():
            self.state = "missing"
            self.error = f"Not a folder: {self.folder}"
            logger.warning(self.error)
            return

        self.state = "indexing"
        files = await asyncio.to_thread(find_files, self.folder)
        self.found = len(files)
        if not files:
            self.state = "ready"
            return

        ledger = await asyncio.to_thread(self._read_ledger)
        # Opening the store loads the embedding model -- a download on a first
        # run -- so it happens on a thread, and only once there is work.
        kb = await asyncio.to_thread(open_store)
        in_store = await self._documents_in(kb)

        # A document's id is its file name without the suffix, so `a/notes.md`
        # and `b/notes.md` are one document and the second would replace the
        # first. Keep the first and say so, rather than lose one silently.
        claimed: dict[str, Path] = {}

        for path in files:
            key = str(path)
            try:
                signature = await asyncio.to_thread(_signature, path)
            except OSError as e:
                self._skip(path, f"could not be read: {e}")
                self.done += 1
                continue

            first = claimed.setdefault(path.stem, path)
            if first != path:
                self._skip(
                    path,
                    f"has the same name as {first.relative_to(self.folder)}, "
                    "which is the one indexed; rename one to index both",
                    "same_name",
                )
                self.done += 1
                continue

            known = ledger.get(key)
            if isinstance(known, dict) and known.get("signature") == signature:
                if known.get("stored") and path.stem in in_store:
                    self.unchanged += 1
                    self.done += 1
                    continue
                if not known.get("stored"):
                    # Failed last time and has not changed since: same result,
                    # so report it again without paying to find out again.
                    self._skip(
                        path,
                        str(known.get("reason") or "could not be indexed"),
                        str(known.get("kind") or "unreadable"),
                    )
                    self.done += 1
                    continue

            try:
                reason, kind = await self._store_one(kb, path)
            except Exception as e:  # noqa: BLE001 - one file must not end the pass
                # A file the loaders did not expect. Until 2026-11-15 this
                # escaped to `run`, and one locked PDF in a real Downloads
                # folder left 172 of 190 files unread. Reported, and kept out
                # of the ledger, so a later version that can read it tries again.
                logger.warning("could not index %s: %s", path, e)
                self._skip(path, f"could not be read ({type(e).__name__}: {e})")
                self.done += 1
                continue
            if reason is None:
                ledger[key] = {"signature": signature, "stored": True}
                self.stored += 1
            else:
                ledger[key] = {
                    "signature": signature,
                    "stored": False,
                    "reason": reason,
                    "kind": kind,
                }
                self._skip(path, reason, kind)
            self.done += 1
            # Written as it goes: a first run over a large folder that is
            # interrupted should resume, not start again.
            await asyncio.to_thread(self._write_ledger, ledger)

        if self.stored:
            await self._warm(kb)
        self.state = "ready"
        logger.info(
            "folder %s: %d stored, %d unchanged, %d not indexed",
            self.folder, self.stored, self.unchanged, len(self.skipped),
        )

    @staticmethod
    async def _documents_in(kb: Any) -> set[str]:
        """Ids the store holds now. The ledger says a file *was* stored; a
        store emptied or a document forgotten since makes that false."""
        listing = await kb.list_documents()
        return {
            str(doc.get("document_id") or doc.get("id"))
            for doc in listing.get("documents") or []
        }

    async def _store_one(self, kb: Any, path: Path) -> tuple[str | None, str]:
        """Store one file. Returns why not and what kind of failure it was,
        or `(None, "")` when it is in the corpus."""
        try:
            result = await kb.add_file(str(path))
        except UnsupportedDocument as e:
            return str(e), "unreadable"
        if not result.get("success"):
            if result.get("empty"):
                return no_text_reason(path), "no_text"
            return str(result.get("message") or "could not be indexed"), "unreadable"
        lost = result.get("unreadable_pages") or {}
        if lost:
            self.warnings.append(unreadable_line(lost))
        return None, ""

    @staticmethod
    async def _warm(kb: Any) -> None:
        """Load the reranker now, so the first question does not wait on it."""
        try:
            await asyncio.to_thread(kb.reranker.score, "ready", ["ready"])
        except RerankerUnavailable as e:
            logger.warning("search model not fetched (%s); the first question will fetch it", e)

    def not_indexed(self) -> list[dict[str, str]]:
        """Every file this pass could not store -- all of them, unlike `status`."""
        return list(self.skipped)

    def _skip(self, path: Path, reason: str, kind: str = "unreadable") -> None:
        try:
            name = str(path.relative_to(self.folder))
        except ValueError:
            name = path.name
        self.skipped.append({"file": name, "reason": reason, "kind": kind})
