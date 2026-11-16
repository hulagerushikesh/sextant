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
