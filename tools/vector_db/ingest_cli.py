"""
Command-line ingestion: `sextant-ingest`.

File loading lives here rather than behind an MCP tool on purpose. A
`kb_ingest_file` tool would hand every client that mounts this server the ability
to read arbitrary paths on the machine, which is a much larger grant than
"search my notes" -- and the agent could not use it anyway, since only read tools
are offered to the model. Indexing a corpus is something a person does
deliberately, so it gets a command.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

from tools.vector_db.loaders import (
    MARKDOWN_SUFFIXES,
    PDF_SUFFIXES,
    TEXT_SUFFIXES,
    UnsupportedDocument,
)
from tools.vector_db.summaries import SummariesUnavailable, summarise
from tools.vector_db.vector_search import KnowledgeBase, KnowledgeBaseUnavailable

SUPPORTED = PDF_SUFFIXES | MARKDOWN_SUFFIXES | TEXT_SUFFIXES


def _expand(paths: list[str], recursive: bool) -> list[Path]:
    """Turn the given paths into a list of loadable files."""
    files: list[Path] = []
    for raw in paths:
        path = Path(raw).expanduser()
        if path.is_dir():
            pattern = "**/*" if recursive else "*"
            files.extend(
                sorted(p for p in path.glob(pattern) if p.suffix.lower() in SUPPORTED)
            )
        else:
            files.append(path)
    return files


def _summaries_wanted(flag: bool | None) -> bool:
    """Resolve `--summaries` / `--no-summaries` / neither against the key.

    An explicit flag wins. With neither, overviews are on when a key resolves:
    they were opt-in only because 21 extra chunks crowded the graded slots and
    cost dense recall@5 0.970 -> 0.900, and the per-document cap took that back
    in full (`learning/candidate-cap.md`). What they buy is rank -- global
    rerank hit@1 0.6 -> 1.0 -- and a `kb_list` listing that reads the model's
    overview instead of the first 240 characters of the document.

    Without a key, ingestion runs exactly as it always has and says why there
    are no overviews. That is the promise this module keeps: everything in
    ingestion works without a model.
    """
    if flag is not None:
        return flag
    if os.getenv("GEMINI_API_KEY"):
        # The default spends money on your behalf, so it says so before it
        # does: a run of 22 documents is about $0.07, and a 144-page PDF is
        # $0.05 of that on its own.
        print(
            "  note  GEMINI_API_KEY found: storing one overview per document, "
            "~$0.003 each. --no-summaries to skip."
        )
        return True
    print("  note  no GEMINI_API_KEY: storing text only, no per-document overviews.")
    return False


async def _ingest(
    files: list[Path], category: str, summaries: bool = False, required: bool = False
) -> int:
    kb = KnowledgeBase()
    failures = 0

    for path in files:
        try:
            if summaries:
                # Read first, summarise, then store text and overview together.
                # One model call per document; the chunks themselves never
                # touch the model.
                document = await kb.load_file(str(path), category=category)
                try:
                    summary = await summarise(document.text, document.title)
                except SummariesUnavailable as e:
                    if required:
                        raise
                    # Asking for overviews and not getting them is an error;
                    # the default asking on your behalf and not getting them
                    # is a line of output. The rest of the run stores text.
                    print(f"  note  overviews off for the rest of this run: {e}")
                    summaries = False
                    result = await kb.add_document(document)
                else:
                    result = await kb.add_document(document, summary=summary)
            else:
                result = await kb.add_file(str(path), category=category)
        except UnsupportedDocument as e:
            print(f"  skip  {path.name}: {e}")
            failures += 1
            continue

        if result.get("success"):
            note = " (+ overview)" if summaries else ""
            print(f"  ok    {path.name}: {result['chunks_added']} chunks{note}")
        else:
            print(f"  fail  {path.name}: {result.get('message')}")
            failures += 1

    stats = await kb.health_check()
    print(
        f"\ncollection: {stats['documents']} documents, {stats['collection_size']} chunks, "
        f"{stats['summaries']} with an overview"
    )
    return failures


def main() -> None:
    """Console-script entry point: `sextant-ingest`."""
    parser = argparse.ArgumentParser(
        prog="sextant-ingest",
        description="Index PDF, Markdown and text files into the knowledge base.",
    )
    parser.add_argument("paths", nargs="+", help="files or directories to index")
    parser.add_argument("-r", "--recursive", action="store_true", help="descend into directories")
    parser.add_argument("-c", "--category", default="general", help="tag stored chunks")
    parser.add_argument("-v", "--verbose", action="store_true", help="show loader logging")
    parser.add_argument(
        "--summaries",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="store one model-written overview chunk per document; on by default "
        "when GEMINI_API_KEY resolves, --no-summaries to store text only",
    )
    args = parser.parse_args()

    # The key lives in .env like the agent's, and is read whether or not a flag
    # was passed, because with neither flag the key is what decides.
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[2] / ".env")

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
        stream=sys.stderr,
    )

    files = _expand(args.paths, args.recursive)
    if not files:
        sys.exit(f"No loadable files found. Supported: {', '.join(sorted(SUPPORTED))}")

    print(f"Indexing {len(files)} file(s)...")
    summaries = _summaries_wanted(args.summaries)
    try:
        failures = asyncio.run(
            _ingest(files, args.category, summaries, required=args.summaries is True)
        )
    except (KnowledgeBaseUnavailable, SummariesUnavailable) as e:
        sys.exit(str(e))
    if failures:
        sys.exit(f"{failures} file(s) failed")


if __name__ == "__main__":
    main()
