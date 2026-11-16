"""The large-library speed measurement and the rule it is judged by."""

from __future__ import annotations

import json

import pytest

from sextant import settings
from sextant.eval import results_page, scale


class TestPercentile:
    def test_nearest_rank(self):
        values = list(range(1, 21))  # 1..20
        assert scale.percentile(values, 95) == 19
        assert scale.percentile(values, 50) == 10
        assert scale.percentile(values, 100) == 20
        assert scale.percentile([7.0], 95) == 7.0

    def test_order_does_not_matter(self):
        assert scale.percentile([5, 1, 4, 2, 3], 50) == 3

    def test_nothing_to_rank_is_refused(self):
        with pytest.raises(ValueError):
            scale.percentile([], 95)


class TestTheRule:
    def test_fast_on_every_count_is_not_slow(self):
        assert scale.verdict(1999, 199, 29) == {"slow": False, "reasons": []}

    @pytest.mark.parametrize(
        ("full", "dense", "first", "word"),
        [(2001, 10, 5, "full"), (500, 201, 5, "dense"), (500, 10, 31, "first")],
    )
    def test_any_one_count_over_its_limit_is_slow(self, full, dense, first, word):
        got = scale.verdict(full, dense, first)
        assert got["slow"] and len(got["reasons"]) == 1 and word in got["reasons"][0]


class TestTheCommittedMeasurement:
    def _measured(self) -> dict:
        return json.loads((scale.Path(scale.__file__).parent / "scale.json").read_text())

    def test_its_verdict_is_what_the_rule_gives_today(self):
        """A file whose verdict was computed under an older rule must not stand."""
        m = self._measured()
        assert m["rule"] == {
            "full_p95_ms_max": scale.SLOW_FULL_P95_MS,
            "dense_p95_ms_max": scale.SLOW_DENSE_P95_MS,
            "first_answer_s_max": scale.SLOW_FIRST_ANSWER_S,
        }
        assert m["verdict"] == scale.verdict(
            m["stages"]["rerank"]["p95_ms"], m["stages"]["dense"]["p95_ms"], m["first_answer_s"]
        )

    def test_it_is_the_large_set(self):
        m = self._measured()
        assert m["set"] == "fiqa" and m["chunks"] > 57_000

    def test_the_page_states_the_verdict_and_the_figures(self):
        root = settings.repo_root()
        assert root is not None
        page = (root / results_page.PAGE).read_text()
        m = self._measured()
        assert ("**not slow**" in page) is (not m["verdict"]["slow"])
        assert f"{m['stages']['rerank']['p95_ms']:.0f} ms" in page
        assert f"{m['first_answer_s']:.1f} s" in page

    def test_a_slow_verdict_is_said_with_its_reason(self, monkeypatch):
        m = self._measured()
        slow = {**m, "verdict": {"slow": True, "reasons": ["dense p95 900 ms > 200 ms"]}}
        monkeypatch.setattr(results_page, "_measurement", lambda name: slow)
        text = "\n".join(results_page._speed())
        assert "**This counts as slow**" in text and "dense p95 900 ms" in text
        assert "not slow" not in text
