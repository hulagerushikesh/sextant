"""
Splitting documents into retrievable pieces.

Two constraints shape this. The embedding model has a hard token limit and
truncates silently past it, so a chunk that overflows loses its tail without
saying so. And a citation has to name a place -- so every chunk carries the
character span it came from, which is what lets `loaders.py` say which page or
section it fell in.

Splitting happens at the largest boundary that fits: paragraphs first, sentences
if a paragraph is too big, words if a sentence is. Chunks then overlap slightly,
so a fact sitting on a chunk boundary is whole in at least one of them.

Tables are the exception to all of that. A row is a record whose meaning lives
in the header, so each row becomes its own chunk with the table's caption and
header written in front of it (`tables.py` finds them). Those chunks are the
one place `text` is not a plain slice of the document: the span still points at
the row alone, so the citation is exact, while the embedded text carries the
column names the row needs to be found by.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from tools.vector_db.tables import TableSpan, table_rows

# Well under the 256-token wall so the chunk plus its special tokens always fit,
# with room for the token count below being an approximation.
DEFAULT_TARGET_TOKENS = 200
DEFAULT_OVERLAP_TOKENS = 40

# Rows are packed under one copy of their header until they reach this many
# tokens. One row per chunk is the purest form of the idea, but a dozen
# near-identical 30-token chunks from one table crowd every other document
# out of a dense top-5 (measured: handbook recall@5 0.99 -> 0.94). Four or
# five rows together keep each row findable without that; 120 beat 80 and
# 0 on both golden sets (`learning/table-chunking.md`).
DEFAULT_ROW_TOKENS = 120

# Below this a chunk is a fragment -- a heading on its own, a stray line -- and
# is merged backwards rather than embedded as if it were a passage.
MIN_CHUNK_TOKENS = 20

_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"\s+")

TokenCounter = Callable[[str], int]


@dataclass(frozen=True)
class Chunk:
    """One retrievable passage, with the span of the document it came from.

    `kind` is "text" for a passage sliced straight from the document and "row"
    for a table row, whose `text` is the row plus its table's header.
    """

    text: str
    index: int
    char_start: int
    char_end: int
    tokens: int
    kind: str = "text"


def _split_span(text: str, lo: int, hi: int, pattern: re.Pattern[str]) -> list[tuple[int, int]]:
    """Split `text[lo:hi]` on `pattern`, returning spans in the original text."""
    spans: list[tuple[int, int]] = []
    pos = lo
    for match in pattern.finditer(text, lo, hi):
        if match.start() > pos:
            spans.append((pos, match.start()))
        pos = match.end()
    if pos < hi:
        spans.append((pos, hi))
    return spans or [(lo, hi)]


def _leaf_spans(
    text: str, count_tokens: TokenCounter, target: int, lo: int = 0, hi: int | None = None
) -> list[tuple[int, int, int]]:
    """Break `text[lo:hi]` into units that each fit the budget.

    Returns (start, end, tokens). Descends only as far as it has to: a
    paragraph that already fits is never split into sentences.
    """
    hi = len(text) if hi is None else hi
    leaves: list[tuple[int, int, int]] = []

    def descend(lo: int, hi: int, patterns: list[re.Pattern[str]]) -> None:
        if lo >= hi:
            return
        tokens = count_tokens(text[lo:hi])
        if tokens <= target or not patterns:
            # No patterns left means a single unbroken word longer than the
            # budget -- a URL, a base64 blob. Emitting it oversized is better
            # than cutting it mid-token; the packer keeps it alone.
            leaves.append((lo, hi, tokens))
            return
        for span_lo, span_hi in _split_span(text, lo, hi, patterns[0]):
            descend(span_lo, span_hi, patterns[1:])

    for para_lo, para_hi in _split_span(text, lo, hi, _PARAGRAPH):
        descend(para_lo, para_hi, [_SENTENCE, _WORD])
    return leaves


def _overlap_tail(
    units: list[tuple[int, int, int]], overlap: int, target: int
) -> list[tuple[int, int, int]]:
    """The trailing units worth up to `overlap` tokens, to open the next chunk."""
    if overlap <= 0 or len(units) < 2:
        return []

    tail: list[tuple[int, int, int]] = []
    total = 0
    for unit in reversed(units):
        if total + unit[2] > overlap:
            break
        tail.insert(0, unit)
        total += unit[2]

    # A greedy fit alone produces no overlap at all whenever the units are
    # coarser than the budget -- one 48-token paragraph against a 40-token
    # overlap fits nothing, and every chunk butts up against the next. Carry the
    # last unit anyway when it still leaves most of the next chunk free.
    if not tail and units[-1][2] <= target // 2:
        tail = [units[-1]]

    # Never carry the whole chunk forward -- that would not advance.
    return tail if len(tail) < len(units) else tail[1:]


def chunk_text(
    text: str,
    count_tokens: TokenCounter,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    min_tokens: int = MIN_CHUNK_TOKENS,
    tables: Sequence[TableSpan] = (),
    row_tokens: int = DEFAULT_ROW_TOKENS,
) -> list[Chunk]:
    """Split `text` into overlapping chunks that fit the embedder's budget.

    Chunk text is sliced straight out of the original, so `char_start` and
    `char_end` are exact and the whitespace between units is preserved. The
    spans in `tables` are chunked row by row instead (see the module note),
    with consecutive rows sharing a chunk up to `row_tokens` of row text
    (0 means one row per chunk); prose on either side of a table is chunked
    on its own, never merged across it.
    """
    if not text.strip():
        return []

    chunks: list[Chunk] = []
    pos = 0
    for table in sorted(tables, key=lambda t: t.start):
        if table.start < pos or table.end > len(text):
            continue  # overlapping or out-of-range spans: keep the prose path
        rows = table_rows(text, table)
        if not rows:
            continue  # nothing row-shaped inside: the prose path keeps the text
        _chunk_prose(text, pos, table.start, count_tokens, target_tokens, overlap_tokens, chunks)
        _chunk_rows(text, table, rows, count_tokens, row_tokens, chunks)
        pos = table.end
    _chunk_prose(text, pos, len(text), count_tokens, target_tokens, overlap_tokens, chunks)

    return _merge_runt(chunks, text, min_tokens)


def _chunk_rows(
    text: str,
    table: TableSpan,
    rows: list[tuple[int, int, str]],
    count_tokens: TokenCounter,
    row_tokens: int,
    chunks: list[Chunk],
) -> None:
    """Emit the table's rows as chunks, a few at a time, each under its header."""
    batch: list[tuple[int, int, str]] = []
    batch_tokens = 0

    def flush() -> None:
        if not batch:
            return
        lines = [f"{g} {text[s:e].strip()}" if g else text[s:e].strip() for s, e, g in batch]
        body = table.context + "\n" + "\n".join(lines)
        chunks.append(
            Chunk(
                text=body,
                index=len(chunks),
                char_start=batch[0][0],
                char_end=batch[-1][1],
                tokens=count_tokens(body),
                kind="row",
            )
        )

    for start, end, group in rows:
        tokens = count_tokens(text[start:end])
        if batch and (batch_tokens + tokens > row_tokens or group != batch[-1][2]):
            flush()
            batch, batch_tokens = [], 0
        batch.append((start, end, group))
        batch_tokens += tokens
    flush()


def _chunk_prose(
    text: str,
    lo: int,
    hi: int,
    count_tokens: TokenCounter,
    target_tokens: int,
    overlap_tokens: int,
    chunks: list[Chunk],
) -> None:
    """Pack `text[lo:hi]` into overlapping chunks, appending to `chunks`."""
    if lo >= hi or not text[lo:hi].strip():
        return
    leaves = _leaf_spans(text, count_tokens, target_tokens, lo, hi)
    if not leaves:
        return

    # Token counts are summed per unit rather than recounted for every candidate
    # chunk. Subword boundaries make that a slight approximation, which is what
    # the margin between target_tokens and the model's 256 absorbs -- and it
    # turns packing a long PDF from quadratic tokenizer calls into linear.
    current: list[tuple[int, int, int]] = []
    current_tokens = 0

    def flush() -> None:
        nonlocal current, current_tokens
        if not current:
            return
        start, end = current[0][0], current[-1][1]
        chunks.append(
            Chunk(
                text=text[start:end],
                index=len(chunks),
                char_start=start,
                char_end=end,
                tokens=current_tokens,
            )
        )

    for unit in leaves:
        if current and current_tokens + unit[2] > target_tokens:
            flush()
            current = _overlap_tail(current, overlap_tokens, target_tokens)
            current_tokens = sum(u[2] for u in current)
        current.append(unit)
        current_tokens += unit[2]
    flush()


def _merge_runt(chunks: list[Chunk], text: str, min_tokens: int) -> list[Chunk]:
    """Fold a too-short final chunk into the one before it.

    Only the last chunk can be short -- every other one was flushed because it
    hit the budget. Table rows are short by design and are never merged.
    """
    if len(chunks) < 2 or chunks[-1].tokens >= min_tokens:
        return chunks
    if chunks[-1].kind == "row" or chunks[-2].kind == "row":
        return chunks

    runt = chunks.pop()
    previous = chunks[-1]
    chunks[-1] = Chunk(
        text=text[previous.char_start : runt.char_end],
        index=previous.index,
        char_start=previous.char_start,
        char_end=runt.char_end,
        tokens=previous.tokens + runt.tokens,
    )
    return chunks
