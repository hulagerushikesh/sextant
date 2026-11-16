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
