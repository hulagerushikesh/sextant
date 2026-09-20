"""
Grading the agent, not the retriever.

Every retrieval number in this repository comes from one `kb.search()` call per
question. The product does not work that way: the model reads the question,
chooses a query, reads what comes back, and may search again with different
words before it answers. A question the harness marks as a miss can be a hit
end to end, if the second search finds what the first did not -- and a question
the harness marks as a hit can still go wrong, if the model phrases its query
badly. Neither is visible from `sextant-eval`.

This harness runs each question through the real loop (`mcp_server.agent.run`,
real model, real MCP subprocess) and records every `kb_search` it makes. Two
things are graded from that record:

  recall@first   what the model's *first* query retrieved, at the depth the tool
                 returned. Measures query phrasing: the harness asks the
                 retriever the golden question verbatim, the model asks it
                 whatever it decides to ask.

  recall@union   everything any search in the loop retrieved, taken together.
                 Measures the loop: whether a second query recovered what the
                 first missed. This is the number a multi-hop question should be
                 judged on, because the agent was built to search twice.

Alongside them: searches per question, turns, tokens and cost -- a loop that
reaches recall 1.0 in five turns has not solved anything.

What is not graded here: the answer text. That is `sextant-judge`, which puts
a second model on the case. This file keeps to what can be checked without one,
so the model whose behaviour is under test is the only model in the run.

This costs money to run and is not part of the CI gate. It exists for an
experiment (Milestone 16, `learning/agent-loop.md`) and for re-running that
experiment after a prompt change.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from tools import settings

EVAL_DIR = Path(__file__).resolve().parent
GOLDEN_PATH = EVAL_DIR / "golden.jsonl"
GOLDEN_LARGE_PATH = EVAL_DIR / "golden-large.jsonl"

# Every question is graded at the depth the tool actually returned -- whatever
# `limit` the model asked for, 5 unless it says otherwise. That is the depth
# the model reads, so it is the depth retrieval has to work at; there is no
# k=10 window here because the model never sees one.
DEFAULT_SAMPLE_SEED = 0


class RecordingHost:
    """An MCPHost that remembers what `kb_search` returned, and every call made.

    The agent reports a search as a one-line summary (`hits: 5`) because that is
    what the trace panel needs. Grading needs the hits themselves -- their
    document and page -- so this wraps the real host and keeps every result
    before handing it on unchanged. The loop under test does not know.

    `calls` is the tool sequence in order -- `kb_list` before `kb_search`, or
    not -- which is what a listing question is graded on.
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.searches: list[dict[str, Any]] = []
        self.calls: list[str] = []
        self.titles: dict[str, str] = {}  # document_id -> title, from kb_list

    @property
    def connected(self) -> bool:
        return bool(self._inner.connected)

    @property
    def tools(self) -> list[dict[str, Any]]:
        return list(self._inner.tools)

    @property
    def error(self) -> str | None:
        return getattr(self._inner, "error", None)

    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = await self._inner.call(name, arguments)
        self.calls.append(name)
        if name == "kb_list":
            for doc in result.get("documents") or []:
                self.titles[str(doc.get("document_id"))] = str(doc.get("title") or "")
        if name == "kb_search":
            self.searches.append(
                {
                    "query": arguments.get("query"),
                    "limit": arguments.get("limit"),
                    "hits": list(result.get("results") or []),
                }
            )
        return result


async def answer_one(host: Any, question: str) -> dict[str, Any]:
    """Run the loop once and return what it did, not just what it said."""
    from typing import cast

    from mcp_server.agent import run as run_agent

    recorder = RecordingHost(host)
    text: list[str] = []
    done: dict[str, Any] = {}
    # Web search forced off: a grounded request is billed per call, and a web
    # hit would make a corpus miss invisible -- exactly the failure this
    # harness exists to see.
    async for event in run_agent(question, cast(Any, recorder), web_search=False):
        if event["type"] == "token":
            text.append(event["text"])
        elif event["type"] == "answer":
            text = [event["text"]]
        elif event["type"] == "done":
            done = event
    return {
        "answer": "".join(text).strip(),
        "searches": recorder.searches,
        "calls": recorder.calls,
        "titles": recorder.titles,
        "turns": done.get("turns", 0),
        "truncated": done.get("truncated", False),
        "usage": done.get("usage", {}),
    }


def grade_record(
    item: dict[str, Any],
    searches: list[dict[str, Any]],
    answer: str = "",
    titles: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Score one question from the searches the loop made.

    Pure: no model, no I/O. A unit is whatever the golden item labels -- a
    document, or a page of one -- so a chunk collapses the same way it does in
    `eval.harness`.

    `named` is the listing grade: the fraction of expected documents whose
    title (as `kb_list` reported it) appears in the answer. A question answered
    from the listing makes no search, so the retrieval columns read 0 for it
    and this column is the one that says whether the answer named the right
    documents.
    """
    from eval.harness import _relevant, _unit
    from eval.metrics import hit_at_1, recall_at_k

    relevant = _relevant(item)
    by_page = "relevant_pages" in item
    ranked = [[_unit(hit, by_page) for hit in search["hits"]] for search in searches]
    first = ranked[0] if ranked else []
    union: list[str] = list(dict.fromkeys(unit for units in ranked for unit in units))
    docs = sorted({unit.split("#p")[0] for unit in relevant})
    text = answer.lower()
    known = titles or {}
    named = [doc for doc in docs if known.get(doc, "").strip() and known[doc].lower() in text]
    return {
        "searches": len(searches),
        "hit@1": hit_at_1(first, relevant),
        "recall@first": recall_at_k(first, relevant, len(first)) if first else 0.0,
        "recall@union": recall_at_k(union, relevant, len(union)) if union else 0.0,
        "named": (len(named) / len(docs)) if docs else 1.0,
        "queries": [search["query"] for search in searches],
        "expected": sorted(relevant),
        "first": list(dict.fromkeys(first)),
        "union": union,
    }


def select(
    golden: list[dict[str, Any]],
    kinds: list[str] | None,
    sample: int | None,
    seed: int = DEFAULT_SAMPLE_SEED,
) -> list[dict[str, Any]]:
    """Answerable questions to run: every one of `kinds`, plus `sample` others.

    Deterministic for a seed, so a re-run after a prompt change grades the same
    questions and the difference is the prompt.
    """
    answerable = [item for item in golden if item["answerable"]]
    if kinds is None and sample is None:
        return answerable
    wanted = [item for item in answerable if kinds and item["kind"] in kinds]
    rest = [item for item in answerable if item not in wanted]
    if sample:
        rng = random.Random(seed)
        wanted += sorted(rng.sample(rest, min(sample, len(rest))), key=lambda i: i["id"])
    return wanted


def summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Means over the graded questions, split by kind so multi-hop is visible."""

    def block(rows: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(rows)
        if not n:
            return {"questions": 0}
        grades = [row["grade"] for row in rows]
        return {
            "questions": n,
            "hit@1": round(sum(g["hit@1"] for g in grades) / n, 4),
            "recall@first": round(sum(g["recall@first"] for g in grades) / n, 4),
            "recall@union": round(sum(g["recall@union"] for g in grades) / n, 4),
            "named": round(sum(g.get("named", 0.0) for g in grades) / n, 4),
            "searches_per_question": round(sum(g["searches"] for g in grades) / n, 2),
            "searched_twice": sum(1 for g in grades if g["searches"] > 1),
            "turns_per_question": round(sum(row["turns"] for row in rows) / n, 2),
            "truncated": sum(1 for row in rows if row["truncated"]),
            "cost_usd": round(sum(row["usage"].get("cost_usd", 0.0) for row in rows), 4),
        }

    kinds = sorted({row["kind"] for row in records})
    return {
        "all": block(records),
        "by_kind": {kind: block([r for r in records if r["kind"] == kind]) for kind in kinds},
        "by_set": {
            name: block([r for r in records if r["set"] == name])
            for name in sorted({row["set"] for row in records})
        },
    }


def print_summary(summary: dict[str, Any]) -> None:
    columns = [
        "questions",
        "hit@1",
        "recall@first",
        "recall@union",
        "named",
        "searches_per_question",
        "searched_twice",
        "turns_per_question",
        "cost_usd",
    ]
    short = {
        "questions": "n",
        "hit@1": "hit@1",
        "recall@first": "r@first",
        "recall@union": "r@union",
        "named": "named",
        "searches_per_question": "searches",
        "searched_twice": "2+",
        "turns_per_question": "turns",
        "cost_usd": "usd",
    }
    header = f"{'split':<18}" + "".join(f"{short[c]:>10}" for c in columns)
    print("\n" + header)
    print("-" * len(header))
    rows = [("all", summary["all"])]
    rows += [(f"set:{k}", v) for k, v in summary["by_set"].items()]
    rows += [(f"kind:{k}", v) for k, v in summary["by_kind"].items()]
    for name, block in rows:
        if not block["questions"]:
            continue
        line = f"{name:<18}"
        for column in columns:
            value = block[column]
            line += f"{value:>10.3f}" if isinstance(value, float) else f"{value:>10}"
        print(line)


async def run(
    items: list[dict[str, Any]], progress: bool = True
) -> list[dict[str, Any]]:
    """Run every item through the agent against whatever store is configured."""
    from mcp_server.mcp_host import MCPHost

    host = MCPHost()
    await host.connect()
    if not host.connected:
        sys.exit(f"MCP connection failed: {host.error}")

    records: list[dict[str, Any]] = []
    try:
        for item in items:
            produced = await answer_one(host, item["question"])
            grade = grade_record(item, produced["searches"], produced["answer"], produced["titles"])
            records.append(
                {
                    "id": item["id"],
                    "set": item["set"],
                    "kind": item["kind"],
                    "question": item["question"],
                    "grade": grade,
                    "answer": produced["answer"],
                    "calls": produced["calls"],
                    "turns": produced["turns"],
                    "truncated": produced["truncated"],
                    "usage": produced["usage"],
                }
            )
            if progress:
                mark = "hit " if grade["recall@union"] >= 1.0 else "MISS"
                print(
                    f"  {item['id']:<4} {item['kind']:<10} {mark} "
                    f"first {grade['recall@first']:.2f} union {grade['recall@union']:.2f} "
                    f"named {grade['named']:.2f} "
                    f"calls {','.join(produced['calls']) or '-'} turns {produced['turns']} "
                    f"${produced['usage'].get('cost_usd', 0.0):.4f}",
                    flush=True,
                )
    finally:
        await host.close()
    return records


def _load(path: Path, name: str) -> list[dict[str, Any]]:
    from eval.harness import load_golden

    return [{**item, "set": name} for item in load_golden(path)]


def main() -> None:
    """Console-script entry point: `sextant-eval-agent`."""
    import os

    from dotenv import load_dotenv

    load_dotenv(EVAL_DIR.parent / ".env")

    parser = argparse.ArgumentParser(
        prog="sextant-eval-agent",
        description="Run golden questions through the agent loop and grade what it retrieved.",
    )
    parser.add_argument(
        "--golden",
        type=Path,
        nargs="+",
        default=[GOLDEN_PATH, GOLDEN_LARGE_PATH],
        help="golden files to draw questions from (default: both)",
    )
    parser.add_argument(
        "--kinds", nargs="+", help="run every answerable question of these kinds"
    )
    parser.add_argument(
        "--sample", type=int, help="plus this many other answerable questions, seeded"
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SAMPLE_SEED)
    parser.add_argument("--ids", nargs="+", help="run exactly these question ids")
    parser.add_argument(
        "--store",
        type=Path,
        help="grade an EXISTING Chroma directory instead of rebuilding from corpus/",
    )
    parser.add_argument("--out", type=Path, help="write every record here (JSON)")
    parser.add_argument("--dry-run", action="store_true", help="list the questions and stop")
    args = parser.parse_args()

    golden: list[dict[str, Any]] = []
    for path in args.golden:
        golden += _load(path, path.stem.replace("golden-", "").replace("golden", "handbook"))
    if args.ids:
        wanted = set(args.ids)
        items = [item for item in golden if item["id"] in wanted]
    else:
        items = select(golden, args.kinds, args.sample, args.seed)

    print(f"{len(items)} question(s) selected from {len(golden)}:")
    for item in items:
        print(f"  {item['id']:<4} {item['set']:<9} {item['kind']:<10} {item['question'][:70]}")
    if args.dry_run:
        return

    if not os.getenv("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY is not set; the agent cannot run without a model.")

    own_store = args.store is None
    store = Path(tempfile.mkdtemp(prefix="sextant-eval-agent-")) if own_store else args.store
    settings.setenv("CHROMA_DIR", str(store))
    try:
        if own_store:
            from eval.harness import build_store
            from tools.vector_db.vector_search import KnowledgeBase

            kb = asyncio.run(build_store(KnowledgeBase))
            del kb  # the agent reaches the same store through its own MCP subprocess
        records = asyncio.run(run(items))
        summary = summarise(records)
        print_summary(summary)
        misses = [r for r in records if r["grade"]["recall@union"] < 1.0]
        if misses:
            print("\nNot fully retrieved even across every search:")
            for r in misses:
                g = r["grade"]
                print(f"  {r['id']} [{r['kind']}] expected {g['expected']} got {g['union'][:6]}")
                for query in g["queries"]:
                    print(f"      > {query}")
        if args.out:
            args.out.write_text(
                json.dumps({"summary": summary, "records": records}, indent=2) + "\n"
            )
            print(f"\nwrote {args.out}")
    finally:
        if own_store:
            shutil.rmtree(store, ignore_errors=True)


if __name__ == "__main__":
    main()
