"""
Score the four search stages on public test sets (milestone 28).

The committed golden set was written by the same hands as the corpus, so its
figures say nothing about how sextant compares with anything else. The BEIR
collection's sets are what the field reports on: fixed documents, fixed
questions, relevance judged by people who never saw this code. Scoring on
them puts sextant's numbers beside numbers other people published.

The measure is BEIR's own: nDCG@10 over *graded* relevance with linear gain
(what `pytrec_eval` computes), on the `test` split, with every judged
document of grade > 0 counting toward the ideal. Chunks collapse to the
document they came from -- a set judges documents, and five chunks of one
abstract are one abstract retrieved.

Two things differ from a published run and are said wherever a figure is:

  * the pipeline returns at most `CANDIDATES` chunks per stage, so recall is
    reported at 10, not BEIR's customary 100;
  * BM25 here is sextant's own index, not the Elasticsearch run in the paper.

Usage:

    python -m sextant.eval.public_sets --data DIR/scifact --out scifact.json

`DIR/<set>` is an unzipped BEIR archive: corpus.jsonl, queries.jsonl and
qrels/test.tsv. Nothing here downloads; the index goes to a throwaway
directory and is deleted afterwards, unless `--store DIR` keeps it so that a
later run grades it without indexing again (FiQA takes half an hour to index).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import shutil
import sys
import tempfile
import time
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

from sextant import settings

K = 10
# Chunks asked for per question. More than K so that, after chunks collapse
# to documents, there are still K distinct documents to grade.
CHUNK_LIMIT = 30
INGEST_BATCH = 256


def graded_ndcg_at_k(retrieved: Sequence[str], gains: dict[str, float], k: int = K) -> float:
    """nDCG@k with graded relevance and linear gain, as `pytrec_eval` computes it.

    `retrieved` is document ids in rank order, already de-duplicated. A
    document judged 0 contributes nothing, and is not in the ideal either.
    """
    judged = sorted((g for g in gains.values() if g > 0), reverse=True)
    if not judged:
        return 0.0
    dcg = sum(
        gains.get(doc, 0.0) / math.log2(rank + 1)
        for rank, doc in enumerate(retrieved[:k], start=1)
        if gains.get(doc, 0.0) > 0
    )
    ideal = sum(g / math.log2(rank + 1) for rank, g in enumerate(judged[:k], start=1))
    return dcg / ideal


def recall_at(retrieved: Sequence[str], gains: dict[str, float], k: int = K) -> float:
    relevant = {doc for doc, g in gains.items() if g > 0}
    if not relevant:
        return 0.0
    return len(relevant & set(retrieved[:k])) / len(relevant)


def documents_in_order(document_ids: Sequence[str]) -> list[str]:
    """Chunk-level document ids collapsed to distinct documents, first seen first."""
    return list(dict.fromkeys(document_ids))


def load_qrels(path: Path) -> dict[str, dict[str, float]]:
    """query id -> {document id: grade}, from a BEIR qrels TSV with a header."""
    qrels: dict[str, dict[str, float]] = {}
    with path.open(newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        header = next(reader)
        if [h.strip() for h in header[:3]] != ["query-id", "corpus-id", "score"]:
            raise ValueError(f"{path} does not start with a BEIR qrels header: {header}")
        for row in reader:
            if len(row) < 3:
                continue
            qrels.setdefault(row[0], {})[row[1]] = float(row[2])
    return qrels


def load_queries(path: Path, wanted: set[str]) -> dict[str, str]:
    queries: dict[str, str] = {}
    with path.open() as handle:
        for line in handle:
            if line.strip():
                item = json.loads(line)
                if item["_id"] in wanted:
                    queries[item["_id"]] = item["text"]
    missing = wanted - set(queries)
    if missing:
        raise ValueError(f"{len(missing)} judged questions have no text in {path}")
    return queries


def iter_corpus(path: Path) -> Iterator[dict[str, str]]:
    """Each document as sextant ingests it: title and text joined, as BEIR does."""
    with path.open() as handle:
        for line in handle:
            if not line.strip():
                continue
            item = json.loads(line)
            title = (item.get("title") or "").strip()
            text = (item.get("text") or "").strip()
            content = f"{title}\n\n{text}" if title and text else (title or text)
            yield {"id": item["_id"], "title": title or item["_id"], "content": content}


async def ingest(kb: Any, corpus: Path) -> dict[str, int]:
    """Store every non-empty document. Empty ones are counted, not hidden."""
    documents = chunks = empty = 0
    batch: list[dict[str, Any]] = []
    started = time.time()

    async def flush() -> None:
        nonlocal documents, chunks
        if not batch:
            return
        result = await kb.add_documents(
            [{**d, "source": corpus.parent.name, "category": "beir"} for d in batch]
        )
        if not result["success"]:
            raise RuntimeError(f"ingest failed: {result['message']}")
        documents += result["documents_added"]
        chunks += result["chunks_added"]
        batch.clear()
        print(
            f"  ingested {documents} documents, {chunks} chunks "
            f"({time.time() - started:.0f}s)",
            file=sys.stderr,
        )

    for document in iter_corpus(corpus):
        if not document["content"]:
            empty += 1
            continue
        batch.append(document)
        if len(batch) >= INGEST_BATCH:
            await flush()
    await flush()
    return {"documents": documents, "chunks": chunks, "empty_skipped": empty}


async def grade_mode(
    kb: Any, queries: dict[str, str], qrels: dict[str, dict[str, float]], mode: str
) -> dict[str, Any]:
    ndcg: list[float] = []
    recall: list[float] = []
    started = time.time()
    for qid, text in queries.items():
        result = await kb.search(text, limit=CHUNK_LIMIT, mode=mode, min_score=0.0)
        docs = documents_in_order([hit["document_id"] for hit in result["results"]])
        ndcg.append(graded_ndcg_at_k(docs, qrels[qid]))
        recall.append(recall_at(docs, qrels[qid]))
    seconds = time.time() - started
    return {
        f"ndcg@{K}": round(sum(ndcg) / len(ndcg), 4),
        f"recall@{K}": round(sum(recall) / len(recall), 4),
        "ms_per_question": round(1000 * seconds / len(queries), 1),
    }


async def run(data: Path, modes: Sequence[str], reuse: bool = False) -> dict[str, Any]:
    from sextant.vector_db import vector_search
    from sextant.vector_db.chunking import configured_chunk_sizes
    from sextant.vector_db.vector_search import KnowledgeBase

    qrels = {
        q: g
        for q, g in load_qrels(data / "qrels" / "test.tsv").items()
        if any(v > 0 for v in g.values())
    }
    queries = load_queries(data / "queries.jsonl", set(qrels))
    print(f"{data.name}: {len(queries)} test questions", file=sys.stderr)

    kb = KnowledgeBase()
    started = time.time()
    if reuse and kb.collection.count():
        # A kept index from an earlier run of the same set: grade it as is.
        print(f"  reusing {kb.collection.count()} stored chunks", file=sys.stderr)
        stored = {"chunks": kb.collection.count(), "reused": 1}
    else:
        stored = await ingest(kb, data / "corpus.jsonl")
    ingest_seconds = round(time.time() - started)
    health = await kb.health_check()

    results: dict[str, Any] = {}
    for mode in modes:
        results[mode] = await grade_mode(kb, queries, qrels, mode)
        print(f"  {mode:<8} {results[mode]}", file=sys.stderr)

    return {
        "set": data.name,
        "split": "test",
        "questions": len(queries),
        "measure": f"nDCG@{K}, graded, linear gain",
        "stored": stored,
        "ingest_seconds": ingest_seconds,
        "embedding_model": health.get("embedding_model"),
        "chunk_tokens": configured_chunk_sizes()[0],
        "chunk_limit": CHUNK_LIMIT,
        "candidates_per_stage": vector_search.CANDIDATES,
        "rerank_depth": vector_search.RERANK_DEPTH,
        "max_per_document": vector_search.MAX_PER_DOCUMENT,
        "modes": results,
    }


def main() -> None:
    from sextant.vector_db.vector_search import RETRIEVAL_MODES

    parser = argparse.ArgumentParser(
        prog="python -m sextant.eval.public_sets",
        description="Score the search stages on one unzipped BEIR test set.",
    )
    parser.add_argument("--data", type=Path, required=True, help="unzipped BEIR set directory")
    parser.add_argument(
        "--modes", nargs="+", default=list(RETRIEVAL_MODES), choices=RETRIEVAL_MODES
    )
    parser.add_argument("--out", type=Path, help="write results JSON here")
    parser.add_argument(
        "--store",
        type=Path,
        help="keep the index here and reuse it on the next run (default: a throwaway "
        "directory, deleted afterwards)",
    )
    args = parser.parse_args()

    store = args.store or Path(tempfile.mkdtemp(prefix="sextant-beir-"))
    settings.setenv("CHROMA_DIR", str(store))
    try:
        payload = asyncio.run(run(args.data, args.modes, reuse=args.store is not None))
    finally:
        if args.store is None:
            shutil.rmtree(store, ignore_errors=True)
    text = json.dumps(payload, indent=2) + "\n"
    if args.out:
        args.out.write_text(text)
    print(text)


if __name__ == "__main__":
    main()
