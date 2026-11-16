"""The library self-test: a sample for the assistant, and an honest grade."""

from __future__ import annotations

import asyncio
import json

import pytest

from sextant.vector_db import selftest
from sextant.vector_db.summaries import SUMMARY_KIND

LONG = " ".join(f"word{i}" for i in range(40))


def _corpus(documents: dict[str, int]) -> dict[str, tuple[str, dict]]:
    """`documents` maps a document id to how many long passages it has."""
    corpus: dict[str, tuple[str, dict]] = {}
    for doc, n in documents.items():
        for i in range(n):
            corpus[f"{doc}#{i}"] = (
                f"{doc} passage {i} " + LONG,
                {"document_id": doc, "title": doc.title(), "chunk_index": i},
            )
    return corpus


class TestTheSample:
    def test_one_long_file_cannot_fill_it(self):
        corpus = _corpus({"big": 100, "a": 3, "b": 3})
        got = selftest.sample(corpus, size=6, seed=1)
        documents = [p["document_id"] for p in got["passages"]]
        assert sorted(documents) == ["a", "a", "b", "b", "big", "big"]
        assert got["documents"] == 3 and got["eligible_passages"] == 106

    def test_a_seed_repeats_the_sample(self):
        corpus = _corpus({"a": 10, "b": 10})
        first = selftest.sample(corpus, size=5, seed=42)
        assert selftest.sample(corpus, size=5, seed=42)["passages"] == first["passages"]
        assert first["seed"] == 42

    def test_without_a_seed_one_is_chosen_and_reported(self):
        got = selftest.sample(_corpus({"a": 3}), size=2)
        assert isinstance(got["seed"], int)
        again = selftest.sample(_corpus({"a": 3}), size=2, seed=got["seed"])
        assert again["passages"] == got["passages"]

    def test_overviews_and_scraps_are_not_asked_about(self):
        corpus = _corpus({"a": 2})
        corpus["a#summary"] = (LONG, {"document_id": "a", "kind": SUMMARY_KIND})
        corpus["a#9"] = ("Page 4", {"document_id": "a"})
        got = selftest.sample(corpus, size=10, seed=3)
        assert {p["passage_id"] for p in got["passages"]} == {"a#0", "a#1"}
        assert got["sampled"] == 2

    def test_an_empty_library_gives_an_empty_sample(self):
        got = selftest.sample({}, size=5, seed=1)
        assert got["passages"] == [] and got["documents"] == 0

    def test_it_tells_the_assistant_what_to_do(self):
        got = selftest.sample(_corpus({"a": 1}), size=1, seed=1)
        assert "kb_selftest_grade" in got["instructions"]
        assert "rough guide" in got["instructions"]

    @pytest.mark.parametrize("size", [0, selftest.MAX_SIZE + 1])
    def test_a_size_out_of_range_is_refused(self, size):
        with pytest.raises(ValueError, match="size"):
            selftest.sample(_corpus({"a": 1}), size=size)


def _search_returning(order: dict[str, list[str]]):
    """A search whose results for each question are fixed passage ids."""

    def search(question: str):
        return [
            {"id": cid, "document_id": cid.split("#")[0], "title": cid} for cid in order[question]
        ]

    return search


class TestTheGrade:
    CORPUS = _corpus({"a": 3, "b": 3})

    def test_first_and_top_five_are_counted_from_the_rank(self):
        search = _search_returning(
            {
                "q1": ["a#0", "b#0"],  # first
                "q2": ["b#0", "b#1", "a#1"],  # third
                "q3": ["b#0", "b#1", "b#2", "a#0", "a#2", "a#1"],  # sixth: missed
            }
        )
        got = selftest.grade(
            self.CORPUS,
            [
                {"passage_id": "a#0", "question": "q1"},
                {"passage_id": "a#1", "question": "q2"},
                {"passage_id": "a#1", "question": "q3"},
            ],
            search,
        )
        assert got["questions"] == 3
        assert got["found_first"] == round(1 / 3, 3)
        assert got["found_in_top_5"] == round(2 / 3, 3)
        assert [g["rank"] for g in got["results"]] == [1, 3, 6]
        assert [m["question"] for m in got["missed"]] == ["q3"]
        assert got["missed"][0]["first_result"]["passage_id"] == "b#0"

    def test_the_right_document_is_reported_apart_from_the_right_passage(self):
        search = _search_returning({"q": ["a#2", "a#0"]})
        got = selftest.grade(self.CORPUS, [{"passage_id": "a#0", "question": "q"}], search)
        assert got["results"][0]["rank"] == 2
        assert got["results"][0]["document_rank"] == 1
        assert got["found_first"] == 0.0 and got["right_document_first"] == 1.0

    def test_a_passage_not_found_at_all_has_no_rank(self):
        got = selftest.grade(
            self.CORPUS, [{"passage_id": "a#0", "question": "q"}], _search_returning({"q": []})
        )
        assert got["results"][0]["rank"] is None
        assert got["results"][0]["first_result"] is None
        assert got["found_in_top_5"] == 0.0

    def test_an_unknown_passage_or_empty_question_is_listed_not_graded(self):
        got = selftest.grade(
            self.CORPUS,
            [{"passage_id": "nope#1", "question": "q"}, {"passage_id": "a#0", "question": "  "}],
            _search_returning({}),
        )
        assert got["questions"] == 0 and got["found_first"] is None
        assert [r["reason"] for r in got["not_graded"]] == ["no such passage", "empty question"]

    def test_a_question_that_copies_the_passage_is_flagged(self):
        text = self.CORPUS["a#0"][0]
        copied = "Why does " + " ".join(text.split()[3:12]) + "?"
        own = "What is the first word listed in this part?"
        search = _search_returning({copied: ["a#0"], own: ["a#0"]})
        got = selftest.grade(
            self.CORPUS,
            [{"passage_id": "a#0", "question": copied}, {"passage_id": "a#0", "question": own}],
            search,
        )
        assert [g["copied_wording"] for g in got["results"]] == [True, False]
        assert got["copied_wording"] == 1

    def test_seven_words_in_a_row_is_not_copying(self):
        assert not selftest.copied(
            "one two three four five six seven", "one two three four five six seven eight"
        )
        assert selftest.copied(
            "one two three four five six seven eight", "x one two three four five six seven eight y"
        )

    def test_the_result_says_it_is_a_rough_guide(self):
        got = selftest.grade(self.CORPUS, [], _search_returning({}))
        assert "rough guide" in got["how_to_read"]


class TestOnARealLibrary:
    """End to end through the knowledge base, with real models."""

    async def test_a_question_written_from_a_passage_finds_it(self, kb):
        sampled = await kb.selftest_sample(size=5, seed=7)
        assert sampled["passages"], "the test corpus has no passage long enough"
        by_title = {p["title"].lower(): p["passage_id"] for p in sampled["passages"]}
        questions = []
        for title, passage_id in by_title.items():
            if "kalman" in title:
                questions.append(
                    {
                        "passage_id": passage_id,
                        "question": (
                            "How is the trust between a prediction and a noisy measurement decided?"
                        ),
                    }
                )
            if "hungarian" in title:
                questions.append(
                    {
                        "passage_id": passage_id,
                        "question": (
                            "Which error is raised when an assignment solve takes too long?"
                        ),
                    }
                )
        assert questions
        got = await kb.selftest_grade(questions)
        assert got["questions"] == len(questions)
        assert got["found_first"] == 1.0, got["results"]
        assert got["copied_wording"] == 0

    async def test_the_grade_searches_without_the_floor(self, kb):
        # A question the reranker dislikes still gets a rank: the floor would
        # otherwise turn a low-ranked hit into "not found".
        sampled = await kb.selftest_sample(size=1, seed=1)
        passage_id = sampled["passages"][0]["passage_id"]
        got = await kb.selftest_grade([{"passage_id": passage_id, "question": "zebra umbrella"}])
        assert got["results"][0]["first_result"] is not None


class TestThroughTheServer:
    def test_both_tools_are_listed_and_the_instructions_name_them(self):
        from sextant.vector_db import server

        names = {t.name for t in asyncio.run(server.mcp.list_tools())}
        assert {"kb_selftest_sample", "kb_selftest_grade"} <= names
        assert "kb_selftest_sample" in (server.mcp.instructions or "")

    def test_the_hosted_agent_does_not_offer_them(self):
        from sextant.mcp_server.agent import READABLE_TOOLS

        assert not {"kb_selftest_sample", "kb_selftest_grade"} & READABLE_TOOLS

    def test_another_owners_passages_are_trimmed_from_both(self):
        from sextant.mcp_server.scope import trim

        sampled = {
            "passages": [
                {
                    "passage_id": "upload:grace:notes#0",
                    "document_id": "upload:grace:notes",
                    "text": "x",
                },
                {"passage_id": "upload:ada:mine#0", "document_id": "upload:ada:mine", "text": "y"},
            ],
            "sampled": 2,
        }
        got = trim(json.loads(json.dumps(sampled)), "ada")
        assert [p["passage_id"] for p in got["passages"]] == ["upload:ada:mine#0"]
