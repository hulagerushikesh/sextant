"""The two rejected ideas re-tested on the public sets, and the rule that judged them."""

from __future__ import annotations

import pytest

from sextant import settings
from sextant.eval import retest


def _run(**ndcg: float) -> dict:
    return {"modes": {mode: {"ndcg@10": value} for mode, value in ndcg.items()}}


CONTROL = {name: _run(dense=0.30, lexical=0.30, rrf=0.30, rerank=0.30) for name in retest.SETS}


class TestTheRule:
    def test_a_gain_on_every_set_with_nothing_falling_is_adopted(self):
        runs = {name: _run(dense=0.34, lexical=0.30, rrf=0.30, rerank=0.30) for name in retest.SETS}
        assert retest.judge(CONTROL, runs, "dense", ("rerank",)) == {
            "verdict": "adopted",
            "reasons": [],
        }

    def test_one_set_short_of_the_gain_rejects(self):
        runs = {name: _run(dense=0.34, rerank=0.30) for name in retest.SETS}
        runs["fiqa"] = _run(dense=0.32, rerank=0.30)
        got = retest.judge(CONTROL, runs, "dense", ("rerank",))
        assert got["verdict"] == "rejected"
        assert got["reasons"] == ["fiqa: dense +0.020, needs +0.03"]

    def test_a_guarded_stage_falling_past_the_tolerance_rejects(self):
        runs = {name: _run(dense=0.34, rerank=0.27) for name in retest.SETS}
        got = retest.judge(CONTROL, runs, "dense", ("rerank",))
        assert got["verdict"] == "rejected" and "rerank -0.030" in got["reasons"][0]

    def test_passing_the_sets_run_so_far_is_not_adoption(self):
        runs = {"nfcorpus": _run(dense=0.34, rerank=0.30)}
        assert retest.judge(CONTROL, runs, "dense", ("rerank",))["verdict"] == "undecided"


class TestTheCommittedRuns:
    def test_each_candidate_changed_one_thing(self):
        control = retest.load("public-sets.json")["sets"]
        candidates = retest.load("retest.json")["candidates"]
        for name, run in candidates["chunk_150"]["runs"].items():
            assert run["chunk_tokens"] == 150
            assert run["embedding_model"] == control[name]["embedding_model"]
        for run in candidates["bge_small"]["runs"].values():
            assert run["chunk_tokens"] == 200
            assert run["embedding_model"] == "BAAI/bge-small-en-v1.5"
        for candidate in candidates.values():
            for name, run in candidate["runs"].items():
                assert run["questions"] == control[name]["questions"]
                assert run["stored"]["documents"] == control[name]["stored"]["documents"]

    def test_both_stay_rejected_for_the_reasons_the_note_gives(self):
        got = retest.verdicts()
        assert got["chunk_150"] == {
            "verdict": "rejected",
            "reasons": ["nfcorpus: rerank -0.005, needs +0.03"],
        }
        assert got["bge_small"] == {
            "verdict": "rejected",
            "reasons": ["fiqa: dense +0.014, needs +0.03"],
        }

    @pytest.mark.parametrize("key", list(retest.RULES))
    def test_the_note_says_what_the_code_computes(self, key):
        root = settings.repo_root()
        assert root is not None
        note = (root / "learning" / "rejected-retest.md").read_text()
        verdict = retest.verdicts()[key]["verdict"]
        assert {"rejected": "Both stay rejected."}[verdict] in note
