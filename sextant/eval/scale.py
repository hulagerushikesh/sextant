"""
Speed and memory on a large library (milestone 28, item 2).

Opens an index that `public_sets --store` kept (FiQA: 57,600 documents,
85,000 chunks) in a fresh process and measures what a user of a library that
size meets: how long the first answer takes from a cold start, how long each
search stage takes after that, how much memory the process holds, and how
much disk the index uses.

The rule was set before the measurement. **Search counts as slow -- and the
parked "faster index tiers" line un-parks -- if any of these holds:**

  * the full pipeline's 95th-percentile search time is over 2 seconds;
  * the dense stage's 95th-percentile time is over 200 ms (that stage is
    what a faster index tier would replace);
  * the first answer after a cold start takes over 30 seconds.

Usage:

    python -m sextant.eval.scale --store DIR --data DIR/fiqa --out scale.json

Nothing is written to the index; it is opened and searched only.
"""

from __future__ import annotations

import argparse
import json
import resource
import statistics
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from sextant import settings

SLOW_FULL_P95_MS = 2000.0
SLOW_DENSE_P95_MS = 200.0
SLOW_FIRST_ANSWER_S = 30.0
QUESTIONS = 200  # the first N test questions, in file order
LIMIT = 5  # what kb_search returns by default


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile: the smallest value with q% of values at or below it."""
    if not values:
        raise ValueError("no values")
    ordered = sorted(values)
    rank = max(1, -(-len(ordered) * q // 100))  # ceil without floats drifting
    return ordered[int(rank) - 1]


def peak_memory_mb() -> float:
    """This process's peak resident memory. macOS reports bytes, Linux kilobytes."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return peak / (1024 * 1024) if sys.platform == "darwin" else peak / 1024


def directory_mb(path: Path) -> float:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / (1024 * 1024)


def verdict(full_p95: float, dense_p95: float, first_answer_s: float) -> dict[str, Any]:
    reasons = []
    if full_p95 > SLOW_FULL_P95_MS:
        reasons.append(f"full pipeline p95 {full_p95:.0f} ms > {SLOW_FULL_P95_MS:.0f} ms")
    if dense_p95 > SLOW_DENSE_P95_MS:
        reasons.append(f"dense p95 {dense_p95:.0f} ms > {SLOW_DENSE_P95_MS:.0f} ms")
    if first_answer_s > SLOW_FIRST_ANSWER_S:
        reasons.append(f"first answer {first_answer_s:.1f} s > {SLOW_FIRST_ANSWER_S:.0f} s")
    return {"slow": bool(reasons), "reasons": reasons}


def load_questions(data: Path, n: int) -> list[str]:
    from sextant.eval.public_sets import load_qrels, load_queries

    qrels = load_qrels(data / "qrels" / "test.tsv")
    wanted = [q for q, g in qrels.items() if any(v > 0 for v in g.values())][:n]
    texts = load_queries(data / "queries.jsonl", set(wanted))
    return [texts[q] for q in wanted]


def measure(store: Path, questions: list[str]) -> dict[str, Any]:
    started = time.perf_counter()
    from sextant.vector_db.vector_search import RETRIEVAL_MODES, KnowledgeBase

    kb = KnowledgeBase()
    opened_s = time.perf_counter() - started
    chunks = kb.collection.count()
    if not chunks:
        raise SystemExit(f"{store} holds no chunks: run public_sets with --store first")

    # The first full-pipeline search pays every cold cost at once: the
    # embedder and reranker load, and the keyword index is built from the
    # store. This is what someone opening a big library waits for.
    first = time.perf_counter()
    kb.search_sync(questions[0], limit=LIMIT, min_score=0.0, mode="rerank")
    first_search_s = time.perf_counter() - first
    first_answer_s = time.perf_counter() - started

    stages: dict[str, Any] = {}
    for mode in RETRIEVAL_MODES:
        times = []
        for question in questions:
            t = time.perf_counter()
            kb.search_sync(question, limit=LIMIT, min_score=0.0, mode=mode)
            times.append(1000 * (time.perf_counter() - t))
        stages[mode] = {
            "p50_ms": round(statistics.median(times), 1),
            "p95_ms": round(percentile(times, 95), 1),
            "max_ms": round(max(times), 1),
        }
        print(f"  {mode:<8} {stages[mode]}", file=sys.stderr)

    return {
        "chunks": chunks,
        "index_on_disk_mb": round(directory_mb(store)),
        "questions": len(questions),
        "limit": LIMIT,
        "open_s": round(opened_s, 1),
        "first_search_s": round(first_search_s, 1),
        "first_answer_s": round(first_answer_s, 1),
        "peak_memory_mb": round(peak_memory_mb()),
        "stages": stages,
        "rule": {
            "full_p95_ms_max": SLOW_FULL_P95_MS,
            "dense_p95_ms_max": SLOW_DENSE_P95_MS,
            "first_answer_s_max": SLOW_FIRST_ANSWER_S,
        },
        "verdict": verdict(
            stages["rerank"]["p95_ms"], stages["dense"]["p95_ms"], first_answer_s
        ),
        "machine": "MacBook Air M2, 8 GB",
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m sextant.eval.scale",
        description="Speed and memory of search over an index kept by public_sets --store.",
    )
    parser.add_argument("--store", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True, help="the BEIR set it holds")
    parser.add_argument("--questions", type=int, default=QUESTIONS)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    settings.setenv("CHROMA_DIR", str(args.store))
    questions = load_questions(args.data, args.questions)
    payload = {"set": args.data.name, **measure(args.store, questions)}
    text = json.dumps(payload, indent=2) + "\n"
    if args.out:
        args.out.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
