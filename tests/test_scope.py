"""Trimming a tool result to what the asker may see.

Milestone 20 item 4. Item 2 chose one collection filtered, and the thing that
makes that real is not the retrieval filter -- it is that `kb_list` hands every
tenant's titles, overviews and opening lines to the model in its prompt.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from mcp_server.identity import DEFAULT_OWNER
from mcp_server.scope import ScopedHost, trim
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
