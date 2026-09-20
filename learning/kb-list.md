# `kb_list` — does the agent reach for a listing unprompted?

*Milestone 17, step 2. 2026-09-20. Cost: $0.034 ≈ ₹3 (two agent runs,
`gemini-3.1-flash-lite`). Decision: the prompt bullet ships, in its
strengthened form; the harness gains a `named` column for listing
questions.*

## Hypothesis

The summary-chunks experiment ([`summary-chunks.md`](summary-chunks.md))
ended on a question no chunk answers at any level of a summary tree:
"what do my documents cover?" is a listing, not a retrieval. `kb_list`
was built for it (2026-09-19): every document with title, size, overview
when one exists, and its opening lines; offered to the agent beside
`kb_search` and `kb_stats`, with one bullet in the system prompt saying a
question about the collection is a listing, answered by title, with no
labels to cite.

Pre-registered before the key existed: **run the agent harness on the
five `global` golden questions and the three starter prompts; the model
reaches for `kb_list` first on ≥ 4 of the 5 global questions, and the
answer names the expected documents.** Rule: ship the bullet as is if
≥ 4/5; otherwise strengthen it once and re-run once.

## Setup

`sextant-eval-agent --kinds global starter` against a fresh store built
from `eval/corpus` (21 handbook pages, no summaries — the listing shows
title + opening 240 characters, the poorer of its two forms). The three
starters are the frontend's opening prompts, added as a small golden file
with no expected documents. Two harness additions, both ₹0: the recording
host now keeps the tool sequence (`calls`), because "did it list first?"
is the question; and a `named` grade — the fraction of expected documents
whose `kb_list` title appears in the answer — because a question answered
from the listing makes no search and read 0 on every retrieval column by
construction.

## Results

**Run 1, bullet as built:**

| id | question (short) | tools | named | recall@union |
| --- | --- | --- | --- | --- |
| g01 | compare one-shot vs two-stage association | `kb_search` | 0.00 | 0.50 |
| g02 | *which of my documents* cover evaluation, on what data | `kb_search` ×2 | 0.50 | 0.50 |
| g03 | what the operations side covers | `kb_list` | 1.00 | — |
| g04 | which doc explains motion models, which the filter | `kb_list` | 1.00 | — |
| g05 | which doc to read first for a track's life | `kb_list` | 1.00 | — |
| s01–s03 | starters | `kb_list` | 1.00 | — |

`kb_list` first on **3/5** global and 3/3 starters. Every listing answer
named 100% of the expected documents — g03 named all three operations
pages, the question experiment 5 said no chunk could answer. Two did not
list: g01 is a comparison of what two methods *do*, a content question
where search was the right call and the bullet should not chase it; g02
opens "which of my documents cover…" and still went to search, found
`mot-metrics` and missed `benchmark-datasets`. That is the phrasing the
bullet exists for, so per the rule one sentence was added:

> "Which of my documents cover X" is a listing even though it names a
> topic: list first, and search inside the named documents only if the
> question also asks what they say.

**Run 2, strengthened bullet:**

| id | tools | named | recall@union | turns |
| --- | --- | --- | --- | --- |
| g01 | `kb_search` | 0.00 | 0.50 | 2 |
| g02 | `kb_list`, `kb_search` ×3 | **1.00** | **1.00** | 5 |
| g03 | `kb_list` | 1.00 | — | 2 |
| g04 | `kb_list`, `kb_search` ×2 | 1.00 | 1.00 | 3 |
| g05 | `kb_list` | 1.00 | — | 2 |
| s01–s03 | `kb_list` | 1.00 | — | 2 |

`kb_list` first on **4/5** global, 3/3 starters — the rule is met. g02 now
lists, reads the titles, then searches inside the two it named ("what
data is used in Benchmark Datasets for tracking evaluation?") and comes
back with both. g04 does the same because its question also asks what
each document explains. g01 still searches, as it should. Global recall@union
0.20 → 0.50 with the listing questions counted as 0; `named` 0.70 → 0.80
on global, 1.00 on starters.

Cost: run 1 $0.014, run 2 $0.020 — the pre-registered estimate was $0.05
for one run. The agent averages 2.5 turns per question at ~$0.002 each.

## What this says

1. **The tool description carried it; the bullet only had to close one
   phrasing.** Three of five global questions and every starter listed
   with the bullet as first written. The one it missed names a topic
   inside the question, which reads as a search cue; one sentence saying
   that a "which of my documents" question is a listing *even so* fixed it
   without moving g01, the question that should search.
2. **List-then-search is the shape the model finds on its own.** Given
   the listing, it searched *inside the named documents* rather than
   across the corpus — the two-stage pattern the summary-tree experiment
   was trying to build in the index, arrived at by the loop with no index
   change. It costs turns (5 on g02) and nothing else.
3. **Listing questions need their own grade.** Retrieval metrics score
   what `kb_search` returned; a question answered from titles returns
   nothing and reads as a miss. `named` is the honest column for them and
   is 1.00 on every listing answer in both runs. It is a title-substring
   match, deliberately blunt: a model that paraphrases a title gets no
   credit, and none did.
4. **Eight questions is a smoke test, not a distribution.** The rule was
   set for the sample size on hand; the behaviour it checks — reach for
   the listing on a collection question — is a prompt-following property,
   not a retrieval one, and eight cases at 100% named are enough to ship
   a bullet. It is not enough to claim a rate.

## Reproducing

`sextant-eval-agent --golden eval/golden.jsonl starters.jsonl --kinds global starter`
with the three starter prompts from `frontend/src/components/Opening.jsx`
as a golden file with empty `relevant_docs`. ~1 minute, ~$0.02 per run.
