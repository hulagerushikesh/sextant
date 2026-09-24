"""`sextant-ingest`: which documents get an overview, and what happens without a key.

Overviews became the default in 0.8 once the per-document cap paid back the
dense recall they cost. The property that must survive that change is the one
the ingestion path has always promised: **without a model it still works**.
So the tests here are about the tri-state flag and the two ways a run can end
up with no overviews -- no key, and a model that fails mid-run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tools.vector_db import ingest_cli
from tools.vector_db.ingest_cli import _ingest, _summaries_wanted
from tools.vector_db.summaries import SummariesUnavailable


class FakeKB:
    """Records how each file was stored: with an overview, or as text alone."""

    def __init__(self) -> None:
        self.stored: list[tuple[str, str | None]] = []

    async def load_file(self, path: str, category: str) -> Any:
        class Doc:
            doc_id = Path(path).stem
            title = Path(path).stem
            text = "body"

        return Doc()

    async def add_document(self, document: Any, summary: str | None = None) -> dict[str, Any]:
        self.stored.append((document.doc_id, summary))
        return {"success": True, "chunks_added": 1}

    async def add_file(self, path: str, category: str) -> dict[str, Any]:
        self.stored.append((Path(path).stem, None))
        return {"success": True, "chunks_added": 1}

    async def health_check(self) -> dict[str, Any]:
        return {"documents": len(self.stored), "collection_size": len(self.stored), "summaries": 0}


@pytest.fixture
def kb_and_files(monkeypatch, tmp_path: Path):
    kb = FakeKB()
    monkeypatch.setattr(ingest_cli, "KnowledgeBase", lambda: kb)
    files = []
    for name in ("one.md", "two.md"):
        path = tmp_path / name
        path.write_text("# x\ntext")
        files.append(path)
    return kb, files


class TestTheFlagAgainstTheKey:
    def test_an_explicit_flag_wins_over_the_key_either_way(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        assert _summaries_wanted(True) is True
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        assert _summaries_wanted(False) is False

    def test_with_no_flag_the_key_decides(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "k")
        assert _summaries_wanted(None) is True

    def test_no_flag_and_no_key_is_a_printed_note_not_an_error(self, monkeypatch, capsys):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        assert _summaries_wanted(None) is False
        assert "GEMINI_API_KEY" in capsys.readouterr().out


class TestIngesting:
    async def test_without_summaries_nothing_is_summarised(self, kb_and_files):
        kb, files = kb_and_files
        assert await _ingest(files, "general", summaries=False) == 0
        assert kb.stored == [("one", None), ("two", None)]

    async def test_with_summaries_every_document_carries_one(self, kb_and_files, monkeypatch):
        kb, files = kb_and_files

        async def fake(text: str, title: str) -> str:
            return f"about {title}"

        monkeypatch.setattr(ingest_cli, "summarise", fake)
        assert await _ingest(files, "general", summaries=True) == 0
        assert kb.stored == [("one", "about one"), ("two", "about two")]

    async def test_a_model_failure_ends_the_run_when_the_flag_asked_for_summaries(
        self, kb_and_files, monkeypatch
    ):
        _, files = kb_and_files

        async def fails(text: str, title: str) -> str:
            raise SummariesUnavailable("no key")

        monkeypatch.setattr(ingest_cli, "summarise", fails)
        with pytest.raises(SummariesUnavailable):
            await _ingest(files, "general", summaries=True, required=True)

    async def test_a_model_failure_only_costs_the_overviews_when_the_default_chose_them(
        self, kb_and_files, monkeypatch, capsys
    ):
        # The text is what the corpus is for. A default that turned a working
        # ingest into a failed one would be a worse default than the flag.
        kb, files = kb_and_files

        async def fails(text: str, title: str) -> str:
            raise SummariesUnavailable("the model returned nothing")

        monkeypatch.setattr(ingest_cli, "summarise", fails)
        assert await _ingest(files, "general", summaries=True, required=False) == 0
        assert kb.stored == [("one", None), ("two", None)]
        out = capsys.readouterr().out
        # Said once, not once per document.
        assert out.count("overviews off") == 1
