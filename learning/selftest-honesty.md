# Is the self-test honest? (milestone 29, item 2) — the rule, written first

**Written 2026-11-16, before any run.** This file is committed and pushed
before a single question is generated, so the rule below cannot have been
fitted to the result. The result will be added underneath, and this section
will not be edited.

**Question.** The self-test (`selftest.md`) says how often search brings back
the passage a question was written from. Does that number rise and fall with
the true score — the one graded against human relevance judgements — or does
it only measure how easy it is to find a passage from words taken out of it?

**The risk it is checking for.** A question written while looking at a passage
tends to reuse that passage's words. Keyword search loves that, so the
self-test could rate keyword search well on a library where it is in fact the
worst choice. If so, the score flatters exactly the wrong thing.

## Design

- **Sets:** SciFact, NFCorpus and FiQA (BEIR), indexed exactly as
  `public-sets.md` measured them. The true nDCG@10 of each search mode is
  re-measured on the same index in the same run, and must match the committed
  `public-sets.json` within 0.005, or the run is void.
- **Conditions:** four search modes (keyword, meaning, fused, fused + reranker)
  on three sets: **12 conditions**, each with a true score and a self-test
  score.
- **Sample:** `kb_selftest_sample` itself, 50 passages per set (the tool's
  maximum), seed 29. One set of questions per set, graded under all four
  modes, so mode differences are paired.
- **Question writers:** two models, so the result is not one writer's habit:
  `gemini-3.1-flash-lite` and `gemini-3.7-flash`, each given the tool's own
  instructions and nothing else — no qrels, no queries from the set.
- **Self-test score:** `found_in_top_5`, the share of questions whose passage
  comes back in the first five. `found_first` and the copied-wording count are
  reported beside it but are not part of the rule.

## The rule

All three must hold **for both writers**:

1. **It tracks the true score.** Across the 12 conditions, the rank
   correlation (Spearman) between the self-test score and the true nDCG@10 is
   **at least 0.6**.
2. **It tells a good library from a poor one.** Under the full search, SciFact
   (true 0.700) gets a higher self-test score than both NFCorpus (0.364) and
   FiQA (0.375).
3. **It is not fooled by keyword search.** On FiQA, where keyword search is
   0.16 below the best mode (0.216 against 0.375), the self-test scores keyword
   search **lowest of the four modes**. On the other two sets the modes sit
   within 0.07 of each other, closer than 50 questions can separate, so no
   order is required there.

## What each outcome means

- **All three hold for both writers:** the tools and the report stop saying
  "rough guide" and say instead that the score was checked against three
  public sets, linking this note.
- **Any one fails for either writer:** the score ships labelled "rough guide"
  (as it is now), and the results page says which rule failed.
- **Rule 1 below 0.3, or rule 2 failing, for both writers:** the score is no
  guide at all. The headline number is dropped and the self-test reports only
  the questions it missed.

Also reported, not judged: how far a score from the default 20 questions can
move by chance (resampled from the 50), so the results page can say how much
to trust a user's number.

**Cost and load, estimated before asking.** About 300 short model calls,
estimated under ₹5 and capped at ₹20. Three downloads from the BEIR host, about
22 MB. Indexing takes about 48 minutes of laptop load in all (FiQA alone about
36), one set at a time, under 1.5 GB of memory.

---

## Result, 2026-11-16 — rough guide

Run as designed: 50 passages per set, seed 29, two writers, every question
graded under all four modes. The true scores reproduced the committed
`public-sets.json` within 0.005 on all 12 conditions. Spent **$0.0765
(about ₹6.5)** on questions; the run took 73 minutes of laptop load, FiQA's
indexing about 43 of them. Every figure is in `sextant/eval/selftest-honesty.json`,
with the questions, so a re-run grades the same ones and spends nothing.

Self-test score (own passage in the first five) beside the true nDCG@10:

| Set | Mode | True | flash-lite writer | flash writer |
| --- | --- | --- | --- | --- |
| SciFact | keyword | 0.635 | 0.60 | 0.90 |
| SciFact | meaning | 0.675 | 0.72 | 0.92 |
| SciFact | fused | 0.688 | 0.70 | 0.94 |
| SciFact | full | 0.700 | 0.78 | 0.96 |
| NFCorpus | keyword | 0.299 | 0.48 | 0.82 |
| NFCorpus | meaning | 0.314 | 0.66 | 0.82 |
| NFCorpus | fused | 0.338 | 0.60 | 0.90 |
| NFCorpus | full | 0.364 | 0.74 | 0.94 |
| FiQA | keyword | 0.216 | 0.06 | 0.34 |
| FiQA | meaning | 0.373 | 0.24 | 0.52 |
| FiQA | fused | 0.343 | 0.16 | 0.56 |
| FiQA | full | 0.375 | 0.22 | 0.64 |

| Rule | flash-lite | flash |
| --- | --- | --- |
| 1. Rank correlation ≥ 0.6 | **0.58 — fails** | 0.65 — holds |
| 2. SciFact highest under the full search | holds (0.78 > 0.74, 0.22) | holds (0.96 > 0.94, 0.64) |
| 3. Keyword lowest on FiQA | holds (0.06) | holds (0.34) |

**Outcome, by the rule: rough guide.** One writer missed rule 1 by 0.02, so
the score keeps its "rough guide" label, and the results page now says which
rule failed. Neither writer came near the "no guide" line.

**Reading it honestly.**

1. **The trap it was built to catch did not spring.** Both writers rated
   keyword search worst on FiQA, where it is worst, and neither copied the
   passage's wording (one flagged question in 300).
2. **Rule 2 held, but narrowly.** SciFact beat NFCorpus by 0.04 and 0.02 —
   well inside chance for 50 questions — even though its true score is twice
   as high. The self-test is a known-passage test; NFCorpus's low true score
   comes from its many judged documents per question, which a known-passage
   test cannot see. So the self-test does **not** say a library is half as
   good as another; it separated FiQA from the rest, not NFCorpus.
3. **The level belongs to the writer.** On FiQA the flash-lite writer asked
   broad questions ("what are the career paths for finance students?") that
   fit many of 57,600 forum posts, and found 22%; the flash writer asked
   specific ones and found 64%. A score is only comparable with another score
   from the same assistant. The results page says so.
4. **Twenty questions are noisy.** Resampled from the 50, a 20-question score
   spans a range 0.10 to 0.35 wide (5th to 95th percentile). Item 3's report
   has to show that range beside the number.
5. **Neither writer is the user's assistant.** Users run Claude; this used two
   Gemini models to keep the check independent of the session that built it.
   A Claude writer is likelier to behave like the specific one, but that is
   not measured.
