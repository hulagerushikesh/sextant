"""
Is the self-test honest? (milestone 29, item 2.)

The rule was written and pushed before this ran: `learning/selftest-honesty.md`.
This applies it. On three BEIR sets, where people have judged which documents
answer which questions, it puts the self-test's score for each of the four
search modes beside the true nDCG@10 of the same mode on the same index, and
asks whether the first rises and falls with the second.

The questions come from two Gemini models, each given the self-test tool's own
instructions and the sampled passages -- nothing from the set's queries or
judgements. They are written once and kept in the output, so a re-run grades
the same questions and spends nothing.

    python -m sextant.eval.selftest_honesty --store-root ~/.cache/sextant/beir-index

This spends money (about ₹8, refused past `BUDGET_USD`), downloads the sets
from the BEIR host if they are not cached, and indexes each one, which takes
most of an hour on a laptop for the three. It is not part of the gate.
"""

from __future__ import annotations

import argparse
import asyncio
import gc
import json
import os
import random
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from sextant import settings
from sextant.eval import public_sets
from sextant.vector_db import selftest

SETS = ("scifact", "nfcorpus", "fiqa")
WRITERS = ("gemini-3.1-flash-lite", "gemini-3.7-flash")
SIZE = selftest.MAX_SIZE
SEED = 29

# The rule, as written before the run.
RULE_CORRELATION = 0.6
NO_GUIDE_CORRELATION = 0.3
GOOD_SET = "scifact"
KEYWORD_SET = "fiqa"
KEYWORD_MODE = "lexical"
FULL_MODE = "rerank"

# USD per million tokens, input and output (thinking bills as output). Dated
# with `pricing.py`; gemini-3.7-flash at its introductory rate to 2026-12-31.
PRICES = {"gemini-3.1-flash-lite": (0.25, 1.50), "gemini-3.7-flash": (0.75, 3.75)}
# A hard stop: no model call is made once the run has spent this (about ₹17).
BUDGET_USD = 0.20

# How far a score from the tool's default 20 questions moves by chance.
SPREAD_QUESTIONS = selftest.DEFAULT_SIZE
SPREAD_DRAWS = 2000

OUT = public_sets.EVAL_DIR / "selftest-honesty.json"

WRITER_NOTE = (
    "\n\nYou cannot call tools here. Instead of calling kb_selftest_grade, "
    "return the questions as JSON: one object per passage, with its passage_id "
    "and your question."
)


class Question(BaseModel):
    passage_id: str
    question: str


class OverBudget(RuntimeError):
    pass


def _ranks(values: Sequence[float]) -> list[float]:
    """Average ranks, 1-based, ties sharing the mean of their places."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float:
    """Rank correlation; 0.0 when either side has no spread to rank."""
    if len(xs) != len(ys) or len(xs) < 2:
        raise ValueError("need two equal-length sequences of at least two values")
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = sum(rx) / len(rx), sum(ry) / len(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    return 0.0 if not vx or not vy else round(cov / (vx * vy) ** 0.5, 4)


def judge_writer(
    selftest_scores: Mapping[str, Mapping[str, float]],
    true_scores: Mapping[str, Mapping[str, float]],
) -> dict[str, Any]:
    """The three rules for one writer. Both arguments map set -> mode -> score."""
    pairs = [
        (selftest_scores[s][m], true_scores[s][m]) for s in selftest_scores for m in true_scores[s]
    ]
    rho = spearman([p[0] for p in pairs], [p[1] for p in pairs])
    others = [s for s in selftest_scores if s != GOOD_SET]
    good = all(selftest_scores[GOOD_SET][FULL_MODE] > selftest_scores[s][FULL_MODE] for s in others)
    modes = selftest_scores[KEYWORD_SET]
    keyword_lowest = all(modes[KEYWORD_MODE] < v for m, v in modes.items() if m != KEYWORD_MODE)
    return {
        "conditions": len(pairs),
        "spearman": rho,
        "rule_1_tracks_true_score": rho >= RULE_CORRELATION,
        "rule_2_good_set_scores_highest": good,
        "rule_3_keyword_lowest_on_fiqa": keyword_lowest,
        "passes": rho >= RULE_CORRELATION and good and keyword_lowest,
        "no_guide": rho < NO_GUIDE_CORRELATION or not good,
    }


def outcome(writers: Mapping[str, Mapping[str, Any]]) -> str:
    """What the rule says to ship, given each writer's verdict."""
    if all(v["passes"] for v in writers.values()):
        return "checked"
    if all(v["no_guide"] for v in writers.values()):
        return "no guide"
    return "rough guide"


def spread(ranks: Sequence[int | None], n: int = SPREAD_QUESTIONS, seed: int = SEED) -> dict:
    """The 5th to 95th percentile of a top-5 share from `n` questions, resampled."""
    hits = [1 if r is not None and r <= 5 else 0 for r in ranks]
    if not hits:
        return {"questions": n, "low": None, "high": None}
    rng = random.Random(seed)
    shares = sorted(sum(rng.choices(hits, k=n)) / n for _ in range(SPREAD_DRAWS))
    return {
        "questions": n,
        "low": shares[int(0.05 * SPREAD_DRAWS)],
        "high": shares[int(0.95 * SPREAD_DRAWS) - 1],
    }


def _check_budget(ledger: Mapping[str, float]) -> None:
    if ledger["usd"] >= BUDGET_USD:
        raise OverBudget(f"spent ${ledger['usd']:.4f}, the cap is ${BUDGET_USD}")


def cost(model: str, input_tokens: int, output_tokens: int) -> float:
    rate_in, rate_out = PRICES[model]
    return (input_tokens * rate_in + output_tokens * rate_out) / 1_000_000


async def write_questions(
    client: Any, model: str, sampled: Mapping[str, Any]
) -> tuple[list[dict[str, str]], float]:
    """One call: the tool's instructions and passages in, one question each out."""
    from google.genai import types

    passages = [{"passage_id": p["passage_id"], "text": p["text"]} for p in sampled["passages"]]
    response = await client.models.generate_content(
        model=model,
        contents=json.dumps(passages, ensure_ascii=False),
        config=types.GenerateContentConfig(
            system_instruction=sampled["instructions"] + WRITER_NOTE,
            response_mime_type="application/json",
            response_schema=list[Question],
        ),
    )
    usage = response.usage_metadata
    spent = cost(
        model,
        usage.prompt_token_count or 0,
        (usage.candidates_token_count or 0) + (usage.thoughts_token_count or 0),
    )
    written = json.loads(response.text or "[]")
    return [{"passage_id": q["passage_id"], "question": q["question"]} for q in written], spent


async def run_set(
    name: str,
    data: Path,
    writers: Sequence[str],
    client: Any,
    kept: Mapping[str, Any],
    ledger: dict[str, float],
) -> dict[str, Any]:
    from sextant.vector_db.vector_search import RETRIEVAL_MODES, KnowledgeBase

    committed = json.loads(public_sets.COMMITTED.read_text())["sets"][name]
    true = await public_sets.run(data, RETRIEVAL_MODES, reuse=True)
    gc.collect()  # that run's index is dropped before this one opens
    problems = public_sets.compare(true, committed)
    if problems:
        raise SystemExit(f"{name}: the index does not reproduce the true score: {problems}")

    kb = KnowledgeBase()
    sampled = await kb.selftest_sample(size=SIZE, seed=SEED)
    by_writer: dict[str, Any] = {}
    for model in writers:
        questions = kept.get("writers", {}).get(model, {}).get("questions")
        if questions is None:
            _check_budget(ledger)
            questions, spent = await write_questions(client, model, sampled)
            ledger["usd"] += spent
            print(f"  {model}: {len(questions)} questions, ${spent:.4f}", file=sys.stderr)
        modes: dict[str, Any] = {}
        for mode in RETRIEVAL_MODES:

            def search(question: str, mode: str = mode) -> list[dict[str, Any]]:
                return kb.search_sync(
                    question, limit=selftest.SEARCH_DEPTH, min_score=0.0, mode=mode
                )["results"]

            graded = selftest.grade(kb._corpus, questions, search)
            modes[mode] = {
                "found_first": graded["found_first"],
                "found_in_top_5": graded["found_in_top_5"],
                "right_document_first": graded["right_document_first"],
                "spread_at_20": spread([g["rank"] for g in graded["results"]]),
            }
            copied = graded["copied_wording"]
            not_graded = len(graded["not_graded"])
            print(f"  {model} {mode:<8} {modes[mode]['found_in_top_5']}", file=sys.stderr)
        by_writer[model] = {
            "questions": questions,
            "graded": len(questions) - not_graded,
            "copied_wording": copied,
            "modes": modes,
        }
    return {
        "set": name,
        "sampled": sampled["sampled"],
        "seed": sampled["seed"],
        "true_ndcg@10": {m: v["ndcg@10"] for m, v in true["modes"].items()},
        "writers": by_writer,
    }


def summarise(sets: Mapping[str, Any], writers: Sequence[str]) -> dict[str, Any]:
    true = {s: v["true_ndcg@10"] for s, v in sets.items()}
    verdicts = {
        w: judge_writer(
            {
                s: {m: r["found_in_top_5"] for m, r in v["writers"][w]["modes"].items()}
                for s, v in sets.items()
            },
            true,
        )
        for w in writers
    }
    return {"writers": verdicts, "outcome": outcome(verdicts)}


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m sextant.eval.selftest_honesty")
    parser.add_argument("--sets", nargs="+", default=list(SETS), choices=SETS)
    parser.add_argument("--cache", type=Path, default=public_sets.DEFAULT_CACHE)
    parser.add_argument(
        "--store-root", type=Path, required=True, help="one kept index per set, reused"
    )
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args()

    from google import genai

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise SystemExit("GEMINI_API_KEY is not set; the questions need a model.")
    client = genai.Client(api_key=key).aio
    previous = json.loads(args.out.read_text()) if args.out.is_file() else {}
    ledger = {"usd": 0.0}
    sets: dict[str, Any] = dict(previous.get("sets", {}))

    async def run_all() -> None:
        # One event loop for the whole run: the model client belongs to it.
        for name in args.sets:
            data = public_sets.fetch(name, args.cache)
            settings.setenv("CHROMA_DIR", str(args.store_root / name))
            sets[name] = await run_set(name, data, WRITERS, client, sets.get(name, {}), ledger)
            args.out.write_text(json.dumps({"sets": sets}, indent=2) + "\n")
            gc.collect()  # one set's index at a time in memory

    try:
        asyncio.run(run_all())
    finally:
        print(f"spent ${ledger['usd']:.4f} on questions this run", file=sys.stderr)
    payload: dict[str, Any] = {
        "about": "Milestone 29 item 2; the rule is learning/selftest-honesty.md.",
        "size": SIZE,
        "seed": SEED,
        "spent_usd_this_run": round(ledger["usd"], 4),
        "sets": sets,
    }
    if set(sets) == set(SETS):
        payload["verdict"] = summarise(sets, WRITERS)
        print(json.dumps(payload["verdict"], indent=2))
    args.out.write_text(json.dumps(payload, indent=2) + "\n")


if __name__ == "__main__":
    main()
