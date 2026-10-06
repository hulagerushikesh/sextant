# Milestone 21 — what else assumed there was one person

Milestone 20 gave the box an identity and taught the tools to answer with the
asker's own view. It closed on 2026-10-06, and none of it is running: 0.8.2,
0.8.3 and 0.8.4 are on `main` and the VM is parked on a 0.8.1 image.

Two things follow, and they are this milestone.

The first is that scoping is only as good as the doors it covers, and I left
two open. Not inherited warts — both are mine, from this week, and both are
demonstrated below rather than suspected. The second is that the rate limiter
and the spend cap still count as though one person were asking, which milestone
20 deferred in as many words: *"both are wrong under tenancy, and both are
cheap to fix once there is an identity to key on."* There is one now.

And then the box, which is the only item here that costs money.

## What is actually true today

Established by reading the code and then checking it against a running server,
not by memory:

| Fact | Where |
| --- | --- |
| `/ann/compare` and `/ann/benchmark` call the **unscoped** host | `main.py:409,421` |
| `kb_ann_compare` returns a `passages` map keyed by *chunk* id, whose values carry no `document_id` | observed payload |
| `trim()` drops a list entry carrying a hidden `document_id` — and nothing else | `scope.py:74` |
| `/ingest` passes the caller's document ids straight through | `main.py:448` |
| `_store` clears a document's existing chunks before writing new ones | `vector_search.py:815` |
| The rate limiter keys on `request.client.host` | `main.py:237,262` |
| …and is one process-global fixed window per key | `observability.py:104` |
| The spend cap is a single daily figure for the whole process | `observability.py:126`, default `0` (off) at `:40` |
| `READABLE_TOOLS` keeps writes away from the model — this is correct and stays | `agent.py:83` |
| The eval harness constructs `KnowledgeBase` directly, so it never crosses the host | `eval/harness.py:259,261` |

That last row is worth saying out loud: **every number in `learning/` is an
unscoped number**, and no eval run would catch a scoping bug. That is fine —
scoping is a boundary, not a retrieval change — but it means tests are the
only thing guarding it, which is why item 1's rule is written the way it is.

## 1 · Two doors the scope does not reach — ₹0

**Not an experiment.** Two defects, both reproduced against a running server
on a scratch store.

### A · The Index Lab hands out other people's text

`/ann/compare` calls `host.call(...)` on the process-global host, not the
scoped one. Asking it a question as `ada`:

```
passages:
  upload:grace:secret#0  "# Grace Secret\n\nGraces confidential salary review notes…"
  upload:ada:notes#0     "…"
```

Verbatim chunk text belonging to somebody else, through a view the UI puts a
button on.

**And the obvious fix is not enough**, which is the more useful half. Route
that call through `ScopedHost` and the leak survives: `passages` is a *mapping
keyed by chunk id*, and `trim()` only knows how to drop a **list entry** that
carries a `document_id` **field**. This shape has neither.

So the finding is not "one endpoint was missed". It is that deny-by-default
only denies the shapes it can recognise, and `scope.py` says in its own
docstring that `kb_ann_compare` is covered. I thought of the tool and still
missed the shape. A rule that can be wrong while reading as though it is right
is worse than an enumerated list, because nobody re-checks it.

### B · Anyone can overwrite anyone's document through `/ingest`

`/ingest` is deliberately not namespaced — its caller states the id outright,
and that was right when the only caller was the operator. It is no longer the
only caller: every authenticated user can reach it, and `_store` clears a
document's existing chunks before writing its own. Reproduced:

```
ada uploads     -> Stored 1 document(s) as 1 chunk(s)     # upload:ada:notes
grace ingests   -> Stored 1 document(s) as 1 chunk(s)     # id: upload:ada:notes
ada's document now reads:
  "FORGED. Graces text, which ada will now see as her own document and cite."
```

This is milestone 20 item 1's collision again, except deliberate rather than
accidental, and worse in its consequence: the victim keeps a document under
their own name, sees it in their own scoped listing, and the agent cites it to
them as theirs. The bug item 1 fixed was two people losing each other's work by
accident; this is one person being fed another's text with their own label on
it.

**Change.** A document id in the `upload:` namespace may only be written by the
owner it names. `/ingest` keeps taking stated ids for everything else, because
that is what it is for and what the CLI depends on.

**Decision rule, pre-registered.** This lands only with all three:

1. a test that `grace` cannot read an `upload:ada:*` passage through any
   `/ann/*` route;
2. a test that `grace` cannot write `upload:ada:*` through `/ingest`, and that
   `ada` still can, and that an unnamespaced id still works for everybody;
3. a test that the trim rule catches a **content-bearing shape that carries no
   `document_id` field** — keyed by chunk id, nested in a mapping. Without
   this one the fix is the specific door and not the rule, and the next shape
   walks through.

Two of three is not a pass. The first two are the doors; the third is the
reason there were doors.

### Shipped — 2026-10-06, 0.8.5, ₹0

All three clauses, and one deliberate departure from the second.

**The rule, not the doors.** `trim()` no longer looks for a field. It
recognises an **id**, wherever an id can reach a caller, and there turned out
to be three places:

| Shape | Where it occurs | What 0.8.4 did |
| --- | --- | --- |
| a string value *anywhere* in an entry | `document_id`, `id`, `source`, a field invented next year | only `document_id` |
| a **key** of a mapping | `passages` | nothing |
| a **bare string** in a list | `exact`, `missed` | nothing |

The check is anchored: `owner_of_document` reports an owner only for a string
that *starts* `upload:<owner>:<stem>`, so a sentence that happens to mention an
id is untouched and only something that genuinely is one is dropped. That
matters in the other direction — over-trimming silently deletes content and
looks exactly like the feature working. `test_prose_that_merely_mentions_an_id_
is_not_an_id` pins it.

**The doors.** `/ann/compare` and `/ann/benchmark` now go through
`ScopedHost`. The benchmark returns only aggregates today and is routed anyway,
because *"nothing to leak yet"* is precisely how `/ann/compare` came to be the
one route calling the global host. `/ingest` and `/upload` go through it too,
so every read and every write crosses one object.

**Writes are an allow-list where reads are a deny-list.** `identity.
writable_by` is not `visible_to`, and the asymmetry is the whole content of the
fix: a document everyone may read is not a document everyone may *replace*,
because `_store` clears a document's chunks as the first step of writing it. So
a write is a delete first, and it is checked **before** the store is touched —
a guard on the way back out has already destroyed what it was protecting.

**The departure.** Clause 2 pre-registered "an unnamespaced id still works for
everybody". It does not. An unnamespaced id — `handbook`, the CLI-ingested
corpus — is writable by `shared` only: curl, the eval harness, a box with no
identity wired up, exactly as before owners existed. An *authenticated* caller
is refused it. Letting ada overwrite `handbook` is the same vandalism as
letting her overwrite `upload:grace:notes`, with a worse blast radius: the
shared corpus is everybody's. The clause as written would have closed one door
and left the wider one open, and writing it down beforehand is not a reason to
ship it. Nothing real loses: `sextant-ingest` constructs `KnowledgeBase`
directly and never crosses the host (`ingest_cli.py:81`), the frontend never
calls `/ingest`, and the 403 names the prefix the caller may use.

**A tool `scope.py` cannot classify is refused.** `READ_TOOLS | WRITE_TOOLS` is
pinned against the live server's tool list, so a tool added later fails a test
rather than defaulting to either behaviour. That is the only honest way to keep
a list — the alternative is the docstring that said `kb_ann_compare` was
covered.

**Left whole on purpose, and written down:** the Lab's measurements *of the
indexes* — `recall`, `latency_ms`, `vectors`, `bytes`. Recall is an index's
property against exact search over the whole store; scoring each index against
a different subset per visitor would measure nothing, and the view exists to
say which index to build over the corpus that exists.

**Verified live**, against a real server on a scratch store with the proxy
secret set, by the same method that found the defects -- not by the tests
agreeing with themselves:

```
ada uploads notes.md, grace uploads secret.md

/ann/compare as ada    exact:    ['upload:ada:sx_notes#0']
                       passages: ['upload:ada:sx_notes#0']      no 'grace' anywhere
/ann/compare as grace  passages: ['upload:grace:sx_secret#0']

grace -> /ingest {"id": "upload:ada:sx_notes", …}
  HTTP 403  'upload:ada:sx_notes' is not grace's to write: re-using an id
            replaces that document. Ids grace may write start with 'upload:grace:'.
grace -> /ingest {"id": "handbook", …}          HTTP 403
/stats as ada          documents: 1             ada's document intact
```

₹0: neither path makes a model call.

**Verification.** 16 new tests (8 in `TestTheShapesAnIdTakes`, 9 in
`TestWrites`, 5 at the HTTP edge in `TestIngest`/`TestIndexLab`), plus
`test_the_index_lab_shows_one_owner_nothing_of_the_others`, which runs a real
`ann_compare` over a real three-document store and asserts the *serialised*
payload — not three fields somebody thought of — contains nothing of the other
owner, after first asserting it did before trimming.

## 2 · The limiter and the cap still count one person — ₹0

Deferred by milestone 20 by name. Both are now one-line keys away from being
right, and both are wrong in a way that is somebody else's problem rather than
the operator's, which is why neither has been noticed.

**The limiter keys on client IP.** Two consequences, opposite in sign: everyone
behind one NAT shares one bucket and throttles each other, and — now that an
authenticated name exists — the key is simply the wrong one. The name is the
thing being limited; the address it arrived from is an accident.

**The cap is one global figure.** `SEXTANT_DAILY_BUDGET_USD` is described in
`deploy/env.example` as *"the one guarantee that a shared/leaked gate can never
surprise you with a bill"*, and it is exactly that. What it is not is fair: the
first user to spend the day's allowance silences everybody until 00:00 UTC.
That is a denial of service available to any authenticated user, by design,
and it needs no malice — one person running a long session is enough.

**This is a design choice, not a measurement**, so what is pre-registered is
the behaviour rather than a number. The question to settle before writing any
of it: does a per-owner cap *replace* the global one, or sit under it? The
global cap protects the owner's wallet and must survive; a per-owner cap
protects the other users' access. The likely answer is both — a global ceiling
that cannot be exceeded, and a per-owner share that cannot be hogged — but
"likely" is why it is written down here and decided before it is built.

**Decision rule, pre-registered.** Lands only with:

1. a test that one owner exhausting their share leaves another owner able to
   ask — the whole point;
2. a test that the global ceiling still holds when every owner is under their
   own share, so the wallet guarantee is not traded away for fairness;
3. unchanged behaviour when no identity is configured: one box, one password,
   one bucket, exactly as today. A single-user deployment must not acquire a
   second kind of limit it never asked for.

The limiter is process-global in-memory state and stays that way. A shared
store for it is the multi-replica problem, and multi-replica is decided
against (`milestone-15.md`).

## 3 · Put it on the box — ≈₹2, and it needs you

Three versions of work that nobody can use. The trip carries 0.8.2, 0.8.3,
0.8.4 and whatever items 1 and 2 add, and it should carry the `GEMINI_API_KEY`
rotation still open from milestone 19 rather than be spent on its own — the key
exposed in a screenshot on 2026-09-23 is live.

Preconditions, already written down and repeated here because this is the page
that will be open during the trip:

- **`SEXTANT_PROXY_SECRET` goes into the box's `.env` before the tree is built
  there.** Caddy has no conditionals: it forwards `X-Sextant-User` regardless,
  and without the secret the app refuses every request with a 403 naming the
  variable. Verified against a running Caddy, not assumed.
- **The second and third `basic_auth` users** go in the same file on the same
  trip, or identity is a mechanism with one name in it.
- **Confirm with `kb_list` that the deployed store holds no pre-0.8.2
  `upload:<stem>` documents.** None are expected — the 2026-09-27 re-ingest
  rebuilt it from `/data/corpus` through the CLI, whose ids are bare stems —
  but this is the trip where "expected" becomes "checked".
- **`deploy/trip.sh`, not a sequence of gcloud commands.** Parking is an `EXIT`
  trap. A checklist is what failed on 2026-09-28 and cost ₹703.

**Decision rule, pre-registered.** The trip is a success only if, from the
public URL: two different `basic_auth` users each upload a file of the same
name and both survive; each sees their own and not the other's; and a
client-supplied `X-Sextant-User` is refused. Anything less and identity shipped
as a configuration file nobody exercised.

## Not in this milestone

- **A user deleting their own upload.** `sextant-forget` is an operator
  command on the box, and re-uploading replaces. A person who uploads the
  wrong file cannot take it back without asking the operator. A real gap, a
  product decision rather than a defect, and it wants the trip to have
  happened first so it is designed against something real.
- **Per-owner conversation history on the server.** It lives in the browser's
  localStorage and that remains the right place for it.
- **Concurrency.** Embedded Chroma is single-writer; `add_documents` holds an
  async write lock inside the one subprocess, so two uploads through the API
  serialise. CLI-while-serving is the known stale-segment gotcha and is
  already written down. No demonstrated failure, so no item — the rule in this
  repo is that nothing starts on a hunch.
- **Making eval cross the host.** The harness builds a `KnowledgeBase`
  directly and should: it measures retrieval, and the scope is not retrieval.
  The caveat is recorded above instead.
- **Public signup, OAuth, password reset, per-user billing.** Out of scope by
  milestone 20 item 3's argument, unchanged.
