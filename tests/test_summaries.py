"""Summary chunks: the model call with a fake client, and the store with a real one."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from tools.vector_db import summaries
from tools.vector_db.loaders import load_path
from tools.vector_db.summaries import (
    SUMMARY_KIND,
    SummariesUnavailable,
    summarise,
    summary_chunk_id,
    summary_text,
)


class FakeSummaryClient:
    """Stands in for `genai.Client(...).aio`, answering with a fixed text."""

    def __init__(self, text: str | None) -> None:
        self.text = text
        self.requests: list[dict[str, Any]] = []
        self.models = self

    async def generate_content(self, **kwargs: Any) -> Any:
        self.requests.append(kwargs)
        return SimpleNamespace(
            text=self.text,
            candidates=[SimpleNamespace(finish_reason="STOP")],
        )


class TestSummarise:
    async def test_sends_the_title_and_text_and_returns_the_summary(self):
        client = FakeSummaryClient("  A page about widgets.\n")
        summary = await summarise("Widgets are small.", "Widgets", client=client)
        assert summary == "A page about widgets."
        sent = client.requests[0]
        assert sent["model"] == summaries.MODEL
        assert "Title: Widgets" in sent["contents"]
        assert "Widgets are small." in sent["contents"]
        assert sent["config"].system_instruction == summaries.SUMMARY_PROMPT

    async def test_an_oversized_document_is_cut_with_a_note(self, monkeypatch):
        monkeypatch.setattr(summaries, "MAX_INPUT_CHARS", 20)
        client = FakeSummaryClient("ok")
        await summarise("x" * 100, "Big", client=client)
        body = client.requests[0]["contents"]
        assert "x" * 20 in body and "x" * 21 not in body
        assert "truncated" in body

    async def test_an_empty_answer_is_an_error_not_an_empty_chunk(self):
        with pytest.raises(SummariesUnavailable, match="no summary"):
            await summarise("text", "T", client=FakeSummaryClient(""))

    def test_without_a_key_the_error_says_what_to_do(self, monkeypatch):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(SummariesUnavailable, match="GEMINI_API_KEY"):
            summaries._client()

    def test_the_chunk_id_and_text_are_fixed_shapes(self):
        assert summary_chunk_id("reid") == "reid#summary"
        assert summary_text("Re-ID", " Appearance matching. ") == (
            "Overview of Re-ID.\nAppearance matching."
        )


KALMAN_SUMMARY = "An explanation of the Kalman filter and how process noise is tuned."


@pytest.fixture
async def kalman_overview(kb, corpus_dir: Path):
    """The shared store with one overview chunk added, removed again after.

    The `kb` fixture is session-scoped and other tests assert on exactly what
    it holds, so the chunk this adds must not outlive the test.
    """
    document = load_path(str(corpus_dir / "kalman.md"), category="test")
    before = (await kb.health_check())["collection_size"]
    result = await kb.add_document(document, summary=KALMAN_SUMMARY)
    yield document, before, result
    kb.collection.delete(ids=[summary_chunk_id(document.doc_id)])
    kb._invalidate_index()


class TestStoredSummary:
    async def test_the_summary_is_one_more_chunk_of_the_document(self, kb, kalman_overview):
        document, before, result = kalman_overview
        assert result["success"]
        stats = await kb.health_check()
        assert stats["summaries"] == 1
        # Re-ingesting the same document: its text chunks were replaced by id,
        # and the overview is the only new one.
        assert stats["collection_size"] == before + 1

        stored = kb.collection.get(
            ids=[summary_chunk_id(document.doc_id)], include=["metadatas", "documents"]
        )
        meta = stored["metadatas"][0]
        assert meta["kind"] == SUMMARY_KIND
        assert meta["document_id"] == document.doc_id
        assert meta["section"] == "Overview"
        assert meta["chunk_index"] >= 1
        assert stored["documents"][0].startswith("Overview of ")

    async def test_the_summary_is_searchable_and_cites_the_document(self, kb, kalman_overview):
        document, _, _ = kalman_overview
        wanted = summary_chunk_id(document.doc_id)
        result = await kb.search("which document explains the Kalman filter overall", limit=5)
        hits = {hit["id"]: hit for hit in result["results"]}
        assert wanted in hits
        assert hits[wanted]["document_id"] == document.doc_id
        assert hits[wanted]["section"] == "Overview"
        assert hits[wanted]["page"] is None

    async def test_without_a_summary_add_document_stores_only_the_text(self, kb, corpus_dir: Path):
        document = load_path(str(corpus_dir / "hungarian.md"), category="test")
        before = (await kb.health_check())["collection_size"]
        await kb.add_document(document)
        assert (await kb.health_check())["collection_size"] == before
        assert kb.collection.get(ids=[summary_chunk_id(document.doc_id)])["ids"] == []
