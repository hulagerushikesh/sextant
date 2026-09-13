"""Chunking invariants.

Every property here corresponds to something that was once wrong: chunks that
overflowed the embedder and lost their tail silently, chunks that did not
overlap at all, and offsets that could not be trusted to locate a citation.
"""

from __future__ import annotations

import pytest

from tools.vector_db.chunking import DEFAULT_TARGET_TOKENS, chunk_text

PARAGRAPH = (
    "The assignment problem asks how to pair workers with tasks at minimum total "
    "cost. The Hungarian algorithm solves it in cubic time by repeatedly "
    "augmenting a matching along equality-graph paths."
)


def words(count: int) -> str:
    return " ".join(f"w{i}" for i in range(count))


@pytest.fixture
def counter(embedder):
    """The real tokenizer. Use this where the model's budget is the point."""
    return embedder.count_tokens


@pytest.fixture
def simple_counter():
    """A tokenizer-independent counter, roughly four characters per token.

    The chunker takes `count_tokens` as a parameter so its packing logic can be
    exercised without a model in the way -- and so branches that a particular
    tokenizer happens not to reach are still reachable here.
    """
    return lambda text: max(1, len(text) // 4)


class TestInvariants:
    @pytest.fixture
    def long_document(self) -> str:
        return "\n\n".join(f"Section {i}. {PARAGRAPH}" for i in range(20))

    def test_offsets_slice_back_to_the_chunk(self, long_document, counter):
        for chunk in chunk_text(long_document, counter):
            assert chunk.text == long_document[chunk.char_start : chunk.char_end]

    def test_nothing_but_whitespace_falls_between_chunks(self, long_document, counter):
        chunks = chunk_text(long_document, counter)
        dropped = "".join(
            long_document[a.char_end : b.char_start]
            for a, b in zip(chunks, chunks[1:], strict=False)
            if b.char_start > a.char_end
        )
        assert dropped.strip() == ""

    def test_document_is_covered_end_to_end(self, long_document, counter):
        chunks = chunk_text(long_document, counter)
        assert chunks[0].char_start == 0
        assert chunks[-1].char_end == len(long_document)

    def test_no_chunk_exceeds_the_embedder_budget(self, long_document, embedder):
        # The bug this pins: MiniLM truncates past 256 word pieces without
        # raising, so an oversized chunk loses its tail and nothing says so.
        for chunk in chunk_text(long_document, embedder.count_tokens):
            assert embedder.count_tokens(chunk.text) <= embedder.max_tokens

    def test_consecutive_chunks_overlap(self, long_document, counter):
        # Regression: with paragraph-sized units larger than the overlap budget,
        # the greedy tail fit nothing and every chunk butted against the next.
        chunks = chunk_text(long_document, counter)
        assert len(chunks) > 1
        assert all(
            b.char_start < a.char_end for a, b in zip(chunks, chunks[1:], strict=False)
        )

    def test_chunks_always_advance(self, long_document, counter):
        chunks = chunk_text(long_document, counter)
        assert all(
            b.char_start > a.char_start for a, b in zip(chunks, chunks[1:], strict=False)
        )


class TestDegenerate:
    def test_empty(self, counter):
        assert chunk_text("", counter) == []

    def test_whitespace_only(self, counter):
        assert chunk_text("   \n\n \t ", counter) == []

    def test_shorter_than_one_chunk(self, counter):
        chunks = chunk_text("Short sentence.", counter)
        assert len(chunks) == 1
        assert chunks[0].text == "Short sentence."

    def test_a_very_long_unbroken_token_survives_intact(self, counter):
        # Note what the real tokenizer does here: BERT caps a word at 100
        # characters and emits [UNK] past it, so a 4,000-character blob counts
        # as one token. The chunk is not oversized -- but the blob contributes
        # nothing to the embedding either, which is a property of the model
        # worth knowing rather than something chunking can fix.
        chunks = chunk_text("x" * 4000, counter)
        assert len(chunks) == 1
        assert chunks[0].text == "x" * 4000

    def test_an_unsplittable_oversized_unit_is_emitted_whole(self, simple_counter):
        # With no split point left, cutting mid-token would be worse than
        # emitting an oversized chunk -- and the packer must not spin trying.
        blob = "x" * 4000  # 1000 tokens under the synthetic counter
        chunks = chunk_text(blob, simple_counter)
        assert len(chunks) == 1
        assert chunks[0].tokens > DEFAULT_TARGET_TOKENS

    def test_one_enormous_sentence_is_split_on_words(self, counter):
        chunks = chunk_text(words(900), counter)
        assert len(chunks) > 1
        assert all(chunk.tokens <= DEFAULT_TARGET_TOKENS * 1.2 for chunk in chunks)

    def test_packing_is_tokenizer_independent(self, simple_counter):
        document = "\n\n".join([PARAGRAPH] * 12)
        chunks = chunk_text(document, simple_counter, target_tokens=100, overlap_tokens=20)
        assert len(chunks) > 1
        assert all(chunk.text == document[chunk.char_start : chunk.char_end] for chunk in chunks)


class TestPacking:
    def test_runt_tail_is_merged_backwards(self, counter):
        # A trailing fragment should join the previous chunk rather than becoming
        # a passage of its own.
        document = "\n\n".join([PARAGRAPH] * 4 + ["Tiny."])
        chunks = chunk_text(document, counter)
        assert chunks[-1].text.endswith("Tiny.")
        assert chunks[-1].tokens > 20

    def test_indices_are_sequential(self, counter):
        chunks = chunk_text("\n\n".join([PARAGRAPH] * 8), counter)
        assert [c.index for c in chunks] == list(range(len(chunks)))

    def test_smaller_target_makes_more_chunks(self, counter):
        document = "\n\n".join([PARAGRAPH] * 8)
        assert len(chunk_text(document, counter, target_tokens=80)) > len(
            chunk_text(document, counter, target_tokens=200)
        )
