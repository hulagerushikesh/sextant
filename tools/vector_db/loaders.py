"""
Turning files into documents that can be cited.

A citation is only useful if it names a place, so a loader's real job is not
extracting text -- it is recording *where in the file* each stretch of text came
from. Every loader returns one flat string plus a list of locators over it, and
`locate()` maps a character offset back to a page or a section heading. That is
what lets a chunk spanning a page break still say which page it starts on.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PDF_SUFFIXES = {".pdf"}
MARKDOWN_SUFFIXES = {".md", ".markdown"}
TEXT_SUFFIXES = {".txt", ".text", ".rst", ".log"}

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*$", re.MULTILINE)


class UnsupportedDocument(RuntimeError):
    """Raised for a file type with no loader."""


@dataclass(frozen=True)
class Locator:
    """A named region of the document: one page, or one section."""

    kind: str  # "page" | "section"
    label: Any  # int for pages, str for sections
    start: int
    end: int


@dataclass
class LoadedDocument:
    """One file, flattened, with everything needed to cite a piece of it."""

    doc_id: str
    title: str
    text: str
    source: str
    category: str = "general"
    locators: list[Locator] = field(default_factory=list)

    def locate(self, offset: int) -> dict[str, Any]:
        """Which page and section the given character offset falls in."""
        found: dict[str, Any] = {}
        for locator in self.locators:
            if locator.start <= offset < locator.end:
                # Later locators of the same kind win, so a nested section
                # heading beats the chapter it sits under.
                found[locator.kind] = locator.label
        return found


def load_path(path: str | Path, category: str = "general") -> LoadedDocument:
    """Read one file into a citable document."""
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise UnsupportedDocument(f"Not a file: {path}")

    suffix = path.suffix.lower()
    if suffix in PDF_SUFFIXES:
        return _load_pdf(path, category)
    if suffix in MARKDOWN_SUFFIXES:
        return _load_markdown(path, category)
    if suffix in TEXT_SUFFIXES:
        return _load_text(path, category)
    raise UnsupportedDocument(
        f"No loader for '{suffix}'. Supported: "
        + ", ".join(sorted(PDF_SUFFIXES | MARKDOWN_SUFFIXES | TEXT_SUFFIXES))
    )


def _load_pdf(path: Path, category: str) -> LoadedDocument:
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover - dependency is declared
        raise UnsupportedDocument(
            f"pypdf is not installed ({e}). Run: pip install -e '.[dev]'"
        ) from e

    reader = PdfReader(str(path))
    parts: list[str] = []
    locators: list[Locator] = []
    offset = 0

    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as e:
            # One malformed page should not lose the other ninety-nine.
            logger.warning("Page %d of %s could not be extracted: %s", number, path.name, e)
            text = ""
        text = text.strip()
        if not text:
            continue
        locators.append(Locator("page", number, offset, offset + len(text)))
        parts.append(text)
        offset += len(text) + 2  # the "\n\n" joining pages

    title = (reader.metadata.title if reader.metadata else None) or path.stem
    return LoadedDocument(
        doc_id=path.stem,
        title=str(title).strip() or path.stem,
        text="\n\n".join(parts),
        source=path.name,
        category=category,
        locators=locators,
    )


def _load_markdown(path: Path, category: str) -> LoadedDocument:
    text = path.read_text(encoding="utf-8", errors="replace")

    headings = [(m.start(), m.group(2).strip()) for m in _HEADING.finditer(text)]
    locators = [
        Locator("section", label, start, headings[i + 1][0] if i + 1 < len(headings) else len(text))
        for i, (start, label) in enumerate(headings)
    ]

    return LoadedDocument(
        doc_id=path.stem,
        title=headings[0][1] if headings else path.stem,
        text=text,
        source=path.name,
        category=category,
        locators=locators,
    )


def _load_text(path: Path, category: str) -> LoadedDocument:
    return LoadedDocument(
        doc_id=path.stem,
        title=path.stem,
        text=path.read_text(encoding="utf-8", errors="replace"),
        source=path.name,
        category=category,
    )
