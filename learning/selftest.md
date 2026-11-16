# A self-test for your own library (milestone 29, item 1)

**Question.** Every number in this repository grades the pipeline on questions
written alongside its test documents. Can a user get a number for *their*
library, with no key and nothing sent anywhere new?

**What was built.** Two tools on the published server (`selftest.py`):

- `kb_selftest_sample` picks passages spread across the library's documents,
  one per document in turn so a long file cannot fill the test, skipping
  overviews and scraps under 25 words. It reports a seed, so a sample can be
  repeated. It hands the passages to the assistant with instructions: one
  question per passage, in its own words, no title.
- `kb_selftest_grade` searches each question exactly as `kb_search` does (with
  no score floor, so a low-ranked passage still has a rank) and reports how
  often the passage a question came from is first and in the first five, how
  often its document is first, and the questions it missed. A question that
  repeats eight words of its passage in a row is flagged and counted, since it
  is a keyword match in disguise.

The user's assistant writes the questions, so no key is needed and the
passages go only to the assistant already reading search results. The hosted
agent does not offer the two tools; under the hosted scope another owner's
passages are trimmed like any other hit.

**Tried on a fresh library, 2026-11-16.** This folder's 21 notes, copied to an
empty folder and indexed by the published server over MCP, as a client would
mount it (models cached, nothing downloaded): indexed in 11 s, 402 passages
eligible. I wrote 20 questions for the sampled passages as the assistant would.
Grading took 10 s.

| | Share of 20 |
| --- | --- |
| Its own passage first | 0.45 |
| Its own passage in the first five | 0.75 |
| Its document first | 0.65 |
| Questions that copied the passage | 0 |

**Reading it honestly.**

1. **The passage-level grade is strict.** These notes overlap heavily — several
   discuss the same experiment, and the index note summarises every other one.
   Of the 11 questions whose passage was not first, 4 lost to another passage
   of the same note, and 2 to the index note. That is why the document-first share (0.65) sits well above the
   passage-first one (0.45). On a library with less repetition the two should
   be closer.
2. **The score depends on who wrote the questions.** I wrote these knowing the
   notes; a user's assistant will write differently. Whether this score rises
   and falls with the true score at all is item 2, on the public sets, with
   its pass rule written first. Until then the tools call it a rough guide.
3. **This was through an MCP client, not Claude Desktop.** The done-when for
   this item is Claude Desktop on a fresh library; that try is the owner's.

**Reproduce.** Point `SEXTANT_FOLDER` at a fresh folder and `SEXTANT_CHROMA_DIR`
at an empty one, mount `sextant-kb`, and ask the assistant *"how well does
search work on my documents?"*. Pass `seed: 29`, size 20, to get this sample
of this folder.

---

## The report (milestone 29, item 3), 2026-11-16

**What changed.** `kb_selftest_grade` now ends in a `report` the assistant is
told to show exactly as written, in three parts:

1. **One score with its chance range.** "14 of 20 questions (70%)", then how
   far chance alone could move a score from that many questions: the graded
   questions resampled 2,000 times with a fixed seed, 5th to 95th percentile.
   It is the same calculation item 2 used for its spread, now one function.
   Then item 2's verdict in one sentence: a rough guide, comparable only with
   the same assistant's earlier scores.
2. **The questions it missed**, five written out and the rest counted. Each
   names its file and what came first instead; when another passage of the
   same file came first, it says so, since that is a near miss and not a
   wrong document.
3. **Documents search cannot use.** Files the folder pass could not store,
   now with a kind as well as a reason: a PDF that loads to no words is called
   probably scanned and needing text recognition (OCR), an empty text file
   is called empty, and two files with one name or a file that will not open
   keep their old reasons. Then documents holding the same words as another
   (compared word by word, so other capitals or line breaks still count).
   Every file is counted, not only the first twenty `kb_stats` lists.

Documents are named by file, not title: a person knows their folder by file
names, and a copy shares its original's title.

**Tried on a fresh library.** This folder's 23 notes plus three planted
problems (an empty text file, a one-page PDF holding only a drawn shape, and
a copy of this note under another name), indexed by the folder pass into an
empty store (models cached): indexed in 9 s, 20 questions I wrote graded in
10 s. The report came to 17 lines:

- **14 of 20 (70%)**, chance range 55% to 85%;
- 6 missed: two lost to another passage of the same note, and two lost to
  the planted copy, which is the copy problem showing up in the score;
- all three planted problems listed, scanned PDF and empty file first.

**Reading it honestly.**

1. **"One screen" is checked by a test, not by a reader.** A test caps the
   report at 25 lines with 50 misses and 30 unreadable files. Whether a
   non-engineer understands it is the item's done-when, and the owner's call.
2. **"Probably scanned" is a guess from no text at all.** A PDF with a few
   scanned pages among typed ones is stored without them and is not listed
   here. Counting those pages is item 4's kind of suggestion.
3. **Only a chosen folder's failures are known.** A file loaded with the
   ingest command that failed was never recorded, so without a folder the
   report says it cannot see them.

## One suggestion (milestone 29, item 4)

The report now closes with at most one line, **Fix first:**, and only when it
can back the line with a number from the same grade. It names the files it is
about (four, then "and N more"; every name stays in the result's `suggestion`),
so the evidence is on the same screen. In order:

1. **Copies that cost questions.** A missed question whose first result was a
   copy of its own document. The missed lines say "a copy of the same text"
   for each one and are moved to the top of the list, so the questions the
   number counts are the ones shown.
2. **PDFs with no text** — probably scanned; run them through text
   recognition (OCR).
3. **Files sharing a name** with another, of which only one is indexed.
4. **Files that would not open.**
5. **Copies that cost nothing measured.**

Nothing else is ever suggested: an empty text file has no fix worth naming,
and a miss within the right document has none a person can make. With none of
these, the line is left out.

**Tried on the same fresh library** as item 3, the same 20 questions: 18
lines, ending *"Fix first: Remove the copy (selftest-copy.md): 1 of the 6
missed questions was beaten by a copy of its own document."* Planted defects
(any wrong first result counted as a copy's fault, scanned files put ahead of a
costly copy, the cited questions not moved up, empty notes treated as scans,
the name list unbounded) were each caught by a test.

**Reading it honestly.**

1. **A correction to item 3.** That section said two misses were lost to the
   planted copy. By this rule it is one: the other question came from a
   different note and the copy merely ranked first. Whether a copy crowds out
   unrelated documents is not measured, so it is not counted.
2. **The order is a judgement, not a measurement.** A copy that cost one
   question beat a scanned PDF that search cannot read at all. A measured
   effect on the score was put first because it is the only kind the grade
   observes; a person could reasonably weigh it the other way.
3. **"Would raise the score" is not claimed.** Removing the copy is likely to
   help those questions, but the report does not re-grade without it, so it
   says what happened, not what would.
