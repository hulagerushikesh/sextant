"""
What a corpus should belong to: one filtered collection, or one each.

Milestone 20 item 2. Two ways to hold more than one person's documents:

  arm A  one collection, filtered after ranking. The only way it can work:
         `search()` has no filter parameter, and the dense index is built once
         over every chunk with no notion of an owner, so a filter cannot reach
         inside the ranking. Ask for N, keep the owner's, take the first k.
         Asking for more than k is the over-fetch budget.

  arm B  one collection per owner. Today's pipeline over a smaller store, so
         it is the ceiling rather than a candidate.

Pre-registered rule (`planning/milestone-20.md`): A is accepted only if, at a
10% corpus share with an over-fetch budget of 10 x k, it reaches B's recall@5
within 0.02.

## The arms differ in exactly one thing, by construction

Arm B is not rebuilt from the source files -- it is the **same chunks with the
same embeddings**, copied out of the mixed store into a collection of their
own. Re-ingesting would have changed the summaries (the mixed store has an
overview per document, which costs a model call to regenerate) and re-chunked
under whatever the chunker does today, and either difference would have shown
up in the result as though it were about tenancy. The only thing that differs
between the arms is whether the index ranks over the whole store or over one
tenant's slice of it.

## Why the tenants are the ones they are

A synthetic partition of `eval/corpus/` was tried first and abandoned: 11 of
its 17 labelled documents are chained into one component by questions that
label two documents at once, so the smallest achievable "10% owner" actually
held 62% of the corpus. The golden set cannot describe a small tenant.

The mixed store can, without inventing anything. It holds the 21-document
handbook (52 chunks) beside one 144-page survey PDF (1,608 chunks), and both
have their own golden set. The handbook is therefore a **3% tenant** inside a
1,660-chunk store -- a smaller share than the rule asks about, with real
questions, and precisely the case A is supposed to fail.

Reproduce:

    ./.venv/bin/python -m eval.tenancy --store ./chroma_db --out /tmp/t.json

The store is opened read-only; the subset collection is written to a temporary
directory and deleted. `SEXTANT_MAX_PER_DOCUMENT=0` turns the per-document cap
off, which changes what an over-fetch budget can even reach.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, cast

from eval.harness import CORPUS_DIR, GOLDEN_PATH, K_PRIMARY, K_WIDE, load_golden
from eval.metrics import hit_at_1, recall_at_k
from tools import settings

# Arm A's budget, as a multiple of the k it has to fill. 1 is no over-fetch at
# all -- ask for k, keep what survives the filter -- which is the naive
# implementation and the one worth showing.
OVER_FETCH = (1, 2, 5, 10, 20)

# The pre-registered rule's arguments. The share is whatever the store makes
# the tenant; the rule asked about 10% and this measures something smaller.
RULE_OVER_FETCH = 10
RULE_TOLERANCE = 0.02

SUBSET_COLLECTION = "tenancy-subset"


def tenant_documents() -> set[str]:
    """The handbook: one tenant's corpus, named by the files it was built from."""
    return {path.stem for path in CORPUS_DIR.glob("*.md")}


def score(ranked_docs: list[str], relevant: set[str]) -> dict[str, float]:
    return {
        "hit@1": hit_at_1(ranked_docs, relevant),
        f"recall@{K_PRIMARY}": recall_at_k(ranked_docs, relevant, K_PRIMARY),
    }


def pooled(rows: list[dict[str, float]]) -> dict[str, float]:
    keys = ("hit@1", f"recall@{K_PRIMARY}")
    if not rows:
        return {**{k: 0.0 for k in keys}, "n": 0}
    out: dict[str, float] = {k: round(sum(r[k] for r in rows) / len(rows), 4) for k in keys}
    out["n"] = len(rows)
    return out


def subset(source: Any, doc_ids: set[str], kb_class: Any) -> Any:
    """A collection holding exactly these documents' chunks, embeddings and all.

    Copied rather than re-ingested so that the two arms differ in one thing.
    """
    kb = kb_class(collection_name=SUBSET_COLLECTION)
    got = source.collection.get(include=["embeddings", "documents", "metadatas"])
    keep = [
        i
        for i, meta in enumerate(got["metadatas"])
        if str(meta.get("document_id")) in doc_ids
    ]
    if not keep:
        sys.exit(f"None of {sorted(doc_ids)[:3]}... are in the store")
    kb.collection.add(
        ids=[got["ids"][i] for i in keep],
        embeddings=cast(Any, [got["embeddings"][i] for i in keep]),
        documents=[got["documents"][i] for i in keep],
        metadatas=cast(Any, [got["metadatas"][i] for i in keep]),
    )
    kb._stamp_embedding_model(kb.embedder.name)
    return kb


async def rank_all(kb: Any, items: list[dict[str, Any]], mode: str, budget: int) -> dict[str, Any]:
    """One search per question. Smaller budgets are prefixes of this ranking."""
    out: dict[str, Any] = {}
    for item in items:
        result = await kb.search(item["question"], limit=budget, mode=mode, min_score=0.0)
        out[item["id"]] = [str(hit["document_id"]) for hit in result["results"]]
    return out


def first_relevant_rank(ranked: list[str], relevant: set[str]) -> int | None:
    """Where the owner's own answer sits in the whole-store ranking.

    This is the number that decides arm A, and the reason share is not what
    decides it. Filtering can only *remove* documents the owner does not have,
    so it never demotes one they do -- their relevant document keeps its order
    and moves up. A loses a question only when that document falls outside the
    budget in the global ranking, which is a property of ranking depth, not of
    how much of the corpus the owner holds.
    """
    for i, doc in enumerate(ranked, start=1):
        if doc in relevant:
            return i
    return None


async def run(store: Path, mode: str, golden_path: Path) -> dict[str, Any]:
    from tools.vector_db.vector_search import MAX_PER_DOCUMENT, KnowledgeBase

    golden = [item for item in load_golden(golden_path) if item["answerable"]]
    items = [item for item in golden if item.get("relevant_docs")]

    whole = KnowledgeBase()
    total = whole.collection.count()
    owned = tenant_documents()
    present = {
        doc: len(whole.collection.get(where={"document_id": doc}).get("ids") or [])
        for doc in sorted(owned)
    }
    owned = {doc for doc, n in present.items() if n}
    held = sum(present.values())
    share = held / total if total else 0.0

    print(f"store {store}: {total} chunks, mode={mode}, per-document cap={MAX_PER_DOCUMENT}")
    print(f"tenant: {len(owned)} documents, {held} chunks = {share:.1%} of the store")
    print(f"questions: {len(items)} answerable, labelled by document\n")

    max_budget = max(OVER_FETCH) * K_WIDE
    ranked = await rank_all(whole, items, mode, max_budget)
    widths = sorted({len(r) for r in ranked.values()})
    print(f"arm A asked for {max_budget}, was returned {widths[0]}-{widths[-1]} results")
    if MAX_PER_DOCUMENT:
        print(
            f"  (the per-document cap of {MAX_PER_DOCUMENT} bounds any budget at "
            f"2 x the number of documents in the store)"
        )

    depths = {
        item["id"]: first_relevant_rank(ranked[item["id"]], set(item["relevant_docs"]))
        for item in items
    }
    found = sorted(d for d in depths.values() if d is not None)
    missing = [q for q, d in depths.items() if d is None]
    print(
        f"\nwhere the tenant's own answer sits in the WHOLE-store ranking: "
        f"median {found[len(found) // 2]}, "
        f"90th {found[int(len(found) * 0.9)]}, max {found[-1]}"
        f"{f', {len(missing)} never found' if missing else ''}"
    )

    subset_kb = subset(whole, owned, KnowledgeBase)
    try:
        b_rows = []
        for item in items:
            result = await subset_kb.search(
                item["question"], limit=K_WIDE, mode=mode, min_score=0.0
            )
            docs = [str(hit["document_id"]) for hit in result["results"]]
            b_rows.append(score(docs, set(item["relevant_docs"])))
        b = pooled(b_rows)
    finally:
        subset_kb.client.delete_collection(SUBSET_COLLECTION)

    a: dict[str, dict[str, float]] = {}
    for factor in OVER_FETCH:
        budget = factor * K_WIDE
        rows = []
        for item in items:
            kept = [doc for doc in ranked[item["id"]][:budget] if doc in owned][:K_WIDE]
            rows.append(score(kept, set(item["relevant_docs"])))
        a[str(factor)] = pooled(rows)

    return {
        "mode": mode,
        "k": K_PRIMARY,
        "per_document_cap": MAX_PER_DOCUMENT,
        "store_chunks": total,
        "tenant_documents": len(owned),
        "tenant_chunks": held,
        "tenant_share": round(share, 4),
        "questions": len(items),
        "results_returned": [widths[0], widths[-1]],
        "first_relevant_rank": {
            "median": found[len(found) // 2],
            "p90": found[int(len(found) * 0.9)],
            "max": found[-1],
            "never_found": len(missing),
        },
        "over_fetch": list(OVER_FETCH),
        "b": b,
        "a": a,
    }


def print_table(payload: dict[str, Any]) -> None:
    metric = f"recall@{K_PRIMARY}"
    print(f"\ntenant share {payload['tenant_share']:.1%}, {payload['questions']} questions\n")
    header = f"{'':>12} {'B (ceiling)':>13}" + "".join(
        f"{'A x' + str(f):>9}" for f in payload["over_fetch"]
    )
    print(header)
    print("-" * len(header))
    for name in (metric, "hit@1"):
        line = f"{name:>12} {payload['b'][name]:>13.4f}"
        line += "".join(f"{payload['a'][str(f)][name]:>9.4f}" for f in payload["over_fetch"])
        print(line)


def verdict(payload: dict[str, Any]) -> str:
    metric = f"recall@{K_PRIMARY}"
    ceiling = payload["b"][metric]
    candidate = payload["a"][str(RULE_OVER_FETCH)][metric]
    gap = ceiling - candidate
    return (
        f"rule: at {payload['tenant_share']:.1%} share and {RULE_OVER_FETCH}x k, "
        f"A {metric} {candidate:.4f} vs B {ceiling:.4f}, gap {gap:+.4f} "
        f"(tolerance {RULE_TOLERANCE}) -> A is "
        + ("ACCEPTED" if gap <= RULE_TOLERANCE else "REJECTED")
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="sextant-eval-tenancy",
        description="Measure filtered-one-collection against collection-per-owner.",
    )
    parser.add_argument(
        "--store", type=Path, required=True, help="an existing mixed Chroma directory"
    )
    parser.add_argument("--mode", default="rerank", help="retrieval mode to grade")
    parser.add_argument("--golden", type=Path, default=GOLDEN_PATH)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    # The subset collection is written beside the source, then deleted. A copy
    # of the whole store would be cleaner and costs a gigabyte.
    settings.setenv("CHROMA_DIR", str(args.store))
    scratch = Path(tempfile.mkdtemp(prefix="sextant-tenancy-"))
    try:
        payload = asyncio.run(run(args.store, args.mode, args.golden))
        print_table(payload)
        line = verdict(payload)
        payload["verdict"] = line
        print(f"\n{line}")
        if args.out:
            args.out.write_text(json.dumps(payload, indent=2) + "\n")
            print(f"wrote {args.out}")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


if __name__ == "__main__":
    main()
