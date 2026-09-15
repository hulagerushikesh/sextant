"""
Turning an uploaded file into documents the knowledge base can store.

Why this exists at all: the browser cannot read a PDF, and the loaders that can
already live in this repo. Before Phase 7 the upload panel worked around that by
accepting only text and markdown and telling the user to run a command for
everything else -- which is a reasonable answer to "how do I index a corpus" and
a bad one to "here is one file".

The file is parsed *here*, in the agent server, and the result is handed to the
`kb_ingest` MCP tool as text plus a list of locators. It is deliberately not sent
as a path: a `kb_ingest_file` tool would let any client that mounts the knowledge
base read arbitrary files on the machine, which is a far larger grant than
"search my notes". Parsing stays on the caller's side of the protocol; only data
crosses it.

Chunking still happens once, over the whole document, exactly as it does for
`sextant-ingest`. Splitting per page first would look equivalent and quietly
lose every page shorter than the minimum chunk size.
"""

from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path
from typing import Any

from tools.vector_db.loaders import (
    MARKDOWN_SUFFIXES,
    PDF_SUFFIXES,
    TEXT_SUFFIXES,
    UnsupportedDocument,
    load_path,
)

logger = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = sorted(PDF_SUFFIXES | MARKDOWN_SUFFIXES | TEXT_SUFFIXES)

# One file. A 25MB PDF is a few thousand pages; past that the CLI is the right
# tool, because it streams from disk instead of holding the upload in memory.
MAX_UPLOAD_BYTES = 25_000_000
MAX_FILES = 20

# Everything except a filename: no directory separators, no traversal, no
# leading dot. The name reaches the filesystem as a temp file and reaches the
# UI as a citation, so it is sanitised for both.
_UNSAFE = re.compile(r"[^A-Za-z0-9._ -]+")


def safe_name(filename: str) -> str:
    """A filename that cannot escape the directory it is written into."""
    base = Path(filename or "upload").name
    cleaned = _UNSAFE.sub("_", base).strip(". ")
    return cleaned or "upload"


def to_document(filename: str, data: bytes, category: str = "upload") -> dict[str, Any]:
    """Parse one uploaded file into a `kb_ingest` document.

    Raises UnsupportedDocument for a file type with no loader, and for a file
    that parses to nothing -- a scanned PDF with no text layer is the common
    case, and it should be reported rather than stored as an empty document that
    silently matches nothing.
    """
    name = safe_name(filename)
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise UnsupportedDocument(
            f"No loader for '{suffix or name}'. Supported: {', '.join(SUPPORTED_SUFFIXES)}"
        )
    if len(data) > MAX_UPLOAD_BYTES:
        raise UnsupportedDocument(
            f"{name} is {len(data) // 1_000_000}MB, over the "
            f"{MAX_UPLOAD_BYTES // 1_000_000}MB limit. Use: sextant-ingest {name}"
        )

    with tempfile.TemporaryDirectory(prefix="sextant-upload-") as directory:
        path = Path(directory) / name
        path.write_bytes(data)
        loaded = load_path(path, category=category)

    if not loaded.text.strip():
        raise UnsupportedDocument(
            f"{name} parsed to no text. A scanned PDF needs OCR before it can be indexed."
        )

    logger.info(
        "parsed %s: %d chars, %d locator(s)",
        name,
        len(loaded.text),
        len(loaded.locators),
    )
    return {
        # Stable, so re-uploading a corrected file replaces it rather than
        # storing a second copy under a new id.
        "id": f"upload:{Path(name).stem}",
        "title": loaded.title,
        "content": loaded.text,
        "source": name,
        "category": category,
        "locators": [
            {"kind": loc.kind, "label": loc.label, "start": loc.start, "end": loc.end}
            for loc in loaded.locators
        ],
    }
