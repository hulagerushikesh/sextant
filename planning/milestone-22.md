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

### What a person sees

The browser is the only client that has an owner of its own, so the
affordance belongs there: each of **your own** uploads carries a way to
remove it, it asks once before it goes, and the listing and the stats it
feeds both reflect it afterwards. A document you do not own has no such
control, because the server would refuse it and an affordance that cannot
work is worse than none.

## Not in this milestone

- **An operator deleting somebody else's upload through the API.**
  `sextant-forget` on the box is the right place for that: it is the one
  action whose authorisation is "you have ssh", and routing it through HTTP
  would mean inventing a role, which milestone 20 item 3 ruled out.
- **Undo.** A delete is a delete; a trash can is a second store and a
  retention policy, and nothing has asked for one.
- **Bulk delete.** One id per call until somebody has too many files to
  manage one at a time.
