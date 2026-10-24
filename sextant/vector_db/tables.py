"""
Finding tables in extracted text, so their rows can be chunked as records.

A table row is not prose. "PaLM [56] Causal decoder 540B Pre LayerNorm RoPE
SwiGLU" only means something next to the header that names its columns, and
embedded in a 200-token chunk with fifteen sibling rows it is diluted past
retrieval -- the measured miss behind L25/L26 in `eval/golden-large.jsonl`.
The fix is structural: find the table, keep its header, and let `chunking.py`
emit one chunk per row with the header prepended.

Two sources, two detectors. PDF text (pypdf) has no markup, so a table is
recognised by its caption: an IEEE/ACM-style `TABLE n:` line, then a header
line, then rows until the text reads like prose again. That is a heuristic
and is documented as one; on the survey the golden set is built on it finds
18 of 21 tables (the three it skips have prose bodies) and the numbers are
in `learning/table-chunking.md`.
Markdown tables carry their own syntax (`| a | b |` under a `|---|` rule) and
need no guessing.

Nothing here imports the rest of the package: the loader and the chunker
both use it, and neither may pull the other's dependencies.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# What a table's row chunks are prefixed with, at most. The caption's opening
# sentence carries the column vocabulary the header abbreviates ("PE denotes
# position embedding"), which is exactly what a paraphrased question uses.
MAX_CONTEXT_CHARS = 240

# A caption that runs past this many lines is a paragraph that happens to
# start with "TABLE", not a caption followed by a table.
MAX_CAPTION_LINES = 12
# pypdf emits a wrapped header one cell fragment per line ("Learning" / "Rate
# Warmup Decay ..."), so a header can run to several lines before the rows.
MAX_HEADER_LINES = 9
MAX_ROWS = 120

_CAPTION = re.compile(r"^(?:TABLE|Table)\s+\d+[:.]")
_NEXT_FLOAT = re.compile(r"^(?:TABLE|Table|Fig\.|Figure|FIGURE)\s+\d+")
_SECTION_HEADING = re.compile(r"^\d+(?:\.\d+)*\s+[A-Z][a-z]")
_DIGIT = re.compile(r"\d")
_SENTENCE_END = re.compile(r"[.!?]\s*$")
# Rows carry numbers or operators; a header line (after its first) carries
# neither. That is what separates "Rate Warmup Decay Method" from
# "Transformer O(H(T +H)) O(TH(T +H))".
_ROW_MARK = re.compile(r"[\d+=×−→✓]")
_PUNCT = ".,;:()[]{}\"'“”‘’"

_MD_ROW = re.compile(r"^\s*\|.*\|\s*$")
_MD_RULE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")


@dataclass(frozen=True)
class TableSpan:
    """One table's rows, and the text every row chunk is prefixed with.

    `start`/`end` bound the rows only -- the caption and header stay in the
    prose stream so a question about the table as a whole ("comparison of
    parallelism and complexity") still finds the caption. `context` is what
    makes a lone row citable and searchable: caption opening plus header.
    """

    start: int
    end: int
    context: str


def _line_spans(text: str, lo: int, hi: int) -> list[tuple[int, int]]:
    """(start, end) of each line in `text[lo:hi]`, ends excluding the newline."""
    spans: list[tuple[int, int]] = []
    pos = lo
    while pos < hi:
        nl = text.find("\n", pos, hi)
        end = hi if nl == -1 else nl
        spans.append((pos, end))
        pos = end + 1
    return spans


_CITED_NAME = re.compile(r"^\[\d+(?:[,\u2013\u2014-]\s?\d+)*\]$")


def _is_prose(line: str) -> bool:
    """A line that reads like running text rather than a row of cells.

    Rows are numbers, symbols and Capitalised names; prose is mostly lowercase
    words. A row whose first cell is a cited name ("EPR [421] ...") is a row
    however lowercase its remaining cells. A short line that closes a
    sentence ("former and RNN.") is the tail of a wrapped paragraph.
    """
    words = line.split()
    if len(words) >= 2 and any(_CITED_NAME.match(w) for w in words[1:4]):
        return False
    if not words:
        return False
    lowercase = sum(1 for w in words if w.strip(_PUNCT).isalpha() and w.strip(_PUNCT).islower())
    ratio = lowercase / len(words)
    if len(words) >= 5:
        return ratio >= 0.5
    return _SENTENCE_END.search(line) is not None and ratio >= 0.3


def _caption_continues(line: str) -> bool:
    """Wrapped caption text, or the short last words of its final sentence."""
    words = line.split()
    return _is_prose(line) or (len(words) < 5 and _SENTENCE_END.search(line) is not None)


def _row_stops_table(line: str) -> bool:
    stripped = line.strip()
    return (
        not stripped
        or bool(_NEXT_FLOAT.match(stripped))
        or bool(_SECTION_HEADING.match(stripped))
        or _is_prose(stripped)
    )


def _is_header_continuation(line: str) -> bool:
    return not _ROW_MARK.search(line) and not _NEXT_FLOAT.match(line)


def _context(caption: str, header: str) -> str:
    caption = " ".join(caption.split())
    if len(caption) > MAX_CONTEXT_CHARS:
        cut = caption.rfind(" ", 0, MAX_CONTEXT_CHARS)
        caption = caption[: cut if cut > 0 else MAX_CONTEXT_CHARS]
    return f"{caption}\n{header}"


def find_pdf_tables(text: str, lo: int = 0, hi: int | None = None) -> list[TableSpan]:
    """Tables in caption-first extracted text, in document order.

    The caption is every line from `TABLE n:` while the lines still read as
    prose. The header is the first that does not, plus the lines after it
    until one carries a number or an operator -- a wrapped header, not a row.
    A group label sitting directly under the header ("Task") is absorbed into
    it, which costs nothing: its rows still get the word. Rows run until a
    blank line, the next float's caption, a section heading, or a line that
    reads like prose again. Fewer than two rows is not a table.
    """
    hi = len(text) if hi is None else hi
    lines = _line_spans(text, lo, hi)
    tables: list[TableSpan] = []
    i = 0
    while i < len(lines):
        s, e = lines[i]
        if not _CAPTION.match(text[s:e]):
            i += 1
            continue

        # The caption wraps mid-sentence, so "ends with a full stop" is no
        # guide to where it ends. It ends where the lines stop reading as
        # prose -- and a caption line dense with model names ("8 A800-80G SXM4
        # GPUs with 6 NVSwitch") can fail that test, so every non-prose line
        # is tried as the header and the first one followed by rows wins.
        caption_lines: list[str] = []
        j = i + 1
        caption_lines.append(text[s:e].strip())
        found: TableSpan | None = None
        while j < len(lines) and len(caption_lines) < MAX_CAPTION_LINES:
            line = text[lines[j][0] : lines[j][1]].strip()
            if not line:
                break
            if _caption_continues(line):
                caption_lines.append(line)
                j += 1
                continue
            header_lines, k = _header_at(text, lines, j)
            rows_start, rows_end, rows, k = _rows_at(text, lines, k, hi)
            if rows >= 2:
                context = _context(" ".join(caption_lines), " ".join(header_lines))
                found = TableSpan(rows_start, rows_end, context)
                j = k
                break
            caption_lines.append(line)
            j += 1

        if found is not None:
            tables.append(found)
            i = j
        else:
            i += 1
    return tables


def _header_at(text: str, lines: list[tuple[int, int]], j: int) -> tuple[list[str], int]:
    """The header starting at line `j`, and the index of the line after it."""
    header_lines: list[str] = []
    while j < len(lines) and len(header_lines) < MAX_HEADER_LINES:
        line = text[lines[j][0] : lines[j][1]].strip()
        if not line or _is_prose(line):
            break
        if header_lines and not _is_header_continuation(line):
            break
        header_lines.append(line)
        j += 1
    return header_lines, j


def _rows_at(
    text: str, lines: list[tuple[int, int]], j: int, hi: int
) -> tuple[int, int, int, int]:
    """(rows_start, rows_end, row count, index of the line after the rows)."""
    rows_start = lines[j][0] if j < len(lines) else hi
    rows_end = rows_start
    rows = 0
    while j < len(lines) and rows < MAX_ROWS:
        if _row_stops_table(text[lines[j][0] : lines[j][1]]):
            break
        rows_end = lines[j][1]
        rows += 1
        j += 1
    return rows_start, rows_end, rows, j


def find_markdown_tables(text: str) -> list[TableSpan]:
    """GitHub-flavoured pipe tables: a header row, a rule, then rows."""
    lines = _line_spans(text, 0, len(text))
    tables: list[TableSpan] = []
    i = 0
    while i + 1 < len(lines):
        head = text[lines[i][0] : lines[i][1]]
        rule = text[lines[i + 1][0] : lines[i + 1][1]]
        if not (_MD_ROW.match(head) and _MD_RULE.match(rule)):
            i += 1
            continue
        j = i + 2
        rows_start = lines[j][0] if j < len(lines) else len(text)
        rows_end = rows_start
        while j < len(lines) and _MD_ROW.match(text[lines[j][0] : lines[j][1]]):
            rows_end = lines[j][1]
            j += 1
        if j - (i + 2) >= 1:
            tables.append(TableSpan(rows_start, rows_end, head.strip()))
        i = j if j > i + 2 else i + 1
    return tables


def table_rows(text: str, table: TableSpan) -> list[tuple[int, int, str]]:
    """(start, end, group) per row line, skipping blanks.

    A line of one or two words with no digits is a group label ("Chat",
    "Basic") that applies to the rows under it, not a row itself; it is
    carried into each following row's text.
    """
    rows: list[tuple[int, int, str]] = []
    group = ""
    for s, e in _line_spans(text, table.start, table.end):
        line = text[s:e].strip()
        if not line:
            continue
        words = line.split()
        if len(words) <= 2 and not _DIGIT.search(line) and not line.startswith("|"):
            group = line
            continue
        rows.append((s, e, group))
    return rows
