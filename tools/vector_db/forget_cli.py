"""
Command-line removal: `sextant-forget`.

A corpus is curated, not only grown. A document gets ingested by mistake, or
belongs to a machine it should not have left, or its source file is gone and
its chunks answer questions about something that no longer exists. Without a
way back out the only remedy is deleting the whole store and starting again.

Removal is a command for the same reason ingestion is one, and more so: the
MCP server offers the model read tools only, and mounting "search my notes"
must never also grant "delete my notes". Deleting a document is something a
person does deliberately, to a named document, after seeing what it holds.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from tools.vector_db.vector_search import KnowledgeBase, KnowledgeBaseUnavailable


async def _listing(kb: KnowledgeBase) -> dict[str, dict[str, object]]:
    """Every document by id, with the title and chunk count `kb_list` reports."""
    result = await kb.list_documents()
    return {str(doc["document_id"]): doc for doc in result.get("documents", [])}


async def _list(kb: KnowledgeBase) -> int:
    documents = await _listing(kb)
    if not documents:
        print("The collection is empty.")
        return 0
    width = max(len(doc_id) for doc_id in documents)
    for doc_id, doc in sorted(documents.items()):
        print(f"{doc_id:<{width}}  {doc['chunks']:>4} chunks  {doc['title']}")
    return 0


async def _forget(kb: KnowledgeBase, doc_ids: list[str], assume_yes: bool) -> int:
    documents = await _listing(kb)
    unknown = [doc_id for doc_id in doc_ids if doc_id not in documents]
    for doc_id in unknown:
        print(f"  skip  {doc_id}: not in the collection")
    known = [doc_id for doc_id in doc_ids if doc_id in documents]
    if not known:
        return len(unknown)

    print("About to remove:")
    for doc_id in known:
        doc = documents[doc_id]
        print(f"  {doc_id}  ({doc['chunks']} chunks)  {doc['title']}")
    # The confirmation is the point of the command, so it is on by default;
    # `--yes` is for the non-interactive case (`docker compose exec -T`).
    if not assume_yes:
        prompt = "Remove them? This cannot be undone. [y/N] "
        answer = (await asyncio.to_thread(input, prompt)).strip().lower()
        if answer not in {"y", "yes"}:
            print("Nothing removed.")
            return 0

    failures = len(unknown)
    for doc_id in known:
        result = await kb.remove_document(doc_id)
        print(("  ok    " if result["success"] else "  fail  ") + str(result["message"]))
        if not result["success"]:
            failures += 1

    stats = await kb.health_check()
    print(f"\ncollection: {stats['documents']} documents, {stats['collection_size']} chunks")
    return failures


def main() -> None:
    """Console-script entry point: `sextant-forget`."""
    parser = argparse.ArgumentParser(
        prog="sextant-forget",
        description="Remove documents and all their chunks from the knowledge base.",
    )
    parser.add_argument(
        "document_ids", nargs="*", help="document ids, as `sextant-forget --list` prints them"
    )
    parser.add_argument(
        "-l", "--list", action="store_true", help="print the documents and their ids"
    )
    parser.add_argument("-y", "--yes", action="store_true", help="skip the confirmation")
    args = parser.parse_args()

    if args.list == bool(args.document_ids):
        parser.error("give document ids to remove, or --list to see them")

    try:
        if args.list:
            failures = asyncio.run(_list(KnowledgeBase()))
        else:
            failures = asyncio.run(_forget(KnowledgeBase(), args.document_ids, args.yes))
    except KnowledgeBaseUnavailable as e:
        sys.exit(str(e))
    if failures:
        sys.exit(f"{failures} document(s) not removed")


if __name__ == "__main__":
    main()
