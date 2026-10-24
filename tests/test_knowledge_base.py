"""The knowledge base end to end: real models, real ChromaDB, isolated store."""

from __future__ import annotations

import asyncio
import time

import pytest

from tools.vector_db import vector_search
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


class TestFloorFallback:
    """Milestone 17: what a search returns when nothing clears the floor."""

    async def test_off_by_default_an_empty_result_stays_empty(self, kb):
        result = await kb.search("boiling point of liquid nitrogen", limit=5, min_score=0.99)
        assert result["results"] == []
        assert result["below_floor"] is False

    async def test_on_the_nearest_chunks_come_back_marked_and_cosine_scored(self, kb, monkeypatch):
        monkeypatch.setattr(vector_search, "FLOOR_FALLBACK", "dense")
        result = await kb.search("boiling point of liquid nitrogen", limit=5, min_score=0.99)
        hits = result["results"]
        assert hits and result["below_floor"] is True
        assert result["scored_by"] == "cosine"
        assert all(hit["scored_by"] == "cosine" for hit in hits)
        # The reported score is the cosine, not a cross-encoder score that
        # would read as a relevance; and the list is in cosine order.
        assert [hit["score"] for hit in hits] == [hit["dense_score"] for hit in hits]
        assert [hit["score"] for hit in hits] == sorted(
            (hit["score"] for hit in hits), reverse=True
        )

    async def test_on_a_search_that_clears_the_floor_is_untouched(self, kb, monkeypatch):
        monkeypatch.setattr(vector_search, "FLOOR_FALLBACK", "dense")
        result = await kb.search("kalman", limit=5)
        assert result["below_floor"] is False
        assert result["scored_by"] == "cross-encoder"

    async def test_a_caller_asking_for_everything_never_gets_the_fallback(self, kb, monkeypatch):
        # min_score 0 keeps nothing out, so there is nothing to fall back from;
        # `sextant-eval` grades at 0 and must see the cross-encoder's order.
        monkeypatch.setattr(vector_search, "FLOOR_FALLBACK", "dense")
        result = await kb.search("boiling point of liquid nitrogen", limit=5, min_score=0.0)
        assert result["below_floor"] is False
        assert result["scored_by"] == "cross-encoder"


class TestListing:
    async def test_every_document_is_listed_with_its_opening(self, kb):
        listing = await kb.list_documents()
        by_id = {d["document_id"]: d for d in listing["documents"]}
        assert listing["count"] == len(by_id) >= 2
        kalman = by_id["kalman"]
        assert kalman["title"] == "Kalman Filter"
        assert kalman["chunks"] >= 1
        assert kalman["lead"].startswith("# Kalman Filter")
        assert kalman["overview"] is None
        assert kalman["pages"] is None

    async def test_listing_is_ordered_by_category_then_title(self, kb):
        listing = await kb.list_documents()
        keys = [(d["category"], d["title"].lower()) for d in listing["documents"]]
        assert keys == sorted(keys)


class TestPerDocumentCap:
    """`_diversify` on its own: the ranking is given, only the slots move."""

    # Ranked ids: three chunks of `a`, then one of `b`, then one of `c`.
    ids = ["a#0", "a#1", "a#2", "b#0", "c#0"]
    order = [0, 1, 2, 3, 4]
    scores = [0.9, 0.8, 0.7, 0.6, 0.5]

    def kb(self):
        stub = KnowledgeBase.__new__(KnowledgeBase)
        stub._corpus = {i: ("", {"document_id": i.split("#")[0]}) for i in self.ids}
        return stub

    def test_a_capped_document_yields_its_slots_to_the_next_documents(self, monkeypatch):
        monkeypatch.setattr(vector_search, "MAX_PER_DOCUMENT", 1)
        chosen = self.kb()._diversify(self.order, self.ids, self.scores, 3)
        assert [self.ids[i] for i in chosen] == ["a#0", "b#0", "c#0"]

    def test_what_the_cap_cuts_backfills_in_score_order(self, monkeypatch):
        # Two slots left after the other documents are in; the cut chunks of
        # `a` take them, still in rank order, so nothing is ever lost.
        monkeypatch.setattr(vector_search, "MAX_PER_DOCUMENT", 1)
        chosen = self.kb()._diversify(self.order, self.ids, self.scores, 5)
        assert [self.ids[i] for i in chosen] == ["a#0", "b#0", "c#0", "a#1", "a#2"]

    def test_a_single_document_corpus_is_unchanged(self, monkeypatch):
        monkeypatch.setattr(vector_search, "MAX_PER_DOCUMENT", 2)
        chosen = self.kb()._diversify([0, 1, 2], self.ids, self.scores, 3)
        assert [self.ids[i] for i in chosen] == ["a#0", "a#1", "a#2"]

    def test_zero_means_off(self, monkeypatch):
        monkeypatch.setattr(vector_search, "MAX_PER_DOCUMENT", 0)
        assert self.kb()._diversify(self.order, self.ids, self.scores, 3) == [0, 1, 2]


async def _tick_gaps(work) -> tuple[list[float], float]:
    """Gaps between 10ms heartbeat ticks while `work()` runs, and the duration.

    Gaps rather than a count, because the property this file cares about is
    *how long the loop ever went unserved* -- which is what decides whether a
    request waits -- and not how much total throughput it kept.
    """
    gaps: list[float] = []
    last = time.perf_counter()

    async def heartbeat():
        nonlocal last
        while True:
            await asyncio.sleep(0.01)
            now = time.perf_counter()
            gaps.append(now - last)
            last = now

    beat = asyncio.create_task(heartbeat())
    started = last = time.perf_counter()
    try:
        await work()
    finally:
        elapsed = time.perf_counter() - started
        beat.cancel()
    return gaps, elapsed


class TestConcurrency:
    async def test_searching_does_not_block_the_event_loop(self, kb):
        # Before this was fixed a 10ms heartbeat ticked zero times during half a
        # second of searching: the server could not stream or answer /health.
        #
        # The assertion is on the longest stall as a fraction of the work, and
        # it took three wrong versions to get there. It was
        # `ticks > (elapsed / 0.01) * 0.5` -- a throughput ratio against the
        # rate a 10ms sleep would give if it slept exactly 10ms, which it never
        # does; idle on a fast machine measures 0.84, so the threshold's whole
        # headroom went to machine speed. Measuring an idle baseline on the
        # same machine fixed that and was still wrong, because throughput is
        # not the property: CI showed 31.9 ticks/s against 98.0 idle, and a
        # loop ticking every 31ms answers /health perfectly well. The
        # regression was one stall covering the entire search.
        #
        # What finally settled it: this test failed on CI only when three
        # unrelated tests were added to this file *below* it, and passed
        # without them -- proven by running the workflow four times over
        # trimmed branches. The mechanism by which later tests affect an
        # earlier one is not understood. What is clear is that a gate which
        # moves when unrelated load is added somewhere else in the suite is
        # measuring the machine, so the measure has to be scale-free.
        #
        # A fraction of `elapsed` is. The regression -- one gap spanning the
        # whole search -- gives a ratio near 1.0 and fails by the entire
        # margin, while CPU contention produces many small gaps and passes
        # however many cores the box has.
        await kb.search("warm up", limit=1)

        gaps, elapsed = await _tick_gaps(
            lambda: asyncio.gather(*(kb.search(f"query {i}", limit=5) for i in range(4)))
        )

        longest = max(gaps, default=elapsed)
        assert longest < elapsed * 0.25, (
            f"loop stalled for {longest * 1000:.0f}ms of a {elapsed * 1000:.0f}ms "
            f"search ({longest / elapsed:.0%} of it in one unserved stretch)"
        )

    async def test_the_starvation_check_can_fail(self, kb):
        # The assertion above only means something if blocking the loop trips
        # it. `time.sleep` in a coroutine is exactly what the original fix
        # removed from the search path.
        async def blocking():
            # The one place in this repository where blocking the loop on
            # purpose is the point, so the lint that forbids it is waived here
            # and nowhere else.
            time.sleep(0.3)  # noqa: ASYNC251

        gaps, elapsed = await _tick_gaps(blocking)
        assert max(gaps, default=elapsed) > elapsed * 0.25

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
    """The dense-retrieval backend switch (SEXTANT_ANN_INDEX).

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
            monkeypatch.setenv("SEXTANT_ANN_INDEX", name.upper())
            assert configured_ann_backend() == name

    def test_an_unknown_backend_is_rejected_loudly(self, monkeypatch):
        from tools.vector_db.vector_search import (
            KnowledgeBaseUnavailable,
            configured_ann_backend,
        )

        # A real index name, but not one exposed as a live dense backend.
        monkeypatch.setenv("SEXTANT_ANN_INDEX", "faiss_hnsw")
        with pytest.raises(KnowledgeBaseUnavailable, match="not a known dense backend"):
            configured_ann_backend()

    async def test_flat_backend_matches_chroma_and_reports_itself(self, kb, monkeypatch):
        # The `kb` fixture guarantees the shared corpus is ingested into the store
        # this new instance also opens.
        from tools.vector_db.vector_search import KnowledgeBase

        query = "how do you estimate hidden state"
        chroma_top = (await kb.search(query, limit=5))["results"][0]["id"]

        monkeypatch.setenv("SEXTANT_ANN_INDEX", "flat")
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


class TestTheStoreReportsWhatIsNotInIt:
    """One place decides whether anything went missing and says so.

    `_store` builds the sentence, so `/upload` (which arrives as a dict) and
    `sextant-ingest` (which arrives as a LoadedDocument) cannot disagree, and
    neither re-derives "was anything lost?" from a chunk count it has no way
    to check. Same shape as `rule_verdict` in eval/tenancy.py.
    """

    @pytest.fixture
    async def own_kb(self, store_dir, request):
        name = f"lossy-{request.node.name[:40]}"
        knowledge_base = KnowledgeBase(collection_name=name)
        yield knowledge_base
        knowledge_base.client.delete_collection(name)

    async def test_a_clean_ingest_reports_no_loss(self, own_kb):
        result = await own_kb.add_documents(
            [{"id": "d1", "content": "Kalman filters predict then update.", "title": "d1"}]
        )
        assert result["success"] is True
        assert result["unreadable_pages"] == {}
        assert "not in the corpus" not in result["message"]

    async def test_the_loss_arrives_through_the_dict_door(self, own_kb):
        # This is the `/upload` path: `to_document` parses the PDF and hands
        # over a plain dict, which used to drop the fact on the floor at
        # `_add_documents_sync`.
        result = await own_kb.add_documents(
            [
                {
                    "id": "paper",
                    "title": "paper",
                    "content": "Page one survived.",
                    "unreadable_pages": [7, 41],
                }
            ]
        )
        assert result["unreadable_pages"] == {"paper": [7, 41]}
        assert "7, 41" in result["message"]
        assert "not in the corpus" in result["message"]

    async def test_the_document_is_still_stored_and_searchable(self, own_kb):
        # The original behaviour is right and stays: a partly readable file is
        # worth having. It may not be presented as a whole one.
        await own_kb.add_documents(
            [
                {
                    "id": "paper",
                    "title": "paper",
                    "content": "The Hungarian algorithm assigns detections to tracks.",
                    "unreadable_pages": [2],
                }
            ]
        )
        hits = await own_kb.search("Hungarian algorithm", limit=3, min_score=0.0)
        assert any("Hungarian" in hit["content"] for hit in hits["results"])
