"""
The evaluation harness.

Runs the golden set against every retrieval configuration and reports what each
one actually buys. This is the phase that separates a demo from a system: before
it, "hybrid retrieval with reranking" was a claim about architecture, and the
only evidence for it was that it sounded right.

Two splits, graded differently.

  answerable    50 questions with labelled relevant documents. Scored on
                recall@k, MRR and nDCG@k -- did the right material come back,
                and how well ordered was it?

  unanswerable  10 questions the corpus provably cannot answer. Scored on
                whether the system would decline. This is the split that tells
                you what `min_score` should be, because it is the only place
                where the correct answer is "nothing".

What this measures and what it does not: the corpus and the questions were
written together, so this grades the retrieval pipeline, not the world. It will
catch a regression and it will settle an ablation. It will not tell you how the
system performs on someone else's documents.

A second, larger set can be graded against an existing store with
`--store DIR --golden FILE`. Its questions label pages (`relevant_pages`)
rather than documents, because a single long PDF is one document and grading at
that grain would score every mode 1.0.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from tools import settings

EVAL_DIR = Path(__file__).resolve().parent
CORPUS_DIR = EVAL_DIR / "corpus"
GOLDEN_PATH = EVAL_DIR / "golden.jsonl"
BASELINE_PATH = EVAL_DIR / "baseline.json"

# Top-k the agent actually asks for, plus a wider window to separate "ranked
# badly" from "not retrieved at all".
K_PRIMARY = 5
K_WIDE = 10
K_TIGHT = 3

# A metric may drift this far below baseline before CI calls it a regression.
# Retrieval is deterministic here, so anything larger than rounding is real.
REGRESSION_TOLERANCE = 0.02


def load_golden(path: Path = GOLDEN_PATH) -> list[dict[str, Any]]:
    with path.open() as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _unit(hit: dict[str, Any], by_page: bool) -> str:
    """The thing a question labels: a document, or a page of one."""
    if by_page:
        return f"{hit['document_id']}#p{hit.get('page')}"
    return str(hit["document_id"])


def _relevant(item: dict[str, Any]) -> set[str]:
    if "relevant_pages" in item:
        return {f"{doc}#p{page}" for doc, pages in item["relevant_pages"].items() for page in pages}
    return set(item["relevant_docs"])


async def build_store(kb_class):
    """Index the fixed corpus from scratch."""
    kb = kb_class()
    files = sorted(CORPUS_DIR.glob("*.md"))
    if not files:
        sys.exit(f"No corpus documents in {CORPUS_DIR}")
    for path in files:
        await kb.add_file(str(path), category="handbook")
    stats = await kb.health_check()
    print(
        f"corpus: {len(files)} documents -> {stats['collection_size']} chunks "
        f"({stats['embedding_model']}, {stats['chunking']['target_tokens']}-token target)\n"
    )
    return kb


async def grade(kb, golden: list[dict[str, Any]], mode: str) -> dict[str, Any]:
    """Run every question in one configuration."""
    from eval.metrics import hit_at_1, ndcg_at_k, recall_at_k, reciprocal_rank, summarise

    answerable_rows: list[dict[str, float]] = []
    top_scores: dict[str, list[float]] = {"answerable": [], "unanswerable": []}
    failures: list[dict[str, Any]] = []
    scored_by = "none"

    for item in golden:
        # min_score=0.0 deliberately. The threshold trades recall for abstention,
        # so leaving it on would confound the two things this harness measures --
        # a mode would look worse purely because its scores are on a scale the
        # floor happens to bite into. Retrieval quality is graded unfiltered
        # here; the cost of a floor is graded separately, by the sweep below.
        result = await kb.search(item["question"], limit=K_WIDE, mode=mode, min_score=0.0)
        hits = result["results"]
        if hits:
            scored_by = result["scored_by"]
        # Chunks collapse to what the question labels: a document (five chunks
        # of one file is one document retrieved) or, for the page-labelled set,
        # a page of one.
        by_page = "relevant_pages" in item
        retrieved = [_unit(hit, by_page) for hit in hits]
        split = "answerable" if item["answerable"] else "unanswerable"
        top_scores[split].append(hits[0]["score"] if hits else 0.0)

        if not item["answerable"]:
            continue

        relevant = _relevant(item)
        row = {
            "hit@1": hit_at_1(retrieved, relevant),
            f"recall@{K_TIGHT}": recall_at_k(retrieved, relevant, K_TIGHT),
            f"recall@{K_PRIMARY}": recall_at_k(retrieved, relevant, K_PRIMARY),
            "mrr": reciprocal_rank(retrieved, relevant),
            f"ndcg@{K_PRIMARY}": ndcg_at_k(retrieved, relevant, K_PRIMARY),
        }
        answerable_rows.append(row)
        if row[f"recall@{K_PRIMARY}"] < 1.0:
            failures.append(
                {
                    "id": item["id"],
                    "kind": item["kind"],
                    "question": item["question"],
                    "expected": sorted(relevant),
                    "got": list(dict.fromkeys(retrieved))[:5],
                    "recall": row[f"recall@{K_PRIMARY}"],
                }
            )

    summary: dict[str, Any] = dict(summarise(answerable_rows))
    summary["scored_by"] = scored_by
    return {"mode": mode, "metrics": summary, "top_scores": top_scores, "failures": failures}


def separation(report: dict[str, Any]) -> dict[str, float]:
    """How far apart the two splits score. The basis for a `min_score`."""
    answerable = report["top_scores"]["answerable"]
    unanswerable = report["top_scores"]["unanswerable"]
    return {
        "answerable_min": round(min(answerable), 4) if answerable else 0.0,
        "answerable_mean": round(sum(answerable) / len(answerable), 4) if answerable else 0.0,
        "unanswerable_max": round(max(unanswerable), 4) if unanswerable else 0.0,
        "unanswerable_mean": (
            round(sum(unanswerable) / len(unanswerable), 4) if unanswerable else 0.0
        ),
    }


def print_table(reports: list[dict[str, Any]]) -> None:
    columns = ["hit@1", f"recall@{K_TIGHT}", f"recall@{K_PRIMARY}", "mrr", f"ndcg@{K_PRIMARY}"]
    header = f"{'mode':<9} {'scored_by':<14}" + "".join(f"{c:>11}" for c in columns)
    print(header)
    print("-" * len(header))
    for report in reports:
        metrics = report["metrics"]
        row = f"{report['mode']:<9} {metrics['scored_by']:<14}"
        row += "".join(f"{metrics[c]:>11.4f}" for c in columns)
        print(row)


THRESHOLD_SWEEP = (0.01, 0.1, 0.3, 0.5, 0.9)


def print_threshold_sweep(report: dict[str, Any]) -> None:
    """What each candidate `min_score` would cost and buy.

    The summary statistics above under-sell this: the min/max gap is decided by
    two outliers, so it reports no usable threshold even where one exists. What
    matters is the count on each side of the line.
    """
    answerable = report["top_scores"]["answerable"]
    unanswerable = report["top_scores"]["unanswerable"]
    print(f"\nThreshold sweep ({report['mode']}) -- top score per question:")
    print(f"  {'min_score':>10} {'answerable lost':>18} {'unanswerable blocked':>22}")
    for threshold in THRESHOLD_SWEEP:
        lost = sum(1 for score in answerable if score < threshold)
        blocked = sum(1 for score in unanswerable if score < threshold)
        print(
            f"  {threshold:>10.2f} {lost:>13}/{len(answerable):<4} "
            f"{blocked:>17}/{len(unanswerable):<4}"
        )


def print_separation(reports: list[dict[str, Any]]) -> None:
    print(f"\n{'mode':<9} {'answerable (min/mean)':>24} {'unanswerable (max/mean)':>26}   gap")
    print("-" * 72)
    for report in reports:
        s = separation(report)
        gap = s["answerable_min"] - s["unanswerable_max"]
        print(
            f"{report['mode']:<9} {s['answerable_min']:>11.4f} /{s['answerable_mean']:>10.4f} "
            f"{s['unanswerable_max']:>13.4f} /{s['unanswerable_mean']:>10.4f}   {gap:+.4f}"
        )


def check_against_baseline(reports: list[dict[str, Any]]) -> int:
    """Compare to the committed baseline. Returns a process exit code."""
    if not BASELINE_PATH.exists():
        print(f"\nNo baseline at {BASELINE_PATH}; nothing to compare against.")
        return 0

    baseline = json.loads(BASELINE_PATH.read_text())["modes"]
    regressions: list[str] = []
    print("\nAgainst baseline:")

    for report in reports:
        previous = baseline.get(report["mode"])
        if previous is None:
            print(f"  {report['mode']}: new configuration, no baseline")
            continue
        for metric, value in report["metrics"].items():
            if not isinstance(value, (int, float)):
                continue
            delta = value - previous.get(metric, value)
            flag = ""
            if delta < -REGRESSION_TOLERANCE:
                flag = "  REGRESSION"
                regressions.append(f"{report['mode']}.{metric} {delta:+.4f}")
            if abs(delta) > 1e-9:
                print(f"  {report['mode']}.{metric}: {value:.4f} ({delta:+.4f}){flag}")

    if regressions:
        print("\nFAILED: " + "; ".join(regressions))
        return 1
    print("  no regressions")
    return 0


async def run(
    modes: list[str], golden_path: Path = GOLDEN_PATH, store: Path | None = None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from tools.vector_db.vector_search import KnowledgeBase

    golden = load_golden(golden_path)
    print(
        f"golden set: {len(golden)} questions "
        f"({sum(q['answerable'] for q in golden)} answerable, "
        f"{sum(not q['answerable'] for q in golden)} unanswerable)"
    )

    if store is None:
        kb = await build_store(KnowledgeBase)
    else:
        kb = KnowledgeBase()
        stats = await kb.health_check()
        print(f"store: {store} -> {stats['collection_size']} chunks (not rebuilt)\n")
    reports = [await grade(kb, golden, mode) for mode in modes]

    print_table(reports)
    print_separation(reports)

    scored = [r for r in reports if r["metrics"]["scored_by"] == "cross-encoder"]
    if scored:
        print_threshold_sweep(scored[0])

    worst = max(reports, key=lambda r: r["metrics"]["hit@1"])
    if worst["failures"]:
        print(f"\nMisses in the best configuration ({worst['mode']}):")
        for failure in worst["failures"]:
            print(
                f"  {failure['id']} [{failure['kind']}] recall {failure['recall']:.2f}  "
                f"expected {failure['expected']} got {failure['got'][:3]}"
            )
            print(f"      {failure['question']}")

    payload = {
        "k_primary": K_PRIMARY,
        "k_wide": K_WIDE,
        "questions": len(golden),
        "modes": {r["mode"]: r["metrics"] for r in reports},
        "separation": {r["mode"]: separation(r) for r in reports},
        "threshold_sweep": {
            f"{threshold}": {
                "answerable_lost": sum(
                    1 for s in r["top_scores"]["answerable"] if s < threshold
                ),
                "unanswerable_blocked": sum(
                    1 for s in r["top_scores"]["unanswerable"] if s < threshold
                ),
            }
            for r in reports
            if r["metrics"]["scored_by"] == "cross-encoder"
            for threshold in THRESHOLD_SWEEP
        },
    }
    return payload, reports


def main() -> None:
    """Console-script entry point: `sextant-eval`."""
    from tools.vector_db.vector_search import RETRIEVAL_MODES

    parser = argparse.ArgumentParser(
        prog="sextant-eval",
        description="Grade retrieval configurations against the committed golden set.",
    )
    parser.add_argument(
        "--modes", nargs="+", default=list(RETRIEVAL_MODES), choices=RETRIEVAL_MODES
    )
    parser.add_argument("--out", type=Path, help="write results JSON here")
    parser.add_argument("--check", action="store_true", help="fail on regression vs baseline")
    parser.add_argument("--keep-store", action="store_true", help="do not delete the eval index")
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH, help="questions to grade")
    parser.add_argument(
        "--store",
        type=Path,
        help="grade an EXISTING Chroma directory read-only instead of rebuilding from corpus/",
    )
    args = parser.parse_args()
    if args.check and (args.store or args.golden != GOLDEN_PATH):
        parser.error("--check compares the committed corpus and golden set only")

    # A throwaway index, so grading never touches whatever the user has
    # actually ingested. Set before KnowledgeBase is ever constructed. With
    # --store the caller owns the directory and it is opened in place.
    own_store = args.store is None
    store = Path(tempfile.mkdtemp(prefix="sextant-eval-")) if own_store else args.store
    settings.setenv("CHROMA_DIR", str(store))
    try:
        payload, reports = asyncio.run(run(args.modes, args.golden, args.store))
        if args.out:
            args.out.write_text(json.dumps(payload, indent=2) + "\n")
            print(f"\nwrote {args.out}")
        code = check_against_baseline(reports) if args.check else 0
    finally:
        if not own_store:
            pass
        elif args.keep_store:
            print(f"eval index kept at {store}")
        else:
            shutil.rmtree(store, ignore_errors=True)
    sys.exit(code)


if __name__ == "__main__":
    main()
