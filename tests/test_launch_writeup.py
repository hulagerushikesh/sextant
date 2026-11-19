"""The launch write-up types its figures by hand, so pin each one to the results page.

RESULTS.md is generated from the measurement files; a figure in the draft that
no longer appears there has gone stale and must be re-read before publishing.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRAFT = ROOT / "planning" / "launch-writeup.md"
RESULTS = ROOT / "docs" / "RESULTS.md"

FIGURE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+\.\d+|\d+%)(?![\w.]*\d)")


def figures(text: str) -> set[str]:
    return set(FIGURE.findall(text))


def test_every_figure_in_the_draft_is_on_the_results_page() -> None:
    results = RESULTS.read_text()
    stale = sorted(f for f in figures(DRAFT.read_text()) if f not in results)
    assert not stale, f"figures not on docs/RESULTS.md: {stale}"


def test_the_check_reads_figures() -> None:
    found = figures("first 93% of the time; 0.312 against 0.316 at 85,362 passages")
    assert found == {"93%", "0.312", "0.316", "85,362"}
    assert figures("on 2026-11-19, version 0.11.1") == set()
