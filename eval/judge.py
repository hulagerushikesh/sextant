"""
Generation metrics: is the answer supported, and does it decline when it should?

Retrieval metrics say whether the right passage came back. They say nothing
about what the model then did with it, and the failure this project most needs
to catch -- an answer that reads well and is not in the sources -- lives
entirely on that side of the line.

Three things are measured, and only two of them need a model.

  citations    Deterministic. Every [n] in the answer must refer to a source
               that was actually returned. A model is not needed to check
               whether a number is in a list, and using one would make a
               mechanical check probabilistic for no reason.

  faithfulness Judged. Is every claim traceable to the cited passages, or has
               the model imported something it knew already?

  abstention   Judged, on the unanswerable split. Did the system decline, or
               did it assemble a confident answer out of adjacent material?

The judge is a separate model call that never sees the expected answer as
ground truth to match against -- it sees the question, the answer, and the
passages, and grades support rather than agreement. Grading against a reference
answer measures paraphrase distance, which is not the thing at issue.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from tools import settings

# The judge's model. Overridable so an experiment can grade on a cheaper model
# when the budget says so (`learning/floor-fallback.md` used flash-lite); the
# default is the stronger one, because a judge that misreads support is worse
# than no judge.
JUDGE_MODEL = settings.getenv("JUDGE_MODEL", "gemini-3.7-flash") or "gemini-3.7-flash"
CITATION = re.compile(r"\[(\d+)\]")

JUDGE_SYSTEM = """You are grading a retrieval-augmented answer. You are strict, \
and you grade support rather than agreement: an answer can be correct in the \
world and still unsupported by the passages it was given, and that is a failure.

You will receive a question, the passages the system retrieved, and the answer \
it produced.

faithfulness, 0.0 to 1.0
  1.0  every factual claim is stated in or directly entailed by the passages
  0.5  the substance is supported but some detail is not in the passages
  0.0  a central claim appears nowhere in the passages

  Judge only what is asserted. Hedging is not unfaithfulness, and an answer \
that declines to answer is vacuously faithful.

relevance, 0.0 to 1.0
  1.0  answers the question that was asked, at the length it needs
  0.5  addresses the topic but not the actual question, or buries it
  0.0  does not address the question

declined, true or false
  true when the answer says the material is not available rather than \
attempting an answer. An answer that hedges but still commits to a substantive \
claim has not declined."""


class Grade(BaseModel):
    faithfulness: float = Field(ge=0.0, le=1.0)
    relevance: float = Field(ge=0.0, le=1.0)
    declined: bool
    reason: str = Field(description="One sentence. Name the unsupported claim if there is one.")


def check_citations(answer: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic citation validity. No model involved."""
    cited = {int(n) for n in CITATION.findall(answer)}
    available = {source["n"] for source in sources}
    dangling = sorted(cited - available)
    return {
        "cited": sorted(cited),
        "dangling": dangling,
        "valid": not dangling,
        "uncited_sources": len(available - cited),
    }


def _passages(sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "(the system retrieved nothing)"
    return "\n\n".join(
        f"[{s['n']}] {s['title']}"
        + (f" ({s['location']})" if s.get("location") else "")
        + f"\n{s['text']}"
        for s in sources
    )


async def grade_one(client, question: str, answer: str, sources: list[dict[str, Any]]) -> Grade:
    """One judge call.

    `response_schema` constrains the decode, so the grade comes back as a Grade
    rather than as prose about a grade. Thinking is disabled: the rubric is
    explicit and a judge that reasons at length is a judge whose cost scales with
    the size of the golden set for no measured gain.
    """
    from google.genai import types

    response = await client.models.generate_content(
        model=JUDGE_MODEL,
        contents=(
            f"Question:\n{question}\n\n"
            f"Passages the system retrieved:\n{_passages(sources)}\n\n"
            f"Answer the system produced:\n{answer}"
        ),
        config=types.GenerateContentConfig(
            system_instruction=JUDGE_SYSTEM,
            response_mime_type="application/json",
            response_schema=Grade,
            max_output_tokens=2048,
            thinking_config=types.ThinkingConfig(thinking_level=types.ThinkingLevel.LOW),
        ),
    )
    parsed = response.parsed
    # `parsed` is None when the decode failed -- a safety block, or the token
    # budget exhausted mid-object. Raising beats recording a zero that would
    # read as a judged failure rather than an ungraded item.
    if not isinstance(parsed, Grade):
        raise RuntimeError(
            f"The judge returned no usable grade (finish: "
            f"{response.candidates[0].finish_reason if response.candidates else 'none'})."
        )
    return parsed


async def answer_one(host, question: str) -> dict[str, Any]:
    """Run the real agent loop and collect what it produced."""
    from mcp_server.agent import run as run_agent

    text: list[str] = []
    sources: list[dict[str, Any]] = []
    tools: list[str] = []
    async for event in run_agent(question, host):
        if event["type"] == "token":
            text.append(event["text"])
        elif event["type"] == "answer":
            # A grounded turn relabelled once it finished. Replaces what was
            # streamed rather than appending to it, or every web citation would
            # be counted twice by `check_citations`.
            text = [event["text"]]
        elif event["type"] == "tool_call":
            tools.append(event["name"])
        elif event["type"] in ("sources", "done"):
            sources = event["sources"]
    return {"answer": "".join(text).strip(), "sources": sources, "tools": tools}


async def run(golden: list[dict[str, Any]], limit: int | None) -> dict[str, Any]:
    from google import genai

    from eval.harness import CORPUS_DIR
    from mcp_server.mcp_host import MCPHost
    from tools.vector_db.vector_search import KnowledgeBase

    kb = KnowledgeBase()
    for path in sorted(CORPUS_DIR.glob("*.md")):
        await kb.add_file(str(path), category="handbook")
    del kb  # the agent reaches the same store through its own MCP subprocess

    host = MCPHost()
    await host.connect()
    if not host.connected:
        sys.exit(f"MCP connection failed: {host.error}")

    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"]).aio
    items = golden[:limit] if limit else golden
    records: list[dict[str, Any]] = []

    try:
        for item in items:
            produced = await answer_one(host, item["question"])
            grade = await grade_one(
                client, item["question"], produced["answer"], produced["sources"]
            )
            records.append(
                {
                    "id": item["id"],
                    "kind": item["kind"],
                    "answerable": item["answerable"],
                    "answer": produced["answer"],
                    "tools": produced["tools"],
                    "citations": check_citations(produced["answer"], produced["sources"]),
                    "grade": grade.model_dump(),
                }
            )
            mark = "declined" if grade.declined else f"f={grade.faithfulness:.2f}"
            print(f"  {item['id']:<4} {mark:<10} {produced['answer'][:70]}")
    finally:
        await host.close()

    return summarise(records)


def summarise(records: list[dict[str, Any]]) -> dict[str, Any]:
    answerable = [r for r in records if r["answerable"]]
    unanswerable = [r for r in records if not r["answerable"]]

    def mean(rows, key):
        return round(sum(r["grade"][key] for r in rows) / len(rows), 4) if rows else None

    return {
        "graded": len(records),
        "faithfulness": mean(answerable, "faithfulness"),
        "relevance": mean(answerable, "relevance"),
        # The two error directions, kept apart. Declining when the answer was
        # there and answering when it was not are different failures with
        # different costs, and one mean would hide both.
        "false_abstention": round(
            sum(r["grade"]["declined"] for r in answerable) / len(answerable), 4
        )
        if answerable
        else None,
        "correct_abstention": round(
            sum(r["grade"]["declined"] for r in unanswerable) / len(unanswerable), 4
        )
        if unanswerable
        else None,
        "citations_valid": round(
            sum(r["citations"]["valid"] for r in records) / len(records), 4
        )
        if records
        else None,
        "dangling_citations": sum(len(r["citations"]["dangling"]) for r in records),
        "records": records,
    }


def main() -> None:
    """Console-script entry point: `sextant-judge`."""
    from eval.harness import load_golden

    parser = argparse.ArgumentParser(
        prog="sextant-judge",
        description="Grade generated answers for faithfulness, relevance and abstention.",
    )
    parser.add_argument("-n", "--limit", type=int, help="grade only the first N questions")
    parser.add_argument("--out", type=Path, help="write the full record set here")
    args = parser.parse_args()

    if not os.getenv("GEMINI_API_KEY"):
        sys.exit(
            "GEMINI_API_KEY is not set. Generation metrics need it twice over: once to "
            "produce the answers and once to grade them. Retrieval metrics do not -- run "
            "`sextant-eval` instead."
        )

    store = Path(tempfile.mkdtemp(prefix="sextant-judge-"))
    settings.setenv("CHROMA_DIR", str(store))
    try:
        summary = asyncio.run(run(load_golden(), args.limit))
        records = summary.pop("records")
        print("\n" + json.dumps(summary, indent=2))
        if args.out:
            args.out.write_text(json.dumps({**summary, "records": records}, indent=2) + "\n")
            print(f"wrote {args.out}")
    finally:
        shutil.rmtree(store, ignore_errors=True)


if __name__ == "__main__":
    main()
