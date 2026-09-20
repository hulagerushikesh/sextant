"""The agent-level harness, with the model scripted.

The grading is what is under test: that a second search counts, that the first
search is graded on its own, and that the selection is deterministic. The loop
itself is covered by `test_agent.py`.
"""

from __future__ import annotations

from typing import Any

from eval.agent_harness import RecordingHost, answer_one, grade_record, select, summarise
from mcp_server import agent
from tests.fakes import (
    FakeGemini,
    FakeHost,
    as_host,
    call_chunk,
    final_chunk,
    hit,
    kb_result,
    text_chunk,
)


def search_turn(query: str):
    return [call_chunk("kb_search", {"query": query}), final_chunk(output_tokens=10)]


def answer_turn(text: str = "An answer [1]."):
    return [text_chunk(text), final_chunk(input_tokens=1000, output_tokens=100)]


class SequencedHost(FakeHost):
    """A FakeHost whose `kb_search` answers differ call by call."""

    def __init__(self, results: list[dict[str, Any]]) -> None:
        super().__init__({})
        self._queue = list(results)

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((name, arguments))
        return self._queue.pop(0)


def item(**overrides: Any) -> dict[str, Any]:
    base = {
        "id": "q1",
        "kind": "multihop",
        "answerable": True,
        "question": "Two things?",
        "relevant_docs": ["alpha", "beta"],
    }
    return {**base, **overrides}


class TestRecordingHost:
    async def test_records_each_search_and_passes_the_result_through(self):
        inner = FakeHost({"kb_search": kb_result(hit("alpha#0", "Alpha", "text"))})
        host = RecordingHost(inner)
        result = await host.call("kb_search", {"query": "one"})
        await host.call("kb_search", {"query": "two", "limit": 3})
        assert result["results"][0]["id"] == "alpha#0"
        assert [s["query"] for s in host.searches] == ["one", "two"]
        assert host.searches[1]["limit"] == 3
        assert host.tools == inner.tools and host.connected

    async def test_other_tools_are_not_searches_but_are_calls(self):
        host = RecordingHost(FakeHost({"kb_stats": {"documents": 2}, "kb_list": {"documents": []}}))
        await host.call("kb_list", {})
        await host.call("kb_stats", {})
        assert host.searches == []
        assert host.calls == ["kb_list", "kb_stats"]


class TestGrading:
    def test_named_credits_titles_from_the_listing_in_the_answer(self):
        titles = {"alpha": "Alpha Handbook", "beta": "Beta Notes"}
        grade = grade_record(item(), [], "Read the Alpha Handbook first.", titles)
        assert grade["searches"] == 0 and grade["recall@union"] == 0.0
        assert grade["named"] == 0.5

    def test_named_is_one_when_nothing_is_expected(self):
        grade = grade_record({**item(), "relevant_docs": []}, [], "anything", {})
        assert grade["named"] == 1.0

    def test_union_credits_a_second_search(self):
        searches = [
            {"query": "first", "hits": [hit("alpha#0", "A", "x"), hit("gamma#0", "G", "x")]},
            {"query": "second", "hits": [hit("beta#2", "B", "x")]},
        ]
        grade = grade_record(item(), searches)
        assert grade["searches"] == 2
        assert grade["hit@1"] == 1.0
        assert grade["recall@first"] == 0.5
        assert grade["recall@union"] == 1.0
        assert grade["union"] == ["alpha", "gamma", "beta"]
        assert grade["queries"] == ["first", "second"]

    def test_no_search_at_all_is_a_zero(self):
        grade = grade_record(item(), [])
        assert grade["searches"] == 0
        assert grade["recall@first"] == 0.0 and grade["recall@union"] == 0.0

    def test_page_labelled_items_grade_pages(self):
        labelled = item(relevant_pages={"survey": [23, 25]})
        del labelled["relevant_docs"]
        searches = [
            {"query": "q", "hits": [hit("survey#1", "S", "x", page=23)]},
            {"query": "q2", "hits": [hit("survey#9", "S", "x", page=25)]},
        ]
        grade = grade_record(labelled, searches)
        assert grade["recall@first"] == 0.5
        assert grade["recall@union"] == 1.0
        assert grade["expected"] == ["survey#p23", "survey#p25"]

    def test_first_search_is_graded_at_the_depth_returned(self):
        # Seven hits came back; the seventh counts. There is no k=5 cut here
        # because the model reads everything the tool handed it.
        hits = [hit(f"other{i}#0", "O", "x") for i in range(6)] + [hit("alpha#0", "A", "x")]
        grade = grade_record(item(relevant_docs=["alpha"]), [{"query": "q", "hits": hits}])
        assert grade["recall@first"] == 1.0
        assert grade["hit@1"] == 0.0


class TestAnswerOne:
    async def test_collects_searches_turns_and_usage_from_the_real_loop(self):
        host = SequencedHost(
            [
                kb_result(hit("alpha#0", "Alpha", "first half")),
                kb_result(hit("beta#0", "Beta", "second half")),
            ]
        )
        client = FakeGemini([search_turn("part one"), search_turn("part two"), answer_turn()])
        agent._client = lambda: client

        produced = await answer_one(as_host(host), "Two things?")

        assert [s["query"] for s in produced["searches"]] == ["part one", "part two"]
        assert produced["turns"] == 3
        assert produced["answer"] == "An answer [1]."
        assert produced["usage"]["cost_usd"] > 0
        grade = grade_record(item(), produced["searches"])
        assert grade["recall@first"] == 0.5 and grade["recall@union"] == 1.0

    async def test_web_search_is_never_offered(self, monkeypatch):
        monkeypatch.setenv(agent.WEB_SEARCH_ENV, "on")
        host = SequencedHost([kb_result(hit("alpha#0", "Alpha", "x"))])
        client = FakeGemini([search_turn("q"), answer_turn()])
        agent._client = lambda: client

        await answer_one(as_host(host), "Anything?")

        offered = {
            t.name for t in client.models.requests[0]["config"].tools[0].function_declarations
        }
        assert offered == {"kb_search", "kb_list", "kb_stats"}
        assert len(client.models.requests[0]["config"].tools) == 1


class TestSelection:
    golden = [
        item(id="q1", kind="multihop"),
        item(id="q2", kind="exact"),
        item(id="q3", kind="paraphrase"),
        item(id="q4", kind="exact"),
        item(id="q5", kind="unanswerable", answerable=False),
    ]

    def test_default_is_every_answerable_question(self):
        assert [i["id"] for i in select(self.golden, None, None)] == ["q1", "q2", "q3", "q4"]

    def test_kinds_first_then_a_seeded_sample_of_the_rest(self):
        chosen = select(self.golden, ["multihop"], 2, seed=0)
        again = select(self.golden, ["multihop"], 2, seed=0)
        assert chosen[0]["id"] == "q1"
        assert len(chosen) == 3
        assert chosen == again
        assert "q5" not in {i["id"] for i in chosen}

    def test_sample_larger_than_the_pool_takes_everything(self):
        assert len(select(self.golden, ["multihop"], 50)) == 4

    def test_the_unanswerable_split_is_added_whole_never_sampled(self):
        assert [i["id"] for i in select(self.golden, None, None, unanswerable=True)][-1] == "q5"
        chosen = select(self.golden, ["multihop"], 1, seed=0, unanswerable=True)
        assert chosen[-1]["id"] == "q5" and len(chosen) == 3


class TestSummary:
    def test_splits_by_kind_and_set(self):
        records = [
            {
                "id": "q1", "set": "handbook", "kind": "multihop", "turns": 3,
                "truncated": False, "usage": {"cost_usd": 0.004},
                "grade": {"hit@1": 1.0, "recall@first": 0.5, "recall@union": 1.0, "searches": 2},
            },
            {
                "id": "L1", "set": "large", "kind": "exact", "turns": 2,
                "truncated": True, "usage": {"cost_usd": 0.002},
                "grade": {"hit@1": 0.0, "recall@first": 0.0, "recall@union": 0.0, "searches": 1},
            },
        ]
        summary = summarise(records)
        assert summary["all"]["recall@union"] == 0.5
        assert summary["all"]["searched_twice"] == 1
        assert summary["all"]["truncated"] == 1
        assert summary["all"]["cost_usd"] == 0.006
        assert summary["by_kind"]["multihop"]["recall@first"] == 0.5
        assert summary["by_set"]["large"]["questions"] == 1

    def test_unanswerable_rows_stay_out_of_the_retrieval_means(self):
        records = [
            {
                "id": "q1", "set": "handbook", "kind": "exact", "answerable": True, "turns": 2,
                "truncated": False, "usage": {"cost_usd": 0.002},
                "grade": {"hit@1": 1.0, "recall@first": 1.0, "recall@union": 1.0, "searches": 1},
            },
            {
                "id": "u1", "set": "handbook", "kind": "unanswerable", "answerable": False,
                "turns": 2, "truncated": False, "usage": {"cost_usd": 0.002},
                "grade": {"hit@1": 0.0, "recall@first": 0.0, "recall@union": 0.0, "searches": 3},
            },
        ]
        summary = summarise(records)
        assert summary["all"]["questions"] == 2
        assert summary["all"]["recall@union"] == 1.0  # not 0.5
        assert summary["all"]["searches_per_question"] == 2.0  # the loop's work counts
        assert "faithfulness" not in summary["all"]

    def test_judge_columns_keep_the_two_abstention_errors_apart(self):
        def row(id, answerable, declined, faith=1.0):
            return {
                "id": id, "set": "handbook", "kind": "x", "answerable": answerable, "turns": 2,
                "truncated": False, "usage": {},
                "grade": {"hit@1": 1.0, "recall@first": 1.0, "recall@union": 1.0, "searches": 1},
                "judge": {"faithfulness": faith, "relevance": 1.0, "declined": declined},
                "citations": {"valid": True},
            }

        summary = summarise(
            [row("q1", True, False), row("q2", True, True, 0.0), row("u1", False, True),
             row("u2", False, False)]
        )
        block = summary["all"]
        assert block["faithfulness"] == 0.5
        assert block["false_abstention"] == 0.5
        assert block["correct_abstention"] == 0.5
        assert block["citations_valid"] == 1.0

    def test_an_unanswerable_item_grades_to_zero_even_when_something_came_back(self):
        # recall over an empty expected set is vacuously 1.0; that would print
        # as a hit for a question that has no answer.
        searches = [{"query": "q", "limit": 5, "hits": [hit("alpha#0", "Alpha", "text")]}]
        grade = grade_record(item(id="u1", answerable=False, relevant_docs=None), searches)
        assert grade["recall@first"] == grade["recall@union"] == grade["hit@1"] == 0.0
        assert grade["expected"] == []

