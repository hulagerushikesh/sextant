# Experiment 5 — Summary chunks for global questions (RAPTOR-lite)

*Milestone 16, 2026-09-16. Cost: $0.07 (22 documents summarised twice,
one of them a 144-page PDF). Decision: `sextant-ingest --summaries` ships
as an opt-in; not the default, and no tree. **Reversed 2026-09-24** — both
conditions this note wrote down for making it the default happened; see the
last section. Still no tree.*

## Hypothesis

A flat chunk store answers local questions and has no passage that says
what a document *is*. "Which of my documents cover evaluation" or
"compare A and B" should therefore retrieve whichever chunk contains the
word "cover", and one model-written overview per document — stored as a
chunk, competing in the same index — should fix that. Rule, written first:
ship as opt-in if global questions go from ≤ 0.3 to ≥ 0.8 hit@5 and local
questions do not move. One level only; the eval decides whether the full
RAPTOR tree is worth building.

## What was built

- `tools/vector_db/summaries.py`: one call to the agent's model per
  document with a prompt written for a search index (what kind of
  document, what it covers, in order, naming the specific things). The
  survey (800k characters) goes in whole; the cap is a million.
- `KnowledgeBase.add_document(document, summary=...)` stores the overview
  as chunk `<doc>#summary`, `kind: summary`, `section: Overview`, after
  the last text chunk. Same collection, same three stages. `health_check`
  reports how many documents carry one.
- `sextant-ingest --summaries`. Off by default; needs `GEMINI_API_KEY`.
- Six `global` questions: g01–g05 in the handbook set (compare two
  methods, which documents cover evaluation, what the operations side
  covers, which document explains X and which Y, which to read first),
  L39 in the survey set, labelled by document. 65 and 39 questions now.

## Setup

Control: the stores as they were. Treatment: the same documents
re-ingested with `--summaries` — 21 overviews on the handbook alone (58 →
79 chunks), 22 on the mixed store with the survey (1,660 → 1,688). Both
golden sets, all four modes, `min_score = 0`. The summaries themselves
read well: the config-reference overview names every parameter in
order; the survey's names its datasets, libraries, model families and
sections in 250 tokens.

## Results

**Global questions, rerank** (the shipped pipeline):

| store | questions | control hit@1 | treatment hit@1 | control hit@5 | treatment hit@5 | control r@5 | treatment r@5 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| handbook alone | 5 | 0.600 | **1.000** | 1.000 | 1.000 | 0.900 | 0.900 |
| mixed | 5 | 0.600 | **1.000** | 1.000 | 1.000 | 0.900 | 0.800 |
| mixed, survey set | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

Under the reranker, the overview chunk is the top hit for all five
handbook global questions, in both stores. Under dense retrieval an
overview is in the top five for all five and first for none — the
cross-encoder likes a passage that names the question's every term; the
bi-encoder prefers the prose chunk that shares its phrasing.

**Local questions** (50 handbook, 33 survey):

| store | mode | control hit@1 | treatment hit@1 | control r@5 | treatment r@5 |
| --- | --- | --- | --- | --- | --- |
| handbook alone | dense | 0.860 | 0.860 | 0.970 | **0.900** |
| handbook alone | rrf | 0.940 | 0.920 | 0.980 | 0.960 |
| handbook alone | rerank | 0.940 | **0.960** | 0.970 | 0.970 |
| mixed | dense | 0.780 | 0.820 | 0.920 | 0.880 |
| mixed | rrf | 0.860 | 0.900 | 0.920 | 0.920 |
| mixed | rerank | 0.920 | **0.940** | 0.970 | 0.970 |
| mixed, survey set | all four | unchanged | unchanged | unchanged | unchanged |

## What the numbers say

**The premise was wrong for this corpus.** Global hit@5 was 1.000 before
any summary existed. The handbook documents are 150–400 words; their
first chunk carries the title and the first two headings, and that *is*
an overview. "Which document should I read first to understand the whole
life of a track" finds `track-lifecycle#0` because the chunk starts
"Track Lifecycle Management / States". The rule's precondition — ≤ 0.3 —
never held, so the rule cannot be met, and the honest reading is that a
corpus of short documents does not need summaries for recall.

**What summaries do buy is rank, through the reranker.** Global hit@1
0.6 → 1.0 on both stores, and local rerank hit@1 up 0.02 on both — a
document's overview is a strong candidate for any question about that
document, and the cross-encoder puts it first when the question is
document-shaped. That is the effect RAPTOR reports at its first level;
here it is worth one question in five on global and one in fifty on local.

**And they cost dense recall, for the third time this milestone.**
Handbook-alone dense recall@5 0.970 → 0.900: 21 more chunks that match
everything about their document crowd the five slots that are graded per
document. Same shape as one-row table chunks (experiment 1) and 150-token
chunks (experiment 3); the reranker is unaffected each time. A
per-document cap on the candidate list is now three experiments overdue.

**On the one long document, the overview competes with 1,608 siblings and
loses in dense, wins in rerank — when the question is direct.** "What is
the survey of large language models about, and how is it organised?"
ranks the overview first under the cross-encoder at 0.998 and outside the
top 25 under dense (cosine 0.56 against prose chunks at 0.72 that use the
word "survey" about themselves). L39 as written — "one of my documents is
a long survey paper rather than a handbook page…" — is meta-language
about the collection, cosine 0.13 to the overview, and no mode finds it;
the reranker's top hit is a paragraph about book corpora scoring 0.0003,
which the product's floor would turn into "no passages". The question is
still a hit at document level, which says more about document-level
grading of a 144-page document than about summaries.

**The opening-screen question is not a retrieval question.** "What topics
do my documents cover?" — the starter prompt this experiment was named
for — retrieves survey prose about topics under every mode, with the
summaries nowhere and the reranker under 0.003. Per-document overviews
answer "what is *this* document about"; a question about the *collection*
has no chunk that answers it, at any level of a summary tree, because the
answer is a listing. The agent already has `kb_stats`; what it needs is a
tool that returns the documents and their overviews. That is a product
change, not a retrieval one, and the first concrete thing this experiment
argues for.

## Decision

**Opt-in, not default, no tree.**

- `sextant-ingest --summaries` ships: one model call per document, a 250-
  token chunk each, +0.02 rerank hit@1 on local questions and rank 1 on
  document-shaped ones. A corpus owner who runs the reranked pipeline and
  asks "which document…" questions gets that for $0.003 a document.
- Not the default: the CI store is built without a key, dense recall@5
  drops past the 0.02 gate on the handbook alone, and the milestone rule
  is that nothing ships as default on one side of the pipeline.
- No RAPTOR tree. The one-level version already saturates hit@5 here;
  the levels above would summarise groups of documents, and the question
  that needs that — what the collection covers — is better served by a
  listing tool than by retrieving a summary of summaries.

Both baselines are regenerated for the new questions: handbook rerank
0.909 / 0.964 (65 questions, no summaries in the CI store), survey set
unchanged at 0.912 / 0.985 (39).

## What would change the decision

- **A `kb_list` tool** (titles, overviews, chunk counts) offered to the
  agent, and the opening prompts re-pointed at it. Then `--summaries`
  has a second consumer and the case for making it default on upload
  improves. Milestone 17 candidate, with the candidate cap.
- A corpus of long documents — ten papers, not one — where "which of my
  papers…" is common and each paper's first chunk is an abstract that
  competes with its own body. That is the RAPTOR setting and this eval
  has one such document.
- A per-document candidate cap (experiments 1, 3, 5 all point at it): if
  it removes the dense recall cost, the argument against default weakens
  to "needs a key at ingest time".

## Reversed — the default, 2026-09-24 (milestone 18, ₹0)

This note listed three things that would change the decision. Two of them
happened, and they are the two that carried it:

1. **`kb_list` shipped** (2026-09-20, [`kb-list.md`](kb-list.md)). The
   listing reads a document's model-written overview when it has one and
   the first 240 characters of its opening when it does not. Summaries now
   have a second consumer, and it is the one the agent reaches for on 4 of
   5 collection questions.
2. **The per-document cap shipped** (2026-09-17,
   [`candidate-cap.md`](candidate-cap.md)) and removed the dense recall
   cost outright: the with-summaries store went 0.900 → **0.973**, which is
   what the no-summaries store scores, with rerank hit@1 unchanged at 0.964
   on every store. The reason this note gave for "not the default" —
   "dense recall@5 drops past the 0.02 gate" — is no longer true of the
   code that ships.

What was left of the argument was "the CI store is built without a key".
That is a fact about ingestion, not a reason for a flag, and it is
answered by making the key the switch rather than the flag: `sextant-ingest`
summarises when `GEMINI_API_KEY` resolves, `--no-summaries` says don't,
`--summaries` says do and fails loudly if it cannot. With no key the run
prints one line and stores text, exactly as it does today — the CI store is
built by the same command it always was.

The default spends money, so it says so first: with a key present the run
prints what it is about to do and what a document costs before the first
model call. One thing is new rather than inherited: under the default, a model failure
mid-run degrades to text for the rest of the run instead of aborting it.
Asking for overviews and not getting them is an error; the default asking
on your behalf and not getting them should not turn a working ingest into a
failed one.

**No measurement was taken for this.** Nothing retrieval-side changed, both
baselines are untouched and `sextant-eval --check` is green on them. The
numbers are the two above, already in `learning/`; this is the decision they
imply, written down where the old decision was.

## Reproduce

```bash
SEXTANT_CHROMA_DIR=/tmp/with-overviews \
  ./.venv/bin/sextant-ingest --summaries eval/corpus/*.md --category handbook
./.venv/bin/sextant-eval --store /tmp/with-overviews
```

Needs `GEMINI_API_KEY` in `.env`; about $0.01 for the handbook, $0.05 for
the survey.
