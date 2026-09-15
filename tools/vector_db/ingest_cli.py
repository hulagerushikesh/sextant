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
import sys
from pathlib import Path

from tools.vector_db.loaders import (
    MARKDOWN_SUFFIXES,
    PDF_SUFFIXES,
    TEXT_SUFFIXES,
    UnsupportedDocument,
)
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


async def _ingest(files: list[Path], category: str) -> int:
    kb = KnowledgeBase()
    failures = 0

    for path in files:
        try:
            result = await kb.add_file(str(path), category=category)
        except UnsupportedDocument as e:
            print(f"  skip  {path.name}: {e}")
            failures += 1
            continue

        if result.get("success"):
            print(f"  ok    {path.name}: {result['chunks_added']} chunks")
        else:
            print(f"  fail  {path.name}: {result.get('message')}")
            failures += 1

    stats = await kb.health_check()
    print(f"\ncollection: {stats['documents']} documents, {stats['collection_size']} chunks")
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
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
        stream=sys.stderr,
    )

    files = _expand(args.paths, args.recursive)
    if not files:
        sys.exit(f"No loadable files found. Supported: {', '.join(sorted(SUPPORTED))}")

    print(f"Indexing {len(files)} file(s)...")
    try:
        failures = asyncio.run(_ingest(files, args.category))
    except KnowledgeBaseUnavailable as e:
        sys.exit(str(e))
    if failures:
        sys.exit(f"{failures} file(s) failed")


if __name__ == "__main__":
    main()
