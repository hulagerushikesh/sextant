# Experiment — one filtered collection, or one collection each

*Milestone 20 item 2, 2026-10-06. Cost: ₹0 (four local runs, ~20 minutes of
laptop CPU; no model calls). Decision: **A — one collection, filtered** —
with the filter pushed inside the dense query and the listing tools scoped.
The pre-registered rule passed, and the honest reading is that it could not
have failed.*

## Hypothesis

Holding more than one person's documents has two shapes. **A**: one Chroma
collection, an `owner` in the metadata, filtered per query. **B**: a
collection per owner. The claim to test was that A loses recall, because
`search()` has no filter parameter and the dense index is built once over
every chunk with no notion of an owner — so a filter cannot reach inside the
ranking, and A must ask for N and keep the owner's share of it. The smaller
the owner, the larger N has to be.

Rule, written first (`planning/milestone-20.md`): *A is accepted only if, at a
10% corpus share with an over-fetch budget of 10 × k, it reaches B's recall@5
within 0.02.*

## Setup

The arms differ in exactly one thing. Arm B is not rebuilt from source files —
it is **the same chunks with the same embeddings**, copied out of the mixed
store into a collection of their own. Re-ingesting would have regenerated the
per-document overviews (a model call each) and re-chunked under today's
chunker, and either difference would have surfaced in the result as though it
were about tenancy. What differs between the arms is only whether the index
ranks over the whole store or over one tenant's slice.

The tenant is real, not invented. The mixed store holds the 21-document
handbook (52 chunks) beside one 144-page survey PDF (1,608 chunks): the
handbook is a **3.1% tenant** of a 1,660-chunk store, with its own 55-question
golden set. That is a *smaller* share than the rule asks about.

`rerank` mode, `min_score=0`, both cap settings. Arm A is searched once per
question at the largest budget and smaller budgets are prefixes of that list,
because they are — the ranking does not change when you ask for fewer.

## Results

Per-document cap on (the production default, 2):

| | B (ceiling) | A ×1 | A ×2 | A ×5 | A ×10 | A ×20 |
| --- | --- | --- | --- | --- | --- | --- |
| recall@5 | 0.9818 | 0.9727 | 0.9727 | 0.9727 | 0.9727 | 0.9727 |
| hit@1 | 0.9273 | **0.9455** | **0.9455** | **0.9455** | **0.9455** | **0.9455** |

Cap off:

| | B (ceiling) | A ×1 | A ×2 | A ×5 | A ×10 | A ×20 |
| --- | --- | --- | --- | --- | --- | --- |
| recall@5 | 0.9818 | 0.9636 | 0.9727 | 0.9727 | 0.9727 | 0.9727 |
| hit@1 | 0.9273 | 0.9273 | **0.9455** | **0.9455** | **0.9455** | **0.9455** |

**Rule: at 3.1% share and 10 × k, A recall@5 0.9727 against B 0.9818, gap
+0.0091 against a tolerance of 0.02 — A is accepted**, in both cap settings.

## Why it passed, which matters more than that it passed

**Filtering cannot demote the owner's own documents.** It removes only
documents the owner does not have, so their relevant document keeps its
relative order and moves *up*. A can therefore lose a question in exactly one
way: the relevant document falls outside the fetched budget in the global
ranking. That is a property of ranking depth, not of the owner's share.

And the depth is not deep. Where the tenant's own answer sits in the
**whole-store** ranking, across all 55 questions:

| | median | 90th | max |
| --- | --- | --- | --- |
| cap on | 1 | 1 | 3 |
| cap off | 1 | 1 | 14 |

A 3% tenant, and the cross-encoder still puts their document first for most
questions and inside the top 14 for all of them. There was nothing for a
larger budget to recover, which is why every over-fetch column is identical.
The hypothesis's arithmetic — *10% share, so over-fetch 10×* — was reasoning
about **filling k slots**, not about **finding the answer**. Those are
different quantities and the rule measured the wrong one.

**A beats B on hit@1** (0.9455 against 0.9273), in both settings. Not noise:
it is the promotion effect above. Filtering removes other tenants' documents
from above the owner's answer. B cannot do that, because those competitors
were never in its store to be beaten.

## What the measurement could not test, and one constant that decides it

**Asking for more than 25 does nothing.** Both runs asked for 200 and were
returned exactly 25, regardless of the cap. The bound is not the cap — it is
`RERANK_DEPTH = 25`, fed by `CANDIDATES = 30`, the shortlist each retriever
proposes. **Arm A's over-fetch budget is not implementable past 30 without
raising `CANDIDATES`**, which widens the cross-encoder's work for every query
on the store, for every tenant. That is the cost A would actually carry at
scale, and it is latency, not recall.

**The filter does not have to be post-hoc.** The default dense backend is
`chroma`, and that path is `self.collection.query(...)`, which takes a `where`.
A filter pushed in there makes the shortlist 30 *of the tenant's* chunks
rather than 30 of everyone's — which removes the over-fetch question
completely. The post-filter measured above is therefore the **pessimistic
bound on A**, and it passed anyway. What does *not* filter inside: the BM25
lexical half, and the four hand-written ANN backends (`flat`, `hnsw`,
`ivfpq`, `ivfpq_rerank`), which index every id with no owner notion. Under
those, A degrades to exactly what was measured here.

**1,660 chunks is not where A would break.** With many tenants and 100k+
chunks, a 30-candidate shortlist may not contain a small tenant's chunks at
all, and `CANDIDATES` would have to grow with the tenant count. That is the
regime where B wins, and it is the regime `ivfpq-100k.md` already describes
for a neighbouring question. Nothing here measures it.

## The decision

**A, one collection filtered — but the filter is not the work.**

1. **Push the filter into the dense query** (`collection.query(where=…)`) on
   the default backend, rather than filtering the result. Post-filtering is
   the fallback for the lexical half and the hand-written backends, and it is
   measured above as adequate at this size.
2. **Scope `kb_list` and `kb_stats` to the owner.** This is the real work and
   the strongest argument that A is not free: both tools report the whole
   collection, so under A every tenant's document titles are handed to the
   model in its prompt. Not a recall problem, and not something an experiment
   would have found — it is a leak, and it has to be closed before A holds
   two people's documents.
3. **B's cost, for the record.** Each `KnowledgeBase` builds its own embedder
   and its own cross-encoder — `get_embedder()` is not cached — so B costs
   ~180 MB of models per corpus, plus an ANN index each, on an 8 GB box.
   Making those process-level singletons would be a prerequisite if B were
   ever chosen; it is stateless work that should be true regardless.
4. **C (a deployment per corpus) stays the answer for one user**, which is the
   current deployment. A is what to build when there is a second.

## What would overturn this

- A corpus past ~25k chunks with several tenants: re-run and watch whether the
  tenant's first relevant document stays inside the shortlist.
- A tenant whose documents are *topically* dominated by another's rather than
  merely outnumbered. The handbook and the survey overlap in vocabulary but
  not in subject; two tenants with near-duplicate corpora is the adversarial
  case and this corpus has no such pair.
- Raising `CANDIDATES`. Every number here is conditional on 30.

## Not measured, and why

A synthetic partition of `eval/corpus/` was built first and abandoned. Three
reasons, all fatal: the corpus is **58 chunks**, so an over-fetch of 200
returns the whole store; 11 of its 17 labelled documents are chained into one
component by questions that label two documents at once, so the smallest
achievable "10% owner" actually held **62%**; and the recall metric cannot
discriminate for the structural reason above. The partition code is not in
the tree — this note is the record that it was tried.

## Reproduce

```bash
./.venv/bin/python -m eval.tenancy --store ./chroma_db --out /tmp/cap2.json
SEXTANT_MAX_PER_DOCUMENT=0 ./.venv/bin/python -m eval.tenancy \
  --store ./chroma_db --out /tmp/cap0.json
```

The store is opened read-only; the subset collection is written beside it and
deleted. Run it against a copy if that matters. It needs a mixed store — the
handbook alone is 58 chunks and cannot express a small tenant.
