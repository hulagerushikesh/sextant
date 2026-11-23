"""The folder a launcher chose: index it when the server starts, then keep it in step.

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
- names each document by its path inside the folder, so `runs/a/notes.md` and
  `runs/b/notes.md` are two documents, not one replacing the other;
- stores a file whose bytes are exactly another file's once, and says which
  copy was left out: two copies of one text only crowd each other out of the
  results;
- reads a scanned PDF with text recognition (`ocr.py`), and tries a scan it
  could not read again when recognition is turned on or given a language --
  and reads a stored scan again when its languages change, since English
  alone turns the Marathi on a marksheet into noise;
- records what it could not store, and why, and says so through `kb_stats`
  and the self-test's report, because a file that silently is not in the
  corpus reads as "the answer is not there".

Then, while the server runs, it looks at the folder again every few seconds
(`SEXTANT_FOLDER_POLL`, default 15; `off` stops it) and, when anything in it
has changed, runs the same pass again: a file added or changed is stored, and
a file deleted is removed from search. Looking costs one directory walk and
a size-and-date check per file; nothing is read or embedded unless a file
changed. Polling rather than an operating-system file watcher, because it
needs no new package, works the same on every platform and every kind of
drive, and "within a minute" is all a person waiting for a file to show up
asks for.

Removing is the one thing here that destroys something, so it is narrow:

- only a document this pass stored, named in its own ledger, is ever
  removed -- never one added through `kb_ingest` or the ingest command;
- only when the file is gone and the folder itself is there: an unplugged
  drive or a folder that was renamed away removes nothing, and its
  documents stay searchable until it is back;
- an entry recorded for a different folder (the setting was changed) is
  left alone, not judged gone.

Nothing here prints. stdout is the JSON-RPC channel.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from sextant import __version__, settings
from sextant.vector_db import ocr
from sextant.vector_db.loaders import (
    MARKDOWN_SUFFIXES,
    PDF_SUFFIXES,
    TEXT_SUFFIXES,
    LoadedDocument,
    UnsupportedDocument,
    has_picture_pages,
    unreadable_line,
)
from sextant.vector_db.retrieval import RerankerUnavailable

logger = logging.getLogger(__name__)

SUPPORTED = PDF_SUFFIXES | MARKDOWN_SUFFIXES | TEXT_SUFFIXES

# Beside the collection, so it is thrown away with it: an emptied store must
# not be remembered as "already indexed".
LEDGER_NAME = "folder_index.json"

# Which program recorded a failure. A file that failed is skipped while it and
# the program are both unchanged; a new version may read what an old one could
# not. Until 2026-11-23 only the file counted, so a 6,155-chunk book refused by
# 0.12.3 stayed "not indexed" under 0.12.7, which stores it in slices.
PROGRAM_VERSION = __version__

# How often the folder is looked at for changes while the server runs.
DEFAULT_POLL_SECONDS = 15.0
# Faster than this, the walk itself becomes the work.
MIN_POLL_SECONDS = 2.0

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


def poll_seconds() -> float:
    """Seconds between looks at the folder; `0` when watching is off.

    `SEXTANT_FOLDER_POLL` takes a number of seconds, or `off`. Unset, empty,
    an unfilled launcher placeholder or anything unreadable is the default.
    """
    raw = (settings.getenv("FOLDER_POLL") or "").strip().lower()
    if raw in ("off", "no", "false", "0"):
        return 0.0
    if not raw or raw.startswith("${"):
        return DEFAULT_POLL_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_POLL_SECONDS
    if value != value or value <= 0:  # NaN or negative: not a number of seconds
        return DEFAULT_POLL_SECONDS
    return max(value, MIN_POLL_SECONDS)


def _snapshot(folder: Path) -> dict[str, list[int] | None] | None:
    """Each loadable file's size and date, or `None` when the folder is not there.

    Compared with the last pass's to tell whether anything changed: a file
    that could not be looked at is `None` rather than left out, so it does
    not read as deleted.
    """
    if not folder.is_dir():
        return None
    seen: dict[str, list[int] | None] = {}
    for path in find_files(folder):
        try:
            seen[str(path)] = _signature(path)
        except OSError:
            seen[str(path)] = None
    return seen


# Recorded for a stored PDF whose picture pages were not read (no data) or
# were read by a version that did not say how: never equal to a language
# list, so the next pass with recognition on reads them.
_UNKNOWN_READING = "?"


def no_text_reason(path: Path, document: LoadedDocument | None = None) -> str:
    """Why a file that loaded but held no words is not searchable, in plain words.

    A PDF with no text at all is nearly always a scan: pictures of pages, with
    no text layer for search to read. Text recognition (`ocr.py`) reads most
    of those now, so the reason says which of its two failures this was.
    """
    if path.suffix.lower() in PDF_SUFFIXES:
        if document is not None and document.recognition_missing:
            return (
                "is a scanned PDF, and text recognition could not read it: "
                f"{document.recognition_missing}"
            )
        if document is not None and document.recognition:
            return "is a scanned PDF, and text recognition found no words in it"
        return (
            "has no text that can be read, so it is probably a scanned PDF; it "
            "needs text recognition (OCR) before it can be searched"
        )
    return "is empty"


def _signature(path: Path) -> list[int]:
    stat = path.stat()
    return [stat.st_mtime_ns, stat.st_size]


def _digest(path: Path) -> str:
    """The file's bytes, hashed: equal digests are the same contents, whatever
    the two files are called."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


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
        # Files left out because another file has exactly the same bytes.
        # Not "not indexed": their text is searchable, through the other one.
        self.copies: list[dict[str, str]] = []
        # Documents stored with at least one page read by text recognition.
        self.recognised = 0
        self._recognition_tried = ""
        # What a stored document's picture pages were read with (`_read_with`).
        self._read_with = ""
        self.warnings: list[str] = []
        self.error: str | None = None
        # Documents removed because their file was deleted, this pass.
        self.removed = 0
        # Seconds between looks while watching; 0 when not watching.
        self.watching = 0.0
        self.passes = 0
        # What the folder looked like when the last pass began (`_snapshot`).
        self._seen: dict[str, list[int] | None] | None = None

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
            "text_recognition": ocr.status(),
        }
        if self.removed:
            report["removed_this_run"] = self.removed
        report["kept_in_sync"] = (
            f"checked for changes every {self.watching:g} seconds" if self.watching
            else "only when the assistant starts"
        )
        if self.recognised:
            report["read_by_text_recognition"] = self.recognised
        if self.skipped:
            report["not_indexed_files"] = self.skipped[:MAX_REPORTED]
            if len(self.skipped) > MAX_REPORTED:
                report["not_indexed_more"] = len(self.skipped) - MAX_REPORTED
        if self.copies:
            report["copies_not_stored"] = len(self.copies)
            report["copies"] = self.copies[:MAX_REPORTED]
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
        if self.state == "unreachable":
            return (
                f"The chosen folder {self.folder} cannot be reached right now (an "
                "unplugged drive, perhaps). What was indexed from it is still "
                "searchable, but changes made since are not."
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

    async def watch(self, open_store: Callable[[], Any], every: float | None = None) -> None:
        """Index the folder, then keep it in step until cancelled.

        The server runs this as its background task. Never raises, except the
        cancellation that ends it.
        """
        interval = poll_seconds() if every is None else every
        await self.run(open_store)
        if interval <= 0:
            return
        self.watching = interval
        while True:
            await asyncio.sleep(interval)
            await self.check(open_store)

    async def check(self, open_store: Callable[[], Any]) -> bool:
        """Run a pass if anything in the folder changed since the last one.

        Returns whether one ran. Never raises.
        """
        try:
            now = await asyncio.to_thread(_snapshot, self.folder)
        except Exception:  # noqa: BLE001 - one bad look must not end the watch
            logger.exception("could not look at %s for changes", self.folder)
            return False
        if now == self._seen:
            return False
        await self.run(open_store)
        return True

    async def run(self, open_store: Callable[[], Any]) -> None:
        """Index what is new or changed and remove what was deleted.
        Never raises: the server must keep serving."""
        try:
            await self._run(open_store)
        except Exception as e:  # noqa: BLE001 - a background task has nobody to raise to
            self.state = "failed"
            self.error = f"{type(e).__name__}: {e}"
            logger.exception("indexing %s failed", self.folder)

    def _start_pass(self) -> None:
        """Clear what one pass counts. Warnings and the recognised count are
        kept: they describe documents still in the store, which a later pass
        leaves alone and would not count again."""
        self.found = self.done = self.stored = self.unchanged = self.removed = 0
        self.skipped = []
        self.copies = []
        self.error = None

    async def _run(self, open_store: Callable[[], Any]) -> None:
        self._start_pass()
        # Taken first, so a change made while this pass works is seen by the
        # next look; a pass that fails is tried again on the next change.
        self._seen = await asyncio.to_thread(_snapshot, self.folder)
        if self._seen is None:
            # Indexed before and gone now is an unplugged drive until shown
            # otherwise: what it held stays, and nothing is removed.
            self.state = "unreachable" if self.passes else "missing"
            self.error = f"Not a folder: {self.folder}"
            logger.warning(self.error)
            return

        self.state = "updating" if self.passes else "indexing"
        files = [Path(key) for key in self._seen]
        self.found = len(files)
        ledger = await asyncio.to_thread(self._read_ledger)
        gone = await asyncio.to_thread(self._gone, ledger, files)
        if not files and not gone:
            self._finish()
            return

        # Opening the store loads the embedding model -- a download on a first
        # run -- so it happens on a thread, and only once there is work.
        kb = await asyncio.to_thread(open_store)
        in_store = await self._documents_in(kb)

        # One file per contents: the first, in path order, is stored, and a
        # later file with the same bytes is reported as a copy of it.
        by_contents: dict[str, Path] = {}

        for path in files:
            key = str(path)
            doc_id = self._doc_id(path)
            try:
                signature = await asyncio.to_thread(_signature, path)
            except OSError as e:
                self._skip(path, f"could not be read: {e}")
                self.done += 1
                continue

            raw = ledger.get(key)
            known: dict[str, Any] = raw if isinstance(raw, dict) else {}
            same = known.get("signature") == signature
            try:
                digest = (
                    str(known["sha256"])
                    if same and known.get("sha256")
                    else await asyncio.to_thread(_digest, path)
                )
            except OSError as e:
                self._skip(path, f"could not be read: {e}")
                self.done += 1
                continue

            first = by_contents.setdefault(digest, path)
            if first != path:
                self.copies.append({"file": doc_id, "same_as": self._doc_id(first)})
                if known.get("stored"):
                    # Stored by an earlier pass, before its twin was there or
                    # before copies were caught: now it only competes with it.
                    await self._forget(kb, str(known.get("doc_id") or path.stem), in_store)
                ledger.pop(key, None)
                await asyncio.to_thread(self._write_ledger, ledger)
                self.done += 1
                continue

            # Before 0.11.3 a document was named by its file name alone, and
            # the ledger did not record the name. Such a file is stored again
            # under its path, once, and the old document removed after.
            stored_as = known.get("doc_id") if known.get("stored") else None
            legacy = path.stem if known.get("stored") and stored_as is None else None

            if same:
                if known.get("stored") and stored_as == doc_id and doc_id in in_store:
                    if "ocr" not in known:
                        # Stored before 0.12.1 recorded how its picture pages
                        # were read. Look once; the answer goes in the ledger.
                        legacy_scan = await asyncio.to_thread(has_picture_pages, path)
                        known["ocr"] = _UNKNOWN_READING if legacy_scan else ""
                        ledger[key] = known
                        await asyncio.to_thread(self._write_ledger, ledger)
                    if not self._worth_rereading(known):
                        self.unchanged += 1
                        self.done += 1
                        continue
                if (
                    not known.get("stored")
                    and known.get("version") == PROGRAM_VERSION
                    and not self._worth_recognising(known)
                ):
                    # Failed last time, and neither the file nor the program
                    # has changed since: same result, so report it again
                    # without paying to find out again.
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
                ledger[key] = {
                    "signature": signature,
                    "sha256": digest,
                    "stored": True,
                    "doc_id": doc_id,
                    # How its picture pages were read: "" when it has none. A
                    # change of languages reads them again (`_worth_rereading`).
                    "ocr": self._read_with,
                }
                self.stored += 1
                if legacy and legacy != doc_id:
                    await self._forget(kb, legacy, in_store)
            else:
                if known.get("stored") and not same:
                    # Its file changed into one that cannot be stored: the
                    # old text no longer says what the file says.
                    await self._forget(kb, str(stored_as or legacy or doc_id), in_store)
                ledger[key] = {
                    "signature": signature,
                    "sha256": digest,
                    "stored": False,
                    "reason": reason,
                    "kind": kind,
                    # What recognition could do for it this time: a scan is
                    # tried again when that changes (`_worth_recognising`).
                    "ocr": self._recognition_tried,
                    # A later version is tried once (`PROGRAM_VERSION`).
                    "version": PROGRAM_VERSION,
                }
                self._skip(path, reason, kind)
            self.done += 1
            # Written as it goes: a first run over a large folder that is
            # interrupted should resume, not start again.
            await asyncio.to_thread(self._write_ledger, ledger)

        if gone:
            await self._remove_gone(kb, ledger, gone, in_store)

        if self.stored:
            await self._warm(kb)
        self._finish()
        logger.info(
            "folder %s: %d stored, %d unchanged, %d removed, %d copies, %d not indexed",
            self.folder, self.stored, self.unchanged, self.removed, len(self.copies),
            len(self.skipped),
        )

    def _finish(self) -> None:
        self.state = "ready"
        self.passes += 1

    def _gone(self, ledger: dict[str, Any], files: list[Path]) -> list[str]:
        """Ledger entries for files inside this folder that are no longer there.

        An entry for a path outside the folder was written when another
        folder was chosen; whether that file exists is not this pass's
        question, so it is never listed.
        """
        present = {str(path) for path in files}
        gone: list[str] = []
        for key in ledger:
            if key in present:
                continue
            path = Path(key)
            try:
                path.relative_to(self.folder)
            except ValueError:
                continue
            if not path.exists():
                gone.append(key)
        return gone

    async def _remove_gone(
        self, kb: Any, ledger: dict[str, Any], gone: list[str], in_store: set[str]
    ) -> None:
        """Remove from search the documents whose files were deleted.

        The folder is looked at once more first: a drive pulled out during the
        pass makes every file look deleted, and that must remove nothing.
        """
        if not await asyncio.to_thread(self.folder.is_dir):
            logger.warning("%s went away during the pass; nothing removed", self.folder)
            return
        for key in gone:
            entry = ledger.pop(key, None)
            if isinstance(entry, dict) and entry.get("stored"):
                # Named by its path since 0.11.3; by its file name before that.
                doc_id = str(entry.get("doc_id") or Path(key).stem)
                if doc_id in in_store:
                    await self._forget(kb, doc_id, in_store)
                    self.removed += 1
        await asyncio.to_thread(self._write_ledger, ledger)

    @staticmethod
    def _worth_recognising(known: dict[str, Any]) -> bool:
        """A scan that failed with recognition off, without its data, or in
        other languages is worth one more try now; anything else fails the
        same way twice."""
        return known.get("kind") == "no_text" and known.get("ocr", "") != ocr.signature()

    @staticmethod
    def _worth_rereading(known: dict[str, Any]) -> bool:
        """A stored document whose picture pages were read in other languages
        than are asked for now -- English only, before Marathi was added -- is
        read again, and replaces itself. Turning recognition off keeps what
        was read."""
        now, then = ocr.signature(), str(known.get("ocr") or "")
        return bool(now and then and then != now)

    def _doc_id(self, path: Path) -> str:
        """The document's name: its path inside the folder, suffix included,
        so neither `a/notes.md` and `b/notes.md` nor `notes.md` and `notes.pdf`
        are one document."""
        return path.relative_to(self.folder).as_posix()

    @staticmethod
    async def _forget(kb: Any, doc_id: str, in_store: set[str]) -> None:
        if doc_id in in_store:
            await kb.remove_document(doc_id)
            in_store.discard(doc_id)

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
        self._recognition_tried = ""
        self._read_with = ""
        try:
            document = await kb.load_file(str(path))
        except UnsupportedDocument as e:
            return str(e), "unreadable"
        if not document.recognition_missing:
            self._recognition_tried = ocr.signature()
        if document.recognised_pages:
            self._read_with = document.recognition
        elif document.recognition_missing:
            self._read_with = _UNKNOWN_READING
        # Named and cited by its place in the folder: two `notes.md` in two
        # folders are two documents, and a citation says which one.
        name = self._doc_id(path)
        result = await kb.add_document(replace(document, doc_id=name, source=name))
        if not result.get("success"):
            if result.get("empty"):
                return no_text_reason(path, document), "no_text"
            return str(result.get("message") or "could not be indexed"), "unreadable"
        if document.recognised_pages:
            self.recognised += 1
        lost = result.get("unreadable_pages") or {}
        if lost and (line := unreadable_line(lost)) not in self.warnings:
            self.warnings.append(line)
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
