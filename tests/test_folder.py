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

import os
from pathlib import Path
from typing import Any

import pytest

from sextant import settings
from sextant.vector_db import folder
from sextant.vector_db.folder import LEDGER_NAME, MAX_REPORTED, FolderSync, configured, find_files
from sextant.vector_db.loaders import UnsupportedDocument


class FakeReranker:
    def __init__(self) -> None:
        self.warmed = 0

    def score(self, query: str, passages: list[str]) -> list[float]:
        self.warmed += 1
        return [1.0 for _ in passages]


class FakeKB:
    """Stores by file stem, like the real loaders, and can refuse a file."""

    def __init__(self, refuse: dict[str, str] | None = None, broken: set[str] | None = None):
        self.added: list[str] = []
        self.docs: set[str] = set()
        self.refuse = refuse or {}
        self.broken = broken or set()
        self.reranker = FakeReranker()

    async def add_file(self, path: str, category: str = "general") -> dict[str, Any]:
        name = Path(path).name
        if name in self.broken:
            raise UnsupportedDocument(f"cannot parse {name}")
        self.added.append(name)
        if name in self.refuse:
            return {"success": False, "message": self.refuse[name]}
        self.docs.add(Path(path).stem)
        return {"success": True, "chunks_added": 1, "unreadable_pages": {}}

    async def list_documents(self) -> dict[str, Any]:
        return {"documents": [{"document_id": d} for d in sorted(self.docs)]}


def _write(root: Path, name: str, text: str = "some words") -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
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
        assert sorted(kb.added) == ["notes.md", "plan.txt", "report.md"]
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
        kb.docs.discard("plan")
        kb.added.clear()
        await _run(library, store, kb)
        assert kb.added == ["plan.txt"]

    async def test_an_unreadable_ledger_means_index_again(self, library, store):
        kb = FakeKB()
        await _run(library, store, kb)
        (store / LEDGER_NAME).write_text("{not json")
        kb.added.clear()
        await _run(library, store, kb)
        assert sorted(kb.added) == ["notes.md", "plan.txt", "report.md"]


class TestWhatIsNotIndexedIsSaid:
    async def test_a_refused_file_is_reported_with_its_reason(self, library, store):
        kb = FakeKB(refuse={"plan.txt": "no text could be extracted"})
        sync = await _run(library, store, kb)
        status = sync.status()
        assert status["not_indexed"] == 1
        assert status["not_indexed_files"] == [
            {"file": "plan.txt", "reason": "no text could be extracted"}
        ]

    async def test_a_parse_error_is_reported_not_raised(self, library, store):
        kb = FakeKB(broken={"report.md"})
        sync = await _run(library, store, kb)
        assert sync.status()["state"] == "ready"
        assert sync.status()["not_indexed_files"][0]["file"] == str(Path("deep/inside/report.md"))

    async def test_an_unchanged_failure_is_reported_again_without_retrying(self, library, store):
        kb = FakeKB(refuse={"plan.txt": "no text could be extracted"})
        await _run(library, store, kb)
        kb.added.clear()
        again = await _run(library, store, kb)
        assert "plan.txt" not in kb.added
        assert again.status()["not_indexed"] == 1

    async def test_two_files_with_one_name_keep_the_first_and_say_so(self, library, store):
        """A document's id is its file name without the suffix, so the second
        `notes` would silently replace the first."""
        _write(library, "zz/notes.txt")
        kb = FakeKB()
        sync = await _run(library, store, kb)
        assert kb.added.count("notes.md") == 1 and "notes.txt" not in kb.added
        reason = sync.status()["not_indexed_files"][0]["reason"]
        assert "same name" in reason and "notes.md" in reason

    async def test_the_report_is_bounded(self, tmp_path, store):
        root = tmp_path / "many"
        names = {f"f{i:03}.txt": "empty" for i in range(MAX_REPORTED + 5)}
        for name in names:
            _write(root, name)
        sync = await _run(root, store, FakeKB(refuse=names))
        status = sync.status()
        assert len(status["not_indexed_files"]) == MAX_REPORTED
        assert status["not_indexed_more"] == 5

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


class TestAPartialLibraryIsSaid:
    async def test_a_search_during_indexing_carries_a_note(self, library, store):
        """Asked mid-pass, the honest answer is about part of the library."""
        notes: list[str | None] = []

        class Watching(FakeKB):
            async def add_file(self, path: str, category: str = "general") -> dict[str, Any]:
                notes.append(sync.note())
                return await super().add_file(path, category)

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
