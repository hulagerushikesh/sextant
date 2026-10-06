# Milestone 20 — what a corpus belongs to

The candidate line in [`NEXT.md`](NEXT.md) reads: *"the app is one corpus per
deployment; a hosted version needs `category` to mean a person."* Reading the
code, that one sentence hides three questions of very different sizes, and
they are not in the order the sentence puts them:

1. **Isolation** — can two corpora live in one store without leaking into
   each other's answers? A retrieval question, measurable, ₹0.
2. **Identity** — who is asking? There is no answer to this anywhere in the
   repo today. Not a retrieval question at all.
3. **Concurrency** — embedded Chroma is single-writer, which is already the
   documented reason scale-out was decided against (`milestone-15.md`).

And underneath all three is a bug that exists **right now**, with one corpus
and no tenancy: two uploads of the same filename destroy each other. That is
item 1, and it ships whether or not the rest of this milestone ever does.

Nothing here costs money. No VM, no model calls — the measurement runs on
`sextant-eval`, which does not spend (`sextant-eval-agent` does, and is not
needed for any of this).

## What is actually true today

Established by reading the code, not by memory:

| Fact | Where |
| --- | --- |
| One shared Basic-auth credential at the front door; nothing downstream learns who asked | `deploy/Caddyfile:22` |
| The frontend has no login, no `Authorization` header — the browser answers Caddy's 401 natively | `frontend/src/lib/api.ts` |
| The rate limiter keys on client IP, so one tenant behind a NAT throttles another | `mcp_server/main.py:231` |
| One process-global `KnowledgeBase`, one Chroma collection (`documents`) | `tools/vector_db/server.py:63`, `vector_search.py:61` |
| `search()` takes `query, limit, min_score, mode`. **There is no filter parameter** | `vector_search.py:381` |
| The dense ANN index is built once over **every** chunk and cached behind a lock | `vector_search.py:588` |
| `get_embedder()` is not cached — each `KnowledgeBase` loads its own MiniLM; each also builds its own cross-encoder | `embeddings.py:112`, `vector_search.py:233,274` |
| `kb_stats` and `kb_list` report the whole collection | `server.py:167,185` |
| Upload ids are `upload:<filename stem>`, global across the store | `mcp_server/uploads.py:99` |
| `_store` clears a document's existing chunks before writing its new ones | `vector_search.py:815` |

The last two rows are the bug. The last row is correct and was shipped
deliberately on 2026-09-25 (`PROGRESS.md`) — a re-ingest **should** be a
replacement. It only becomes a bug when combined with an id that is not
unique to the person who uploaded it.

## 1 · The collision that already exists — ₹0

**Not an experiment.** A defect with a known cause and a known fix.

Two people behind the shared gate upload `notes.pdf`. Both become
`upload:notes`. The second upload clears the first's chunks and writes its
own. The first person's document is gone from the store, and nothing told
anybody: `/upload` returns success, and the only symptom is that their
citations stop appearing.

Everyone behind one password is already a tenant in the only sense that
matters here — they can destroy each other's data. That is true of the box
as deployed today, which makes this fix independent of every design question
below.

**Change.** The upload id carries something the uploader does not choose:
the content. `upload:<stem>-<first 8 of sha256(content)>` keeps re-uploading
a *corrected* file a replacement only when the bytes are the same, which is
not what the stable id was for. So instead the id carries the *owner* —
`upload:<owner>:<stem>` — and falls back to a per-session value until item 3
provides a real one.

**Decision rule, pre-registered.** The fix lands only with a test that two
uploads of the same filename under different owners both survive, and that
re-uploading the same filename under the *same* owner still replaces. Both
halves, or the fix has only moved the bug.

**Shipped 2026-10-06 (0.8.2), ₹0.** `mcp_server/identity.py` holds the owner
and the reason it is not a permission; `to_document` takes it and the id
becomes `upload:<owner>:<stem>`; `/upload` reads it from `X-Sextant-Client`,
which the frontend sets from a random per-browser id in localStorage. Nothing
that does not send the header changes behaviour -- the CLI, curl and the eval
harness all land in `upload:shared:<stem>`.

Both halves are pinned, at the store and not only on the id: two owners
uploading `notes.md` both keep their chunks *and* both stay findable, and the
same owner re-uploading still collapses a many-chunk document to one with the
old text gone from the index (`tests/test_removal.py::TestUploadsOfTheSame
Filename`). The owner is sanitised because it reaches a document id and from
there a chunk id — an owner carrying `:` or `#` could otherwise name a
document that is not theirs.

**The old-id question, settled: a documented one-way break, no migration.**
A store written before 0.8.2 keeps its `upload:<stem>` documents — they are
searchable and `sextant-forget` still removes them — but a re-upload of the
same file lands beside them rather than replacing them. The deployed store is
not affected in practice: the 2026-09-27 re-ingest rebuilt it from
`/data/corpus` through the CLI, whose ids are bare stems, and dropped the one
`upload:` document it held. **Worth confirming with `kb_list` on the next
trip** rather than assumed.

**Found while fixing it:** the test rate limiter is module-level state keyed on
client IP, and every API test arrives as the same `testclient`. Adding two
tests 429'd an unrelated one and the failure pointed at the wrong file. The
`client` fixture now resets it.

**Verified in the browser, not only in tests.** The frontend half has no test
coverage, so it was run: `clientId()` returned `bmuwdv257cib2ds2z`, stable
across calls and persisted; the real `uploadFiles` posted a real file to the
real server on `:8100` (`VITE_MOCK=0`); and the store held
`upload:bmuwdv257cib2ds2z:ownership-check`. Removed with `sextant-forget`
afterwards -- the local store is back to 22 documents / 1,660 chunks.

## 2 · Decide what a corpus is — ₹0, one measurement

Three architectures. They are not equally good and the differences are
measurable, so this is a decision on a number, not on taste.

**A · One collection, filtered by metadata.** Add `owner` to chunk metadata,
pass `where=` on every query. Cheapest to write.

The problem is the index. The dense path does not go through Chroma's
filtered `query()` when the backend is anything but `chroma`
(`vector_search.py:559`) — it goes through a flat/HNSW/IVF-PQ index built
over **all** ids with no notion of ownership. Filtering can therefore only
happen *after* ranking, so asking for `k` returns fewer than `k`. To fill
`k=5` for a tenant holding 10% of the corpus you must over-fetch roughly
`10 × k` and hope; at 1% you must over-fetch 100×, at which point it is a
scan with extra steps. The reranker and the per-document cap then run over
whatever survived.

**B · One collection per corpus.** `KnowledgeBase.__init__` already takes
`collection_name` (`vector_search.py:222`) — this is the seam. Recall is
exactly today's recall, because each search is today's pipeline over a
smaller store. No filter, no over-fetch, nothing to measure.

The cost is memory, and it has a number. Each `KnowledgeBase` builds its own
embedder and its own cross-encoder, neither shared, plus its own ANN index
held resident. At roughly 90 MB per model that is ~180 MB of models per
corpus before a single chunk is indexed, on an e2-standard-2 with 8 GB. A
dozen corpora and the box is models. **If B is chosen, making `get_embedder`
and the reranker process-level singletons is a prerequisite, not a
follow-up** — they are stateless and identical across instances, so this is
a small change that should have been true anyway.

**C · One deployment per corpus.** What exists. Scales to about one, at a VM
each. It is the baseline the other two have to beat, and it is not a joke —
for the actual user count it may be the right answer.

### The measurement

`eval/corpus/` holds 21 documents and the local store holds 1,660 chunks;
`eval/golden.jsonl` holds 65 questions over them. Assign the documents to
synthetic owners, then run the golden set restricted to one owner:

- **B is the ceiling**: a collection holding only that owner's documents.
  Today's pipeline, today's numbers, at a smaller size.
- **A is the candidate**: the full index, post-filtered, with a fixed
  over-fetch budget.

Sweep the owner's share of the corpus (50%, 25%, 10%) and the over-fetch
factor, and report hit@5 and recall@5 for both arms.

**Decision rule, pre-registered.** A is accepted only if, at a **10% corpus
share** with an over-fetch budget of **10 × k**, it reaches B's hit@5 within
**0.02**. If A needs an over-fetch that grows with the number of tenants, it
is not an architecture and B wins on the measurement. If B wins, the
singleton refactor above is in scope.

**Shipped 2026-10-06, ₹0 — A, with the filter pushed inside the query and the
listing tools scoped.** Full note: [`../learning/multi-corpus.md`](../learning/multi-corpus.md),
harness `eval/tenancy.py`.

At a **3.1%** tenant share — smaller than the rule asks — A reaches recall@5
0.9727 against B's 0.9818, a gap of +0.0091 inside the 0.02 tolerance, and
*beats* B on hit@1 (0.9455 vs 0.9273). **The rule passed and could not have
failed**, which matters more: filtering removes only documents the owner does
not have, so it never demotes one they do, and the tenant's own answer sits at
global rank **1** (median; max 3 with the cap, 14 without). The arithmetic in
this file — *10% share, so over-fetch 10×* — was about filling k slots, not
about finding the answer. It measured the wrong quantity.

Two facts the run turned up that decide more than the table does:

- **The over-fetch budget does not exist past 30.** Both runs asked for 200
  and got exactly 25: `RERANK_DEPTH = 25`, fed by `CANDIDATES = 30`. Raising
  it widens the cross-encoder for every query and every tenant — A's real cost
  at scale is latency, not recall.
- **The filter need not be post-hoc at all.** The default dense backend is
  `chroma`, whose path is `collection.query(...)`, which takes a `where`. The
  shortlist then holds 30 of the *tenant's* chunks. What was measured is
  therefore the pessimistic bound on A, and it passed. The BM25 half and the
  four hand-written ANN backends have no filter and keep the post-hoc
  behaviour.

**The work A actually needs is not the filter — it is `kb_list` and
`kb_stats`**, which report the whole collection and would hand every tenant's
document titles to the model in its prompt. A leak, not a recall problem, and
no experiment would have found it.

**The synthetic partition this file proposed was built first and abandoned.**
`eval/corpus/` is 58 chunks, so an over-fetch of 200 returns everything; and
11 of its 17 labelled documents are chained into one component by questions
labelling two at once, so the smallest achievable "10% owner" held **62%**.
The golden set cannot describe a small tenant. The mixed store can, without
inventing one: the handbook is 52 chunks beside the survey's 1,608.

If neither clears C's bar — that is, if the whole thing turns out to serve a
tenant count that one VM each would serve more simply — then C wins and this
milestone's output is a decided-against note, which is a real result.

### The invariant that is not up for measurement

**The corpus must never be a tool argument.** If the model sees
`kb_search(corpus=...)` in a discovered schema, then a sentence inside an
uploaded PDF can tell it to search someone else's corpus, and it will — the
model has no way to know it should not. Tool schemas are discovered at
startup and handed straight to the model (`mcp_host.py`).

So isolation is enforced **below** the tool boundary: the corpus is pinned
into the KB subprocess at spawn (`_FORWARDED_ENV` is already the mechanism),
or there is one subprocess per corpus. The tools keep exactly the signatures
they have. This holds whichever of A, B or C wins, and it is a hard
constraint, not a preference.

## 3 · Identity, and the case against building much of it — ₹0

Items 1 and 2 both need to know who is asking, and nothing in the repo does.

The reflex is signup, sessions, a user table, password reset — weeks of work
for an app whose entire deployment is one box behind one password, and every
line of it is auth code, which is the worst kind of code to own.

**The proposal: multiple Basic-auth users, and a header Caddy sets.** Caddy's
`basic_auth` takes more than one `user hash` line, and it exposes the
authenticated user as `{http.auth.user.id}`, which `reverse_proxy` can send
on as a header. Identity then arrives from the transport — set by the
component that did the authenticating — and never from the client and never
from the model, which is exactly what item 2's invariant demands.

What it costs: adding a person is a line in the box's `.env` and a reload.
What it does not do: public signup, self-service, password reset. For a
deployment whose users are "people I gave the password to", that is the
correct scope.

**Decision rule, pre-registered.** This lands only with a test that a
client-supplied identity header is refused. Caddy must overwrite the header
rather than append, and the API must reject a request carrying it when it did
not come through the proxy — otherwise the gate is a formality and anyone can
type another person's name into a curl. The local-dev path needs a named
default so that no-proxy development does not quietly become
no-authentication production.

## Not in this milestone

- **Deploying any of it.** A VM trip, ≈₹2, and it should ride with the
  `GEMINI_API_KEY` rotation still open from M19 rather than be spent alone.
- **Public signup, OAuth, password reset, per-user billing.** Out of scope
  by the argument in item 3, not by omission.
- **Per-user rate limits and budgets.** The limiter keys on IP and the budget
  cap is global; both are wrong under tenancy, and both are cheap to fix once
  there is an identity to key on. They wait for item 3 to land.
- **Concurrency.** Embedded Chroma stays single-writer. Two people uploading
  at once is a real question and it is `milestone-15.md`'s question, not this
  one.
