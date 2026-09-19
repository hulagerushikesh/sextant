"""The agent loop, driven by scripted model turns.

Everything except the model is real: tool declaration, MCP dispatch, the source
registry, citation placement, the turn cap and history replay.
"""

from __future__ import annotations

import pytest
from google.genai import types

from mcp_server import agent
from tests.fakes import (
    FakeGemini,
    FakeHost,
    as_host,
    call_chunk,
    final_chunk,
    grounding,
    hit,
    kb_result,
    text_chunk,
)


async def collect(
    query: str, host, turns, history=None, prior_sources=None
) -> tuple[list[dict], FakeGemini]:
    client = FakeGemini(turns)
    agent._client = lambda: client
    events = [event async for event in agent.run(query, host, history, prior_sources)]
    return events, client


def answer_turn(text: str = "An answer [1].", **final):
    return [text_chunk(text), final_chunk(**final)]


def search_turn(query: str = "a question"):
    return [call_chunk("kb_search", {"query": query}), final_chunk(output_tokens=10)]


@pytest.fixture
def host() -> FakeHost:
    return FakeHost(
        results={
            "kb_search": kb_result(
                hit("notes#0", "Kalman Filter", "Predict then update.", page=3),
                hit("notes#1", "Hungarian", "Cubic time.", page=7, score=0.02),
            )
        }
    )


class TestToolDeclaration:
    def test_web_search_is_withheld_unless_asked_for(self, host):
        # The expensive tier is opt-in: off by default, still fully wired.
        assert "google_search" not in {t["name"] for t in agent.declare_tools(as_host(host))}

    def test_web_search_is_declared_when_switched_on(self, host):
        declared = agent.declare_tools(as_host(host), web_search=True)
        assert [t["name"] for t in declared][-1] == "google_search"

    def test_the_environment_sets_the_default(self, host, monkeypatch):
        monkeypatch.setenv(agent.WEB_SEARCH_ENV, "on")
        assert "google_search" in {t["name"] for t in agent.declare_tools(as_host(host))}
        # An explicit request still wins over the server default, both ways.
        assert "google_search" not in {
            t["name"] for t in agent.declare_tools(as_host(host), web_search=False)
        }

    def test_ingest_is_withheld_from_the_model(self, host):
        # Answering a question must not be able to write to the corpus.
        assert "kb_ingest" in {tool["name"] for tool in host.tools}
        assert "kb_ingest" not in {t["name"] for t in agent.declare_tools(as_host(host))}

    def test_the_listing_tool_is_offered(self, host):
        # "What do my documents cover?" is answered from a listing, not a
        # search; the model can only choose the listing if it is declared.
        assert "kb_list" in {t["name"] for t in agent.declare_tools(as_host(host))}

    def test_schemas_pass_through_unchanged(self, host):
        declared = {t["name"]: t for t in agent.declare_tools(as_host(host))}
        assert declared["kb_search"]["description"] == "kb_search description"

    def test_a_disconnected_knowledge_base_still_leaves_web_search(self):
        tools = agent.declare_tools(as_host(FakeHost(tools=[])), web_search=True)
        assert [t["name"] for t in tools] == ["google_search"]

    def test_nothing_is_offered_when_both_tiers_are_gone(self):
        # Neither a corpus nor the web: the prompt has to say so, because a
        # model with no tools will otherwise answer from memory.
        assert agent.declare_tools(as_host(FakeHost(tools=[])), web_search=False) == []

    def test_the_mcp_schema_is_handed_over_verbatim(self, host):
        # `parameters_json_schema` takes JSON Schema as-is, so no translation
        # layer stands between the MCP server's contract and the model's.
        tools, config = agent._tool_config(agent.declare_tools(as_host(host)))
        declaration = tools[0].function_declarations[0]
        assert declaration.parameters_json_schema == host.tools[0]["input_schema"]

    def test_built_in_and_declared_tools_are_allowed_to_coexist(self, host):
        # Without this flag the API rejects the request outright with a 400.
        tools, config = agent._tool_config(agent.declare_tools(as_host(host), web_search=True))
        assert config.include_server_side_tool_invocations is True
        assert any(tool.google_search is not None for tool in tools)

    def test_the_built_in_tool_is_absent_when_web_search_is_off(self, host):
        # Declared and built-in are gated by one decision, not two: whatever
        # `declare_tools` withheld must not reappear in the SDK objects.
        tools, _ = agent._tool_config(agent.declare_tools(as_host(host), web_search=False))
        assert all(tool.google_search is None for tool in tools)


class TestLoop:
    async def test_a_tool_call_reaches_the_mcp_host(self, host):
        await collect("q", host, [search_turn("state estimation"), answer_turn()])
        assert host.calls[0][0] == "kb_search"
        assert host.calls[0][1]["query"] == "state estimation"

    async def test_events_arrive_in_order(self, host):
        events, _ = await collect("q", host, [search_turn(), answer_turn()])
        kinds = [event["type"] for event in events]
        assert kinds == ["tool_call", "tool_result", "sources", "token", "done"]

    async def test_the_result_the_model_sees_is_numbered(self, host):
        _, client = await collect("q", host, [search_turn(), answer_turn()])
        responses = [
            part.function_response
            for content in client.models.requests[1]["contents"]
            for part in (content.parts or [])
            if part.function_response is not None
        ]
        assert len(responses) == 1
        assert responses[0].response["result"].startswith("[1] Kalman Filter (notes.md p.3)")
        assert "cross-encoder score" in responses[0].response["result"]

    async def test_a_tool_result_is_an_object_not_a_bare_string(self, host):
        # The API rejects a scalar function response, and `error` travelling
        # alongside is what lets the model tell a failure from an empty result.
        _, client = await collect("q", host, [search_turn(), answer_turn()])
        response = next(
            part.function_response
            for content in client.models.requests[1]["contents"]
            for part in (content.parts or [])
            if part.function_response is not None
        )
        assert set(response.response) == {"result", "error"}

    async def test_sources_reach_the_done_event(self, host):
        events, _ = await collect("q", host, [search_turn(), answer_turn()])
        assert [s["title"] for s in events[-1]["sources"]] == ["Kalman Filter", "Hungarian"]

    async def test_usage_accumulates_across_turns(self, host):
        events, _ = await collect(
            "q", host, [search_turn(), answer_turn(output_tokens=25)]
        )
        assert events[-1]["usage"]["output_tokens"] == 35

    async def test_thinking_tokens_are_billed_as_output(self, host):
        # They are, and leaving them out understates a six-turn loop badly.
        events, _ = await collect(
            "q", host, [answer_turn(output_tokens=20, thinking_tokens=180)]
        )
        assert events[-1]["usage"]["output_tokens"] == 200

    async def test_an_answer_with_no_tool_call_still_completes(self, host):
        events, _ = await collect("q", host, [answer_turn()])
        assert events[-1]["turns"] == 1
        assert events[-1]["truncated"] is False
        assert events[-1]["sources"] == []

    async def test_thinking_parts_are_not_streamed_to_the_browser(self, host):
        events, _ = await collect(
            "q",
            host,
            [[text_chunk("reasoning…", thought=True), text_chunk("The answer."), final_chunk()]],
        )
        assert [e["text"] for e in events if e["type"] == "token"] == ["The answer."]

    async def test_the_model_turn_is_echoed_back_with_its_thought_signature(self, host):
        # Gemini 3 attaches a signature to the parts it returns and expects it
        # back. Rebuilding parts by hand drops it and loses the model's context.
        _, client = await collect("q", host, [search_turn(), answer_turn()])
        model_turn = next(
            content
            for content in client.models.requests[1]["contents"]
            if content.role == "model"
        )
        assert model_turn.parts[0].thought_signature == b"sig"


def list_turn():
    return [call_chunk("kb_list", {}), final_chunk(output_tokens=10)]


def tool_text(client: FakeGemini) -> str:
    """What the model was handed back after its first tool call."""
    return client.models.requests[1]["contents"][-1].parts[0].function_response.response["result"]


class TestListing:
    """`kb_list` reaches the model as prose, one block per document."""

    async def test_documents_are_rendered_with_overview_or_lead(self, host):
        host.results["kb_list"] = {
            "count": 2,
            "documents": [
                {"title": "Kalman Filter", "category": "notes", "chunks": 3, "pages": None,
                 "overview": "Explains predict and update.", "lead": "# Kalman Filter"},
                {"title": "Survey", "category": "papers", "chunks": 1600, "pages": 144,
                 "overview": None, "lead": "A Survey of Large Language Models"},
            ],
        }
        _, client = await collect("What do my documents cover?", host, [list_turn(), answer_turn()])
        sent = tool_text(client)
        assert sent.startswith("2 document(s):")
        assert "- Kalman Filter [notes; 3 chunk(s)]\n  Explains predict and update." in sent
        assert "- Survey [papers; 144 page(s), 1600 chunk(s)]\n  A Survey of Large" in sent

    async def test_an_empty_collection_says_so(self, host):
        host.results["kb_list"] = {"count": 0, "documents": []}
        _, client = await collect("q", host, [list_turn(), answer_turn()])
        assert "empty" in tool_text(client)

    async def test_the_trace_reports_the_document_count(self, host):
        host.results["kb_list"] = {"count": 2, "documents": [{}, {}]}
        events, _ = await collect("q", host, [list_turn(), answer_turn()])
        result = next(e for e in events if e["type"] == "tool_result")
        assert result["summary"] == {"status": "ok", "documents": 2}


class TestTrace:
    """Each call now reports what came back. See `Trace.jsx` for why."""

    async def test_a_search_reports_its_hit_count_and_top_score(self, host):
        events, _ = await collect("q", host, [search_turn(), answer_turn()])
        result = next(e for e in events if e["type"] == "tool_result")
        assert result["summary"] == {
            "status": "ok", "hits": 2, "scored_by": "cross-encoder", "top_score": 0.99
        }
        assert result["duration_ms"] >= 0

    async def test_an_empty_search_is_labelled_empty_not_ok(self, host):
        # The distinction the old trace could not draw: this row is why the
        # model searches again, and it should not look like a successful call.
        host.results["kb_search"] = {
            "success": True, "results": [], "total_found": 0, "collection_size": 12,
        }
        events, _ = await collect("q", host, [search_turn(), answer_turn()])
        result = next(e for e in events if e["type"] == "tool_result")
        assert result["summary"]["status"] == "empty"

    async def test_a_failing_tool_reports_the_failure(self):
        events, _ = await collect("q", FakeHost(results={}), [search_turn(), answer_turn()])
        result = next(e for e in events if e["type"] == "tool_result")
        assert result["summary"]["status"] == "error"

    async def test_a_multi_hop_answer_shows_both_searches(self, host):
        events, _ = await collect(
            "q", host, [search_turn("first phrasing"), search_turn("second"), answer_turn()]
        )
        assert len([e for e in events if e["type"] == "tool_result"]) == 2


class TestWebTier:
    async def test_web_results_are_registered_as_numbered_sources(self, host):
        events, _ = await collect(
            "q",
            host,
            [[
                text_chunk("An answer."),
                final_chunk(grounding=grounding(("wikipedia.org", "https://redirect/1"))),
            ]],
        )
        source = events[-1]["sources"][0]
        assert source["origin"] == "web"
        assert source["title"] == "wikipedia.org"
        assert source["url"] == "https://redirect/1"

    async def test_the_search_appears_in_the_trace_despite_running_server_side(self, host):
        # There is no function call to hang a row on; the queries Gemini chose
        # are the only evidence the web tier ran at all.
        events, _ = await collect(
            "q",
            host,
            [[
                text_chunk("An answer."),
                final_chunk(grounding=grounding(("a.com", "https://r/1"), queries=["who won"])),
            ]],
        )
        call = next(e for e in events if e["type"] == "tool_call")
        assert call["where"] == "google"
        assert call["input"]["query"] == "who won"
        assert next(e for e in events if e["type"] == "tool_result")["where"] == "google"

    async def test_a_grounded_answer_is_relabelled_when_the_turn_ends(self, host):
        # Gemini attributes spans over finished text, so labels cannot be
        # streamed inline the way Anthropic's citation events allowed.
        events, _ = await collect(
            "q",
            host,
            [[
                text_chunk("Bormio hosted it."),
                final_chunk(
                    grounding=grounding(
                        ("a.com", "https://r/1"), supports=[(17, [0])]
                    )
                ),
            ]],
        )
        assert next(e for e in events if e["type"] == "answer")["text"] == "Bormio hosted it.[1]"

    async def test_labels_are_placed_by_byte_offset_not_character_offset(self, host):
        # The bug this pins: an em dash is three bytes and one character, so a
        # character-indexed insert lands two places early -- and only ever on
        # answers containing non-ASCII, which is the worst way to find out.
        text = "Bormio—Italy hosted it."
        end = len(text.encode("utf-8"))
        events, _ = await collect(
            "q",
            host,
            [[
                text_chunk(text),
                final_chunk(grounding=grounding(("a.com", "https://r/1"), supports=[(end, [0])])),
            ]],
        )
        assert next(e for e in events if e["type"] == "answer")["text"] == text + "[1]"

    async def test_one_span_citing_two_results_gets_both_labels(self, host):
        events, _ = await collect(
            "q",
            host,
            [[
                text_chunk("Two sources agree."),
                final_chunk(
                    grounding=grounding(
                        ("a.com", "https://r/1"),
                        ("b.com", "https://r/2"),
                        supports=[(18, [0, 1])],
                    )
                ),
            ]],
        )
        assert next(e for e in events if e["type"] == "answer")["text"].endswith("[1][2]")

    async def test_grounding_with_no_spans_leaves_the_text_alone(self, host):
        # Sources still register; there is simply nowhere honest to put a label.
        events, _ = await collect(
            "q",
            host,
            [[text_chunk("An answer."), final_chunk(grounding=grounding(("a.com", "https://r/1")))]],
        )
        assert not [e for e in events if e["type"] == "answer"]
        assert len(events[-1]["sources"]) == 1

    async def test_a_grounded_request_is_priced_as_well_as_its_tokens(self, host):
        # Google bills search per request, outside the token budget.
        events, _ = await collect(
            "q",
            host,
            [[text_chunk("An answer."), final_chunk(grounding=grounding(("a.com", "https://r/1")))]],
        )
        assert events[-1]["usage"]["grounded_requests"] == 1
        assert events[-1]["usage"]["cost_usd"] > 0.014

    async def test_both_tiers_share_one_numbered_list(self, host):
        events, _ = await collect(
            "q",
            host,
            [
                search_turn(),
                [text_chunk("An answer."),
                 final_chunk(grounding=grounding(("a.com", "https://r/1")))],
            ],
        )
        origins = [s["origin"] for s in events[-1]["sources"]]
        assert origins == ["knowledge_base", "knowledge_base", "web"]


class TestConversation:
    async def test_earlier_turns_precede_the_question(self, host):
        history = [
            {"role": "user", "content": "what is a Kalman filter?"},
            {"role": "assistant", "content": "It estimates hidden state [1]."},
        ]
        _, client = await collect("and the gate?", host, [answer_turn()], history=history)
        sent = client.models.requests[0]["contents"]
        # "assistant" is Anthropic's word for it; Gemini calls the role "model".
        assert [c.role for c in sent] == ["user", "model", "user"]
        assert sent[-1].parts[0].text == "and the gate?"

    async def test_a_single_shot_question_is_unchanged(self, host):
        _, client = await collect("q", host, [answer_turn()])
        sent = client.models.requests[0]["contents"]
        assert len(sent) == 1 and sent[0].parts[0].text == "q"

    async def test_labels_from_an_earlier_turn_are_not_reused(self, host):
        prior = [{"n": 1, "key": "old#0", "origin": "knowledge_base", "title": "Old"}]
        events, _ = await collect(
            "q", host, [search_turn(), answer_turn()], prior_sources=prior
        )
        assert [s["n"] for s in events[-1]["sources"]] == [1, 2, 3]

    async def test_restored_labels_alone_do_not_look_like_new_sources(self, host):
        # Otherwise the first frame of a follow-up would announce sources the
        # client handed us a moment earlier.
        prior = [{"n": 1, "key": "old#0", "origin": "knowledge_base", "title": "Old"}]
        events, _ = await collect("q", host, [answer_turn()], prior_sources=prior)
        assert [e for e in events if e["type"] == "sources"] == []

    async def test_a_passage_cited_last_turn_keeps_its_number(self, host):
        prior = [
            {"n": 5, "key": "notes#0", "origin": "knowledge_base", "title": "Kalman Filter"}
        ]
        events, _ = await collect(
            "q", host, [search_turn(), answer_turn()], prior_sources=prior
        )
        by_key = {source["key"]: source for source in events[-1]["sources"]}
        assert by_key["notes#0"]["n"] == 5
        assert by_key["notes#0"]["text"] == "Predict then update."
        assert by_key["notes#1"]["n"] == 6

    async def test_the_prompt_tells_the_model_labels_persist(self):
        assert "stable for the whole conversation" in agent.SYSTEM_PROMPT


class TestSafetyRails:
    async def test_the_turn_cap_stops_a_model_that_never_finishes(self, host):
        events, client = await collect(
            "q", host, [search_turn() for _ in range(agent.MAX_TURNS + 5)]
        )
        assert events[-1]["turns"] == agent.MAX_TURNS
        assert events[-1]["truncated"] is True
        assert len(client.models.requests) == agent.MAX_TURNS

    async def test_the_last_permitted_turn_is_told_it_is_the_last(self, host):
        # Otherwise a model still searching at the cap ends with calls and no
        # text, and the user sees an empty answer.
        _, client = await collect("q", host, [search_turn() for _ in range(agent.MAX_TURNS)])
        last = client.models.requests[-1]["contents"]
        assert last[-1].role == "user"
        assert last[-1].parts[0].text == agent.LAST_TURN_NOTE
        assert last[-2].parts[0].function_response is not None
        # And only then: the note is not in any earlier request.
        for request in client.models.requests[:-1]:
            assert all(
                part.text != agent.LAST_TURN_NOTE
                for content in request["contents"]
                for part in content.parts
            )

    async def test_max_tokens_is_reported_as_truncated(self, host):
        events, _ = await collect(
            "q", host, [answer_turn("Half an ans", finish=types.FinishReason.MAX_TOKENS)]
        )
        assert events[-1]["truncated"] is True

    async def test_a_turn_stopped_for_safety_ends_cleanly(self, host):
        # Not truncated -- the model did not run out of room, it was stopped.
        events, _ = await collect(
            "q", host, [answer_turn("", finish=types.FinishReason.SAFETY)]
        )
        assert events[-1]["type"] == "done"
        assert events[-1]["truncated"] is False

    async def test_a_failing_tool_is_reported_to_the_model_not_raised(self):
        # The knowledge base being down should not take the whole answer with it.
        events, client = await collect(
            "q", FakeHost(results={}), [search_turn(), answer_turn()]
        )
        response = next(
            part.function_response
            for content in client.models.requests[1]["contents"]
            for part in (content.parts or [])
            if part.function_response is not None
        )
        assert response.response["error"] is True
        assert events[-1]["type"] == "done"

    async def test_an_empty_knowledge_base_is_described_not_faked(self, host):
        host.results["kb_search"] = {
            "success": True, "results": [], "total_found": 0, "collection_size": 0,
        }
        _, client = await collect("q", host, [search_turn(), answer_turn()])
        response = next(
            part.function_response
            for content in client.models.requests[1]["contents"]
            for part in (content.parts or [])
            if part.function_response is not None
        )
        assert "empty" in response.response["result"].lower()

    async def test_automatic_function_calling_is_disabled(self, host):
        # The SDK would otherwise run the loop itself, swallowing the streamed
        # deltas and the pre-numbered passages this file exists to produce.
        _, client = await collect("q", host, [answer_turn()])
        config = client.models.requests[0]["config"]
        assert config.automatic_function_calling.disable is True

    async def test_the_output_budget_leaves_room_to_think(self, host):
        # 4096 was enough for the answer alone and truncated in practice,
        # because thinking spends the same allowance.
        assert agent.MAX_OUTPUT_TOKENS >= 8192


class TestSystemPrompt:
    def test_the_prompt_warns_when_the_knowledge_base_is_missing(self):
        assert "unavailable" in agent.NO_KB_NOTE

    def test_the_prompt_requires_citation(self):
        assert "[3]" in agent.SYSTEM_PROMPT
