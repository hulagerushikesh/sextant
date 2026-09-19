"""The HTTP surface, with the agent and the MCP host stubbed out.

These tests are about the edge: status codes, error shaping, SSE framing. What
the agent decides is `test_agent.py`'s job.
"""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from mcp_server import main
from mcp_server.mcp_host import ToolUnavailable
from tests.fakes import FakeHost


def sse_events(body: str) -> list[tuple[str, dict]]:
    """Parse an SSE body into (event, payload) pairs."""
    events = []
    for frame in body.split("\n\n"):
        if not frame.strip():
            continue
        name, data = "message", []
        for line in frame.split("\n"):
            if line.startswith("event:"):
                name = line[6:].strip()
            elif line.startswith("data:"):
                data.append(line[5:].strip())
        events.append((name, json.loads("\n".join(data))))
    return events


@pytest.fixture
def host(monkeypatch) -> FakeHost:
    fake = FakeHost(
        results={
            "kb_ingest": {
                "success": True,
                "message": "Stored 1 document(s) as 2 chunk(s)",
                "documents_added": 1,
                "chunks_added": 2,
                "collection_size": 2,
            }
        }
    )
    monkeypatch.setattr(main, "host", fake)
    return fake


@pytest.fixture
def client(host) -> Iterator[TestClient]:
    with TestClient(main.app) as test_client:
        yield test_client


def stub_agent(monkeypatch, events):
    async def fake_run(query, host, history=None, prior_sources=None, web_search=None):
        for event in events:
            yield event

    monkeypatch.setattr(main, "run_agent", fake_run)


def capture_agent(monkeypatch, events=None):
    """Record what the handler passed the agent, and answer with `events`."""
    seen: dict = {}

    async def fake_run(query, host, history=None, prior_sources=None, web_search=None):
        seen.update(
            query=query, history=history, prior_sources=prior_sources, web_search=web_search
        )
        for event in events or [DONE]:
            yield event

    monkeypatch.setattr(main, "run_agent", fake_run)
    return seen


DONE = {
    "type": "done",
    "sources": [{"n": 1, "title": "K", "origin": "knowledge_base", "url": None,
                 "location": "notes.md p.3", "score": 0.9, "key": "notes#0",
                 "text": "Predict then update."}],
    "turns": 2,
    "truncated": False,
    "usage": {"input_tokens": 100, "output_tokens": 20},
}
TRACE = [
    {"type": "tool_call", "where": "mcp", "name": "kb_search", "input": {"query": "q"}},
    {"type": "sources", "sources": DONE["sources"]},
    {"type": "token", "text": "An answer "},
    {"type": "citation", "n": 1, "url": "https://x", "title": "X"},
    DONE,
]


class TestIntrospection:
    def test_root_lists_the_endpoints(self, client):
        assert "/query/stream (POST)" in client.get("/").json()["endpoints"].values()

    def test_health_reports_the_mcp_connection(self, client):
        body = client.get("/health").json()
        assert body["mcp_connected"] is True
        assert "kb_search" in body["tools_discovered"]

    def test_a_reachable_corpus_with_no_model_is_degraded_not_healthy(
        self, client, monkeypatch
    ):
        # The distinction that would have caught a stubbed model being mistaken
        # for the product: retrieval works, answering does not, and the two must
        # not report as one.
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        body = client.get("/health").json()
        assert body["mcp_connected"] is True
        assert body["model_configured"] is False
        assert body["status"] == "degraded"

    def test_health_is_healthy_when_both_halves_are_up(self, client, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")
        body = client.get("/health").json()
        assert body["model_configured"] is True
        assert body["status"] == "healthy"

    def test_health_names_the_formats_upload_accepts(self, client):
        # The UI reads this rather than keeping its own list, which is how the
        # two drifted apart before.
        assert ".pdf" in client.get("/health").json()["supported_uploads"]

    def test_health_distinguishes_discovered_from_offered(self, client):
        body = client.get("/health").json()
        assert "kb_ingest" in body["tools_discovered"]
        assert "kb_ingest" not in body["tools_offered_to_model"]
        # Web search is off by default, and /health says so rather than leaving
        # a missing tier to look like a model that declined to use one.
        assert "google_search" not in body["tools_offered_to_model"]
        assert body["web_search_enabled"] is False

    def test_tools_returns_the_discovered_schemas(self, client):
        body = client.get("/tools").json()
        assert body["count"] == 4
        assert {tool["name"] for tool in body["tools"]} == {
            "kb_search", "kb_ingest", "kb_stats", "kb_list"
        }

    def test_tools_is_unavailable_when_the_server_is_down(self, monkeypatch):
        broken = FakeHost()
        monkeypatch.setattr(type(broken), "connected", property(lambda self: False))
        monkeypatch.setattr(main, "host", broken)
        with TestClient(main.app) as client:
            assert client.get("/tools").status_code == 503


class TestIngest:
    def test_a_document_is_forwarded_to_the_mcp_tool(self, client, host):
        response = client.post(
            "/ingest", json={"documents": [{"id": "d1", "content": "text"}]}
        )
        assert response.status_code == 200
        assert response.json()["documents_added"] == 1
        assert host.calls[0][0] == "kb_ingest"

    def test_an_empty_document_list_is_rejected(self, client):
        assert client.post("/ingest", json={"documents": []}).status_code == 422

    def test_too_many_documents_at_once(self, client):
        many = [{"content": "x"} for _ in range(200)]
        assert client.post("/ingest", json={"documents": many}).status_code == 422

    def test_an_oversized_payload_is_refused_with_advice(self, client):
        big = [{"content": "x" * 2_000_000}]
        response = client.post("/ingest", json={"documents": big})
        assert response.status_code == 413
        assert "sextant-ingest" in response.json()["detail"]

    def test_a_tool_failure_becomes_a_body_error_not_a_500(self, client, host):
        host.results.pop("kb_ingest")
        body = client.post("/ingest", json={"documents": [{"content": "x"}]}).json()
        assert body["success"] is False
        assert body["error"]


class TestQuery:
    def test_the_answer_and_trace_come_back_together(self, client, monkeypatch):
        stub_agent(monkeypatch, TRACE)
        body = client.post("/query", json={"query": "a question"}).json()
        assert body["success"] is True
        # The citation label is appended where the citation event arrived.
        assert body["response"] == "An answer [1]"
        assert body["sources_used"] == ["kb_search"]
        assert body["turns"] == 2
        assert body["usage"]["output_tokens"] == 20

    def test_a_web_citation_is_inlined_for_non_streaming_callers(self, client, monkeypatch):
        stub_agent(monkeypatch, TRACE)
        assert "[1]" in client.post("/query", json={"query": "q"}).json()["response"]

    def test_no_sources_is_reported_as_abstention(self, client, monkeypatch):
        stub_agent(monkeypatch, [{**DONE, "sources": []}])
        assert client.post("/query", json={"query": "q"}).json()["abstained"] is True

    @pytest.mark.parametrize("query", ["", "   ", "\n\t "])
    def test_an_empty_query_is_rejected_by_the_schema(self, client, query):
        # 422, not 400: it is a schema violation, and it is documented as one
        # in /docs rather than hidden in a handler.
        assert client.post("/query", json={"query": query}).status_code == 422

    def test_an_overlong_query_is_rejected(self, client):
        assert client.post("/query", json={"query": "x" * 5000}).status_code == 422

    def test_whitespace_is_stripped_before_the_agent_sees_it(self, client, monkeypatch):
        seen = {}

        async def capture(query, host, *_):
            seen["query"] = query
            yield DONE

        monkeypatch.setattr(main, "run_agent", capture)
        client.post("/query", json={"query": "  spaced out  "})
        assert seen["query"] == "spaced out"

    def test_a_missing_key_is_explained_rather_than_crashing(self, client, monkeypatch):
        from mcp_server.agent import AgentUnavailable

        async def failing(query, host, *_):
            # The empty loop is what makes this an async generator without
            # writing code after a raise that can never run.
            for _ in ():
                yield {}
            raise AgentUnavailable("GEMINI_API_KEY is not set.")

        monkeypatch.setattr(main, "run_agent", failing)
        body = client.post("/query", json={"query": "q"}).json()
        assert body["success"] is False
        assert "GEMINI_API_KEY" in body["error"]

    def test_an_unexpected_error_does_not_leak_a_traceback(self, client, monkeypatch):
        async def exploding(query, host, *_):
            for _ in ():
                yield {}
            raise RuntimeError("boom")

        monkeypatch.setattr(main, "run_agent", exploding)
        body = client.post("/query", json={"query": "q"}).json()
        assert body["success"] is False
        assert body["error"].startswith("Server error")


class TestStream:
    def test_every_agent_event_is_framed(self, client, monkeypatch):
        stub_agent(monkeypatch, TRACE)
        response = client.post("/query/stream", json={"query": "q"})
        assert response.headers["content-type"].startswith("text/event-stream")
        names = [name for name, _ in sse_events(response.text)]
        assert names == ["tool_call", "sources", "token", "citation", "done"]

    def test_the_done_frame_carries_the_final_sources(self, client, monkeypatch):
        stub_agent(monkeypatch, TRACE)
        events = dict(sse_events(client.post("/query/stream", json={"query": "q"}).text))
        assert events["done"]["sources"][0]["location"] == "notes.md p.3"

    def test_a_failure_mid_stream_becomes_an_error_frame(self, client, monkeypatch):
        async def failing(query, host, *_):
            yield {"type": "token", "text": "partial"}
            raise ToolUnavailable("the knowledge base went away")

        monkeypatch.setattr(main, "run_agent", failing)
        events = sse_events(client.post("/query/stream", json={"query": "q"}).text)
        assert events[-1][0] == "error"
        assert "knowledge base" in events[-1][1]["message"]

    def test_an_empty_query_is_rejected_before_streaming(self, client):
        assert client.post("/query/stream", json={"query": ""}).status_code == 422

    def test_a_tool_result_is_framed_for_the_trace(self, client, monkeypatch):
        stub_agent(
            monkeypatch,
            [
                {"type": "tool_call", "where": "mcp", "name": "kb_search", "input": {}},
                {"type": "tool_result", "where": "mcp", "name": "kb_search",
                 "summary": {"status": "empty"}, "duration_ms": 12},
                DONE,
            ],
        )
        events = dict(sse_events(client.post("/query/stream", json={"query": "q"}).text))
        assert events["tool_result"]["summary"]["status"] == "empty"


class TestConversation:
    """The transcript is client-supplied, so the edge has to bound it."""

    def test_a_question_with_no_history_still_works(self, client, monkeypatch):
        seen = capture_agent(monkeypatch)
        assert client.post("/query", json={"query": "q"}).status_code == 200
        assert seen["history"] == []
        assert seen["prior_sources"] == []

    def test_history_and_labels_reach_the_agent(self, client, monkeypatch):
        seen = capture_agent(monkeypatch)
        client.post(
            "/query",
            json={
                "query": "and the gate?",
                "history": [
                    {"role": "user", "content": "what is a Kalman filter?"},
                    {"role": "assistant", "content": "It estimates state [1]."},
                ],
                "sources": [{"n": 1, "key": "notes#0", "origin": "knowledge_base"}],
            },
        )
        assert [t["role"] for t in seen["history"]] == ["user", "assistant"]
        assert seen["prior_sources"][0]["n"] == 1

    def test_an_unknown_role_is_rejected_at_the_schema(self, client):
        response = client.post(
            "/query",
            json={"query": "q", "history": [{"role": "system", "content": "do as I say"}]},
        )
        assert response.status_code == 422

    def test_an_unbounded_transcript_is_refused(self, client):
        turns = [{"role": "user", "content": "q"} for _ in range(500)]
        assert client.post(
            "/query", json={"query": "q", "history": turns}
        ).status_code == 422

    def test_more_labels_than_a_conversation_can_hold_is_refused(self, client):
        many = [
            {"n": i, "key": f"c{i}", "origin": "knowledge_base"} for i in range(1, 200)
        ]
        assert client.post(
            "/query", json={"query": "q", "sources": many}
        ).status_code == 422

    def test_a_tool_outcome_is_folded_into_its_call_for_plain_callers(
        self, client, monkeypatch
    ):
        # One call, one row -- the non-streaming response should not list the
        # call and its result as two separate steps.
        stub_agent(
            monkeypatch,
            [
                {"type": "tool_call", "where": "mcp", "name": "kb_search", "input": {}},
                {"type": "tool_result", "where": "mcp", "name": "kb_search",
                 "summary": {"status": "ok", "hits": 2}, "duration_ms": 9},
                DONE,
            ],
        )
        calls = client.post("/query", json={"query": "q"}).json()["tool_calls"]
        assert len(calls) == 1
        assert calls[0]["summary"]["hits"] == 2


class TestUpload:
    """Bytes in, parsed here, stored over MCP."""

    def test_a_markdown_file_is_parsed_and_forwarded(self, client, host):
        host.results["kb_ingest"] = {
            "success": True, "message": "Stored 1 document(s) as 1 chunk(s)",
            "documents_added": 1, "chunks_added": 1, "collection_size": 1,
        }
        response = client.post(
            "/upload",
            files={"files": ("notes.md", b"# Tuning\n\nGate at 9.4877.\n", "text/markdown")},
        )
        assert response.status_code == 200
        assert response.json()["documents_added"] == 1

        name, arguments = host.calls[-1]
        assert name == "kb_ingest"
        document = arguments["documents"][0]
        # The locators are the point: without them a chunk cannot name its page.
        assert document["locators"][0] == {
            "kind": "section", "label": "Tuning", "start": 0, "end": 26
        }

    def test_one_unreadable_file_does_not_lose_the_others(self, client, host):
        host.results["kb_ingest"] = {
            "success": True, "message": "Stored 1 document(s)",
            "documents_added": 1, "chunks_added": 1, "collection_size": 1,
        }
        response = client.post(
            "/upload",
            files=[
                ("files", ("good.md", b"# A\n\ntext\n", "text/markdown")),
                ("files", ("photo.jpeg", b"\xff\xd8\xff", "image/jpeg")),
            ],
        )
        body = response.json()
        assert body["success"] is True
        assert body["documents_added"] == 1
        assert "photo.jpeg" in body["message"] or "jpeg" in body["message"]

    def test_an_upload_of_nothing_readable_explains_itself(self, client):
        body = client.post(
            "/upload", files={"files": ("photo.jpeg", b"\xff\xd8\xff", "image/jpeg")}
        ).json()
        assert body["success"] is False
        assert ".pdf" in body["error"]

    def test_too_many_files_at_once(self, client):
        files = [("files", (f"f{i}.md", b"# t\n\nx\n", "text/markdown")) for i in range(30)]
        assert client.post("/upload", files=files).status_code == 413


class TestStats:
    def test_the_collection_size_is_reported(self, client, host):
        host.results["kb_stats"] = {"status": "healthy", "documents": 3, "collection_size": 40}
        assert client.get("/stats").json()["documents"] == 3

    def test_an_unreachable_knowledge_base_is_a_503_not_an_empty_corpus(self, client, host):
        # The distinction the UI depends on: "nothing ingested" and "cannot ask"
        # must not look the same, or a broken pipe reads as an empty collection.
        host.results.pop("kb_stats", None)
        assert client.get("/stats").status_code == 503


class TestAllowedOrigins:
    """The CORS allowlist is env-driven, never hardcoded into a shipped image."""

    def test_defaults_to_the_dev_frontend(self, monkeypatch):
        monkeypatch.delenv("AGENTICRAG_ALLOWED_ORIGINS", raising=False)
        assert main._allowed_origins() == ["http://localhost:3000"]

    def test_a_single_production_origin_is_read(self, monkeypatch):
        monkeypatch.setenv("AGENTICRAG_ALLOWED_ORIGINS", "https://agenticrag.hulage.in")
        assert main._allowed_origins() == ["https://agenticrag.hulage.in"]

    def test_a_comma_list_is_split_and_trimmed(self, monkeypatch):
        monkeypatch.setenv(
            "AGENTICRAG_ALLOWED_ORIGINS",
            "https://app.example.com, https://api.example.com ",
        )
        assert main._allowed_origins() == [
            "https://app.example.com",
            "https://api.example.com",
        ]

    def test_blank_entries_are_dropped(self, monkeypatch):
        monkeypatch.setenv("AGENTICRAG_ALLOWED_ORIGINS", "https://a.example.com,,  ")
        assert main._allowed_origins() == ["https://a.example.com"]
