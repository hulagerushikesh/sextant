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

    @staticmethod
    def _quiet(monkeypatch) -> None:
        """Unset every name the host forwards.

        These tests assert on the *whole* dict the host builds, so any one of
        those names left set in the shell changes the answer. They passed on
        this laptop because none of the cache variables happens to be set here
        -- and HF_HOME is set in our own production image. An assertion whose
        result depends on who runs it is the failure this milestone keeps
        finding, so the environment is made explicit rather than inherited.
        """
        from mcp_server.mcp_host import _FORWARDED_ENV

        for name in _FORWARDED_ENV:
            monkeypatch.delenv(name, raising=False)

    def test_the_launch_parameters_carry_the_override(self, monkeypatch):
        from mcp_server.mcp_host import kb_server

        self._quiet(monkeypatch)
        monkeypatch.setenv(PERSIST_DIR_ENV, "/tmp/somewhere")
        assert kb_server().env == {PERSIST_DIR_ENV: "/tmp/somewhere"}

    def test_no_override_means_no_forced_environment(self, monkeypatch):
        from mcp_server.mcp_host import kb_server

        self._quiet(monkeypatch)
        assert kb_server().env is None

    def test_every_retrieval_knob_crosses_the_process_boundary(self, monkeypatch):
        """A knob the KB reads but the host does not forward is a silent no-op
        in the app while working in every test and CLI.

        This used to name three knobs of the seven while calling itself
        `every`, which is the same kind of claim as a title that outruns its
        assertions. It is driven off the declared list now, so a knob added to
        one place and not the other has somewhere to show up.
        """
        from mcp_server.mcp_host import _FORWARDED_SETTINGS, kb_server
        from tools import settings

        self._quiet(monkeypatch)
        expected = {}
        for i, key in enumerate(_FORWARDED_SETTINGS):
            name = settings.env_name(key)
            value = f"value-{i}"
            monkeypatch.setenv(name, value)
            expected[name] = value

        assert len(expected) == 7, "seven knobs; update this count deliberately"
        assert kb_server().env == expected


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


class TestTheOldEnvironmentPrefixIsLoudNotSilent:
    """The rename kept `AGENTICRAG_*` working as a fallback so the deployed
    box's `.env` would not silently fall back to defaults. The box was
    rewritten onto `SEXTANT_*` on 2026-09-28 and the fallback went with it --
    but the failure it guarded against is still real, so a leftover variable
    now has to announce itself instead of doing nothing."""

    def test_the_old_spelling_is_no_longer_read(self, monkeypatch):
        from tools import settings

        monkeypatch.delenv("SEXTANT_MAX_PER_DOCUMENT", raising=False)
        monkeypatch.setenv("AGENTICRAG_MAX_PER_DOCUMENT", "7")
        assert settings.getenv("MAX_PER_DOCUMENT", "2") == "2"

    def test_a_leftover_variable_is_reported_with_its_new_name(self, monkeypatch):
        from tools import settings

        monkeypatch.setenv("AGENTICRAG_ANN_INDEX", "hnsw")
        warning = settings.legacy_warning()
        assert warning is not None
        assert "AGENTICRAG_ANN_INDEX -> SEXTANT_ANN_INDEX" in warning

    def test_a_clean_environment_says_nothing(self, monkeypatch):
        from tools import settings

        for name in settings.legacy_names():
            monkeypatch.delenv(name, raising=False)
        assert settings.legacy_warning() is None


class TestTheSubprocessGetsTheModelCache:
    """Shipped 2026-09-28 and live until now: the image bakes the embedder and
    the cross-encoder into `HF_HOME=/opt/models` and sets `HF_HUB_OFFLINE=1` so
    that, in the Dockerfile's own words, the first query does not "silently
    download ~180 MB and appear to hang". Both names are set on the *agent
    server*. The models load in the knowledge-base subprocess -- keeping torch
    out of the agent server's import graph is the entire reason the knowledge
    base speaks a protocol -- and MCP's stdio client does not pass this
    process's environment to its child. It builds
    `get_default_environment() | params.env`, and on POSIX that default is
    HOME, LOGNAME, PATH, SHELL, TERM, USER and nothing else.

    So the process that loads the weights resolved
    `$HOME/.cache/huggingface/hub` instead of `/opt/models/hub`, found it
    empty, and downloaded them -- with the offline pin also dropped, so it
    checked the hub for newer weights too -- into a path that dies with the
    container. The baked cache the image pays for was never read.
    """

    def test_the_cache_location_crosses_the_process_boundary(self, monkeypatch):
        from mcp_server.mcp_host import kb_server

        monkeypatch.setenv("HF_HOME", "/opt/models")
        monkeypatch.setenv("HF_HUB_OFFLINE", "1")
        env = kb_server().env or {}
        assert env.get("HF_HOME") == "/opt/models"
        assert env.get("HF_HUB_OFFLINE") == "1"

    def test_the_subprocess_resolves_the_baked_cache(self, monkeypatch):
        """The consequence, not just the mechanism.

        `huggingface_hub` derives its cache from HF_HOME and falls back to
        $HOME. Resolving the same way the child does proves the dropped name
        changes *where the weights are looked for*, which is the failure --
        rather than only proving a dict has a key.
        """
        from mcp.client.stdio import get_default_environment

        from mcp_server.mcp_host import kb_server

        monkeypatch.setenv("HOME", "/home/app")
        monkeypatch.setenv("HF_HOME", "/opt/models")
        # The child's actual environment, assembled MCP's way rather than ours.
        child = get_default_environment() | (kb_server().env or {})

        def hub_cache(env: dict[str, str]) -> str:
            home = env.get("HF_HOME") or f"{env.get('HOME', '')}/.cache/huggingface"
            return f"{home}/hub"

        assert hub_cache(child) == "/opt/models/hub"
        # The failure this replaced, spelled out: with the name dropped the
        # child looks somewhere the image never wrote.
        assert hub_cache({k: v for k, v in child.items() if k != "HF_HOME"}) == (
            "/home/app/.cache/huggingface/hub"
        )
