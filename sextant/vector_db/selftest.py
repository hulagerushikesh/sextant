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

The grade ends in a report a person can read in one screen (item 3): one
score with how far chance alone could move it, the questions whose passage
was missed, and the documents search cannot use at all -- files the folder
pass could not store (scanned, empty, unreadable) and documents that hold the
same text as another. The assistant is told to show it as it is.

It closes with at most one suggestion (item 4), and only one the report can
back with a number: copies that cost questions, other versions of a document
that cost questions, PDFs with no text, files sharing a name, files that would
not open, copies that cost nothing. It
names the files it is about, so the evidence is in the same screen, and it
is left out when nothing found has a clear fix.

One shortcut is checked rather than trusted: a question that copies a long run
of the passage's words verbatim is a keyword match in disguise and flatters
the score. Such questions are graded and flagged, and the headline says how
many there were.
"""

from __future__ import annotations

import hashlib
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
# Another version of a document: a missed question's first result came from a
# document that holds at least this share of the passage's five-word runs.
# Found on the owner's own library (2026-11-17), where four of five misses
# were the same text in another version of the same résumé, and the report,
# which only knew word-for-word copies, could not say so.
VERSION_RUN = 5
VERSION_SHARE = 0.5
# How the chance range is drawn: the graded questions resampled this many
# times, with a fixed seed so one grade always reports one range.
CHANCE_DRAWS = 2000
CHANCE_SEED = 29
# One screen: this many missed questions and unusable documents are written
# out in the report; the rest are counted, and every one stays in the result.
REPORTED_MISSES = 5
REPORTED_DOCUMENTS = 8
# How many file names the suggestion writes out; the result keeps them all.
REPORTED_EVIDENCE = 4

# What item 2 found on three public sets (`learning/selftest-honesty.md`): the
# score followed the true one only roughly, and its level belongs to the writer.
ROUGH_GUIDE = (
    "This is a rough guide, not a measurement. Checked on three public test "
    "sets, this score followed true search quality only roughly, and it "
    "depends on who writes the questions: compare it only with earlier scores "
    "from this same assistant."
)

INSTRUCTIONS = (
    "For each passage below, write ONE question that the passage answers, the "
    "way someone who has not seen the passage would ask it. Use your own words: "
    "do not copy a phrase of eight or more words from the passage, and do not "
    "mention the document's title or file name. Then call kb_selftest_grade once "
    "with every question, each paired with its passage_id. Show the user the "
    "report it returns exactly as it is written -- it is a rough guide, and it "
    "already says so."
)

Corpus = Mapping[str, tuple[str, Mapping[str, Any]]]


def _name(meta: Mapping[str, Any], fallback: str) -> str:
    """What a person calls a document: its file name, else its title. A file
    name is what they see in their folder, and two copies can share a title."""
    source = meta.get("source")
    if source and source != "unknown":
        return str(source)
    return str(meta.get("title") or fallback)


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


def chance_range(
    ranks: Sequence[int | None],
    n: int | None = None,
    seed: int = CHANCE_SEED,
    draws: int = CHANCE_DRAWS,
) -> tuple[float, float] | None:
    """The 5th to 95th percentile of the first-five share from `n` questions,
    resampled from these ranks (`n` defaults to as many as there are)."""
    hits = [1 if r is not None and r <= 5 else 0 for r in ranks]
    if not hits:
        return None
    n = n or len(hits)
    rng = random.Random(seed)
    shares = sorted(sum(rng.choices(hits, k=n)) / n for _ in range(draws))
    return shares[int(0.05 * draws)], shares[int(0.95 * draws) - 1]


def duplicates(corpus: Corpus) -> list[dict[str, Any]]:
    """Documents whose text is the same as an earlier document's.

    Compared on the words, in order, so a copy saved with other line breaks
    or capitals still counts. The first id in sorted order is the original;
    every later one is listed against it.
    """
    chunks: dict[str, list[tuple[int, str]]] = {}
    names: dict[str, str] = {}
    for chunk_id, (text, meta) in corpus.items():
        if meta.get("kind") == SUMMARY_KIND:
            continue
        doc = str(meta.get("document_id", chunk_id))
        chunks.setdefault(doc, []).append((int(meta.get("chunk_index") or 0), text))
        names.setdefault(doc, _name(meta, doc))
    first: dict[str, str] = {}
    found: list[dict[str, Any]] = []
    for doc in sorted(chunks):
        words = " ".join(" ".join(_words(t)) for _, t in sorted(chunks[doc]))
        if not words:
            continue
        key = hashlib.sha256(words.encode()).hexdigest()
        if key in first:
            found.append(
                {
                    "document_id": doc,
                    "name": names[doc],
                    "same_as": first[key],
                    "same_as_name": names[first[key]],
                }
            )
        else:
            first[key] = doc
    return found


def cannot_search(
    corpus: Corpus,
    not_indexed: Sequence[Mapping[str, Any]] | None,
    copies: Sequence[Mapping[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """Every document search cannot use: files the folder pass could not
    store, then copies of another document. Each with a reason in plain words."""
    found = [
        {
            "name": str(item.get("file") or ""),
            "kind": str(item.get("kind") or "unreadable"),
            "why": str(item.get("reason") or "could not be indexed"),
        }
        for item in not_indexed or []
    ]
    found.sort(key=lambda d: d["kind"] != "no_text")  # scanned and empty first
    for dup in duplicates(corpus) if copies is None else copies:
        found.append(
            {
                "name": dup["name"],
                "kind": "duplicate",
                "why": (
                    f"has the same text as {dup['same_as_name']}, so the two "
                    "compete for the same results; one copy is enough"
                ),
            }
        )
    return found


def lost_to_copies(
    missed: Sequence[dict[str, Any]], copies: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    """Missed questions whose first result was another copy of their own text."""
    original = {d["document_id"]: d["same_as"] for d in copies}
    original.update({d["same_as"]: d["same_as"] for d in copies})
    lost = []
    for g in missed:
        first = g["first_result"]
        mine = g["document_id"]
        theirs = first.get("document_id") if first else None
        if theirs and theirs != mine and mine in original:
            if original.get(theirs) == original[mine]:
                lost.append(g)
    return lost


def _runs(words: Sequence[str], run: int = VERSION_RUN) -> set[tuple[str, ...]]:
    return {tuple(words[i : i + run]) for i in range(len(words) - run + 1)}


def lost_to_versions(missed: Sequence[dict[str, Any]], corpus: Corpus) -> list[dict[str, Any]]:
    """Missed questions whose first result came from another version of their
    own document: one holding most of the passage's text, and most of the
    document's (measured against the smaller of the two).

    Measured against the whole of the other document, so a version cut into
    passages at other places still counts; the second test keeps a long
    passage two different documents share, such as a footer, from counting.
    A question already lost to an exact copy is left to that.
    """
    text_of: dict[str, list[tuple[int, str]]] = {}
    for chunk_id, (text, meta) in corpus.items():
        if meta.get("kind") == SUMMARY_KIND:
            continue
        doc = str(meta.get("document_id", chunk_id))
        text_of.setdefault(doc, []).append((int(meta.get("chunk_index") or 0), text))
    runs_of: dict[str, set[tuple[str, ...]]] = {}
    lost = []
    for g in missed:
        first = g["first_result"]
        theirs = str(first.get("document_id") or "") if first else ""
        if g.get("lost_to_copy") or not theirs or theirs == str(g["document_id"]):
            continue
        mine = _runs(_words(corpus[g["passage_id"]][0]))
        own = str(g["document_id"])
        if not mine or theirs not in text_of or own not in text_of:
            continue
        for doc in (own, theirs):
            if doc not in runs_of:
                runs_of[doc] = _runs([w for _, t in sorted(text_of[doc]) for w in _words(t)])
        passage = len(mine & runs_of[theirs]) / len(mine)
        smaller = min(len(runs_of[own]), len(runs_of[theirs])) or 1
        document = len(runs_of[own] & runs_of[theirs]) / smaller
        if passage >= VERSION_SHARE and document >= VERSION_SHARE:
            lost.append(g)
    return lost


def _listing(names: Sequence[str]) -> str:
    shown = ", ".join(names[:REPORTED_EVIDENCE])
    if len(names) > REPORTED_EVIDENCE:
        shown += f" and {len(names) - REPORTED_EVIDENCE} more"
    return shown


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def suggestion(
    unusable: Sequence[Mapping[str, str]],
    lost: Sequence[Mapping[str, Any]],
    missed: int,
    versions: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any] | None:
    """The one change the report can back with a number, or `None`.

    In order: copies that cost questions (a measured effect on this score),
    then other versions of a document that cost questions, then files
    search cannot read at all -- PDFs with no text, files that would
    not open -- then
    copies that cost nothing measured. An empty non-PDF has no fix worth
    suggesting, and a miss within the right document has none a person can
    make, so neither is ever the suggestion.
    """

    def names(test: Callable[[Mapping[str, str]], bool]) -> list[str]:
        return [d["name"] for d in unusable if test(d)]

    copies = names(lambda d: d["kind"] == "duplicate")
    scanned = names(lambda d: d["kind"] == "no_text" and d["name"].lower().endswith(".pdf"))
    unreadable = names(lambda d: d["kind"] == "unreadable")
    questions: list[str] = []

    if copies and lost:
        questions = [str(g["question"]) for g in lost]
        kind, files, count = "remove_copies", copies, len(lost)
        which = "the copy" if len(copies) == 1 else f"the {len(copies)} copies"
        text = (
            f"Remove {which} ({_listing(copies)}): **{count} of the {missed} missed "
            f"questions** {'was' if count == 1 else 'were'} beaten by a copy of "
            f"{'its' if count == 1 else 'their'} own document."
        )
    elif versions:
        kind, count = "keep_one_version", len(versions)
        questions = [str(g["question"]) for g in versions]
        files = list(
            dict.fromkeys(name for g in versions for name in (g["name"], g["first_result"]["name"]))
        )
        their = "its" if count == 1 else "their"
        text = (
            f"Keep one version of each document ({_listing(files)}): "
            f"**{count} of the {missed} missed questions** found {their} text "
            f"in another version of {their} own document, which came first instead."
        )
    elif scanned:
        kind, files, count = "recognise_text", scanned, len(scanned)
        text = (
            f"Make **{_plural(count, 'PDF', 'PDFs')} with no readable text** "
            f"({_listing(scanned)}) readable: text recognition could not read "
            f"{'it' if count == 1 else 'them'}, for the reason listed above, and "
            "until then search can find nothing in "
            f"{'it' if count == 1 else 'them'}."
        )
    elif unreadable:
        kind, files, count = "check_unreadable", unreadable, len(unreadable)
        text = (
            f"Open and save again **{_plural(count, 'file', 'files')} that could "
            f"not be read** ({_listing(unreadable)}); the reason for each is "
            "listed above."
        )
    elif copies:
        kind, files, count = "remove_copies", copies, len(copies)
        text = (
            f"Remove **{_plural(count, 'copy', 'copies')}** ({_listing(copies)}): "
            "each holds the same text as another document, so the two take up "
            "each other's places in the results."
        )
    else:
        return None
    return {
        "kind": kind,
        "count": count,
        "text": text,
        "evidence": {"files": files, "questions": questions},
    }


def report(graded: Mapping[str, Any], unusable: Sequence[Mapping[str, str]], folder: bool) -> str:
    """The grade for a person: one score, what it missed, what cannot be searched."""
    n = graded["questions"]
    ranks = [g["rank"] for g in graded["results"]]
    sections: list[str] = []

    if not n:
        sections.append("No question could be graded, so there is no score.")
    else:
        found = sum(1 for r in ranks if r is not None and r <= 5)
        lines = [
            f"Search brought back the right passage in its first five results for "
            f"**{found} of {n} questions ({round(100 * found / n)}%)**."
        ]
        span = chance_range(ranks)
        if span and span[0] != span[1]:
            lines.append(
                f"With {n} questions, chance alone could move this score anywhere "
                f"from {round(100 * span[0])}% to {round(100 * span[1])}%."
                + (
                    f" Testing more passages (up to {MAX_SIZE}) narrows that."
                    if n < MAX_SIZE
                    else ""
                )
            )
        sections.append(" ".join(lines))
        caveat = ROUGH_GUIDE
        if graded["copied_wording"]:
            caveat += (
                f" {graded['copied_wording']} of the questions copied the passage's "
                "wording, which makes the score look better than it is."
            )
        sections.append(caveat)

    missed = graded["missed"]
    if missed:
        lines = [f"**Questions it missed ({len(missed)}):**"]
        # The questions a suggestion cites come first, so its evidence is shown.
        shown = sorted(
            missed, key=lambda g: (not g.get("lost_to_copy"), not g.get("lost_to_version"))
        )
        for g in shown[:REPORTED_MISSES]:
            first = g["first_result"]
            if not first:
                instead = "nothing came back"
            elif g.get("lost_to_copy"):
                instead = f"the first result was from {first['name']}, a copy of the same text"
            elif g.get("lost_to_version"):
                instead = (
                    f"the first result was from {first['name']}, another version "
                    "holding most of the same text"
                )
            elif g["document_rank"] == 1:
                instead = "another passage of the same document came first"
            else:
                instead = f"the first result was from {first['name']}"
            lines.append(f'- "{g["question"]}" (from {g["name"]}); {instead}.')
        if len(missed) > REPORTED_MISSES:
            lines.append(f"- and {len(missed) - REPORTED_MISSES} more.")
        sections.append("\n".join(lines))
    elif n:
        sections.append("**No question missed.**")

    if unusable:
        lines = [f"**Documents search cannot use ({len(unusable)}):**"]
        for d in unusable[:REPORTED_DOCUMENTS]:
            lines.append(f"- {d['name']}: {d['why']}.")
        if len(unusable) > REPORTED_DOCUMENTS:
            lines.append(f"- and {len(unusable) - REPORTED_DOCUMENTS} more.")
        sections.append("\n".join(lines))
    elif folder:
        sections.append(
            "**Every file in the folder was indexed**, and no two documents are copies."
        )
    else:
        sections.append(
            "**No two documents are copies.** Files that failed to load are "
            "listed here only when the library is a folder chosen at install."
        )

    advice = graded.get("suggestion")
    if advice:
        sections.append(f"**Fix first:** {advice['text']}")
    return "\n\n".join(sections)


def grade(
    corpus: Corpus,
    questions: Iterable[Mapping[str, Any]],
    search: Callable[[str], Sequence[Mapping[str, Any]]],
    not_indexed: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Search each question and find where its passage lands.

    `search` takes a question and returns hits in rank order, each with `id`
    and `document_id` -- `kb_search`'s own results, so the grade sees what a
    user would. `not_indexed` is the folder pass's list of files it could not
    store, or `None` when the library is not a chosen folder. A question
    naming a passage the library does not hold is not graded and is listed,
    so a typo cannot pass as a miss or a hit.
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
                "name": _name(meta, passage_id),
                "document_id": document_id,
                "rank": ids.index(passage_id) + 1 if passage_id in ids else None,
                "document_rank": (
                    documents.index(document_id) + 1 if document_id in documents else None
                ),
                "copied_wording": copied(question, text),
                "first_result": (
                    {
                        "passage_id": hits[0].get("id"),
                        "document_id": hits[0].get("document_id"),
                        "title": hits[0].get("title"),
                        "name": _name(hits[0], str(hits[0].get("id"))),
                    }
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
    ranks = [g["rank"] for g in graded]
    span = chance_range(ranks)
    result: dict[str, Any] = {
        "questions": n,
        "score": {
            "found_in_top_5": sum(1 for g in graded if top5(g)),
            "of": n,
            "chance_low": span[0] if span else None,
            "chance_high": span[1] if span else None,
        },
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
    copies = duplicates(corpus)
    lost = lost_to_copies(missed, copies)
    for g in lost:
        g["lost_to_copy"] = True
    versions = lost_to_versions(missed, corpus)
    for g in versions:
        g["lost_to_version"] = True
    result["cannot_search"] = cannot_search(corpus, not_indexed, copies)
    result["suggestion"] = suggestion(result["cannot_search"], lost, len(missed), versions)
    result["report"] = report(result, result["cannot_search"], folder=not_indexed is not None)
    return result
