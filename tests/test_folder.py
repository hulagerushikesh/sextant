"""The folder a bundle chose: what gets indexed, what is skipped, and what is said.

A person who installed with a double-click picks a folder and asks a question.
Three things have to be true for the answer to be honest, and each has a test
class here:

- the folder is indexed once, and a second launch does not re-embed it;
- a file that could not be stored is *reported*, with the reason, never just
  missing -- a missing file reads as "the answer is not in your documents";
- a question asked while indexing is still going says the library is partial.

The store is a fake that records what it was asked to do; the real one is
exercised by `test_knowledge_base.py`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from sextant import settings
from sextant.vector_db import folder
from sextant.vector_db.folder import LEDGER_NAME, MAX_REPORTED, FolderSync, configured, find_files
from sextant.vector_db.loaders import LoadedDocument, UnsupportedDocument


class FakeReranker:
    def __init__(self) -> None:
        self.warmed = 0

    def score(self, query: str, passages: list[str]) -> list[float]:
        self.warmed += 1
        return [1.0 for _ in passages]


class FakeKB:
    """Loads and stores like the real store, keyed by the id it is handed, and
    can refuse a file. `added` holds each stored document's id, which for a
    file at the top of the folder is its file name."""

    def __init__(
        self,
        refuse: dict[str, str] | None = None,
        broken: set[str] | None = None,
        crash: set[str] | None = None,
        empty: set[str] | None = None,
    ):
        self.added: list[str] = []
        self.docs: set[str] = set()
        self.removed: list[str] = []
        self.sources: dict[str, str] = {}
        self.refuse = refuse or {}
        self.broken = broken or set()
        self.crash = crash or set()
        self.empty = empty or set()
        self.tried: list[str] = []
        self.reranker = FakeReranker()

    async def load_file(self, path: str, category: str = "general") -> LoadedDocument:
        name = Path(path).name
        self.tried.append(name)
        if name in self.broken:
            raise UnsupportedDocument(f"cannot parse {name}")
        if name in self.crash:
            # What PyMuPDF raised on a locked PDF in a real Downloads folder.
            raise ValueError("document closed or encrypted")
        # What the real loaders name it: the stem. The folder pass renames it.
        return LoadedDocument(doc_id=Path(path).stem, title=name, text="words", source=name)

    async def add_document(self, document: LoadedDocument) -> dict[str, Any]:
        name = Path(document.source).name
        self.added.append(document.doc_id)
        if name in self.empty:
            # What the real store answers when a file loads to no words.
            return {"success": False, "message": "Nothing to store", "empty": True}
        if name in self.refuse:
            return {"success": False, "message": self.refuse[name]}
        self.docs.add(document.doc_id)
        self.sources[document.doc_id] = document.source
        return {"success": True, "chunks_added": 1, "unreadable_pages": {}}

    async def remove_document(self, document_id: str) -> dict[str, Any]:
        self.removed.append(document_id)
        self.docs.discard(document_id)
        return {"success": True, "found": True}

    async def list_documents(self) -> dict[str, Any]:
        return {"documents": [{"document_id": d} for d in sorted(self.docs)]}


def _write(root: Path, name: str, text: str | None = None) -> Path:
    """Each file's text is its own unless a test says otherwise: two files
    with equal bytes are one document's copies."""
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"the words of {name}" if text is None else text)
    return path


@pytest.fixture
def library(tmp_path: Path) -> Path:
    root = tmp_path / "library"
    _write(root, "notes.md")
    _write(root, "plan.txt")
    _write(root, "deep/inside/report.md")
    return root


@pytest.fixture
def store(tmp_path: Path) -> Path:
    return tmp_path / "store"


async def _run(root: Path, store: Path, kb: FakeKB) -> FolderSync:
    sync = FolderSync(root, store)
    await sync.run(lambda: kb)
    return sync


class TestWhichFolder:
    def test_unset_is_none(self, monkeypatch):
        monkeypatch.delenv(settings.env_name("FOLDER"), raising=False)
        assert configured() is None

    def test_an_unsubstituted_placeholder_is_not_a_path(self, monkeypatch):
        """A client that passes `${user_config.folder}` through literally must
        not produce "folder ${user_config.folder} not found"."""
        monkeypatch.setenv(settings.env_name("FOLDER"), "${user_config.folder}")
        assert configured() is None

    def test_home_is_expanded(self, monkeypatch):
        monkeypatch.setenv(settings.env_name("FOLDER"), "~/notes")
        assert configured() == Path.home() / "notes"


class TestWhatIsFound:
    def test_only_loadable_files_and_no_hidden_directories(self, library: Path):
        _write(library, "picture.png")
        _write(library, ".git/description.txt")
        _write(library, ".obsidian/workspace.md")
        names = sorted(p.name for p in find_files(library))
        assert names == ["notes.md", "plan.txt", "report.md"]


class TestIndexedOnce:
    async def test_every_file_is_stored_and_the_models_are_warmed(self, library, store):
        kb = FakeKB()
        sync = await _run(library, store, kb)
        assert sorted(kb.added) == ["deep/inside/report.md", "notes.md", "plan.txt"]
        assert sync.status()["state"] == "ready"
        assert sync.status()["stored_this_run"] == 3
        assert kb.reranker.warmed == 1
        assert sync.note() is None

    async def test_a_second_launch_stores_nothing(self, library, store):
        kb = FakeKB()
        await _run(library, store, kb)
        kb.added.clear()
        again = await _run(library, store, kb)
        assert kb.added == []
        assert again.status()["unchanged"] == 3
        assert kb.reranker.warmed == 1, "nothing new, so no model load is needed"

    async def test_a_changed_file_is_stored_again(self, library, store):
        kb = FakeKB()
        await _run(library, store, kb)
        kb.added.clear()
        changed = library / "notes.md"
        changed.write_text("different and longer words")
        stat = changed.stat()
        os.utime(changed, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
        await _run(library, store, kb)
        assert kb.added == ["notes.md"]

    async def test_a_document_gone_from_the_store_is_stored_again(self, library, store):
        """The ledger says what *was* stored. An emptied store, or a document
        forgotten since, makes that false, and trusting it would leave the
        file out for good."""
        kb = FakeKB()
        await _run(library, store, kb)
        kb.docs.discard("plan.txt")
        kb.added.clear()
        await _run(library, store, kb)
        assert kb.added == ["plan.txt"]

    async def test_an_unreadable_ledger_means_index_again(self, library, store):
        kb = FakeKB()
        await _run(library, store, kb)
        (store / LEDGER_NAME).write_text("{not json")
        kb.added.clear()
        await _run(library, store, kb)
        assert sorted(kb.added) == ["deep/inside/report.md", "notes.md", "plan.txt"]


class TestWhatIsNotIndexedIsSaid:
    async def test_a_refused_file_is_reported_with_its_reason(self, library, store):
        kb = FakeKB(refuse={"plan.txt": "no text could be extracted"})
        sync = await _run(library, store, kb)
        status = sync.status()
        assert status["not_indexed"] == 1
        assert status["not_indexed_files"] == [
            {"file": "plan.txt", "reason": "no text could be extracted", "kind": "unreadable"}
        ]

    async def test_a_parse_error_is_reported_not_raised(self, library, store):
        kb = FakeKB(broken={"report.md"})
        sync = await _run(library, store, kb)
        assert sync.status()["state"] == "ready"
        assert sync.status()["not_indexed_files"][0]["file"] == str(Path("deep/inside/report.md"))

    async def test_an_unexpected_error_skips_one_file_not_the_rest(self, library, store):
        """One locked PDF ended the whole pass on a real 190-file folder."""
        kb = FakeKB(crash={"notes.md"})
        sync = await _run(library, store, kb)
        status = sync.status()
        assert status["state"] == "ready"
        assert sorted(kb.added) == ["deep/inside/report.md", "plan.txt"]
        assert status["not_indexed_files"] == [
            {
                "file": "notes.md",
                "reason": "could not be read (ValueError: document closed or encrypted)",
                "kind": "unreadable",
            }
        ]

    async def test_an_unexpected_error_is_tried_again_next_launch(self, library, store):
        """Kept out of the ledger: a later version that can read it should."""
        kb = FakeKB(crash={"notes.md"})
        await _run(library, store, kb)
        kb.tried.clear()
        await _run(library, store, kb)
        assert kb.tried == ["notes.md"]

    async def test_an_unchanged_failure_is_reported_again_without_retrying(self, library, store):
        kb = FakeKB(refuse={"plan.txt": "no text could be extracted"})
        await _run(library, store, kb)
        kb.added.clear()
        again = await _run(library, store, kb)
        assert "plan.txt" not in kb.added
        assert again.status()["not_indexed"] == 1

    async def test_a_pdf_with_no_text_is_called_scanned_and_a_text_file_empty(self, library, store):
        _write(library, "scan.pdf")
        kb = FakeKB(empty={"scan.pdf", "plan.txt"})
        sync = await _run(library, store, kb)
        got = {f["file"]: f for f in sync.not_indexed()}
        assert got["scan.pdf"]["kind"] == got["plan.txt"]["kind"] == "no_text"
        assert "scanned" in got["scan.pdf"]["reason"] and "OCR" in got["scan.pdf"]["reason"]
        assert got["plan.txt"]["reason"] == "is empty"

    async def test_the_kind_survives_a_second_launch(self, library, store):
        _write(library, "scan.pdf")
        kb = FakeKB(empty={"scan.pdf"})
        await _run(library, store, kb)
        kb.tried.clear()
        again = await _run(library, store, kb)
        assert "scan.pdf" not in kb.tried
        assert again.not_indexed()[0]["kind"] == "no_text"

    async def test_the_report_is_bounded(self, tmp_path, store):
        root = tmp_path / "many"
        names = {f"f{i:03}.txt": "empty" for i in range(MAX_REPORTED + 5)}
        for name in names:
            _write(root, name)
        sync = await _run(root, store, FakeKB(refuse=names))
        status = sync.status()
        assert len(status["not_indexed_files"]) == MAX_REPORTED
        assert status["not_indexed_more"] == 5
        # The self-test's report counts every one, not the first twenty.
        assert len(sync.not_indexed()) == MAX_REPORTED + 5

    async def test_a_missing_folder_is_a_state_and_a_note(self, tmp_path, store):
        sync = await _run(tmp_path / "nowhere", store, FakeKB())
        assert sync.status()["state"] == "missing"
        assert "could not be found" in (sync.note() or "")

    async def test_a_store_that_will_not_open_is_failed_not_raised(self, library, store):
        def broken() -> Any:
            raise RuntimeError("embedding model unavailable")

        sync = FolderSync(library, store)
        await sync.run(broken)
        assert sync.status()["state"] == "failed"
        assert "embedding model unavailable" in sync.status()["error"]


class TestOneDocumentPerFileAndPerContents:
    """A document is named by its path in the folder, and a file whose bytes
    are exactly another's is stored once. Before 0.11.3 the name was the file
    name alone: a folder of copied runs lost every `notes.md` but the first."""

    async def test_two_files_with_one_name_in_two_folders_are_both_stored(self, library, store):
        _write(library, "runs/a/notes.md", "the first run")
        _write(library, "runs/b/notes.md", "the second run")
        kb = FakeKB()
        sync = await _run(library, store, kb)
        assert {"notes.md", "runs/a/notes.md", "runs/b/notes.md"} <= kb.docs
        assert sync.status()["not_indexed"] == 0

    async def test_one_name_with_two_suffixes_is_two_documents(self, library, store):
        _write(library, "notes.txt", "a different note")
        kb = FakeKB()
        await _run(library, store, kb)
        assert {"notes.md", "notes.txt"} <= kb.docs

    async def test_a_citation_names_the_folder_it_came_from(self, library, store):
        kb = FakeKB()
        await _run(library, store, kb)
        assert kb.sources["deep/inside/report.md"] == "deep/inside/report.md"

    async def test_an_exact_copy_under_another_name_is_stored_once_and_said(self, library, store):
        _write(library, "zz-backup/notes-copy.md", "the words of notes.md")
        kb = FakeKB()
        sync = await _run(library, store, kb)
        assert "zz-backup/notes-copy.md" not in kb.added and "notes.md" in kb.docs
        report = sync.status()
        assert report["copies_not_stored"] == 1
        assert report["copies"] == [{"file": "zz-backup/notes-copy.md", "same_as": "notes.md"}]
        # A copy is searchable through its twin, so it is not "not indexed".
        assert report["not_indexed"] == 0

    async def test_one_changed_byte_is_two_documents(self, library, store):
        _write(library, "notes-edited.md", "the words of notes.md!")
        kb = FakeKB()
        sync = await _run(library, store, kb)
        assert {"notes.md", "notes-edited.md"} <= kb.docs
        assert "copies" not in sync.status()

    async def test_a_copy_stored_before_its_twin_appeared_is_removed(self, library, store):
        kb = FakeKB()
        await _run(library, store, kb)
        _write(library, "a-first/notes.md", "the words of notes.md")
        await _run(library, store, kb)
        # `a-first/notes.md` sorts first, so it is the one kept and the old
        # `notes.md` is the copy: one document of that text either way.
        assert kb.removed == ["notes.md"] and "a-first/notes.md" in kb.docs

    async def test_when_the_kept_copy_goes_the_other_is_stored(self, library, store):
        twin = _write(library, "zz/notes.md", "the words of notes.md")
        kb = FakeKB()
        await _run(library, store, kb)
        assert "zz/notes.md" not in kb.docs
        (library / "notes.md").unlink()
        await _run(library, store, kb)
        assert "zz/notes.md" in kb.docs and twin.exists()

    async def test_a_library_from_before_names_by_path_is_moved_once(self, library, store):
        """A ledger written before 0.11.3 records no document name; the store
        holds `notes`, `plan` and `report`."""
        kb = FakeKB()
        await _run(library, store, kb)
        ledger_file = store / LEDGER_NAME
        old = json.loads(ledger_file.read_text())
        for entry in old.values():
            del entry["doc_id"], entry["sha256"]
        ledger_file.write_text(json.dumps(old))
        kb.docs = {"notes", "plan", "report"}
        kb.added.clear()

        sync = await _run(library, store, kb)
        assert sorted(kb.removed) == ["notes", "plan", "report"]
        assert kb.docs == {"deep/inside/report.md", "notes.md", "plan.txt"}
        assert sync.stored == 3

        kb.added.clear()
        again = await _run(library, store, kb)
        assert kb.added == [] and again.unchanged == 3


class TestAPartialLibraryIsSaid:
    async def test_a_search_during_indexing_carries_a_note(self, library, store):
        """Asked mid-pass, the honest answer is about part of the library."""
        notes: list[str | None] = []

        class Watching(FakeKB):
            async def add_document(self, document: LoadedDocument) -> dict[str, Any]:
                notes.append(sync.note())
                return await super().add_document(document)

        sync = FolderSync(library, store)
        await sync.run(lambda: Watching())
        assert notes and all(n and "still being indexed" in n for n in notes)
        assert sync.note() is None


class TestTheServerWiresItIn:
    """The server reads the folder at import, so these reload it in a child
    interpreter rather than mutate the module everybody else imports."""

    def _probe(self, env: dict[str, str]) -> str:
        import subprocess
        import sys

        code = (
            "import json, asyncio\n"
            "from sextant.vector_db import server\n"
            "print(json.dumps({'folder': None if server._folder is None "
            "else str(server._folder.folder)}))\n"
        )
        child = {k: v for k, v in os.environ.items() if not k.startswith("SEXTANT_")}
        child.update(env)
        child[settings.SEALED] = "1"
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, env=child, check=True
        )
        return out.stdout.strip().splitlines()[-1]

    def test_no_folder_means_the_server_it_always_was(self):
        assert self._probe({}) == '{"folder": null}'

    def test_a_chosen_folder_is_picked_up(self, tmp_path):
        out = self._probe({settings.env_name("FOLDER"): str(tmp_path)})
        assert str(tmp_path) in out

    def test_the_module_never_prints(self):
        """stdout is the JSON-RPC channel."""
        source = Path(folder.__file__).read_text()
        assert "print(" not in source
