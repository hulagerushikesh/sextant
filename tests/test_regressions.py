"""Named regressions.

Each of these is a bug this codebase actually shipped or nearly shipped. They
are collected here rather than scattered so that the list of things that went
wrong stays visible, and so nobody quietly reintroduces one.
"""

from __future__ import annotations

from typing import Any, cast

import pytest

from tools.vector_db.vector_search import (
    DISTANCE_SPACE,
    PERSIST_DIR_ENV,
    KnowledgeBase,
    KnowledgeBaseUnavailable,
)


class TestScoresMeanWhatTheySay:
    """Phase 2: the collection used l2 distance while the code reported
    `1 - distance` as a cosine similarity. Under l2 that expression is unbounded
    and runs negative, so every score was meaningless and the threshold built on
    top of it silently dropped correct hits."""

    def test_an_l2_collection_is_refused_loudly(self, tmp_path, monkeypatch):
        import chromadb

        store = tmp_path / "legacy"
        client = chromadb.PersistentClient(path=str(store))
        client.get_or_create_collection(
            name="documents", configuration={"hnsw": {"space": "l2"}}
        )
        del client

        monkeypatch.setenv(PERSIST_DIR_ENV, str(store))
        with pytest.raises(KnowledgeBaseUnavailable) as caught:
            KnowledgeBase()

        message = str(caught.value)
        assert "l2" in message
        # The error has to say what to do, not just that something is wrong.
        assert "re-ingest" in message

    def test_a_fresh_collection_is_cosine(self, kb):
        assert kb._configured_space() == DISTANCE_SPACE == "cosine"

    def test_a_store_remembers_its_embedding_model(self, kb):
        # Stamped on first write, so a later process cannot mix vectors from a
        # different model into it. Both MiniLM and bge-small are 384-d, so
        # nothing else would catch that.
        assert kb.collection.metadata["embedding_model"] == kb.embedder.name

    def test_a_store_from_another_model_is_refused(self, tmp_path, monkeypatch):
        import chromadb

        store = tmp_path / "other"
        client = chromadb.PersistentClient(path=str(store))
        collection = client.get_or_create_collection(
            name="documents",
            configuration={"hnsw": {"space": "cosine"}},
            metadata={"embedding_model": "some-other/model"},
        )
        collection.add(ids=["x"], embeddings=cast(Any, [[0.0] * 384]), documents=["x"])
        del client

        monkeypatch.setenv(PERSIST_DIR_ENV, str(store))
        with pytest.raises(KnowledgeBaseUnavailable) as caught:
            KnowledgeBase()
        message = str(caught.value)
        assert "some-other/model" in message and "SEXTANT_EMBEDDER" in message

    def test_a_pre_stamp_store_is_taken_to_be_minilm(self, tmp_path, monkeypatch):
        """Every store that existed before the stamp was built with MiniLM."""
        import chromadb

        from tools.vector_db.embeddings import LOCAL_MODEL

        store = tmp_path / "old"
        client = chromadb.PersistentClient(path=str(store))
        collection = client.get_or_create_collection(
            name="documents", configuration={"hnsw": {"space": "cosine"}}
        )
        collection.add(ids=["x"], embeddings=cast(Any, [[0.0] * 384]), documents=["x"])
        del client

        monkeypatch.setenv(PERSIST_DIR_ENV, str(store))
        kb = KnowledgeBase()
        assert kb.collection.metadata["embedding_model"] == LOCAL_MODEL


class TestTheStoreOverrideReachesTheServer:
    """Phase 5: MCP's stdio client passes only an allowlist of environment
    variables to the subprocess, so the store override was dropped and the
    server opened the default collection. Grading, and any test using an
    isolated store, would silently have read the user's real corpus."""

    async def test_the_subprocess_opens_the_overridden_store(self, tmp_path, monkeypatch):
        from mcp_server.mcp_host import MCPHost

        store = tmp_path / "forwarded"
        monkeypatch.setenv(PERSIST_DIR_ENV, str(store))

        host = MCPHost()
        await host.connect()
        assert host.connected, host.error
        try:
            stats = await host.call("kb_stats", {})
        finally:
            await host.close()

        assert stats["persist_dir"] == str(store)

    def test_the_launch_parameters_carry_the_override(self, monkeypatch):
        from mcp_server.mcp_host import kb_server

        monkeypatch.setenv(PERSIST_DIR_ENV, "/tmp/somewhere")
        assert kb_server().env == {PERSIST_DIR_ENV: "/tmp/somewhere"}

    def test_no_override_means_no_forced_environment(self, monkeypatch):
        from mcp_server.mcp_host import kb_server

        monkeypatch.delenv(PERSIST_DIR_ENV, raising=False)
        assert kb_server().env is None


class TestLongDocumentsAreReachable:
    """Phase 4: documents were stored whole, and the embedder truncates at 256
    word pieces without raising. A 622-token document embedded identically to
    its first 256 tokens, so anything past roughly two paragraphs could not be
    retrieved by any query."""

    async def test_a_fact_at_the_end_of_a_long_document_is_findable(self, kb):
        filler = "The assignment problem pairs workers with tasks at minimum cost. " * 40
        secret = "The mitochondrial transfer coefficient for kryptonite is 4.71 millijoules."
        await kb.add_documents(
            [{"id": "longdoc", "title": "Long", "content": f"{filler}\n\n{secret}"}]
        )

        result = await kb.search(
            "what is the mitochondrial transfer coefficient for kryptonite", limit=5
        )
        assert any("kryptonite" in hit["content"] for hit in result["results"])


class TestTheAgentCannotWrite:
    """Answering a question must never be able to change the corpus it is
    answering from. `kb_ingest` is discovered over MCP and deliberately withheld
    from the model."""

    def test_ingest_is_not_declared_to_the_model(self):
        from mcp_server.agent import READABLE_TOOLS, declare_tools
        from tests.fakes import FakeHost, as_host

        assert "kb_ingest" not in READABLE_TOOLS
        declared = {tool.get("name") for tool in declare_tools(as_host(FakeHost()))}
        assert "kb_ingest" not in declared
