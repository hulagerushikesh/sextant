# Milestone 22 — the way back out

Milestone 21 closed on 2026-11-03 with the trip that proved identity against a
running box: two gated users uploaded a file of the same name through the
public URL, each saw their own and not the other's, a client-supplied name was
refused, and the box parked itself. Everything that milestone built is now
running rather than asserted.

Which makes one gap, deferred twice on purpose, the obvious next thing.

**A person can put a document in and cannot take it back.** `sextant-forget`
is an operator command that runs on the box, and re-uploading replaces rather
than removes. So the only way to undo an upload today is to ask the operator,
over whatever channel exists, to ssh in — on a box that is parked by default,
which means a ₹2 trip to delete somebody's file. For a corpus that is now
genuinely multi-tenant, that is not a missing nicety; it is the one direction
of the boundary that was never built.

It was held back until the deployment had actually had two users, in those
words, so that it would be designed against something real rather than
imagined. It has.

## What is actually true today

| Fact | Where |
| --- | --- |
| `KnowledgeBase.remove_document` exists, deletes every chunk and the overview, and reports `chunks_removed` | `vector_search.py:685` |
| It is reachable only from `sextant-forget`, which constructs a `KnowledgeBase` in the operator's shell | `vector_db/forget_cli.py` |
| The API process never holds a `KnowledgeBase`; the store lives in the MCP subprocess, and Chroma is single-writer | `mcp_host.kb_server` |
| `identity.writable_by` already answers "may this caller replace this id?" — allow-list, anchored on `upload:<owner>:` | `identity.py:219` |
| `ScopedHost._guard` refuses a write naming another owner's id **before** the store is touched | `scope.py:213` |
| …by reading `arguments["documents"]`, and nothing else | `scope.py:229` |
| Only `READABLE_TOOLS` are declared to the model; `kb_ingest` is discovered and withheld | `agent.py:84` |
| Every HTTP route is pinned as reaching the corpus or not; a new one fails the gate until declared | `test_scope.py:408` |

## 1 · A person deletes their own upload — ₹0

### The fork that actually mattered

The delete has to happen in the process that owns the store, and that is the
MCP subprocess. There are only three ways to reach it, and two of them are
wrong:

| Way | Why not |
| --- | --- |
| The API process opens its own `KnowledgeBase` and deletes | a second writer to a single-writer store, and the subprocess's segment goes stale afterwards — the CLI-ingest gotcha, promoted from a footnote to a request path |
| A plain `kb_forget` MCP tool | `sextant-kb` is on PyPI. Every client that mounts this server — a person's Claude Desktop — would hand its model the ability to delete a corpus. `remove_document`'s own docstring is the argument: *"search my notes" must not carry "delete my notes" with it*. `READABLE_TOOLS` protects **this** project's model, not somebody else's client |
| A tool the launcher turns on | the parent already seals the child's environment in exactly this shape (`settings.SEALED`, set in `kb_server()` and read before the `.env` load). The same handshake says *this server was started by something that knows who is asking* |

So: `kb_forget` exists on the knowledge-base server **only when the launcher
asked for it**, which this project's API does and a third-party mount does
not. The capability and the authorisation stay in different processes — the
child can delete, and has no idea who anyone is; the parent knows who is
asking, and cannot delete anything itself.

### The hole that opening this makes

`_guard` is the single place that refuses a write it should not perform, and
it reads one argument shape: a `documents` list of dicts with an `id`. A
second write tool whose id arrives as `document_id` would walk straight past
it — not denied, not noticed, because the loop finds no `documents` key and
falls off the end. That is the `trim()` lesson from 0.8.5 one directory over:
**deny by default only denies the shapes it recognises**, and a guard that
reads as general while being specific is worse than an enumerated list,
because nobody re-checks it.

So the guard gets a declared reader per write tool, and a write tool with no
reader is refused the way an unclassified tool already is. Adding the third
write tool will then fail a test rather than ship a door.

### The decision rule, pre-registered

The item succeeds only if all of these hold, against a real store and a real
subprocess rather than a mock:

1. An owner can delete their own upload, and after it the document is gone
   from their own listing **and** from the store — the chunk count drops by
   what the call reported.
2. `ada` asking to delete `upload:grace:notes` is refused **before** anything
   is removed, and grace's document still answers a search afterwards.
3. An authenticated caller cannot delete an unnamespaced document — the
   CLI-ingested shared corpus is not theirs, which is `writable_by`'s existing
   asymmetry and not a new rule.
4. Deleting an id that does not exist is reported as not found, not as a
   success. A delete that deletes nothing and says `success` is the
   `/upload`-returns-200 shape again.
5. A knowledge-base server started **without** the launcher's flag does not
   list `kb_forget` at all — proved by launching one and reading its tool
   list, not by reading the source.
6. The route is declared, scoped and rate limited, which the existing route
   pin enforces on its own.

Failing 2, 3 or 5 is a leak and the item does not ship. Failing 4 is a lie
and the item does not ship.

### One thing the design did not have, found by building it

**There was no way to list the documents you have.** `/stats` reports counts —
scoped counts, since 0.8.4 — and nothing reported *which* documents, because
until now nothing needed to: the agent reads the corpus through a tool and the
UI only ever printed a number under "documents". So "remove the file I uploaded
by mistake" had nothing to point at, and a delete route on its own would have
been an endpoint only curl could use.

`GET /documents` is therefore part of this item rather than a follow-on. It is
the full scoped listing — the same walk `/stats` already does to recompute its
counts, so it is scoped and rate limited for the same reason — and each entry
carries `yours`, which is `identity.writable_by` answered **on the server**.

That last part is the decision worth recording. The browser knows the client id
it generated and nothing else; behind the gate the owner is the name Caddy
vouched for instead, so a UI that tested the id's prefix itself would draw the
control correctly on this laptop and wrongly on the only deployment that has
more than one person in it. The thing that will refuse the delete is the thing
that says whether to offer it.

### What a person sees

The browser is the only client that has an owner of its own, so the
affordance belongs there: each of **your own** uploads carries a way to
remove it, it asks once before it goes, and the listing and the stats it
feeds both reflect it afterwards. A document you do not own has no such
control, because the server would refuse it and an affordance that cannot
work is worse than none.

### How it was proved

Against a real store and the real browser, not mocks — the suite is the
pre-registered rule, this is the evidence the rule describes something that
happens. Four requests, in one session against the local API on `:8100` with a
corpus of 22 documents and 1,660 chunks:

| Request | Answer |
| --- | --- |
| the owner's own upload | **200**, carrying the number of chunks taken out, and the collection smaller by exactly that many afterwards |
| another owner's `upload:<name>:<stem>` | **403**, and the store untouched — the refusal happens before it is asked |
| an id in the shared corpus | **403**, from an authenticated caller who does not inherit it |
| an id that is not there | **404**, read off `found`, not matched out of a sentence |

Then the UI: the control is drawn on owned rows and absent from the rest, the
row is gone after confirming, and the count under "documents" agrees with the
listing. And an interpreter launched the way a third party would mount the
published package does not list `kb_forget` at all — the one check that cannot
be made by reading the file.

The corpus was restored to its 22 documents and 1,660 chunks afterwards.

## 2 · Deploy it and prove the delete through the gate — ≈₹2

Item 1 met every clause of its own rule, against a real store and a real
subprocess, in the real browser. What it did not do is run anywhere other
than this laptop — and the recurring lesson in this repository is that the
environment is the thing that was never the question. The frontend linter is
the smallest possible instance of it, found on item 1's own first push: a
check this machine cannot run is a check whose result was unknown. The
preflight, the BSD `tar`, the `cd ""` stub, the `.env` the sealed child could
read — every one of them was code that was correct here.

So the item is a trip, and the trip is the proof.

`deploy/trip.sh` step 7 is already the only part that writes: both gate users
upload a file of the same name through the public URL, each must see their own
and not the other's, and the probes are removed in the EXIT trap. The delete
is the one write path it does not exercise, and it is the write path that
cannot be undone — which is exactly the order this project does things in, not
the reverse.

### The decision rule, pre-registered

Through `PUBLIC_URL`, with Caddy in the path, as the two real gate users:

1. `ada` uploads, lists, and removes their own document: the removal reports a
   chunk count, the listing no longer carries it, and the store read back
   directly is smaller by that many chunks.
2. `ada` asking to remove `grace`'s id is **403**, and grace's document still
   answers a search afterwards — the same row step 7 already proves for a
   forged *write*, now for a delete.
3. An id that is not there is **404**, not a 200 that says nothing happened.
4. Every probe is gone before the box is parked, and anything left behind
   makes the trip exit non-zero — step 7's existing contract, extended to
   whatever this adds.
5. The box is `TERMINATED` with no reserved address and no DNS record at the
   end, by the EXIT trap, whether or not any of the above passed.

Failing 2 is a leak and the deployment is rolled back. Failing 4 or 5 is the
2026-09-28 failure and is the reason the trap exists.

**This costs money and does not start without the owner saying so.**

## Not in this milestone

- **An operator deleting somebody else's upload through the API.**
  `sextant-forget` on the box is the right place for that: it is the one
  action whose authorisation is "you have ssh", and routing it through HTTP
  would mean inventing a role, which milestone 20 item 3 ruled out.
- **Undo.** A delete is a delete; a trash can is a second store and a
  retention policy, and nothing has asked for one.
- **Bulk delete.** One id per call until somebody has too many files to
  manage one at a time.
