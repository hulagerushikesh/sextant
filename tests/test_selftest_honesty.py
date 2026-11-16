"""The honesty check applies the rule as it was written, and spends only what it says."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from sextant.eval import selftest_honesty as honesty

TRUE = {
    "scifact": {"dense": 0.6713, "lexical": 0.6348, "rrf": 0.6877, "rerank": 0.7004},
    "nfcorpus": {"dense": 0.3116, "lexical": 0.2993, "rrf": 0.3377, "rerank": 0.3635},
    "fiqa": {"dense": 0.3722, "lexical": 0.2157, "rrf": 0.3414, "rerank": 0.3752},
}


def _honest() -> dict[str, dict[str, float]]:
    """A self-test that follows the true score, offset upwards."""
    return {s: {m: round(v + 0.2, 4) for m, v in modes.items()} for s, modes in TRUE.items()}


class TestTheRankCorrelation:
    def test_same_order_is_one_and_reversed_is_minus_one(self):
        assert honesty.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
        assert honesty.spearman([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0

    def test_ties_share_their_rank(self):
        assert honesty._ranks([5, 1, 5, 2]) == [3.5, 1.0, 3.5, 2.0]

    def test_no_spread_is_no_correlation(self):
        assert honesty.spearman([1, 1, 1], [1, 2, 3]) == 0.0

    def test_mismatched_lengths_are_refused(self):
        with pytest.raises(ValueError):
            honesty.spearman([1, 2], [1, 2, 3])


class TestTheRule:
    def test_a_self_test_that_follows_the_true_score_passes(self):
        got = honesty.judge_writer(_honest(), TRUE)
        assert got["conditions"] == 12
        assert got["spearman"] == 1.0
        assert got["passes"] and not got["no_guide"]

    def test_flattering_keyword_search_on_fiqa_fails_rule_3_only(self):
        scores = _honest()
        scores["fiqa"]["lexical"] = 0.90
        got = honesty.judge_writer(scores, TRUE)
        assert not got["rule_3_keyword_lowest_on_fiqa"]
        assert got["rule_1_tracks_true_score"] and got["rule_2_good_set_scores_highest"]
        assert not got["passes"] and not got["no_guide"]

    def test_a_tie_for_lowest_is_not_lowest(self):
        scores = _honest()
        scores["fiqa"]["lexical"] = scores["fiqa"]["rrf"]
        assert not honesty.judge_writer(scores, TRUE)["rule_3_keyword_lowest_on_fiqa"]

    def test_the_good_set_not_highest_is_no_guide(self):
        scores = _honest()
        scores["nfcorpus"]["rerank"] = 0.99
        got = honesty.judge_writer(scores, TRUE)
        assert not got["rule_2_good_set_scores_highest"]
        assert got["no_guide"]

    def test_the_thresholds_are_the_written_ones(self):
        assert honesty.RULE_CORRELATION == 0.6
        assert honesty.NO_GUIDE_CORRELATION == 0.3
        assert len(honesty.WRITERS) == 2 and honesty.SIZE == 50 and honesty.SEED == 29

    def test_both_writers_must_pass(self):
        good = {"passes": True, "no_guide": False}
        middling = {"passes": False, "no_guide": False}
        bad = {"passes": False, "no_guide": True}
        assert honesty.outcome({"a": good, "b": good}) == "checked"
        assert honesty.outcome({"a": good, "b": middling}) == "rough guide"
        assert honesty.outcome({"a": good, "b": bad}) == "rough guide"
        assert honesty.outcome({"a": bad, "b": bad}) == "no guide"


class TestTheSpread:
    def test_all_found_cannot_move(self):
        assert honesty.spread([1] * 50) == {"questions": 20, "low": 1.0, "high": 1.0}

    def test_half_found_moves_both_ways(self):
        got = honesty.spread([1, None] * 25)
        assert got["low"] < 0.5 < got["high"]

    def test_rank_six_is_a_miss(self):
        assert honesty.spread([6] * 10)["high"] == 0.0


class _FakeModels:
    def __init__(self, text: str):
        self.text = text
        self.calls: list[dict] = []

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        usage = SimpleNamespace(
            prompt_token_count=10_000, candidates_token_count=1_000, thoughts_token_count=1_000
        )
        return SimpleNamespace(text=self.text, usage_metadata=usage)


class TestTheWriter:
    SAMPLED = {
        "instructions": "write questions",
        "passages": [{"passage_id": "d#0", "text": "a passage", "title": "Secret title"}],
    }

    def test_it_sends_the_tools_instructions_and_passages_only(self):
        models = _FakeModels(json.dumps([{"passage_id": "d#0", "question": "why?"}]))
        client = SimpleNamespace(models=models)
        questions, spent = asyncio.run(
            honesty.write_questions(client, "gemini-3.1-flash-lite", self.SAMPLED)
        )
        assert questions == [{"passage_id": "d#0", "question": "why?"}]
        sent = models.calls[0]
        assert sent["config"].system_instruction.startswith("write questions")
        assert json.loads(sent["contents"]) == [{"passage_id": "d#0", "text": "a passage"}]
        assert "Secret title" not in sent["contents"]
        # 10k in at $0.25, 2k out (thinking included) at $1.50.
        assert spent == pytest.approx(0.0055)

    def test_every_writer_has_a_price(self):
        assert set(honesty.WRITERS) <= set(honesty.PRICES)

    def test_the_budget_stops_the_next_call(self):
        ledger = {"usd": honesty.BUDGET_USD}
        with pytest.raises(honesty.OverBudget):
            honesty._check_budget(ledger)
        honesty._check_budget({"usd": 0.0})
