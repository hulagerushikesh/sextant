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
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

# Well under the 256-token wall so the chunk plus its special tokens always fit,
# with room for the token count below being an approximation.
DEFAULT_TARGET_TOKENS = 200
DEFAULT_OVERLAP_TOKENS = 40

# Below this a chunk is a fragment -- a heading on its own, a stray line -- and
# is merged backwards rather than embedded as if it were a passage.
MIN_CHUNK_TOKENS = 20

_PARAGRAPH = re.compile(r"\n\s*\n")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"\s+")

TokenCounter = Callable[[str], int]


@dataclass(frozen=True)
class Chunk:
    """One retrievable passage, with the span of the document it came from."""

    text: str
    index: int
    char_start: int
    char_end: int
    tokens: int


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
    text: str, count_tokens: TokenCounter, target: int
) -> list[tuple[int, int, int]]:
    """Break the document into units that each fit the budget.

    Returns (start, end, tokens). Descends only as far as it has to: a
    paragraph that already fits is never split into sentences.
    """
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

    for para_lo, para_hi in _split_span(text, 0, len(text), _PARAGRAPH):
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
) -> list[Chunk]:
    """Split `text` into overlapping chunks that fit the embedder's budget.

    Chunk text is sliced straight out of the original, so `char_start` and
    `char_end` are exact and the whitespace between units is preserved.
    """
    if not text.strip():
        return []

    leaves = _leaf_spans(text, count_tokens, target_tokens)
    if not leaves:
        return []

    # Token counts are summed per unit rather than recounted for every candidate
    # chunk. Subword boundaries make that a slight approximation, which is what
    # the margin between target_tokens and the model's 256 absorbs -- and it
    # turns packing a long PDF from quadratic tokenizer calls into linear.
    chunks: list[Chunk] = []
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

    return _merge_runt(chunks, text, min_tokens)


def _merge_runt(chunks: list[Chunk], text: str, min_tokens: int) -> list[Chunk]:
    """Fold a too-short final chunk into the one before it.

    Only the last chunk can be short -- every other one was flushed because it
    hit the budget.
    """
    if len(chunks) < 2 or chunks[-1].tokens >= min_tokens:
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
