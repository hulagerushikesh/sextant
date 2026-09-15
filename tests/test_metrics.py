"""Metric correctness, against values worked out by hand."""

from __future__ import annotations

import math

import pytest

from eval.metrics import abstention, ndcg_at_k, recall_at_k, reciprocal_rank, summarise


class TestRecall:
    def test_all_relevant_found(self):
        assert recall_at_k(["a", "b", "c"], {"a", "b"}, k=3) == 1.0

    def test_half_found(self):
        assert recall_at_k(["a", "x", "y"], {"a", "b"}, k=3) == 0.5

    def test_cutoff_excludes_late_hit(self):
        assert recall_at_k(["x", "y", "a"], {"a"}, k=2) == 0.0
        assert recall_at_k(["x", "y", "a"], {"a"}, k=3) == 1.0

    def test_duplicate_document_counted_once(self):
        # Three chunks of the same document are one document found.
        assert recall_at_k(["a", "a", "a"], {"a", "b"}, k=3) == 0.5

    def test_no_relevant_documents_is_vacuously_perfect(self):
        assert recall_at_k(["x"], set(), k=3) == 1.0

    def test_empty_retrieval(self):
        assert recall_at_k([], {"a"}, k=3) == 0.0


class TestReciprocalRank:
    @pytest.mark.parametrize("retrieved,expected", [
        (["a", "x", "y"], 1.0),
        (["x", "a", "y"], 0.5),
        (["x", "y", "a"], 1 / 3),
        (["x", "y", "z"], 0.0),
    ])
    def test_rank_of_first_hit(self, retrieved, expected):
        assert reciprocal_rank(retrieved, {"a"}) == pytest.approx(expected)

    def test_uses_earliest_of_several_relevant(self):
        assert reciprocal_rank(["x", "b", "a"], {"a", "b"}) == 0.5


class TestNDCG:
    def test_perfect_ordering(self):
        assert ndcg_at_k(["a", "b"], {"a", "b"}, k=2) == pytest.approx(1.0)

    def test_single_hit_at_rank_two(self):
        # DCG = 1/log2(3); ideal for one relevant doc = 1/log2(2) = 1
        assert ndcg_at_k(["x", "a"], {"a"}, k=2) == pytest.approx(1 / math.log2(3))

    def test_order_matters(self):
        good = ndcg_at_k(["a", "x", "b"], {"a", "b"}, k=3)
        bad = ndcg_at_k(["x", "a", "b"], {"a", "b"}, k=3)
        assert good > bad

    def test_repeated_document_earns_gain_once(self):
        # Without deduplication this would exceed the ideal DCG and go above 1.
        assert ndcg_at_k(["a", "a"], {"a", "b"}, k=2) <= 1.0
        assert ndcg_at_k(["a", "a"], {"a"}, k=2) == pytest.approx(1.0)

    def test_nothing_found(self):
        assert ndcg_at_k(["x", "y"], {"a"}, k=2) == 0.0


class TestAbstention:
    def test_no_results_abstains(self):
        assert abstention(None, threshold=0.1) is True

    def test_low_score_abstains(self):
        assert abstention(0.0, threshold=0.1) is True

    def test_confident_score_answers(self):
        assert abstention(0.98, threshold=0.1) is False

    def test_threshold_is_exclusive_below(self):
        assert abstention(0.1, threshold=0.1) is False


def test_summarise_averages_each_key():
    assert summarise([{"a": 1.0, "b": 0.0}, {"a": 0.0, "b": 1.0}]) == {"a": 0.5, "b": 0.5}


def test_summarise_of_nothing():
    assert summarise([]) == {}


class TestGradingUnit:
    """The harness grades what a question labels: documents, or pages of one."""

    def test_document_labelled_question_collapses_chunks_to_document(self):
        from eval.harness import _relevant, _unit

        hit = {"document_id": "kalman-filter", "page": 3}
        assert _unit(hit, by_page=False) == "kalman-filter"
        assert _relevant({"relevant_docs": ["kalman-filter"]}) == {"kalman-filter"}

    def test_page_labelled_question_grades_pages(self):
        from eval.harness import _relevant, _unit

        hit = {"document_id": "survey", "page": 24}
        assert _unit(hit, by_page=True) == "survey#p24"
        assert _relevant({"relevant_pages": {"survey": [23, 24]}}) == {
            "survey#p23",
            "survey#p24",
        }
