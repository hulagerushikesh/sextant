"""The knowledge base end to end: real models, real ChromaDB, isolated store."""

from __future__ import annotations

import asyncio
import time

import pytest

from tools.vector_db.vector_search import RETRIEVAL_MODES, KnowledgeBase


class TestIngestion:
    async def test_a_document_becomes_several_chunks(self, kb):
        stats = await kb.health_check()
        assert stats["documents"] == 2
        assert stats["collection_size"] >= 2

    async def test_chunks_carry_the_section_they_start_in(self, kb):
        # Attribution is by where a chunk *starts*, so a short document that
        # fits in one chunk reports its top heading, not the last one it covers.
        # `test_loaders.py` pins the offset-to-heading mapping precisely.
        result = await kb.search("how is process noise tuned", limit=5)
        sections = {hit["section"] for hit in result["results"]}
        assert sections <= {"Kalman Filter", "Tuning", "Hungarian Algorithm", None}
        assert sections - {None}

    async def test_reingesting_the_same_id_replaces_rather_than_duplicates(self, kb):
        before = (await kb.health_check())["collection_size"]
        doc = {"id": "replaceme", "title": "T", "content": "Original text about widgets."}
        await kb.add_documents([doc])
        after_first = (await kb.health_check())["collection_size"]
        await kb.add_documents([{**doc, "content": "Replacement text about widgets."}])
        assert (await kb.health_check())["collection_size"] == after_first
        assert after_first > before

    async def test_a_document_without_content_is_rejected_by_name(self, kb):
        result = await kb.add_documents([{"id": "x", "title": "T"}])
        assert result["success"] is False
        assert "content" in result["message"]

    async def test_no_documents(self, kb):
        assert (await kb.add_documents([]))["success"] is False


class TestSearch:
    async def test_finds_a_passage_by_meaning(self, kb):
        result = await kb.search("how do you estimate hidden state", limit=3)
        assert result["results"][0]["title"] == "Kalman Filter"

    async def test_finds_an_exact_error_code(self, kb):
        # The case dense retrieval alone is bad at.
        result = await kb.search("TRK-104", limit=3)
        assert "TRK-104" in result["results"][0]["content"]

    async def test_every_hit_says_how_it_was_scored(self, kb):
        result = await kb.search("kalman", limit=3)
        assert result["scored_by"] == "cross-encoder"
        for hit in result["results"]:
            assert hit["scored_by"] == "cross-encoder"
            assert 0.0 <= hit["score"] <= 1.0
            assert hit["matched"]

    async def test_hits_carry_the_provenance_a_citation_needs(self, kb):
        hit = (await kb.search("kalman gain", limit=1))["results"][0]
        assert hit["source"].endswith(".md")
        assert hit["document_id"]
        assert hit["id"].startswith(hit["document_id"])

    async def test_results_are_ordered_by_score(self, kb):
        scores = [hit["score"] for hit in (await kb.search("filter", limit=5))["results"]]
        assert scores == sorted(scores, reverse=True)

    async def test_limit_is_respected(self, kb):
        assert len((await kb.search("filter", limit=1))["results"]) <= 1

    @pytest.mark.parametrize("mode", RETRIEVAL_MODES)
    async def test_every_mode_runs_and_labels_itself(self, kb, mode):
        result = await kb.search("assignment problem", limit=3, mode=mode)
        assert result["mode"] == mode
        assert result["results"]

    async def test_an_unknown_mode_is_rejected(self, kb):
        with pytest.raises(ValueError, match="mode must be one of"):
            await kb.search("q", mode="magic")

    async def test_dense_only_reports_cosine(self, kb):
        assert (await kb.search("kalman", mode="dense"))["scored_by"] == "cosine"


class TestThreshold:
    async def test_the_floor_filters_cross_encoder_scores(self, kb):
        wide = await kb.search("kalman", limit=10, min_score=0.0)
        strict = await kb.search("kalman", limit=10, min_score=0.99)
        assert len(strict["results"]) < len(wide["results"])

    async def test_the_floor_is_not_applied_to_fusion_ranks(self, kb):
        # RRF scores live near 0.016 and mean nothing on a 0-1 scale. Applying a
        # relevance floor to them would delete everything -- which is the exact
        # shape of the l2-distance bug this project already shipped once.
        result = await kb.search("kalman", limit=5, min_score=0.5, mode="rrf")
        assert result["results"]


class TestConcurrency:
    async def test_searching_does_not_block_the_event_loop(self, kb):
        # Before this was fixed a 10ms heartbeat ticked zero times during half a
        # second of searching: the server could not stream or answer /health.
        await kb.search("warm up", limit=1)

        ticks = 0

        async def heartbeat():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        beat = asyncio.create_task(heartbeat())
        started = time.perf_counter()
        await asyncio.gather(*(kb.search(f"query {i}", limit=5) for i in range(4)))
        elapsed = time.perf_counter() - started
        beat.cancel()

        expected = elapsed / 0.01
        assert ticks > expected * 0.5, f"loop was starved: {ticks} ticks in {elapsed:.3f}s"

    async def test_concurrent_ingests_do_not_lose_a_document(self, kb):
        docs = [
            {"id": f"conc{i}", "title": f"C{i}", "content": f"Concurrent document number {i}."}
            for i in range(4)
        ]
        await asyncio.gather(*(kb.add_documents([doc]) for doc in docs))
        stored = await kb.search("concurrent document number", limit=10, min_score=0.0)
        found = {hit["document_id"] for hit in stored["results"]}
        assert {f"conc{i}" for i in range(4)} <= found


class TestHealth:
    async def test_reports_the_pipeline_it_is_running(self, kb):
        stats = await kb.health_check()
        assert stats["status"] == "healthy"
        assert "BM25" in stats["retrieval"]
        assert stats["embedding_max_tokens"] == 256

    async def test_persist_dir_is_the_isolated_one(self, kb, store_dir):
        assert (await kb.health_check())["persist_dir"] == str(store_dir)


class TestEmptyCollection:
    async def test_search_on_an_empty_store_returns_nothing(self, tmp_path, monkeypatch):
        from tools.vector_db.vector_search import PERSIST_DIR_ENV

        monkeypatch.setenv(PERSIST_DIR_ENV, str(tmp_path / "empty"))
        empty = KnowledgeBase(collection_name="empty")
        result = await empty.search("anything at all")
        assert result["results"] == []
        assert result["total_found"] == 0


class TestDenseBackend:
    """The dense-retrieval backend switch (AGENTICRAG_ANN_INDEX).

    The default is Chroma's own vector search, unchanged. The point of the switch
    is that one of the hand-written ANN indexes can answer the dense half instead
    -- so the HNSW/IVF-PQ comparison becomes a live setting, not just a benchmark.
    """

    def test_the_default_backend_is_chroma(self):
        from tools.vector_db.vector_search import configured_ann_backend

        assert configured_ann_backend() == "chroma"

    def test_every_known_backend_is_accepted_case_insensitively(self, monkeypatch):
        from tools.vector_db.vector_search import ANN_BACKENDS, configured_ann_backend

        for name in ANN_BACKENDS:
            monkeypatch.setenv("AGENTICRAG_ANN_INDEX", name.upper())
            assert configured_ann_backend() == name

    def test_an_unknown_backend_is_rejected_loudly(self, monkeypatch):
        from tools.vector_db.vector_search import (
            KnowledgeBaseUnavailable,
            configured_ann_backend,
        )

        # A real index name, but not one exposed as a live dense backend.
        monkeypatch.setenv("AGENTICRAG_ANN_INDEX", "faiss_hnsw")
        with pytest.raises(KnowledgeBaseUnavailable, match="not a known dense backend"):
            configured_ann_backend()

    async def test_flat_backend_matches_chroma_and_reports_itself(self, kb, monkeypatch):
        # The `kb` fixture guarantees the shared corpus is ingested into the store
        # this new instance also opens.
        from tools.vector_db.vector_search import KnowledgeBase

        query = "how do you estimate hidden state"
        chroma_top = (await kb.search(query, limit=5))["results"][0]["id"]

        monkeypatch.setenv("AGENTICRAG_ANN_INDEX", "flat")
        flat_kb = KnowledgeBase()
        assert flat_kb._health_check_sync()["dense_backend"] == "flat"

        flat = await flat_kb.search(query, limit=5)
        # Flat dense is exact, so the reranked top hit must agree with Chroma's.
        assert flat["results"][0]["id"] == chroma_top

        # The dense index is built once and reused, then dropped on a write.
        built = flat_kb._ann_index
        assert built is not None
        assert flat_kb._ensure_ann_index() is built
        flat_kb._invalidate_index()
        assert flat_kb._ann_index is None
