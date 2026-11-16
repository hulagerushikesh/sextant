"""
A self-test for the user's own library (milestone 29, item 1).

The project's numbers grade the pipeline on questions written alongside the
test documents. This grades it on *the user's* documents, with no key and
nothing sent anywhere new:

1. `sample` picks passages from the library, spread across its documents.
2. The user's own assistant -- the one already reading `kb_search` results --
   writes one question per passage that the passage answers.
3. `grade` searches each question exactly as `kb_search` would and reports
   whether the passage it came from comes back first, or in the first five.

The questions are written by whatever model the user runs, so the score is a
property of the library *and* of that model's question-writing. Whether it
tracks the true score at all is item 2's job, on the public sets, where the
true answers are known; until that passes, this is a rough guide and says so.

One shortcut is checked rather than trusted: a question that copies a long run
of the passage's words verbatim is a keyword match in disguise and flatters
the score. Such questions are graded and flagged, and the headline says how
many there were.
"""

from __future__ import annotations

import random
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

from sextant.vector_db.summaries import SUMMARY_KIND

DEFAULT_SIZE = 20
MAX_SIZE = 50
# A passage this short rarely holds a fact worth asking about: a heading, a
# page number, the tail of a table. Counted in words, as a reader would.
MIN_WORDS = 25
# How deep the grade looks. The headline is the first result; five is what
# an assistant usually reads; ten says whether it was close.
SEARCH_DEPTH = 10
# Eight words in a row taken from the passage is copying, not asking.
COPIED_RUN = 8

INSTRUCTIONS = (
    "For each passage below, write ONE question that the passage answers, the "
    "way someone who has not seen the passage would ask it. Use your own words: "
    "do not copy a phrase of eight or more words from the passage, and do not "
    "mention the document's title or file name. Then call kb_selftest_grade once "
    "with every question, each paired with its passage_id. Show the user the "
    "score and the missed questions it returns, and say this is a rough guide: "
    "the score depends on the questions you wrote."
)

Corpus = Mapping[str, tuple[str, Mapping[str, Any]]]


def _words(text: str) -> list[str]:
    return re.findall(r"\w+", text.lower())


def eligible(corpus: Corpus) -> dict[str, list[str]]:
    """Passage ids worth asking about, grouped by document, in a fixed order."""
    by_document: dict[str, list[str]] = {}
    for chunk_id in sorted(corpus):
        text, meta = corpus[chunk_id]
        if meta.get("kind") == SUMMARY_KIND or len(_words(text)) < MIN_WORDS:
            continue
        by_document.setdefault(str(meta.get("document_id", chunk_id)), []).append(chunk_id)
    return by_document


def sample(corpus: Corpus, size: int = DEFAULT_SIZE, seed: int | None = None) -> dict[str, Any]:
    """Up to `size` passages, one per document in turn, so one long file
    cannot fill the test. The seed is reported, so a sample can be repeated."""
    if not 1 <= size <= MAX_SIZE:
        raise ValueError(f"size must be between 1 and {MAX_SIZE}, got {size}")
    if seed is None:
        seed = random.SystemRandom().randrange(1, 1_000_000)
    rng = random.Random(seed)
    by_document = eligible(corpus)
    pools = {doc: rng.sample(ids, len(ids)) for doc, ids in by_document.items()}
    order = sorted(pools)
    rng.shuffle(order)

    # Round by round, one passage from each document that still has one. A
    # bounded loop: every round takes at least one passage or the loop ends.
    chosen: list[str] = []
    for _ in range(max((len(ids) for ids in pools.values()), default=0)):
        for doc in order:
            if pools[doc] and len(chosen) < size:
                chosen.append(pools[doc].pop())

    passages = []
    for chunk_id in chosen:
        text, meta = corpus[chunk_id]
        passages.append(
            {
                "passage_id": chunk_id,
                "document_id": meta.get("document_id", chunk_id),
                "title": meta.get("title", "Untitled document"),
                "page": meta.get("page"),
                "section": meta.get("section"),
                "text": text,
            }
        )
    return {
        "instructions": INSTRUCTIONS,
        "seed": seed,
        "passages": passages,
        "sampled": len(passages),
        "eligible_passages": sum(len(ids) for ids in by_document.values()),
        "documents": len(by_document),
    }


def copied(question: str, passage: str, run: int = COPIED_RUN) -> bool:
    """Whether the question repeats `run` consecutive words of the passage."""
    asked = _words(question)
    if len(asked) < run:
        return False
    source = _words(passage)
    windows = {tuple(source[i : i + run]) for i in range(len(source) - run + 1)}
    return any(tuple(asked[i : i + run]) in windows for i in range(len(asked) - run + 1))


def grade(
    corpus: Corpus,
    questions: Iterable[Mapping[str, Any]],
    search: Callable[[str], Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Search each question and find where its passage lands.

    `search` takes a question and returns hits in rank order, each with `id`
    and `document_id` -- `kb_search`'s own results, so the grade sees what a
    user would. A question naming a passage the library does not hold is not
    graded and is listed, so a typo cannot pass as a miss or a hit.
    """
    graded: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    for item in questions:
        passage_id = str(item.get("passage_id") or "")
        question = str(item.get("question") or "").strip()
        if passage_id not in corpus:
            refused.append({"passage_id": passage_id, "reason": "no such passage"})
            continue
        if not question:
            refused.append({"passage_id": passage_id, "reason": "empty question"})
            continue
        text, meta = corpus[passage_id]
        document_id = meta.get("document_id", passage_id)
        hits = list(search(question))[:SEARCH_DEPTH]
        ids = [hit.get("id") for hit in hits]
        documents = [hit.get("document_id") for hit in hits]
        graded.append(
            {
                "passage_id": passage_id,
                "question": question,
                "title": meta.get("title", "Untitled document"),
                "rank": ids.index(passage_id) + 1 if passage_id in ids else None,
                "document_rank": (
                    documents.index(document_id) + 1 if document_id in documents else None
                ),
                "copied_wording": copied(question, text),
                "first_result": (
                    {"passage_id": hits[0].get("id"), "title": hits[0].get("title")}
                    if hits
                    else None
                ),
            }
        )

    n = len(graded)

    def share(test: Callable[[dict[str, Any]], bool]) -> float | None:
        return round(sum(1 for g in graded if test(g)) / n, 3) if n else None

    def first(g: dict[str, Any]) -> bool:
        return g["rank"] == 1

    def top5(g: dict[str, Any]) -> bool:
        return g["rank"] is not None and g["rank"] <= 5

    missed = [g for g in graded if not top5(g)]
    return {
        "questions": n,
        "found_first": share(first),
        "found_in_top_5": share(top5),
        "right_document_first": share(lambda g: g["document_rank"] == 1),
        "copied_wording": sum(1 for g in graded if g["copied_wording"]),
        "missed": missed,
        "results": graded,
        "not_graded": refused,
        "how_to_read": (
            "found_first is the share of questions whose own passage came back as "
            "the first result; found_in_top_5 allows the first five. 'missed' lists "
            "the questions whose passage was not in the first five. A rough guide, "
            "not a measurement: the score depends on how the questions were written, "
            "and questions that copied the passage's wording (copied_wording) make "
            "it look better than it is."
        ),
    }
