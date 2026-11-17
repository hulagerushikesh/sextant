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
                # Each document's own words, so two documents are not versions.
                f"{doc} passage {i} " + LONG.replace("word", f"{doc}word"),
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


class TestTheChanceRange:
    def test_all_found_cannot_move(self):
        assert selftest.chance_range([1] * 20) == (1.0, 1.0)

    def test_half_found_moves_both_ways_and_more_questions_narrow_it(self):
        ranks = [1, None] * 25
        low20, high20 = selftest.chance_range(ranks, n=20) or (0, 0)
        low50, high50 = selftest.chance_range(ranks, n=50) or (0, 0)
        assert low20 < 0.5 < high20
        assert high50 - low50 < high20 - low20

    def test_rank_six_is_a_miss_and_nothing_graded_is_no_range(self):
        assert selftest.chance_range([6] * 10) == (0.0, 0.0)
        assert selftest.chance_range([]) is None

    def test_one_grade_always_reports_one_range(self):
        ranks = [1, 3, None, 7, 2] * 4
        assert selftest.chance_range(ranks) == selftest.chance_range(ranks)


class TestWhatCannotBeSearched:
    def _with_copy(self) -> dict[str, tuple[str, dict]]:
        corpus = _corpus({"notes": 2, "other": 2})
        for i in range(2):
            text, meta = corpus[f"notes#{i}"]
            # Same words, other capitals and line breaks: still a copy.
            corpus[f"notes-copy#{i}"] = (
                text.upper().replace(" ", "\n"),
                {**meta, "document_id": "notes-copy", "title": "Notes copy"},
            )
        return corpus

    def test_a_copy_is_found_against_the_first_in_order(self):
        assert selftest.duplicates(self._with_copy()) == [
            {
                "document_id": "notes-copy",
                "name": "Notes copy",
                "same_as": "notes",
                "same_as_name": "Notes",
            }
        ]

    def test_a_copy_is_named_by_its_file_when_it_has_one(self):
        corpus = self._with_copy()
        for chunk_id, (text, meta) in list(corpus.items()):
            # Two copies of one note share a title; only the file tells them apart.
            corpus[chunk_id] = (
                text,
                {**meta, "title": "Notes", "source": f"{meta['document_id']}.md"},
            )
        got = selftest.cannot_search(corpus, None)
        assert got[0]["name"] == "notes-copy.md" and "same text as notes.md" in got[0]["why"]

    def test_a_shared_passage_is_not_a_copy(self):
        corpus = _corpus({"a": 2, "b": 2})
        corpus["b#0"] = (corpus["a#0"][0], corpus["b#0"][1])
        assert selftest.duplicates(corpus) == []

    def test_an_overview_does_not_make_two_documents_differ(self):
        corpus = self._with_copy()
        corpus["notes#summary"] = ("an overview", {"document_id": "notes", "kind": SUMMARY_KIND})
        assert [d["document_id"] for d in selftest.duplicates(corpus)] == ["notes-copy"]

    def test_scanned_and_empty_files_come_first_then_copies(self):
        skipped = [
            {"file": "same/notes.md", "reason": "has the same name", "kind": "same_name"},
            {"file": "scan.pdf", "reason": "probably a scanned PDF", "kind": "no_text"},
        ]
        got = selftest.cannot_search(self._with_copy(), skipped)
        assert [d["kind"] for d in got] == ["no_text", "same_name", "duplicate"]
        assert got[2]["name"] == "Notes copy" and "same text as Notes" in got[2]["why"]


class TestTheReport:
    CORPUS = _corpus({"a": 3, "b": 3})

    def _grade(self, ranks_found: int, missed: int, not_indexed=None) -> dict:
        order = {f"hit{i}": ["a#0"] for i in range(ranks_found)}
        order |= {f"miss{i}": ["b#0"] for i in range(missed)}
        questions = [{"passage_id": "a#0", "question": q} for q in order]
        return selftest.grade(self.CORPUS, questions, _search_returning(order), not_indexed)

    def test_one_score_with_its_chance_range_and_the_rough_guide(self):
        got = self._grade(15, 5)
        assert got["score"]["found_in_top_5"] == 15 and got["score"]["of"] == 20
        low, high = got["score"]["chance_low"], got["score"]["chance_high"]
        assert low < 0.75 < high
        report = got["report"]
        assert "**15 of 20 questions (75%)**" in report
        assert f"from {round(100 * low)}% to {round(100 * high)}%" in report
        assert selftest.ROUGH_GUIDE in report

    def test_the_missed_questions_are_named_and_bounded(self):
        report = self._grade(10, 8)["report"]
        assert "**Questions it missed (8):**" in report
        assert report.count('- "miss') == selftest.REPORTED_MISSES
        assert "- and 3 more." in report
        assert "the first result was from b#0" in report

    def test_another_passage_of_the_same_document_is_said_plainly(self):
        order = {"q": ["a#2", "a#0"] * 3}
        got = selftest.grade(
            self.CORPUS,
            [{"passage_id": "a#1", "question": "q"}],
            _search_returning(order),
        )
        assert "another passage of the same document came first" in got["report"]

    def test_every_unusable_document_is_counted_and_a_screenful_shown(self):
        skipped = [
            {"file": f"scan{i}.pdf", "reason": "probably a scanned PDF", "kind": "no_text"}
            for i in range(selftest.REPORTED_DOCUMENTS + 4)
        ]
        got = self._grade(20, 0, skipped)
        assert len(got["cannot_search"]) == selftest.REPORTED_DOCUMENTS + 4
        assert (
            f"**Documents search cannot use ({selftest.REPORTED_DOCUMENTS + 4}):**"
            in (got["report"])
        )
        assert "- and 4 more." in got["report"]
        assert "**No question missed.**" in got["report"]

    def test_a_clean_folder_says_so_and_no_folder_says_what_it_cannot_see(self):
        assert "Every file in the folder was indexed" in self._grade(5, 0, [])["report"]
        assert "only when the library is a folder" in self._grade(5, 0, None)["report"]

    def test_copied_questions_are_counted_in_the_caveat(self):
        text = self.CORPUS["a#0"][0]
        copied = "Why does " + " ".join(text.split()[3:12]) + "?"
        got = selftest.grade(
            self.CORPUS,
            [{"passage_id": "a#0", "question": copied}],
            _search_returning({copied: ["a#0"]}),
        )
        assert "1 of the questions copied the passage's wording" in got["report"]

    def test_nothing_graded_is_no_score_not_zero(self):
        got = selftest.grade(
            self.CORPUS, [{"passage_id": "nope", "question": "q"}], _search_returning({})
        )
        assert got["report"].startswith("No question could be graded")
        assert got["score"]["chance_low"] is None

    def test_it_fits_one_screen(self):
        skipped = [{"file": f"f{i}.pdf", "reason": "x" * 60, "kind": "no_text"} for i in range(30)]
        report = self._grade(0, selftest.MAX_SIZE, skipped)["report"]
        assert len(report.splitlines()) <= 25

    def test_the_assistant_is_told_to_show_it_as_it_is(self):
        assert "report" in selftest.INSTRUCTIONS and "exactly" in selftest.INSTRUCTIONS


def _advice(unusable: list, lost: list, missed: int) -> dict:
    got = selftest.suggestion(unusable, lost, missed)
    assert got is not None
    return got


class TestTheSuggestion:
    def _with_copy(self) -> dict[str, tuple[str, dict]]:
        return TestWhatCannotBeSearched()._with_copy()

    def _graded(self) -> dict:
        order = {
            "q1": ["notes-copy#0"],
            "q2": ["notes-copy#1"],
            "q3": ["other#0"],
            "hit": ["notes#0"],
        }
        # The miss that is not a copy's fault is asked first, so the report
        # has to move the cited ones up to show them.
        questions = [
            {"passage_id": "notes#0", "question": "q3"},
            {"passage_id": "notes#0", "question": "q1"},
            {"passage_id": "notes#1", "question": "q2"},
            {"passage_id": "notes#0", "question": "hit"},
        ]
        return selftest.grade(self._with_copy(), questions, _search_returning(order), [])

    def test_copies_that_cost_questions_are_backed_by_the_count(self):
        got = self._graded()
        advice = got["suggestion"]
        assert advice is not None
        assert advice["kind"] == "remove_copies" and advice["count"] == 2
        assert "**2 of the 3 missed questions**" in advice["text"]
        assert advice["evidence"] == {"files": ["Notes copy"], "questions": ["q1", "q2"]}
        assert f"**Fix first:** {advice['text']}" in got["report"]

    def test_the_cited_questions_are_shown_and_marked(self):
        report = self._graded()["report"]
        lines = [line for line in report.splitlines() if line.startswith('- "')]
        assert lines[0].startswith('- "q1"') and lines[1].startswith('- "q2"')
        assert report.count("a copy of the same text") == 2
        assert "the first result was from other#0." in report

    def test_a_copy_that_cost_nothing_gives_way_to_a_scanned_pdf(self):
        copy = {"name": "notes copy.md", "kind": "duplicate", "why": ""}
        scan = {"name": "scan.pdf", "kind": "no_text", "why": ""}
        assert _advice([scan, copy], [], 3)["kind"] == "recognise_text"
        lost = [{"question": "q"}]
        assert _advice([scan, copy], lost, 3)["kind"] == "remove_copies"
        assert _advice([copy], [], 3)["kind"] == "remove_copies"

    def test_the_order_after_that(self):
        def kinds(*present: str) -> str:
            unusable = [{"name": f"{k}.md", "kind": k, "why": ""} for k in present]
            return _advice(unusable, [], 0)["kind"]

        assert kinds("duplicate", "unreadable", "same_name") == "rename"
        assert kinds("duplicate", "unreadable") == "check_unreadable"

    def test_an_empty_note_or_nothing_found_suggests_nothing(self):
        empty = [{"name": "blank.txt", "kind": "no_text", "why": "is empty"}]
        assert selftest.suggestion(empty, [], 2) is None
        got = TestTheReport()._grade(5, 2, [])
        assert got["suggestion"] is None and "Fix first" not in got["report"]

    def test_it_names_a_few_files_and_keeps_them_all(self):
        scans = [{"name": f"scan{i}.pdf", "kind": "no_text", "why": ""} for i in range(6)]
        advice = _advice(scans, [], 0)
        assert advice["count"] == 6 and len(advice["evidence"]["files"]) == 6
        assert "**6 PDFs with no readable text**" in advice["text"]
        assert "scan3.pdf and 2 more" in advice["text"] and "scan4.pdf" not in advice["text"]


def _words(prefix: str, n: int) -> list[str]:
    return [f"{prefix}{i}" for i in range(n)]


def _versions() -> dict[str, tuple[str, dict]]:
    """Two versions of a CV: v5 adds a line, and v3 is cut into passages at
    other places. A third document shares one sentence with v5 and no more."""
    body = _words("skill", 60)
    v5 = ["new", "line", "here", "first"] + body
    v3 = body
    other = body[:6] + _words("unrelated", 60)

    def doc(name: str, words: list[str], size: int) -> dict[str, tuple[str, dict]]:
        return {
            f"{name}#{i}": (
                " ".join(words[i * size : (i + 1) * size]),
                {"document_id": name, "source": f"{name}.pdf", "chunk_index": i},
            )
            for i in range((len(words) + size - 1) // size)
        }

    return doc("cv-v5", v5, 32) | doc("cv-v3", v3, 20) | doc("other", other, 33)


class TestAnotherVersion:
    def _grade(self, order: dict[str, list[str]], not_indexed=None) -> dict:
        questions = [{"passage_id": "cv-v5#0", "question": q} for q in order]
        return selftest.grade(_versions(), questions, _search_returning(order), not_indexed)

    def test_a_miss_won_by_another_version_is_named_and_suggested(self):
        got = self._grade({"q1": ["cv-v3#1"], "q2": ["other#0"], "hit": ["cv-v5#0"]})
        assert [g["question"] for g in got["missed"] if g.get("lost_to_version")] == ["q1"]
        advice = got["suggestion"]
        assert advice["kind"] == "keep_one_version" and advice["count"] == 1
        # The first result is named as the search names it.
        assert advice["evidence"] == {"files": ["cv-v5.pdf", "cv-v3#1"], "questions": ["q1"]}
        assert "**1 of the 2 missed questions** found its text" in advice["text"]
        report = got["report"]
        assert "cv-v3#1, another version holding most of the same text" in report
        assert "the first result was from other#0." in report

    def test_one_shared_sentence_is_not_a_version(self):
        got = self._grade({"q": ["other#0"]})
        assert not any(g.get("lost_to_version") for g in got["missed"])
        assert got["suggestion"] is None

    def test_a_long_shared_passage_in_different_documents_is_not_a_version(self):
        corpus = _versions()
        # Most of the passage is the footer; little of either document is.
        footer = " ".join(_words("footer", 20))
        corpus["other#0"] = (footer + " " + corpus["other#0"][0], corpus["other#0"][1])
        own = " ".join(_words("own", 10))
        corpus["cv-v5#0"] = (footer + " " + own, corpus["cv-v5#0"][1])
        order = {"q": ["other#0"]}
        got = selftest.grade(
            corpus, [{"passage_id": "cv-v5#0", "question": "q"}], _search_returning(order)
        )
        assert not any(g.get("lost_to_version") for g in got["missed"])

    def test_it_comes_before_a_scanned_pdf_and_after_a_costly_copy(self):
        scan = [{"file": "scan.pdf", "reason": "probably scanned", "kind": "no_text"}]
        assert self._grade({"q": ["cv-v3#0"]}, scan)["suggestion"]["kind"] == "keep_one_version"
        copy = {"name": "a copy.pdf", "kind": "duplicate", "why": ""}
        lost = [{"question": "c"}]
        versions = [{"question": "v", "name": "a", "first_result": {"name": "b"}}]
        assert _advice([copy], lost, 2)["kind"] == "remove_copies"
        advice = selftest.suggestion([copy], lost, 2, versions)
        assert advice is not None and advice["kind"] == "remove_copies"

    def test_an_exact_copy_stays_a_copy(self):
        got = TestTheSuggestion()._graded()
        assert not any(g.get("lost_to_version") for g in got["missed"])
        assert got["suggestion"]["kind"] == "remove_copies"


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
        assert f"**{len(questions)} of {len(questions)} questions (100%)**" in got["report"]
        assert got["cannot_search"] == []

    async def test_a_file_with_no_words_is_flagged_empty_for_the_folder(self, kb):
        # The folder pass tells "scanned or empty" from "could not open" by this
        # flag, so the report can say which.
        got = await kb.add_documents([{"id": "blank", "content": "   \n\n  "}])
        assert got["success"] is False and got.get("empty") is True

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

    def test_the_grade_carries_the_folders_unreadable_files(self, monkeypatch):
        from sextant.vector_db import server

        seen: dict = {}

        class Store:
            async def selftest_grade(self, questions, not_indexed=None):
                seen["not_indexed"] = not_indexed
                return {"report": "r"}

        class Folder:
            def not_indexed(self):
                return [{"file": "scan.pdf", "reason": "scanned", "kind": "no_text"}]

            def note(self):
                return None

        monkeypatch.setattr(server, "_store", lambda: Store())
        monkeypatch.setattr(server, "_folder", Folder())
        asyncio.run(server.kb_selftest_grade([{"passage_id": "a#0", "question": "q"}]))
        assert seen["not_indexed"][0]["file"] == "scan.pdf"
        monkeypatch.setattr(server, "_folder", None)
        asyncio.run(server.kb_selftest_grade([{"passage_id": "a#0", "question": "q"}]))
        assert seen["not_indexed"] is None

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
