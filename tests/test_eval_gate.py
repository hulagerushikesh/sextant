"""The gate on retrieval quality, and what it cannot see.

`sextant-eval --check` is CI's only check on retrieval quality, and it had no
tests at all. The interesting failures are not wrong arithmetic -- the
comparison itself was right -- but the ways the comparison could quietly stop
covering anything: grade one mode of four, rename a metric, delete sixty
golden questions. Each made the numbers look better and none of them failed.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from eval import harness

MODES = ("dense", "lexical", "rrf", "rerank")
METRICS = ("hit@1", "recall@3", "recall@5", "mrr", "ndcg@5")
QUESTIONS = 65


def _metrics(**overrides: float) -> dict[str, Any]:
    values: dict[str, Any] = {name: 0.9 for name in METRICS}
    values["scored_by"] = "cosine"
    values.update(overrides)
    return values


def _report(mode: str, **overrides: float) -> dict[str, Any]:
    return {"mode": mode, "metrics": _metrics(**overrides), "failures": []}


def _write_baseline(tmp_path: Path, monkeypatch, questions: int | None = QUESTIONS) -> Path:
    payload: dict[str, Any] = {"modes": {mode: _metrics() for mode in MODES}}
    if questions is not None:
        payload["questions"] = questions
    path = tmp_path / "baseline.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setattr(harness, "BASELINE_PATH", path)
    return path


class TestTheGateComparesWhatItClaimsTo:
    def test_a_matching_run_passes(self, tmp_path, monkeypatch, capsys):
        _write_baseline(tmp_path, monkeypatch)
        code = harness.check_against_baseline([_report(m) for m in MODES], QUESTIONS)
        assert code == 0
        assert "no regressions" in capsys.readouterr().out

    def test_a_real_regression_still_fails(self, tmp_path, monkeypatch, capsys):
        _write_baseline(tmp_path, monkeypatch)
        reports = [_report(m) for m in MODES]
        reports[3]["metrics"]["recall@5"] = 0.9 - harness.REGRESSION_TOLERANCE - 0.01
        assert harness.check_against_baseline(reports, QUESTIONS) == 1
        assert "rerank.recall@5" in capsys.readouterr().out

    def test_a_drop_of_exactly_the_tolerance_is_at_the_gate_not_past_it(
        self, tmp_path, monkeypatch
    ):
        _write_baseline(tmp_path, monkeypatch)
        reports = [_report(m) for m in MODES]
        reports[0]["metrics"]["mrr"] = 0.9 - harness.REGRESSION_TOLERANCE
        assert harness.check_against_baseline(reports, QUESTIONS) == 0


class TestTheGateCannotNarrowItsOwnScope:
    def test_a_mode_the_baseline_grades_and_the_run_skipped_fails(
        self, tmp_path, monkeypatch, capsys
    ):
        # `--check --modes dense` graded a quarter of the gate and reported no
        # regressions, because the loop walks the reports: a mode that was
        # never run leaves nothing behind to notice.
        _write_baseline(tmp_path, monkeypatch)
        assert harness.check_against_baseline([_report("dense")], QUESTIONS) == 1
        out = capsys.readouterr().out
        assert "not graded" in out
        for skipped in ("lexical", "rrf", "rerank"):
            assert skipped in out

    def test_a_metric_the_baseline_grades_and_the_run_dropped_fails(
        self, tmp_path, monkeypatch, capsys
    ):
        # Renaming a metric used to un-check it for free: the absent name
        # defaulted to the value it was being compared against, so the delta
        # was always exactly zero.
        _write_baseline(tmp_path, monkeypatch)
        reports = [_report(m) for m in MODES]
        del reports[3]["metrics"]["recall@5"]
        reports[3]["metrics"]["recall_at_5"] = 0.1
        assert harness.check_against_baseline(reports, QUESTIONS) == 1
        assert "no longer reports recall@5" in capsys.readouterr().out

    def test_a_shorter_golden_set_fails(self, tmp_path, monkeypatch, capsys):
        # Fewer questions is less evidence, and the easy ones survive, so every
        # metric rises. Nothing read the question count.
        _write_baseline(tmp_path, monkeypatch)
        assert harness.check_against_baseline([_report(m) for m in MODES], 5) == 1
        assert "5 questions, baseline used 65" in capsys.readouterr().out

    def test_a_longer_golden_set_is_fine(self, tmp_path, monkeypatch):
        _write_baseline(tmp_path, monkeypatch)
        assert harness.check_against_baseline([_report(m) for m in MODES], 120) == 0

    def test_a_baseline_with_no_question_count_fails(self, tmp_path, monkeypatch, capsys):
        _write_baseline(tmp_path, monkeypatch, questions=None)
        assert harness.check_against_baseline([_report(m) for m in MODES], QUESTIONS) == 1
        assert "records no question count" in capsys.readouterr().out

    def test_a_missing_baseline_fails(self, tmp_path, monkeypatch, capsys):
        # `--check` is a claim that a committed baseline was matched. No
        # baseline is could-not-tell, which is a third outcome, not a pass.
        monkeypatch.setattr(harness, "BASELINE_PATH", tmp_path / "absent.json")
        assert harness.check_against_baseline([_report(m) for m in MODES], QUESTIONS) == 1
        assert "nothing to compare" in capsys.readouterr().out


class TestSomethingGenuinelyNewIsReportedNotFailed:
    def test_an_added_mode_is_reported(self, tmp_path, monkeypatch, capsys):
        _write_baseline(tmp_path, monkeypatch)
        reports = [_report(m) for m in (*MODES, "splade")]
        assert harness.check_against_baseline(reports, QUESTIONS) == 0
        assert "splade: new configuration" in capsys.readouterr().out

    def test_an_added_metric_is_reported(self, tmp_path, monkeypatch, capsys):
        _write_baseline(tmp_path, monkeypatch)
        reports = [_report(m) for m in MODES]
        reports[0]["metrics"]["recall@20"] = 0.99
        assert harness.check_against_baseline(reports, QUESTIONS) == 0
        assert "new metric" in capsys.readouterr().out


class TestCheckRefusesAPartialGateBeforeGrading:
    """The parser guard, so `--check --modes dense` costs a second, not a minute."""

    class Grading(Exception):
        """Raised in place of the real eval, to prove grading was reached."""

    @pytest.fixture
    def never_grade(self, monkeypatch):
        def boom(coro=None, *args, **kwargs):
            if coro is not None:
                coro.close()  # the real run() is never awaited; do not warn about it
            raise TestCheckRefusesAPartialGateBeforeGrading.Grading

        monkeypatch.setattr(asyncio, "run", boom)

    def test_a_narrowed_mode_set_is_refused(self, monkeypatch, never_grade):
        monkeypatch.setattr(sys, "argv", ["sextant-eval", "--check", "--modes", "dense"])
        with pytest.raises(SystemExit) as caught:
            harness.main()
        assert caught.value.code == 2, "argparse usage error, not a graded run"

    def test_the_full_mode_set_reaches_grading(self, monkeypatch, never_grade):
        # The guard must refuse a *smaller* set, not every use of --modes.
        monkeypatch.setattr(sys, "argv", ["sextant-eval", "--check", "--modes", *MODES])
        with pytest.raises(TestCheckRefusesAPartialGateBeforeGrading.Grading):
            harness.main()

    def test_a_narrowed_mode_set_without_check_is_allowed(self, monkeypatch, never_grade):
        monkeypatch.setattr(sys, "argv", ["sextant-eval", "--modes", "dense"])
        with pytest.raises(TestCheckRefusesAPartialGateBeforeGrading.Grading):
            harness.main()


class TestTheCommittedBaselineIsWhatCiCompares:
    def test_it_records_every_mode_the_code_can_run(self):
        from tools.vector_db.vector_search import RETRIEVAL_MODES

        baseline = json.loads(harness.BASELINE_PATH.read_text())
        assert set(baseline["modes"]) == set(RETRIEVAL_MODES)

    def test_it_records_the_question_count_of_the_committed_golden_set(self):
        baseline = json.loads(harness.BASELINE_PATH.read_text())
        assert baseline["questions"] == len(harness.load_golden())
