"""
Turning files into documents that can be cited.

A citation is only useful if it names a place, so a loader's real job is not
extracting text -- it is recording *where in the file* each stretch of text came
from. Every loader returns one flat string plus a list of locators over it, and
`locate()` maps a character offset back to a page or a section heading. That is
what lets a chunk spanning a page break still say which page it starts on.

Loaders also mark the tables they can see (`tables.py`), as "table" locators
whose label is the text a row chunk should be prefixed with. The chunker turns
those into one chunk per row; nothing else about the text changes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.vector_db.tables import TableSpan, find_markdown_tables, find_pdf_tables

logger = logging.getLogger(__name__)

PDF_SUFFIXES = {".pdf"}
MARKDOWN_SUFFIXES = {".md", ".markdown"}
TEXT_SUFFIXES = {".txt", ".text", ".rst", ".log"}

_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*$", re.MULTILINE)


class UnsupportedDocument(RuntimeError):
    """Raised for a file type with no loader."""


@dataclass(frozen=True)
class Locator:
    """A named region of the document: one page, one section, or one table."""

    kind: str  # "page" | "section" | "table"
    label: Any  # int for pages, str for sections, the row prefix for tables
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
            if locator.kind == "table":
                continue  # a place to cite is a page or a section, not a table
            if locator.start <= offset < locator.end:
                # Later locators of the same kind win, so a nested section
                # heading beats the chapter it sits under.
                found[locator.kind] = locator.label
        return found

    @property
    def tables(self) -> list[TableSpan]:
        """The table regions, in the form the chunker takes."""
        return [
            TableSpan(loc.start, loc.end, str(loc.label))
            for loc in self.locators
            if loc.kind == "table"
        ]


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
    pages, title = _pdf_pages(path)
    parts: list[str] = []
    locators: list[Locator] = []
    offset = 0

    for number, text in enumerate(pages, start=1):
        text = text.strip()
        if not text:
            continue
        locators.append(Locator("page", number, offset, offset + len(text)))
        # Tables are found page by page: a table that continues onto the next
        # page is broken there anyway, and the header is reprinted.
        for table in find_pdf_tables(text):
            locators.append(
                Locator("table", table.context, offset + table.start, offset + table.end)
            )
        parts.append(text)
        offset += len(text) + 2  # the "\n\n" joining pages

    return LoadedDocument(
        doc_id=path.stem,
        title=str(title or "").strip() or path.stem,
        text="\n\n".join(parts),
        source=path.name,
        category=category,
        locators=locators,
    )


def _pdf_pages(path: Path) -> tuple[list[str], str | None]:
    """Each page's text, and the document title if the file records one.

    PyMuPDF first. pypdf infers the spaces between words from glyph spacing
    and gets it wrong on some LaTeX builds -- arXiv 2303.18223v19 comes out
    as "isgreedy searchthat" with 3% of its words fused -- while MuPDF
    reads the layout. It also returns each table cell on its own line, so
    lines are rebuilt from span baselines here (`_page_lines`), which is
    what lets `tables.py` see a row as a row. pypdf stays as the fallback
    for an environment without the MuPDF wheel.
    """
    try:
        import pymupdf
    except ImportError:
        return _pdf_pages_pypdf(path)

    pages: list[str] = []
    with pymupdf.open(str(path)) as document:
        for number, page in enumerate(document, start=1):
            try:
                pages.append(_page_lines(page))
            except Exception as e:
                # One malformed page should not lose the other ninety-nine.
                logger.warning("Page %d of %s could not be extracted: %s", number, path.name, e)
                pages.append("")
        title = (document.metadata or {}).get("title")
    return pages, title


# Spans on one baseline closer than this are the same word (a math glyph run
# like "O(H(T+H))" arrives as several spans); further apart they are cells.
_TOUCHING_PT = 1.0
# Baselines closer than this are one line.
_BASELINE_TOL_PT = 1.5
# A span this much smaller than the page's body size is a sub/superscript
# and belongs to a line near it, not to a line of its own.
_SCRIPT_RATIO = 0.8
# How far above or below a line's baseline a script may sit and still be its.
_SCRIPT_REACH_PT = 6.0
# Blocks with fewer spans than this borrow the page's body size.
_BLOCK_BODY_MIN_SPANS = 3


def _page_lines(page: Any) -> str:
    """The page as lines, one per baseline within each text block.

    MuPDF's plain text mode emits a table row as one line per cell. Grouping
    the spans of a block by baseline instead puts the cells back on one
    line in x order, while prose -- one span per line already -- is
    unchanged. Blocks keep the two-column reading order MuPDF worked out.

    Sub- and superscripts are placed afterwards, on the row whose baseline
    is nearest and that sits beside them horizontally: a superscript's own
    baseline is above its line, so sorting it in by y would hand it to the
    line before ("hyper-parameters−8" instead of "10−8"), and a page-wide
    search by y alone would hand it to the other column.
    """
    blocks = [b for b in page.get_text("dict")["blocks"] if b.get("type") == 0]
    all_spans = [
        span
        for block in blocks
        for line in block["lines"]
        for span in line["spans"]
        if span["text"].strip()
    ]
    if not all_spans:
        return ""
    page_body = _median_size(all_spans)

    rows: list[tuple[float, list[Any]]] = []
    scripts: list[Any] = []
    for block in blocks:
        spans = [s for line in block["lines"] for s in line["spans"] if s["text"].strip()]
        # "Small" is relative to the block: a table set in \small is not a
        # page of subscripts. A block too small to have a body size of its
        # own (one stray span) is judged against the page.
        body_size = _median_size(spans) if len(spans) >= _BLOCK_BODY_MIN_SPANS else page_body
        for span in sorted(spans, key=lambda s: (s["origin"][1], s["origin"][0])):
            if span["size"] < _SCRIPT_RATIO * body_size:
                scripts.append(span)
                continue
            baseline = span["origin"][1]
            if rows and abs(rows[-1][0] - baseline) <= _BASELINE_TOL_PT:
                rows[-1][1].append(span)
            else:
                rows.append((baseline, [span]))

    for span in scripts:
        if not rows:
            rows.append((span["origin"][1], [span]))
        else:
            min(rows, key=lambda row: _script_distance(row, span))[1].append(span)

    lines: list[str] = []
    for _, cells in rows:
        cells.sort(key=lambda s: s["bbox"][0])
        text = ""
        right = None
        for span in cells:
            if right is not None and span["bbox"][0] - right > _TOUCHING_PT:
                text += " "
            text += span["text"]
            right = span["bbox"][2]
        lines.append(" ".join(text.split()))
    return "\n".join(lines)


def _median_size(spans: list[Any]) -> float:
    sizes = sorted(span["size"] for span in spans)
    return float(sizes[len(sizes) // 2])


def _script_distance(row: tuple[float, list[Any]], span: Any) -> tuple[bool, float]:
    """Rows within reach of the script's baseline first, then the nearest."""
    dy = abs(row[0] - span["origin"][1])
    left = min(s["bbox"][0] for s in row[1])
    right = max(s["bbox"][2] for s in row[1])
    dx = max(left - span["bbox"][2], span["bbox"][0] - right, 0.0)
    return (dy > _SCRIPT_REACH_PT, dx + dy)


def _pdf_pages_pypdf(path: Path) -> tuple[list[str], str | None]:
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover - dependency is declared
        raise UnsupportedDocument(
            f"Neither pymupdf nor pypdf is installed ({e}). Run: pip install -e '.[dev]'"
        ) from e

    reader = PdfReader(str(path))
    pages: list[str] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            pages.append(page.extract_text() or "")
        except Exception as e:
            logger.warning("Page %d of %s could not be extracted: %s", number, path.name, e)
            pages.append("")
    title = reader.metadata.title if reader.metadata else None
    return pages, title


def _load_markdown(path: Path, category: str) -> LoadedDocument:
    text = path.read_text(encoding="utf-8", errors="replace")

    headings = [(m.start(), m.group(2).strip()) for m in _HEADING.finditer(text)]
    locators = [
        Locator("section", label, start, headings[i + 1][0] if i + 1 < len(headings) else len(text))
        for i, (start, label) in enumerate(headings)
    ]
    locators += [
        Locator("table", table.context, table.start, table.end)
        for table in find_markdown_tables(text)
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
