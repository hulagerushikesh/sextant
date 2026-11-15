"""The public-set scorer computes BEIR's measure, worked out by hand."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from sextant.eval.public_sets import (
    documents_in_order,
    graded_ndcg_at_k,
    iter_corpus,
    load_qrels,
    load_queries,
    recall_at,
)


class TestGradedNDCG:
    def test_perfect_order_is_one(self):
        assert graded_ndcg_at_k(["a", "b"], {"a": 2, "b": 1}) == pytest.approx(1.0)

    def test_grades_count_linearly_not_exponentially(self):
        # Swapped: DCG = 1 + 2/log2(3); ideal = 2 + 1/log2(3). pytrec_eval's gain is the grade.
        expected = (1 + 2 / math.log2(3)) / (2 + 1 / math.log2(3))
        assert graded_ndcg_at_k(["b", "a"], {"a": 2, "b": 1}) == pytest.approx(expected)

    def test_unretrieved_judged_documents_lower_the_score(self):
        # One of two relevant found, at rank 1: 1 / (1 + 1/log2(3)).
        assert graded_ndcg_at_k(["a", "x"], {"a": 1, "b": 1}) == pytest.approx(
            1 / (1 + 1 / math.log2(3))
        )

    def test_a_document_judged_zero_is_not_relevant(self):
        assert graded_ndcg_at_k(["z"], {"z": 0, "a": 1}) == 0.0
        assert graded_ndcg_at_k(["a"], {"z": 0, "a": 1}) == pytest.approx(1.0)

    def test_only_the_top_k_count(self):
        late = [f"n{i}" for i in range(10)] + ["a"]
        assert graded_ndcg_at_k(late, {"a": 1}, k=10) == 0.0


class TestRecallAndCollapse:
    def test_recall_counts_documents_in_the_top_k(self):
        assert recall_at(["a", "x", "b"], {"a": 1, "b": 2, "c": 1}, k=2) == pytest.approx(1 / 3)

    def test_chunks_collapse_to_documents_in_first_seen_order(self):
        assert documents_in_order(["a", "a", "b", "a", "c"]) == ["a", "b", "c"]


class TestTheFilesAreReadAsBEIRWritesThem:
    def test_qrels_need_the_header(self, tmp_path: Path):
        path = tmp_path / "test.tsv"
        path.write_text("query-id\tcorpus-id\tscore\nq1\td1\t2\nq1\td2\t0\n")
        assert load_qrels(path) == {"q1": {"d1": 2.0, "d2": 0.0}}
        path.write_text("q1\td1\t2\n")
        with pytest.raises(ValueError, match="header"):
            load_qrels(path)

    def test_a_judged_question_without_text_is_refused(self, tmp_path: Path):
        path = tmp_path / "queries.jsonl"
        path.write_text(json.dumps({"_id": "q1", "text": "why"}) + "\n")
        assert load_queries(path, {"q1"}) == {"q1": "why"}
        with pytest.raises(ValueError, match="no text"):
            load_queries(path, {"q1", "q2"})

    def test_title_and_text_are_joined_and_empty_documents_show(self, tmp_path: Path):
        path = tmp_path / "corpus.jsonl"
        rows = [
            {"_id": "1", "title": "T", "text": "body"},
            {"_id": "2", "title": "", "text": "only body"},
            {"_id": "3", "title": "", "text": ""},
        ]
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        docs = list(iter_corpus(path))
        assert [d["content"] for d in docs] == ["T\n\nbody", "only body", ""]
        assert docs[1]["title"] == "2"
