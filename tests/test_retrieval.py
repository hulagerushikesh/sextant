"""BM25, fusion and the reranker, in isolation."""

from __future__ import annotations

import pytest

from tools.vector_db.retrieval import BM25Index, reciprocal_rank_fusion, tokenize

DOCS = {
    "c1": "A Kalman filter estimates hidden state from noisy measurements.",
    "c2": "The Hungarian algorithm solves the assignment problem in cubic time.",
    "c3": "Error code TRK-4471 is raised when the cost matrix contains a NaN entry.",
    "c4": "Recursive Bayesian estimation underlies most online tracking filters.",
}


@pytest.fixture
def index() -> BM25Index:
    return BM25Index(list(DOCS), list(DOCS.values()))


class TestTokenize:
    def test_lowercases_and_drops_function_words(self):
        assert tokenize("What is THE Kalman filter?") == ["kalman", "filter"]

    def test_drops_single_characters(self):
        assert tokenize("a b filter") == ["filter"]

    def test_splits_on_punctuation_keeping_alphanumerics(self):
        assert "4471" in tokenize("Error code TRK-4471")

    def test_empty(self):
        assert tokenize("") == []


class TestBM25:
    def test_finds_an_exact_term_dense_search_would_blur(self, index):
        assert index.search("TRK-4471", 3)[0][0] == "c3"

    def test_ranks_the_matching_document_first(self, index):
        assert index.search("assignment problem", 3)[0][0] == "c2"

    def test_returns_nothing_when_no_term_matches(self, index):
        assert index.search("zzzz", 3) == []

    def test_respects_the_limit(self, index):
        assert len(index.search("filter estimation state", 2)) <= 2

    def test_scores_descend(self, index):
        scores = [score for _, score in index.search("filter tracking estimation", 4)]
        assert scores == sorted(scores, reverse=True)

    def test_empty_index_is_not_an_error(self):
        assert BM25Index([], []).search("anything", 5) == []

    def test_length_normalisation_favours_the_shorter_document(self):
        short = "kalman filter"
        padded = "kalman filter " + " ".join(f"term{i}" for i in range(200))
        results = dict(BM25Index(["short", "long"], [short, padded]).search("kalman filter", 2))
        assert results["short"] > results["long"]


class TestFusion:
    def test_a_document_both_retrievers_found_wins(self):
        fused = reciprocal_rank_fusion(dense=["c4", "c1", "c2"], lexical=["c1", "c3"])
        assert fused[0].id == "c1"
        assert fused[0].matched == ["dense", "lexical"]

    def test_ranks_are_recorded_for_the_trace(self):
        fused = {f.id: f for f in reciprocal_rank_fusion(["c4", "c1"], ["c1", "c3"])}
        assert fused["c1"].dense_rank == 2
        assert fused["c1"].lexical_rank == 1
        assert fused["c3"].dense_rank is None

    def test_scores_descend(self):
        fused = reciprocal_rank_fusion(["a", "b", "c"], ["c", "d"])
        assert [f.rrf_score for f in fused] == sorted(
            (f.rrf_score for f in fused), reverse=True
        )

    def test_one_empty_ranking_passes_the_other_through(self):
        assert [f.id for f in reciprocal_rank_fusion([], ["a", "b"])] == ["a", "b"]

    def test_both_empty(self):
        assert reciprocal_rank_fusion([], []) == []

    def test_fusion_can_beat_either_input_ordering(self):
        # The point of RRF: something ranked second by both beats something
        # ranked first by only one.
        fused = reciprocal_rank_fusion(dense=["x", "shared"], lexical=["y", "shared"])
        assert fused[0].id == "shared"


@pytest.fixture(scope="module")
def reranker():
    from tools.vector_db.retrieval import CrossEncoderReranker

    return CrossEncoderReranker()


class TestReranker:
    def test_scores_are_bounded(self, reranker):
        scores = reranker.score("what is a Kalman filter", list(DOCS.values()))
        assert all(0.0 <= score <= 1.0 for score in scores)

    def test_the_relevant_passage_scores_highest(self, reranker):
        scores = reranker.score("how do you estimate hidden state", list(DOCS.values()))
        assert scores.index(max(scores)) == 0

    def test_no_passages(self, reranker):
        assert reranker.score("anything", []) == []
