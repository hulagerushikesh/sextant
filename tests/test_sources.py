"""The source registry: numbering, identity and location."""

from __future__ import annotations

from mcp_server.sources import MAX_RESTORED, SourceRegistry


def kb_hit(**overrides):
    base = {
        "id": "notes#0",
        "title": "Kalman Filter",
        "content": "A Kalman filter estimates hidden state.",
        "source": "notes.md",
        "page": 3,
        "score": 0.98,
    }
    return {**base, **overrides}


class TestNumbering:
    def test_numbers_start_at_one_and_increment(self):
        registry = SourceRegistry()
        assert registry.add_kb(kb_hit(id="a")).n == 1
        assert registry.add_kb(kb_hit(id="b")).n == 2
        assert registry.add_web("Title", "https://x").n == 3

    def test_numbering_is_shared_across_both_tiers(self):
        registry = SourceRegistry()
        registry.add_web("W", "https://w")
        assert registry.add_kb(kb_hit()).n == 2

    def test_a_repeated_hit_keeps_its_original_number(self):
        # The model may search twice and see the same passage; it must not
        # appear under two labels.
        registry = SourceRegistry()
        first = registry.add_kb(kb_hit())
        registry.add_kb(kb_hit(id="other"))
        assert registry.add_kb(kb_hit()) is first
        assert len(registry) == 2

    def test_chunks_of_one_document_are_separate_sources(self):
        # They cite different pages, so they are different sources.
        registry = SourceRegistry()
        registry.add_kb(kb_hit(id="notes#0", page=3))
        registry.add_kb(kb_hit(id="notes#1", page=4))
        assert len(registry) == 2

    def test_web_identity_is_the_url(self):
        registry = SourceRegistry()
        first = registry.add_web("Title", "https://x")
        assert registry.add_web("A different title", "https://x") is first


class TestLocation:
    def test_page_wins_when_present(self):
        assert SourceRegistry().add_kb(kb_hit()).location == "notes.md p.3"

    def test_section_used_when_there_is_no_page(self):
        source = SourceRegistry().add_kb(kb_hit(page=None, section="Tuning"))
        assert source.location == "notes.md § Tuning"

    def test_falls_back_to_the_file(self):
        assert SourceRegistry().add_kb(kb_hit(page=None)).location == "notes.md"

    def test_no_source_at_all(self):
        assert SourceRegistry().add_kb(kb_hit(source=None, page=None)).location is None


class TestLookup:
    def test_find_web_returns_the_registered_source(self):
        registry = SourceRegistry()
        source = registry.add_web("T", "https://x")
        assert registry.find_web("https://x") is source

    def test_find_web_misses_cleanly(self):
        assert SourceRegistry().find_web("https://nope") is None

    def test_a_snippet_arriving_later_fills_an_empty_one(self):
        # A citation registers a URL with no text; the search result that
        # follows carries one and should win.
        registry = SourceRegistry()
        registry.add_web("T", "https://x")
        registry.add_web("T", "https://x", snippet="the real text")
        assert registry.sources[0].content == "the real text"


class TestRestoration:
    """Labels have to survive a round trip through the browser.

    The server keeps no session state, so continuity across questions is the
    client sending back what it was given. Without it, turn two starts numbering
    at [1] again and one transcript holds two different [1]s.
    """

    def test_numbering_resumes_after_restored_labels(self):
        registry = SourceRegistry()
        registry.restore(
            [
                {"n": 1, "key": "notes#0", "origin": "knowledge_base", "title": "K"},
                {"n": 2, "key": "https://x", "origin": "web", "url": "https://x"},
            ]
        )
        assert registry.add_kb(kb_hit(id="new")).n == 3

    def test_a_restored_passage_keeps_its_number_when_retrieved_again(self):
        registry = SourceRegistry()
        registry.restore([{"n": 4, "key": "notes#0", "origin": "knowledge_base", "title": "K"}])
        again = registry.add_kb(kb_hit())
        assert again.n == 4
        assert len(registry) == 1

    def test_the_passage_text_arrives_with_the_second_retrieval(self):
        # Only the label travels between questions. The moment retrieval returns
        # the passage again, the empty restored source is filled in.
        registry = SourceRegistry()
        registry.restore([{"n": 1, "key": "notes#0", "origin": "knowledge_base", "title": "K"}])
        assert registry.sources[0].content == ""
        registry.add_kb(kb_hit())
        assert registry.sources[0].content == "A Kalman filter estimates hidden state."

    def test_restoring_the_same_label_twice_is_harmless(self):
        registry = SourceRegistry()
        entry = {"n": 1, "key": "notes#0", "origin": "knowledge_base", "title": "K"}
        registry.restore([entry, entry])
        assert len(registry) == 1

    def test_a_web_label_can_be_restored_from_its_url_alone(self):
        registry = SourceRegistry()
        registry.restore([{"n": 7, "origin": "web", "url": "https://x", "title": "X"}])
        found = registry.find_web("https://x")
        assert found is not None and found.n == 7

    def test_malformed_entries_are_skipped_not_raised(self):
        # Client-supplied. A bad label should cost a citation, not the answer.
        registry = SourceRegistry()
        registry.restore(
            [
                {"n": 1},                                    # no key
                {"key": "k", "origin": "knowledge_base"},    # no number
                {"n": "two", "key": "k2", "origin": "web", "url": "u"},  # wrong type
                {"n": 3, "key": "k3", "origin": "elsewhere"},  # unknown tier
                {"n": 5, "key": "good", "origin": "knowledge_base"},
            ]
        )
        assert [source.n for source in registry.sources] == [5]

    def test_only_the_most_recent_labels_are_kept(self):
        registry = SourceRegistry()
        registry.restore(
            [
                {"n": i, "key": f"c{i}", "origin": "knowledge_base"}
                for i in range(1, MAX_RESTORED + 20)
            ]
        )
        assert len(registry) == MAX_RESTORED
        # Numbers are never reused, so a citation to a dropped label resolves to
        # nothing -- visible -- rather than to the wrong passage.
        assert registry.add_kb(kb_hit(id="fresh")).n == MAX_RESTORED + 20


class TestSerialisation:
    def test_the_whole_passage_travels_not_a_preview(self):
        # The 400-character cap this replaces was sized for whole documents. A
        # source has been a ~200-token chunk since Phase 4, so the cap was only
        # hiding the end of passages the model had already read.
        passage = "y" * 5000
        assert SourceRegistry().add_kb(kb_hit(content=passage)).as_json()["text"] == passage

    def test_json_carries_what_the_ui_renders(self):
        payload = SourceRegistry().add_kb(kb_hit()).as_json()
        assert payload["n"] == 1
        assert payload["key"] == "notes#0"
        assert payload["origin"] == "knowledge_base"
        assert payload["location"] == "notes.md p.3"
        assert payload["score"] == 0.98
        assert payload["url"] is None

    def test_sources_is_a_copy(self):
        registry = SourceRegistry()
        registry.add_kb(kb_hit())
        registry.sources.clear()
        assert len(registry) == 1
