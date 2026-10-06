"""Trimming a tool result to what the asker may see, and refusing a write
that names a document the asker does not own.

Milestone 20 item 4. Item 2 chose one collection filtered, and the thing that
makes that real is not the retrieval filter -- it is that `kb_list` hands every
tenant's titles, overviews and opening lines to the model in its prompt.

Milestone 21 item 1 closes the two doors that item 4 left open, both of them
defects in item 4's own week: `/ann/compare` never routed through the scope,
and would not have been trimmed if it had, because its ids arrive as mapping
keys and bare strings rather than as a `document_id` field. The class
`TestTheShapesAnIdTakes` is the general rule that replaces the specific fix --
without it this is one patched endpoint and the next shape walks through.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path
from typing import Any

import pytest

from mcp_server.identity import DEFAULT_OWNER
from mcp_server.scope import (
    READ_TOOLS,
    WRITE_TOOLS,
    ForbiddenWrite,
    ScopedHost,
    trim,
)
from mcp_server.uploads import to_document
from tools.vector_db.vector_search import KnowledgeBase

SEARCH: dict[str, Any] = {
    "success": True,
    "results": [
        {"document_id": "kalman", "text": "shared corpus"},
        {"document_id": "upload:ada:notes", "text": "ada's"},
        {"document_id": "upload:grace:notes", "text": "grace's"},
    ],
    "total_found": 3,
    # Same value as the untrimmed list length, and not a count of it.
    "min_score": 3,
    "collection_size": 1660,
}


class TestTrim:
    def test_another_owners_upload_does_not_survive(self):
        kept = trim(SEARCH, "ada")["results"]
        assert [hit["document_id"] for hit in kept] == ["kalman", "upload:ada:notes"]

    def test_the_shared_corpus_belongs_to_everybody(self):
        # An allow-list would hide every document the operator ingested from
        # every user, which is the opposite of what the deployment is for.
        for owner in ("ada", "grace", DEFAULT_OWNER, "nobody-by-that-name"):
            assert "kalman" in [hit["document_id"] for hit in trim(SEARCH, owner)["results"]]

    def test_the_count_follows_the_list_it_counted(self):
        assert trim(SEARCH, "ada")["total_found"] == 2

    def test_an_integer_that_merely_collides_is_left_alone(self):
        # `min_score` is 3 and the list was 3 long. A length-only rule would
        # have rewritten it to 2.
        assert trim(SEARCH, "ada")["min_score"] == 3

    def test_the_shared_fallback_is_scoped_like_anybody_else(self):
        # If it were not, every tenant could read every other tenant's uploads
        # by deleting one header.
        kept = [hit["document_id"] for hit in trim(SEARCH, DEFAULT_OWNER)["results"]]
        assert kept == ["kalman"]

    def test_a_tool_nobody_thought_about_is_covered_too(self):
        # kb_ann_compare's shape: passages nested two levels down, under keys
        # this module has never heard of. Deny by default, or it leaks.
        compare = {
            "indexes": {
                "hnsw": {"hits": [{"document_id": "upload:grace:notes", "text": "grace's"}]},
                "flat": {"hits": [{"document_id": "kalman"}]},
            }
        }
        trimmed = trim(compare, "ada")
        assert trimmed["indexes"]["hnsw"]["hits"] == []
        assert trimmed["indexes"]["flat"]["hits"] == [{"document_id": "kalman"}]

    def test_an_entry_with_no_document_is_not_ours_to_judge(self):
        payload = {"timings": [{"index": "hnsw", "ms": 4}], "count": 1}
        assert trim(payload, "ada") == payload

    def test_nothing_is_mutated_in_place(self):
        before = len(SEARCH["results"])
        trim(SEARCH, "ada")
        assert len(SEARCH["results"]) == before


# What `_ann_compare_sync` actually returns, taken from a live run against a
# three-document store rather than imagined: ids as bare strings in `exact`,
# as an `id` field in each hit, and as the *keys* of `passages`, whose values
# carry the document's title and its opening 200 characters and no id field at
# all. None of these is a list entry with a `document_id`, which is every shape
# 0.8.4 knew about.
COMPARE: dict[str, Any] = {
    "k": 5,
    "exact": ["upload:ada:notes#0", "handbook#1", "upload:grace:secret#0"],
    "results": {
        "hnsw": {
            "hits": [
                {"id": "upload:ada:notes#0", "score": 0.52},
                {"id": "handbook#1", "score": 0.47},
                {"id": "upload:grace:secret#0", "score": -0.10},
            ],
            "missed": ["upload:grace:secret#0"],
            "recall": 0.75,
            "stats": {"name": "hnsw", "vectors": 4, "bytes": 6192},
        }
    },
    "passages": {
        "upload:ada:notes#0": {"title": "Notes", "excerpt": "# Notes\n\nada's own."},
        "handbook#1": {"title": "Handbook", "excerpt": "The handbook."},
        "upload:grace:secret#0": {
            "title": "Grace Secret",
            "excerpt": "# Grace Secret\n\nConfidential salary review notes.",
        },
    },
}


class TestTheShapesAnIdTakes:
    """An id is an id wherever it appears: a field, a key, or a bare string.

    The rule, not the endpoint. `test_nothing_of_the_other_owner_survives_any_of
    _them` is the one that fails if a fourth shape is ever added.
    """

    def test_a_bare_id_in_a_list_is_dropped(self):
        # `exact` is a plain list of chunk ids. The id itself is the leak: it
        # carries the owner's name and the stem of the file they uploaded.
        assert trim(COMPARE, "ada")["exact"] == ["upload:ada:notes#0", "handbook#1"]

    def test_an_entry_identified_by_a_field_called_something_else_is_dropped(self):
        # `id`, not `document_id`. A rule keyed on the field name misses this.
        kept = trim(COMPARE, "ada")["results"]["hnsw"]["hits"]
        assert [hit["id"] for hit in kept] == ["upload:ada:notes#0", "handbook#1"]

    def test_a_mapping_keyed_by_id_loses_the_key_and_its_contents(self):
        passages = trim(COMPARE, "ada")["passages"]
        assert set(passages) == {"upload:ada:notes#0", "handbook#1"}

    def test_nothing_of_the_other_owner_survives_any_of_them(self):
        # The whole payload, serialised. Not "the three shapes I thought of".
        assert "grace" not in json.dumps(trim(COMPARE, "ada"))

    def test_the_other_owner_keeps_their_own_and_loses_ada(self):
        trimmed = trim(COMPARE, "grace")
        assert "ada" not in json.dumps(trimmed)
        assert "upload:grace:secret#0" in trimmed["passages"]

    def test_what_the_index_measures_about_itself_is_left_alone(self):
        # Recall is a property of the index against the whole corpus. Scoring
        # each index against a different subset per visitor measures nothing.
        hnsw = trim(COMPARE, "ada")["results"]["hnsw"]
        assert hnsw["recall"] == 0.75
        assert hnsw["stats"]["vectors"] == 4

    def test_prose_that_merely_mentions_an_id_is_not_an_id(self):
        # The parse is anchored at the start of the string, so a sentence does
        # not become a document. Over-trimming would quietly delete content
        # and look exactly like the feature working.
        payload = {"notes": [{"text": "see upload:grace:secret for the figures"}]}
        assert trim(payload, "ada") == payload

    def test_a_pre_0_8_2_id_still_belongs_to_everybody(self):
        # `upload:<stem>` with no owner segment: the scheme before namespacing.
        payload = {"ids": ["upload:notes", "upload:grace:notes"]}
        assert trim(payload, "ada")["ids"] == ["upload:notes"]


class TestWrites:
    """Re-using an id replaces that document, so a write is a delete first.

    Door two of milestone 21 item 1, reproduced before it was fixed: `ada`
    uploads `notes.md`, `grace` posts `/ingest` with `id: upload:ada:notes`,
    and ada's document now holds grace's text under ada's name, in ada's own
    scoped listing, cited back to her as hers.
    """

    async def test_one_owner_cannot_write_over_anothers_document(self):
        host = ScopedHost(FakeInner({"kb_ingest": {"success": True}}), "grace")
        with pytest.raises(ForbiddenWrite):
            await host.call(
                "kb_ingest", {"documents": [{"id": "upload:ada:notes", "content": "x"}]}
            )

    async def test_the_store_is_never_reached(self):
        # Checked before the call, not after: `_store` clears a document's
        # chunks as the first step of writing it, so a guard on the way out
        # has already deleted what it was protecting.
        inner = FakeInner({"kb_ingest": {"success": True}})
        with pytest.raises(ForbiddenWrite):
            await ScopedHost(inner, "grace").call(
                "kb_ingest", {"documents": [{"id": "upload:ada:notes", "content": "x"}]}
            )
        assert inner.calls == []

    async def test_a_named_user_cannot_write_the_shared_corpus_either(self):
        # Readable by everyone is not writable by everyone. Seeding the shared
        # corpus is `sextant-ingest`, run on the box, with no identity.
        host = ScopedHost(FakeInner({"kb_ingest": {"success": True}}), "ada")
        with pytest.raises(ForbiddenWrite):
            await host.call("kb_ingest", {"documents": [{"id": "handbook", "content": "x"}]})

    async def test_an_id_left_off_is_judged_as_the_one_it_would_get(self):
        # `doc_0`, which is a shared id. Waving it through for being absent
        # would be the same hole with one field deleted.
        host = ScopedHost(FakeInner({"kb_ingest": {"success": True}}), "ada")
        with pytest.raises(ForbiddenWrite):
            await host.call("kb_ingest", {"documents": [{"content": "x"}]})

    async def test_writing_in_your_own_namespace_is_what_upload_does(self):
        host = ScopedHost(FakeInner({"kb_ingest": {"success": True}}), "ada")
        result = await host.call(
            "kb_ingest", {"documents": [{"id": "upload:ada:notes", "content": "x"}]}
        )
        assert result == {"success": True}

    async def test_a_box_with_no_identity_behaves_exactly_as_before(self):
        # curl, the CLI, the eval harness: `shared` owns the shared corpus, so
        # nothing that worked before 0.8.5 stopped working.
        host = ScopedHost(FakeInner({"kb_ingest": {"success": True}}), DEFAULT_OWNER)
        assert await host.call("kb_ingest", {"documents": [{"id": "handbook", "content": "x"}]})

    async def test_a_batch_is_refused_whole(self):
        # One bad id in ten does not get nine documents written and then fail.
        inner = FakeInner({"kb_ingest": {"success": True}})
        with pytest.raises(ForbiddenWrite):
            await ScopedHost(inner, "ada").call(
                "kb_ingest",
                {
                    "documents": [
                        {"id": "upload:ada:one", "content": "mine"},
                        {"id": "upload:grace:two", "content": "hers"},
                    ]
                },
            )
        assert inner.calls == []

    async def test_a_tool_this_module_cannot_classify_is_refused(self):
        # Fail closed. The alternative is that a write tool added next year is
        # unguarded by default and nothing says so.
        host = ScopedHost(FakeInner({"kb_delete_everything": {}}), "ada")
        with pytest.raises(ForbiddenWrite):
            await host.call("kb_delete_everything", {})

    async def test_the_agent_hears_a_refusal_as_a_tool_error_not_a_crash(self):
        # Only READABLE_TOOLS are ever declared, so this means the model named
        # something it was not offered. Telling it so lets the turn finish; a
        # raised exception would 500 a question somebody asked in good faith.
        from mcp_server.agent import _execute
        from mcp_server.sources import SourceRegistry

        host = ScopedHost(FakeInner({}), "ada")
        text, is_error, _ = await _execute("kb_wipe", {}, host, SourceRegistry())
        assert is_error and "kb_wipe" in text

    def test_every_tool_the_server_exposes_is_classified(self):
        # The pin that makes an allow-list honest: adding a tool fails here
        # until somebody decides which half of the boundary it is on.
        from tools.vector_db import server

        exposed = {name for name in dir(server) if name.startswith("kb_")}
        assert exposed == READ_TOOLS | WRITE_TOOLS


class FakeInner:
    """The process-global host, with canned results."""

    def __init__(self, results: dict[str, Any]) -> None:
        self.results = results
        self.calls: list[str] = []
        self.tools = [{"name": "kb_search", "input_schema": {"properties": {"query": {}}}}]
        self.connected = True
        self.error = None

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append(name)
        return self.results[name]


STATS = {"status": "healthy", "documents": 22, "collection_size": 1660, "summaries": 21}
LISTING = {
    "documents": [
        {"document_id": "kalman", "chunks": 4, "overview": "a filter"},
        {"document_id": "upload:ada:notes", "chunks": 2, "overview": None},
        {"document_id": "upload:grace:secret", "chunks": 90, "overview": "grace's"},
    ],
    "count": 3,
}


class TestScopedHost:
    async def test_the_listing_loses_the_other_tenant(self):
        host = ScopedHost(FakeInner({"kb_list": LISTING}), "ada")
        result = await host.call("kb_list", {})
        assert [d["document_id"] for d in result["documents"]] == ["kalman", "upload:ada:notes"]
        assert result["count"] == 2

    async def test_the_statistics_describe_what_this_owner_can_see(self):
        # 4 + 2 chunks, plus the one overview among them. Not 1660.
        host = ScopedHost(FakeInner({"kb_stats": STATS, "kb_list": LISTING}), "ada")
        result = await host.call("kb_stats", {})
        assert result["documents"] == 2
        assert result["collection_size"] == 7
        assert result["summaries"] == 1

    async def test_the_statistics_keep_everything_that_is_not_a_count(self):
        host = ScopedHost(FakeInner({"kb_stats": STATS, "kb_list": LISTING}), "ada")
        assert (await host.call("kb_stats", {}))["status"] == "healthy"

    async def test_a_store_that_cannot_be_listed_reports_no_counts_at_all(self):
        # Rather than falling back to the whole store's, which is the leak.
        host = ScopedHost(FakeInner({"kb_stats": STATS, "kb_list": {"error": "gone"}}), "ada")
        result = await host.call("kb_stats", {})
        assert "collection_size" not in result and "documents" not in result
        assert "summaries" not in result
        assert result["status"] == "healthy"

    async def test_the_schemas_the_model_sees_are_untouched(self):
        inner = FakeInner({})
        assert ScopedHost(inner, "ada").tools is inner.tools


class TestTheInvariant:
    """The corpus is never a tool argument -- milestone 20, not up for measurement.

    Tool schemas are discovered at startup and handed to the model verbatim, so
    a parameter named here is a parameter a sentence inside an uploaded PDF can
    ask the model to set.
    """

    def test_no_tool_lets_its_caller_name_a_corpus(self):
        from tools.vector_db import server

        forbidden = {"owner", "corpus", "tenant", "user", "client", "collection", "namespace"}
        for name in (n for n in dir(server) if n.startswith("kb_")):
            tool = getattr(server, name)
            signature = inspect.signature(getattr(tool, "fn", tool))
            named = set(signature.parameters) & forbidden
            assert not named, f"{name} exposes {named} to the model"


class TestAgainstARealStore:
    """The two halves meeting: ids `to_document` writes, parsed back by `trim`.

    Everything above agrees with itself. This is the only test that would
    notice the id scheme and the filter drifting apart.
    """

    @pytest.fixture
    async def kb(self, store_dir: Path, request: pytest.FixtureRequest):
        name = f"scope-{request.node.name[:40]}".rstrip("._-")
        knowledge_base = KnowledgeBase(collection_name=name)
        yield knowledge_base
        knowledge_base.client.delete_collection(name)

    async def test_each_owner_searches_their_own_uploads_and_the_shared_corpus(self, kb):
        text = b"# Kalman\n\nA Kalman filter estimates hidden state from noisy measurements.\n"
        await kb.add_documents(
            [
                to_document("notes.md", text, owner="ada"),
                to_document("notes.md", text, owner="grace"),
                {"id": "handbook", "content": "The Kalman filter, as the handbook has it."},
            ]
        )
        found = await kb.search("Kalman filter", limit=10, min_score=0.0)
        everyone = {hit["document_id"] for hit in found["results"]}
        assert everyone == {"upload:ada:notes", "upload:grace:notes", "handbook"}

        for owner, theirs in (("ada", "upload:ada:notes"), ("grace", "upload:grace:notes")):
            visible = {hit["document_id"] for hit in trim(found, owner)["results"]}
            assert visible == {theirs, "handbook"}

    async def test_the_index_lab_shows_one_owner_nothing_of_the_others(self, kb):
        # The payload trimmed here is one a real `ann_compare` built over real
        # vectors, not a fixture agreeing with the fixture above it. This is
        # the test that would have failed on 2026-10-06, when asking as `ada`
        # returned grace's title and the opening line of her salary review.
        await kb.add_documents(
            [
                to_document(
                    "notes.md", b"# Notes\n\nA Kalman filter estimates state.\n", owner="ada"
                ),
                to_document(
                    "secret.md",
                    b"# Grace Secret\n\nConfidential salary review notes.\n",
                    owner="grace",
                ),
                {"id": "handbook", "content": "The Kalman filter, as the handbook has it."},
            ]
        )
        whole = await kb.ann_compare("Kalman filter", k=5)
        assert "grace" in json.dumps(whole), "nothing to scope -- the fixture is wrong"
        assert "grace" not in json.dumps(trim(whole, "ada"))
        assert "upload:ada" in json.dumps(trim(whole, "ada"))
