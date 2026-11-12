"""
The results page, written from the measurement files rather than by hand.

`docs/RESULTS.md` is the one page a visitor reads to answer "how good is it,
how do you know, what did you reject". Every figure on it comes from a file a
measurement wrote: the two committed baselines, the golden sets, and the notes
in `learning/`. A baseline figure is formatted here; a note's figure is quoted,
and the quote has to be in the note -- so a note that is corrected, or a
baseline that is re-run, fails `--check` until the page is regenerated.

    python -m sextant.eval.results_page            # print
    python -m sextant.eval.results_page --write    # write docs/RESULTS.md
    python -m sextant.eval.results_page --check    # exit 1 if the page is stale

This is a checkout tool: the notes are not in the wheel, and it says so
instead of writing a page with half its sources missing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sextant import settings
from sextant.eval.harness import CORPUS_DIR, REGRESSION_TOLERANCE

EVAL_DIR = Path(__file__).resolve().parent
PAGE = Path("docs") / "RESULTS.md"
NOTES = Path("learning")

MODES = (
    ("dense", "Meaning search only"),
    ("lexical", "Keyword search only"),
    ("rrf", "Both, fused"),
    ("rerank", "Both, fused, then re-read (the shipped pipeline)"),
)
METRICS = (
    ("hit@1", "right passage first"),
    ("recall@3", "recall@3"),
    ("recall@5", "recall@5"),
    ("mrr", "MRR"),
    ("ndcg@5", "nDCG@5"),
)
# The score under which `kb_search` returns nothing; the sweep is keyed by it.
FLOOR = "0.01"


@dataclass(frozen=True)
class Rejected:
    """One idea that was measured and not shipped.

    `quotes` are copied from `note`. `render` refuses to run if any of them
    is no longer there, and a test refuses a `finding` whose figures are not
    in its quotes -- together the only thing that makes a number in this
    table more than something somebody typed.
    """

    idea: str
    finding: str
    note: str
    quotes: tuple[str, ...]


REJECTED = (
    Rejected(
        "A tree of summaries (RAPTOR)",
        "The questions a tree would serve already scored 1.000 hit@5 without one.",
        "summary-chunks.md",
        ("Global hit@5 was 1.000 before", "No RAPTOR tree."),
    ),
    Rejected(
        "A newer embedding model (bge-small)",
        "Gains 0.091 first-result hit rate on one test set, loses 0.04 on the other; "
        "the rule said both.",
        "embedder-swap.md",
        ("+0.091 dense hit@1", "On the handbook it loses 0.04 hit@1"),
    ),
    Rejected(
        "Smaller passages (150 tokens instead of 200)",
        "Meaning search alone fell from 0.820 to 0.720 on the handbook set.",
        "chunk-size.md",
        ("| MiniLM | 150 | 0.720 |", "| MiniLM | 200 | **0.820** |", "**200 stays.**"),
    ),
    Rejected(
        "Dropping the re-reading stage (the reranker)",
        "On the long-paper set it scores 0.000 on every off-topic question; "
        "no other stage separates them.",
        "reranker-decision.md",
        ("It puts 0.000 on every off-corpus question",),
    ),
    Rejected(
        "Letting the model imagine an answer first (HyDE)",
        "Meaning search fell from 0.873 to 0.800, and after re-reading the score "
        "was 0.909 either way.",
        "hyde.md",
        (
            "| control | dense | 0.873 |",
            "| hyde_dense | dense | 0.800 |",
            "| control | rerank | 0.909 |",
            "| hyde_dense | rerank | 0.909 |",
        ),
    ),
    Rejected(
        "Prompt caching",
        "A 28% net saving, against the 30% the rule asked for.",
        "prompt-caching.md",
        ("**28%**, against the 30% the rule",),
    ),
    Rejected(
        "A fallback below the confidence floor, as a cost saving",
        "Across all 55 answerable questions it fired once.",
        "floor-fallback-cost.md",
        ("across all 55 answerable questions the fallback fired **once**",),
    ),
    Rejected(
        "The same fallback, as a way to find missed answers",
        "The question it was built for scored 0.5 with it and 0.5 without.",
        "floor-fallback.md",
        (
            "| handbook | none | q29 1.0, q47 0.5, q48 0.5,",
            "| handbook | dense | q29 1.0, q47 0.5, q48 0.5,",
        ),
    ),
    Rejected(
        "Choosing a different index per question",
        "One index already reaches 0.996 recall in 1.48 ms at 100k passages.",
        "ivfpq-100k.md",
        ("HNSW at 100k: recall 0.996 at 1.48 ms",),
    ),
)

# Where the cost of a question was last measured across a whole test set.
COST_NOTE = "floor-fallback-cost.md"
COST_PATTERN = re.compile(
    r"Cost: \$(?P<usd>[\d.]+) ≈ ₹(?P<inr>[\d.]+) "
    r"\((?P<runs>\d+) agent runs \$(?P<agent>[\d.]+)"
)


class StaleSource(RuntimeError):
    """A source no longer says what the page would claim it says."""


def _squash(text: str) -> str:
    return " ".join(text.split())


def _root() -> Path:
    root = settings.repo_root()
    if root is None:
        raise StaleSource(
            "the results page is built in a checkout: the notes it quotes are not in the wheel"
        )
    return root


def _baseline(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads((EVAL_DIR / name).read_text())
    return loaded


def _split(golden: str) -> tuple[int, int]:
    """(answerable, unanswerable) questions in a golden set."""
    lines = (EVAL_DIR / golden).read_text().splitlines()
    rows = [json.loads(line) for line in lines if line.strip()]
    answerable = sum(1 for row in rows if row["answerable"])
    return answerable, len(rows) - answerable


def _pct(value: float) -> str:
    return f"{round(value * 100)}%"


def _comparison(baseline: dict[str, Any]) -> list[str]:
    lines = [
        "| Stage | " + " | ".join(label for _, label in METRICS) + " |",
        "| --- |" + " --- |" * len(METRICS),
    ]
    for mode, label in MODES:
        row = baseline["modes"][mode]
        cells = " | ".join(f"{row[metric]:.3f}" for metric, _ in METRICS)
        lines.append(f"| {label} | {cells} |")
    return lines


def _abstention(baseline: dict[str, Any], golden: str) -> str:
    answerable, unanswerable = _split(golden)
    sweep = baseline["threshold_sweep"][FLOOR]
    return (
        f"declines **{sweep['unanswerable_blocked']} of {unanswerable}** questions the "
        f"documents cannot answer, and wrongly declines {sweep['answerable_lost']} of "
        f"{answerable} that they can"
    )


def _rejected(root: Path) -> list[str]:
    lines = ["| Idea | What the measurement said | Note |", "| --- | --- | --- |"]
    for row in REJECTED:
        note = _squash((root / NOTES / row.note).read_text())
        for quote in row.quotes:
            if _squash(quote) not in note:
                raise StaleSource(
                    f"learning/{row.note} no longer says {quote!r} -- "
                    f"the row for {row.idea!r} is unsupported"
                )
        link = f"[`{row.note}`](../learning/{row.note})"
        lines.append(f"| {row.idea} | {row.finding} | {link} |")
    return lines


def _cost(root: Path) -> list[str]:
    match = COST_PATTERN.search(_squash((root / NOTES / COST_NOTE).read_text()))
    if match is None:
        raise StaleSource(
            f"learning/{COST_NOTE} no longer states its run cost in the form this page reads"
        )
    runs, agent = int(match["runs"]), float(match["agent"])
    rupees_per_dollar = float(match["inr"]) / float(match["usd"])
    per_question = agent / runs
    link = f"[`{COST_NOTE}`](../learning/{COST_NOTE})"
    return [
        f"**About ₹{per_question * rupees_per_dollar:.2f} a question** "
        f"(${per_question:.4f}): {runs} complete answers cost ${agent:.3f} in the "
        f"whole-set run that note records, converted at the note's own rate of "
        f"₹{rupees_per_dollar:.0f} to the dollar ({link}). Searching alone costs "
        "nothing: the search models run on your machine, and only writing the "
        "answer calls a paid model.",
    ]


def render() -> str:
    """The page, or `StaleSource` if a source stopped supporting it."""
    root = _root()
    small, large = _baseline("baseline.json"), _baseline("baseline-large.json")
    small_answerable, _ = _split("golden.jsonl")
    large_answerable, _ = _split("golden-large.jsonl")
    best, plain = small["modes"]["rerank"]["hit@1"], small["modes"]["dense"]["hit@1"]
    documents = len(list(CORPUS_DIR.glob("*.md")))
    lines = [
        "# Results",
        "",
        "How good the search is, how that is known, and what was tried and rejected.",
        "",
        "> Generated by `python -m sextant.eval.results_page --write` from the committed",
        "> measurement files. Do not edit it by hand: a test fails when this page and",
        "> the files disagree.",
        "",
        "## How good is it",
        "",
        f"On {small['questions']} test questions over {documents} documents, the shipped "
        f"pipeline puts the right passage first **{_pct(best)}** of the time. Plain "
        f"meaning search manages {_pct(plain)}. Each stage below is in the product "
        "because this table says it earns its place.",
        "",
        *_comparison(small),
        "",
        f"Scored on the {small_answerable} questions that have an answer. The same four "
        f"stages on a harder set — {large['questions']} questions over one long research "
        f"paper, {large_answerable} with an answer, graded by page:",
        "",
        *_comparison(large),
        "",
        "## Knowing when not to answer",
        "",
        "A search that always returns something will happily answer a question the",
        "documents cannot. The last stage's score is what lets the system decline.",
        "",
        f"- Small set: it {_abstention(small, 'golden.jsonl')}.",
        f"- Large set: it {_abstention(large, 'golden-large.jsonl')}.",
        "",
        f"## What was tried and rejected ({len(REJECTED)} ideas)",
        "",
        "Each had a pass rule written before it ran. None is argued again without a",
        "new fact; the linked note has the method and the full tables.",
        "",
        *_rejected(root),
        "",
        "## What a question costs",
        "",
        *_cost(root),
        "",
        "## Check it yourself",
        "",
        "```bash",
        "sextant-eval",
        "```",
        "",
        f"That rebuilds the index from the {documents} committed documents and prints the "
        "first table above. It needs no key and spends nothing. `sextant-eval --check` "
        "compares the run against the committed figures and fails on any drop over "
        f"{REGRESSION_TOLERANCE}; that check runs on every change to the project.",
        "",
        "What these numbers do **not** show: the questions and the documents were",
        "written together, so this grades the search pipeline, not how it will do on",
        "someone else's library.",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write docs/RESULTS.md from measurements.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write", action="store_true", help="write the page")
    group.add_argument("--check", action="store_true", help="exit 1 if the page is stale")
    args = parser.parse_args(argv)
    try:
        page = render()
        target = _root() / PAGE
    except StaleSource as problem:
        print(f"FAILED: {problem}", file=sys.stderr)
        return 1
    if args.write:
        target.parent.mkdir(exist_ok=True)
        target.write_text(page)
        print(f"wrote {PAGE}")
        return 0
    if args.check:
        if not target.is_file() or target.read_text() != page:
            print(f"FAILED: {PAGE} is stale; run with --write", file=sys.stderr)
            return 1
        print(f"{PAGE} matches the measurement files")
        return 0
    print(page, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
