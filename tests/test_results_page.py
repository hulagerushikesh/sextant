"""The results page is generated, and this is what makes that true.

`docs/RESULTS.md` is the page a visitor judges the project by. A figure typed
into a page like that is written on the day it flatters and not revisited, so
every figure on it comes from a measurement file -- and these tests are the
only reason that sentence stays true after the next re-run.
"""

from __future__ import annotations

import re

import pytest

from sextant import settings
from sextant.eval import public_sets, results_page


def _page() -> str:
    root = settings.repo_root()
    assert root is not None
    return (root / results_page.PAGE).read_text()


class TestTheResultsPageMatchesTheMeasurementFiles:
    def test_the_committed_page_is_what_the_files_generate(self):
        assert _page() == results_page.render(), (
            "docs/RESULTS.md is stale: run `python -m sextant.eval.results_page --write`"
        )

    def test_the_check_command_agrees(self, capsys):
        assert results_page.main(["--check"]) == 0
        assert "match" in capsys.readouterr().out

    def test_the_readme_table_is_the_generated_one(self):
        """The first number a visitor sees was two baselines old once."""
        root = settings.repo_root()
        assert root is not None
        readme = (root / results_page.README).read_text()
        assert results_page.with_summary(readme) == readme, (
            "README.md's results table is stale: run "
            "`python -m sextant.eval.results_page --write`"
        )
        between = readme.split(results_page.BLOCK_START)[1].split(results_page.BLOCK_END)[0]
        assert between.strip() == results_page.render_summary()
        assert "%" in between, "the block is empty"

    def test_a_readme_without_the_markers_is_refused(self):
        with pytest.raises(results_page.StaleSource, match="exactly once"):
            results_page.with_summary("# a README nobody marked\n")

    def test_a_changed_baseline_changes_the_page(self, monkeypatch):
        """The test above is vacuous if the page ignores the files."""
        real = results_page._baseline

        def moved(name: str):
            loaded = real(name)
            if name == "baseline.json":
                loaded["modes"]["rerank"]["hit@1"] -= 0.1
            return loaded

        monkeypatch.setattr(results_page, "_baseline", moved)
        assert results_page.render() != _page()
        root = settings.repo_root()
        assert root is not None
        readme = (root / results_page.README).read_text()
        assert results_page.with_summary(readme) != readme
        assert results_page.main(["--check"]) == 1

    def test_a_changed_threshold_sweep_changes_the_page(self, monkeypatch):
        real = results_page._baseline

        def moved(name: str):
            loaded = real(name)
            loaded["threshold_sweep"][results_page.FLOOR]["answerable_lost"] += 1
            return loaded

        monkeypatch.setattr(results_page, "_baseline", moved)
        assert results_page.render() != _page()


class TestARejectedIdeaIsOnlyAsGoodAsItsNote:
    def test_there_are_nine_and_each_names_a_note_that_exists(self):
        root = settings.repo_root()
        assert root is not None
        assert len(results_page.REJECTED) == 9
        for row in results_page.REJECTED:
            assert (root / results_page.NOTES / row.note).is_file(), row.note
            assert row.quotes, f"{row.idea} quotes nothing"

    @pytest.mark.parametrize("row", results_page.REJECTED, ids=lambda row: row.note)
    def test_every_figure_in_a_finding_is_in_what_it_quotes(self, row):
        """A finding may reword its note; it may not bring its own numbers."""
        quoted = " ".join(row.quotes + row.retest)
        figures = re.findall(r"\d+(?:\.\d+)?", row.finding)
        assert figures, f"{row.idea} states no figure"
        missing = [figure for figure in figures if figure not in quoted]
        assert not missing, f"{row.idea}: {missing} appear in the finding and in none of its quotes"

    def test_a_note_that_stops_saying_it_stops_the_page(self, monkeypatch):
        first = results_page.REJECTED[0]
        never = ("a sentence this note has never contained",)
        gone = results_page.Rejected(first.idea, first.finding, first.note, never)
        monkeypatch.setattr(results_page, "REJECTED", (gone, *results_page.REJECTED[1:]))
        with pytest.raises(results_page.StaleSource, match="no longer says"):
            results_page.render()
        assert results_page.main(["--check"]) == 1

    def test_the_cost_is_computed_from_the_note_not_typed(self):
        root = settings.repo_root()
        assert root is not None
        text = (root / results_page.NOTES / results_page.COST_NOTE).read_text()
        match = results_page.COST_PATTERN.search(" ".join(text.split()))
        assert match is not None
        per_question = float(match["agent"]) / int(match["runs"])
        assert f"${per_question:.4f}" in _page()

    def test_a_note_that_restates_its_cost_stops_the_page(self, monkeypatch):
        monkeypatch.setattr(results_page, "COST_PATTERN", re.compile(r"never matches \d+"))
        with pytest.raises(results_page.StaleSource, match="run cost"):
            results_page.render()


class TestThePageSaysWhereItCameFrom:
    def test_it_is_refused_outside_a_checkout(self, monkeypatch):
        """In a wheel the notes are absent; half a page is worse than none."""
        monkeypatch.setattr(settings, "repo_root", lambda: None)
        with pytest.raises(results_page.StaleSource, match="checkout"):
            results_page.render()
        assert results_page.main([]) == 1


class TestTheFirstScreenSaysWhereItLoses:
    """Milestone 28's rule: a loss to a plain baseline is said in the first screen."""

    def test_it_comes_before_everything_else(self):
        page = _page()
        assert page.index("## Where it loses to a plain baseline") < page.index(
            "## How good is it"
        )
        first_screen = "\n".join(page.splitlines()[:30])
        for line in results_page.public_losses():
            assert line in first_screen

    def test_the_two_known_losses_are_said(self):
        losses = "\n".join(results_page.public_losses())
        assert "**Its keyword search loses to plain BM25 (the BEIR paper's)** on all three" in (
            losses
        )
        assert "below meaning search alone**: FiQA 0.341 against 0.372" in losses

    def test_a_new_loss_in_the_measurement_appears(self, monkeypatch):
        real = results_page._measurement

        def worse(name: str):
            loaded = real(name)
            if name == "public-sets.json":
                loaded["sets"]["scifact"]["modes"]["rerank"]["ndcg@10"] = 0.5
            return loaded

        monkeypatch.setattr(results_page, "_measurement", worse)
        losses = "\n".join(results_page.public_losses())
        assert "**The full search loses to the paper's BM25 + re-reading baseline**" in losses
        assert "SciFact 0.500 against 0.688" in losses
        assert results_page.render() != _page()

    def test_no_loss_is_said_as_none(self, monkeypatch):
        monkeypatch.setattr(results_page, "public_losses", lambda: [])
        assert "- Nowhere" in "\n".join(results_page._first_screen())

    def test_figures_round_as_the_notes_do(self):
        assert results_page._three(0.3635) == "0.364"
        assert results_page._three(0.31594) == "0.316"


class TestAStrangerCanReproduceOneSet:
    def test_the_page_gives_the_one_command_for_a_set_it_can_fetch(self):
        command = f"python -m sextant.eval.public_sets --set {results_page.REPRODUCE_SET} --check"
        assert command in _page()
        assert results_page.REPRODUCE_SET in public_sets.ARCHIVES
