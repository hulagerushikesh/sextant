"""
The results page, written from the measurement files rather than by hand.

`docs/RESULTS.md` is the one page a visitor reads to answer "how good is it,
how do you know, what did you reject". Every figure on it comes from a file a
measurement wrote: the two committed baselines, the golden sets, and the notes
in `learning/`. A baseline figure is formatted here; a note's figure is quoted,
and the quote has to be in the note -- so a note that is corrected, or a
baseline that is re-run, fails `--check` until the page is regenerated.

    python -m sextant.eval.results_page            # print
    python -m sextant.eval.results_page --write    # write the page and the README table
    python -m sextant.eval.results_page --check    # exit 1 if either is stale

The README carries a four-row summary between two markers. It is written by
the same command for the same reason: it is the first number a visitor sees,
and it was two baselines out of date on the day this module was written.

This is a checkout tool: the notes are not in the wheel, and it says so
instead of writing a page with half its sources missing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from sextant import settings
from sextant.eval import public_sets
from sextant.eval.harness import CORPUS_DIR, REGRESSION_TOLERANCE

EVAL_DIR = Path(__file__).resolve().parent
PAGE = Path("docs") / "RESULTS.md"
README = Path("README.md")
BLOCK_START, BLOCK_END = "<!-- results:start -->", "<!-- results:end -->"
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
    # Quotes from the public-set re-test note, for the two ideas it re-ran.
    retest: tuple[str, ...] = ()


RETEST_NOTE = "rejected-retest.md"


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
        "the rule said both. Re-tested on the public sets: meaning search gains only "
        "0.014 on FiQA against the 0.03 asked, and the full search moves by at most 0.011.",
        "embedder-swap.md",
        ("+0.091 dense hit@1", "On the handbook it loses 0.04 hit@1"),
        (
            "| FiQA | 0.3722 → 0.3865 | **+0.014** |",
            "rises by **≥ 0.03 on all three sets**",
            "the better embedder changes the answer by at most 0.011",
        ),
    ),
    Rejected(
        "Smaller passages (150 tokens instead of 200)",
        "Meaning search alone fell from 0.820 to 0.720 on the handbook set. Re-tested "
        "on the public sets: the full search fell 0.005 on NFCorpus where it had to "
        "gain 0.03.",
        "chunk-size.md",
        ("| MiniLM | 150 | 0.720 |", "| MiniLM | 200 | **0.820** |", "**200 stays.**"),
        ("The full pipeline had to gain 0.03 and lost 0.005 instead.",),
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


def _measurement(name: str) -> dict[str, Any]:
    """A measurement file that is not a quality baseline (speed, public sets)."""
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
        sources = [(row.note, row.quotes)] + ([(RETEST_NOTE, row.retest)] if row.retest else [])
        for name, quotes in sources:
            note = _squash((root / NOTES / name).read_text())
            for quote in quotes:
                if _squash(quote) not in note:
                    raise StaleSource(
                        f"learning/{name} no longer says {quote!r} -- "
                        f"the row for {row.idea!r} is unsupported"
                    )
        link = ", ".join(f"[`{name}`](../learning/{name})" for name, _ in sources)
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


SET_NAMES = {"fiqa": "FiQA", "nfcorpus": "NFCorpus", "scifact": "SciFact"}
PUBLIC_SETS = ("nfcorpus", "scifact", "fiqa")  # smallest first
# The set a stranger is told to reproduce: the smallest download.
REPRODUCE_SET = "nfcorpus"
BASELINES = {
    "bm25": "plain BM25 (the BEIR paper's)",
    "minilm_dense": "the published score of the same meaning model",
    "bm25_ce": "the paper's BM25 + re-reading baseline",
}
# Each stage against the plain baselines it could be replaced by. `None` is
# the stage before it in the product: fusion must beat meaning search alone.
COMPARED = (
    ("dense", "Its meaning search", ("minilm_dense",)),
    ("lexical", "Its keyword search", ("bm25",)),
    ("rrf", "Fusing keyword with meaning search", (None,)),
    ("rerank", "The full search", ("bm25", "minilm_dense", "bm25_ce")),
)


def _where(names: list[str]) -> str:
    if len(names) == len(PUBLIC_SETS):
        return "all three sets"
    labels = [SET_NAMES[name] for name in names]
    return labels[0] if len(labels) == 1 else " and ".join(labels)


def _public() -> tuple[dict[str, Any], dict[str, Any]]:
    loaded = _measurement("public-sets.json")
    return loaded["sets"], loaded["published"]


def _score(run: dict[str, Any], mode: str) -> float:
    return float(run["modes"][mode]["ndcg@10"])


def _three(value: float) -> str:
    """Three places, halves rounded up as the notes round them (0.3635 -> 0.364)."""
    return str(Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def public_losses() -> list[str]:
    """Every place a stage scores below a plain baseline, one line per pairing.

    Computed, so a re-run that changes who wins changes the page's first
    screen with it -- the milestone's rule is that a loss is said there.
    """
    runs, published = _public()
    lines = []
    for mode, subject, baselines in COMPARED:
        for baseline in baselines:
            lost = []
            for name in PUBLIC_SETS:
                ours = _score(runs[name], mode)
                theirs = (
                    _score(runs[name], "dense") if baseline is None else published[name][baseline]
                )
                if ours < theirs:
                    lost.append((name, ours, theirs))
            if not lost:
                continue
            against = "meaning search alone" if baseline is None else BASELINES[baseline]
            figures = "; ".join(
                f"{SET_NAMES[name]} {_three(ours)} against {_three(theirs)}"
                for name, ours, theirs in lost
            )
            verb = "lowers the score below" if baseline is None else "loses to"
            everywhere = " on all three sets" if len(lost) == len(PUBLIC_SETS) else ""
            lines.append(f"- **{subject} {verb} {against}**{everywhere}: {figures}.")
    return lines


def _beats_bm25_ce() -> str:
    """Where the shipped pipeline beats the strongest published baseline."""
    runs, published = _public()
    won = [n for n in PUBLIC_SETS if _score(runs[n], "rerank") > published[n]["bm25_ce"]]
    return _where(won) if won else "none of them"


def _public_wins() -> str:
    where = _beats_bm25_ce()
    if where == "none of them":
        return "The full search beats the paper's BM25 + re-reading baseline on none of them."
    return (
        f"The full search, as shipped, beats the paper's BM25 + re-reading baseline on "
        f"{where}, so the losses above are in stages the product does not stop at."
    )


def _first_screen() -> list[str]:
    losses = public_losses()
    return [
        "## Where it loses to a plain baseline",
        "",
        "On three public test sets (NFCorpus, SciFact and FiQA from BEIR, scored with",
        "the field's standard measure, nDCG@10, beside published figures):",
        "",
        *(losses or ["- Nowhere: every stage beats the plain baseline it is compared with."]),
        "",
        _public_wins() + " The tables are [below](#on-public-test-sets).",
    ]


def _reproduce_minutes(run: dict[str, Any]) -> int:
    searching = sum(m["ms_per_question"] for m in run["modes"].values()) * run["questions"]
    return max(1, round((run["ingest_seconds"] + searching / 1000) / 60))


def _public_tables() -> list[str]:
    runs, published = _public()
    lines = [
        "| Set | documents | questions | meaning | keyword | fused | full search |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for name in PUBLIC_SETS:
        run = runs[name]
        cells = " | ".join(_three(_score(run, mode)) for mode, _ in MODES)
        lines.append(
            f"| {SET_NAMES[name]} | {run['stored']['documents']:,} | {run['questions']} "
            f"| {cells} |"
        )
    lines += [
        "",
        "Published, same measure and split:",
        "",
        "| Set | plain BM25 | same meaning model | BM25 + re-reading |",
        "| --- | --- | --- | --- |",
    ]
    for name in PUBLIC_SETS:
        row = published[name]
        lines.append(
            f"| {SET_NAMES[name]} | {_three(row['bm25'])} | {_three(row['minilm_dense'])} "
            f"| {_three(row['bm25_ce'])} |"
        )
    return lines


def _public_section() -> list[str]:
    runs, _ = _public()
    run = runs[REPRODUCE_SET]
    _, size = public_sets.ARCHIVES[REPRODUCE_SET]
    return [
        "Fixed documents and questions, judged by people who never saw this code. "
        "Scores are nDCG@10 on each set's test questions, graded, as the BEIR paper "
        "reports them:",
        "",
        *_public_tables(),
        "",
        "Two things differ from the published runs: sextant's keyword search is its own "
        "index, not the paper's Elasticsearch, and each stage hands on at most "
        f"{run['candidates_per_stage']} passages. Plain BM25 and BM25 + re-reading are "
        "from the BEIR paper (Table 2); the meaning model's figure is from the MTEB "
        "results. Method and sources: "
        "[`public-sets.md`](../learning/public-sets.md).",
        "",
        "Reproduce one set:",
        "",
        "```bash",
        f"python -m sextant.eval.public_sets --set {REPRODUCE_SET} --check",
        "```",
        "",
        f"That downloads {SET_NAMES[REPRODUCE_SET]} ({size / 1e6:.1f} MB) from the BEIR "
        "host, refuses it unless its checksum is the one BEIR publishes, scores all four "
        "stages and fails if any lands more than "
        f"{public_sets.REPRODUCE_TOLERANCE} from the table above. About "
        f"{_reproduce_minutes(run)} minutes on a MacBook Air; no key, nothing spent.",
    ]


def _speed() -> list[str]:
    """Search time and memory on the largest library measured (milestone 28, item 2)."""
    m = _measurement("scale.json")
    stages, rule = m["stages"], m["rule"]
    slow = m["verdict"]["slow"]
    name = SET_NAMES.get(m["set"], m["set"])
    return [
        f"Measured on a library of {m['chunks']:,} passages (the public {name} set) "
        f"on a {m['machine']}, over {m['questions']} of its questions:",
        "",
        "| | typical | slowest 1 in 20 |",
        "| --- | --- | --- |",
        f"| Full search, as shipped | {stages['rerank']['p50_ms']:.0f} ms "
        f"| {stages['rerank']['p95_ms']:.0f} ms |",
        f"| Meaning search alone | {stages['dense']['p50_ms']:.0f} ms "
        f"| {stages['dense']['p95_ms']:.0f} ms |",
        f"| Keyword search alone | {stages['lexical']['p50_ms']:.0f} ms "
        f"| {stages['lexical']['p95_ms']:.0f} ms |",
        "",
        f"The first answer after opening the library takes **{m['first_answer_s']:.1f} s** "
        "with the search models already downloaded (they load, and the keyword index is "
        "built). The process peaks at "
        f"**{m['peak_memory_mb'] / 1024:.1f} GB** of memory, and the index takes "
        f"{m['index_on_disk_mb']} MB of disk. Most of a search is the final reranking "
        "step, whose cost does not grow with the library.",
        "",
        (
            "**This counts as slow** by the rule set before measuring: "
            + "; ".join(m["verdict"]["reasons"])
            + "."
            if slow
            else "This is **not slow** by the rule set before measuring (slow would be "
            f"the slowest 1 in 20 full searches over {rule['full_p95_ms_max'] / 1000:.0f} s "
            f"or meaning searches over {rule['dense_p95_ms_max']:.0f} ms, or a first "
            f"answer over {rule['first_answer_s_max']:.0f} s), so faster index types "
            "stay parked."
        ),
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
        *_first_screen(),
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
        "## On public test sets",
        "",
        *_public_section(),
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
        "## How fast it is on a big library",
        "",
        *_speed(),
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
        "What these numbers do **not** show: the first two tables' questions and",
        "documents were written together, and the public sets are three particular",
        "collections, so neither says how the search will do on someone else's library.",
        "",
    ]
    return "\n".join(lines)


def render_summary() -> str:
    """The README's table: one figure per stage, and the abstention line."""
    small = _baseline("baseline.json")
    _, unanswerable = _split("golden.jsonl")
    documents = len(list(CORPUS_DIR.glob("*.md")))
    blocked = small["threshold_sweep"][FLOOR]["unanswerable_blocked"]
    lines = ["| Search stage | Right passage first |", "| --- | --- |"]
    for mode, label in MODES:
        figure = _pct(small["modes"][mode]["hit@1"])
        lines.append(f"| {label} | {f'**{figure}**' if mode == MODES[-1][0] else figure} |")
    lines += [
        "",
        f"{small['questions']} test questions over {documents} documents. Asked "
        f"{unanswerable} questions those documents cannot answer, it declines {blocked}.",
        "",
        f"On three public test sets (BEIR) the full search beats the published BM25 + "
        f"re-reading baseline on {_beats_bm25_ce()}"
        + (
            "; where a stage loses to a plain baseline is the first thing on the results page."
            if public_losses()
            else ", and no stage loses to a plain baseline."
        ),
    ]
    return "\n".join(lines)


def with_summary(readme: str) -> str:
    """`readme` with the text between the markers replaced by the summary."""
    if readme.count(BLOCK_START) != 1 or readme.count(BLOCK_END) != 1:
        raise StaleSource(f"{README} must contain {BLOCK_START} and {BLOCK_END} exactly once")
    head, rest = readme.split(BLOCK_START)
    _, tail = rest.split(BLOCK_END)
    return f"{head}{BLOCK_START}\n{render_summary()}\n{BLOCK_END}{tail}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Write docs/RESULTS.md from measurements.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--write", action="store_true", help="write the page")
    group.add_argument("--check", action="store_true", help="exit 1 if the page is stale")
    args = parser.parse_args(argv)
    try:
        page = render()
        target, readme = _root() / PAGE, _root() / README
        front = with_summary(readme.read_text())
    except StaleSource as problem:
        print(f"FAILED: {problem}", file=sys.stderr)
        return 1
    if args.write:
        target.parent.mkdir(exist_ok=True)
        target.write_text(page)
        readme.write_text(front)
        print(f"wrote {PAGE} and the table in {README}")
        return 0
    if args.check:
        stale = [
            str(name)
            for name, path, wanted in ((PAGE, target, page), (README, readme, front))
            if not path.is_file() or path.read_text() != wanted
        ]
        if stale:
            print(f"FAILED: stale, run with --write: {', '.join(stale)}", file=sys.stderr)
            return 1
        print(f"{PAGE} and {README} match the measurement files")
        return 0
    print(page, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
