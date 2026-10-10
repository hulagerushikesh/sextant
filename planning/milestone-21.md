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

**Verification.** 24 new tests (8 in `TestTheShapesAnIdTakes`, 10 in
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

### Shipped — 2026-10-06, 0.8.6, ₹0

**The design question, settled: the per-owner cap sits *under* the global one,
it does not replace it.** The global cap is the only thing a shared or leaked
gate can never get past, and `deploy/env.example` promises exactly that; a
per-owner cap that replaced it would make the bill scale with the number of
users, which is the opposite promise. So there are two ceilings and a query
passes both — `check` is the wallet, `check_owner` is the fairness.

**Not one line, and the plan was wrong to guess it would be.** "Key the
limiter on the owner" is only right for an owner somebody *checked*. The name
is `X-Sextant-Client` on a box with no proxy secret — a header the caller
types — so keying the bucket on it would let anyone get a fresh bucket by
typing a different one. That is **weaker than the client address it replaced**.
The rule shipped is therefore a choice, not a fallback:

| Identity | Limiter key | Per-owner share |
| --- | --- | --- |
| vouched for by the proxy | `user:<name>` | applied |
| anything else | `ip:<address>` | not applied — the global cap alone |

Keys are prefixed so a user named after an address cannot inherit its bucket.
`identity.resolve()` now returns `Identity(name, trusted)`; `owner_of` is the
name half, kept because most callers only ever wanted the name. Untrusted
spend still counts against the *day* — it is real money — it is simply not
attributed to a name not worth attributing to.

**The share is a fixed fraction, `SEXTANT_DAILY_BUDGET_SHARE`, default 1
(off).** It is not a division between whoever turns up: that needs to know how
many people there are, and this process cannot see the user list, which lives
in Caddy's `.env`. Two schemes were rejected for concrete reasons — an
absolute per-owner figure drifts out of step with the cap it sits under, and
`cap ÷ owners-seen-today` is self-balancing but shrinks a share retroactively,
so somebody who spent inside their share at 10am is over it at noon because
another person logged in. A fraction the operator picks with the user list in
front of them is legible, and the cost of getting it wrong is legible too:
too low wastes the wallet, too high lets one person take more of it.

Default 1 for the same reason the cap itself defaults to off: a share below 1
leaves part of a wallet the operator paid for unspendable when they are the
only person asking. `deploy/env.example` carries the arithmetic for a gate
with three users (0.5 guarantees half the day is always left for the others;
0.34 divides it about equally) and `deploy/README.md` says what each half is
for.

**Scope added on purpose, and stated rather than slipped in:** `/ann/benchmark`
and `/ann/compare` are now rate limited. Building two ANN indexes over every
vector is the heaviest thing the box serves and they were the only routes with
no limit at all — the same defect as the rest of this item, in the same place
item 1 found the scope hole.

**The UI had to change or the fix would read as a bug.** The spend card
tracked the box-wide cap. A user refused at 60% of a cap the card showed as
40% unspent, with no explanation, is a bug report. `/health` now carries the
asker's own share when there is one, the card labels itself *Your daily share*
and tracks whichever figure is closer to stopping them, with the box's beside
it; `lib/mock.ts` carries the new fields so design mode renders that branch.

**Verified live** on a real server, limit 2 per 120s, ₹0 — the limiter half
needs no model key, so it was checked rather than argued:

```
ada   (proven), 3 tries        200 200 429     own bucket
grace (proven), same address   200 200         not throttled by ada -- the NAT fix
unproven, a new client header every time        429 429 429   no fresh bucket
...and a proven name beside them                200           separate keys
/ann/benchmark, three tries    503 503 429      now limited at all
```

The *share* half is not live-verifiable for free: spend only accumulates
through a model call, and this box has no key wired up. It is covered at the
HTTP edge with a stubbed agent instead, which is stated here rather than
dressed up as a live run.

**Verification.** 19 new tests. The three pre-registered clauses each have one
named for it: `test_exhausting_a_share_leaves_the_other_owner_able_to_ask`,
`test_the_global_ceiling_still_holds` (three owners each inside their own
share, $1.05 between them, box shut), and
`test_a_box_with_no_identity_behaves_exactly_as_before`. Plus the one the plan
did not ask for and needed most:
`test_an_unproven_name_does_not_buy_a_fresh_bucket`.

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

---

## Item 4 — the pin that would have caught all three (0.8.7)

Not planned. It came out of asking a question nobody had asked while item 3
sat blocked: **are there more doors?**

There were not. Every route that reaches the corpus hands the host to
`scoped()`, `/query` included — the agent is given a `ScopedHost`, and
`SourceRegistry.restore()` sets `content=""` rather than looking a
client-supplied key up in the store, so replaying prior sources cannot pull
another owner's text. That half of the audit found nothing, which is worth
writing down as a result rather than silence.

What it found instead is that **nothing stops the next one.**
`test_every_tool_the_server_exposes_is_classified` makes adding a *tool* fail
until somebody decides which half of the boundary it is on. The route list had
no such pin — and all three defects this milestone fixed were routes:

| Defect | Shape |
| --- | --- |
| `/ann/compare` (item 1) | had a host; it was not the scoped one |
| `/ingest` (item 1) | wrote without asking whose document it was |
| `/ann/*` (item 2) | the heaviest call on the box, with no rate limit |

Every one was found because somebody went looking. So the route table is now
read off the live app and each path must be declared as reaching the corpus or
not. A corpus route must call `scoped(`, must never contain `host.call(`, and
must be rate limited. A route declared harmless must call no tool. A handler
whose source cannot be read counts as unclassified and fails — the same
fail-closed rule `scope.py` applies to a tool it does not recognise.

**Each pin was verified by planting the defect it is for** — an undeclared
`/leak` route calling the process-global host — and watching all five fail.
A pin that cannot fail is a comment.

**One real finding, and it is mine again.** `/stats` was the last corpus route
with no rate limit. That was defensible when it was a cheap count; 0.8.4
scoped it by recomputing from a full listing, which made it walk the corpus
on every call, and the limit was never revisited. Same defect as `/ann/*`,
introduced by the fix for something else. Now limited; the UI calls it once a
page load and never polls, so nothing legitimate is near the limit.

**Departure worth stating:** the classification reads handler *source*, which
is crude and would be the wrong tool for a subtle question. The question is
not subtle — somebody writes an endpoint and reaches for `host` instead of
`scoped(host, ...)` — and a crude check that runs in the gate beats a precise
one that nobody runs.

₹0; no model call on either path.


---

## Item 5 — the trap's own result (₹0)

Also unplanned, and the same shape as item 4: not a new door, but the thing
that would notice one.

`deploy/trip.sh` exists because of 2026-09-28, when a checklist's last step —
park the box — was never reached and ₹703 went to a VM nobody was using. The
fix made parking an `EXIT` trap, so that *"the script returned"* means *"the
box is parked"*.

**It did not mean that.** `park()` ran `instances stop ... || true`, then read
the state back and printed it:

```
== parking agenticrag (this runs even on failure or Ctrl-C)
   agenticrag is RUNNING; reserved addresses: 0
   trip took 0 min; VM time ~Rs0
```

Exit code **0**. That is a real offline run of the current script, and this
module's own happy-path test asserted `code == 0` against exactly it. Printing
a state is not checking it. The checklist became a trap, and then the trap's
outcome became the new line nobody read — one level down, same failure.

Two reasons it stayed invisible:

- **`|| true` on the stop.** Correct in itself: a trap that aborts half way
  leaves the address reserved too. But it means the stop's failure has to be
  caught by the readback, and the readback was only printed.
- **A stub that could not fail.** The offline harness answered `RUNNING` to
  every `instances describe` and ignored `instances stop`, so "the trip parked
  the box" was not an assertion anybody could have written. The stub now keeps
  state: the instance answers `RUNNING` until a stop succeeds, the address
  exists until a delete succeeds, and both can be told to refuse.

What changed, in `park()`:

- the stop is **retried once** — a single transient API error is the dullest
  explanation for a bad readback and the cheapest to rule out;
- a state that is not `TERMINATED`/`STOPPED` prints the hourly rate, the daily
  rate and the manual command **on stderr**, and **takes the 0 away**;
- the reserved address is checked **by name** rather than counted, because
  ₹21/day for an address attached to nothing is the same silence in smaller
  type;
- the check may only turn a 0 into a 1. A trip that already failed keeps its
  own exit code, so the park never overwrites the reason.

`--keep-up` is untouched: a box left up on purpose is a decision somebody had
to type, not the failure this guards.

**Four of the seven new tests fail against the previous script**; the other
three are the no-regression clauses (`--keep-up`, a failing trip keeping its
code, and the happy path now reaching `TERMINATED` — which only became a real
assertion once the stub could say otherwise).

₹0, and it is the only kind of work that pays for itself before item 3 runs:
the next trip is the one that will be read for whether the box came back down.

---

## Item 6 — the trip had never touched the gate (₹0)

Found by reading step 5 after item 5: **every check in the trip runs through
`docker exec` at `localhost:8000`.** That is inside the box and behind Caddy.

So the trip that exists to deploy the gate 0.8.3 built had never once gone
through it. A box whose Caddy was misconfigured, pointed at the wrong
upstream, or simply not running passes every check in step 5 and reports
green. Even the forged-name check is the easy half: `docker exec` to localhost
always skips the proxy, so it proves the *app* refuses an unvouched name — it
cannot say whether the *proxy* would have let one through.

Step 6 runs from the operator's machine against `PUBLIC_URL`, read off the box
rather than hardcoded because this repo is public.

| Check | Want |
| --- | --- |
| no credentials | 401 |
| a wrong password | 401 |
| a real user | 200 |
| a real user, **forged `X-Sextant-Proxy-Auth`** | **200** |
| naming yourself, no password | 401 |
| a second user | 200 |

**The fourth row reads backwards and is the one worth having.** `header_up` in
Caddy is a *set*: the client's own proof header is replaced by the real secret
before the app ever sees it. A request that forges the proof and still succeeds
is Caddy doing its job. A 403 would mean it appended instead of replacing, or
is not in the path at all — and then the header is worthless, because anyone
can send it. Nothing in the test suite could have caught that: it is a property
of the deployment, not of the code.

**Credentials are the operator's.** Exported as `SEXTANT_TRIP_AUTH` and
`SEXTANT_TRIP_AUTH_2`, passed to `curl` through a config file on a pipe rather
than argv so they are not in `ps` while the trip runs, and never printed.
Unset, the step says the gate is unproven and the trip still passes — choosing
not to prove something is not a defect. A box with **no `PUBLIC_URL`** does
fail, because that is the box being wrong.

Any failed check exits non-zero; the park is a trap, so it still happens.
Nothing here writes to the corpus or calls the model — every request is a
`GET /health`, so the step costs nothing but seconds.

A late read of the diff found two more of my own: `curl` exits non-zero on a
refused connection or a DNS failure, and `set -o pipefail` would have made
that the *script's* problem rather than the check's. It is the check's --
curl still prints `000`, which is not the code wanted, so an unreachable box
counts as a gate failure like any other. There is a test for that now.

**8 of the 9 new tests fail against the previous script.** The ninth
(`test_the_password_never_reaches_the_output`) passes trivially when nothing
uses a password; it is a no-regression clause, not a pin.

### What this still does not prove

The pre-registered success criterion for item 3 is two users uploading the
same filename from the public URL, both surviving, each seeing only their own.
Step 6 proves the gate; it does not prove the isolation behind it, because
every check in it is a read. That needs two uploads into the production corpus
and a cleanup that itself has to be checked rather than assumed — the same
discipline item 5 just installed — so it is its own item rather than something
bolted onto this one. Until then that half of the criterion is done by hand
with the meter running, which is exactly the shape this milestone keeps
finding.

---

## Item 7 — the criterion, run by the script (₹0 to write)

Item 6 proved the gate. Every check in it is a read, so it proved nothing about
what is behind the gate — and the half it left out is this milestone's
pre-registered success criterion, which was going to be done by hand on the box
with the meter running:

> two different `basic_auth` users each upload a file of the same name and both
> survive; each sees their own and not the other's; and a client-supplied
> `X-Sextant-User` is refused.

Step 7 runs it. It is the **only part of the trip that writes**: two small text
files through the public URL, one per gate user, same filename. It only runs
when both credentials are exported, which is already a deliberate act.

| Check | Want |
| --- | --- |
| first user uploads `sextant-trip-probe.txt` | 200 |
| they see one more document | `a0 + 1` |
| the second user sees nothing new | `b0` |
| **naming yourself the other user** | **still `a0 + 1`** |
| second user uploads the same filename | 200 |
| they see one more | `b0 + 1` |
| **the first user's copy survived** | **still `a0 + 1`** |
| probe documents in the store | 2 |
| owned by distinct names | 2 |

The last two are read straight off chroma rather than through `/stats`, because
`/stats` reports what the asker can *see* and those two report what is actually
*there*. Both matter and they are not the same question.

### Two defects of my own, found by running it

**The forged-name check was in the wrong place.** I had it after both uploads.
At that point both users are at the same count, so the check's two sides agree
no matter which identity the request resolved as — it passed against a simulated
proxy that forwarded the client's name, which is the exact failure it exists
for. It now runs in the one window where the two views differ: after the first
upload and before the second. Pinned by position, not just by outcome
(`test_the_forged_name_is_checked_while_the_two_views_differ`).

**The cleanup failure was swallowed.** `forget_probes || echo "..."` printed a
loud warning and returned 0, so a trip that left two documents in the production
corpus exited successfully. That is item 5's defect, in code written the day
after item 5 — a result read and not compared. It now takes the 0 away, the
same way the park does.

### Why the cleanup is in the trap

Not at the end of step 7: the run that most needs the cleanup is the one that
died half way through it. It happens in `park()`, before the box is stopped, and
it reports what it removed and then re-reads to confirm nothing is left.

The documents are found by **scanning the store for the probe filename**, not by
rebuilding `upload:<owner>:<stem>` from the usernames here — so `safe_owner()`
spelling a name differently cannot leave documents behind that the trip then
reports as gone.

### Cost

₹0 to write and to test. When it runs: two uploads, each generating a summary
when a model key is configured, ≈$0.006 total. Everything else in the step is a
`GET /stats` or a metadata read.

**All 8 new tests fail against the previous script.** Four simulated boxes are
exercised end to end offline: a correct one, one on the pre-0.8.2 id scheme
(the second upload replaces the first), one whose proxy forwards the client's
name, and one where `sextant-forget` does not take.

With this, the whole of item 3's success criterion is something the script
decides. What is left for a person is creating the key and the second gate user.

---

## Item 8 — an upload is judged by what it stored (₹0)

Item 7 shipped with a check that could not fail for the thing it named.

`/upload` answers **HTTP 200 with `"success": false`** when the file was
unreadable, the tool was unavailable, or the ingest failed — the status code
says the request arrived, not that anything was stored. Step 7 compared the
status code. So against a box that refused both uploads, step 7 printed:

```
   first user uploads sextant-trip-probe.txt    200
   second user uploads the same filename        200
   they see one more                            got 21, wanted 22
   they see one more                            got 21, wanted 22
```

Two ticks on the lines that describe the action, then unexplained count
mismatches, with the actual reason — *No readable files in the upload* —
nowhere on screen. The trip still failed, which is why this is a reporting
defect rather than a correctness one, but an operator reading that output
would go looking in the wrong place with the meter running.

The verdict now comes out of the body:

```
   first user uploads sextant-trip-probe.txt    got refused: No readable files in the upload., wanted stored 1
```

`stored 1` on success, `refused: <the box's own reason>` otherwise, `http
<code>` when the request did not return 200 at all, and `200 with an
unreadable body` when it did but said nothing parseable.

### The harness was lying too

The first attempt to demonstrate this against the previous script did not
work, because the `curl` stub printed the body regardless of `-o /dev/null`
and appended a status line regardless of `-w`. The old code path could not be
simulated, so the defect could not be planted.

The stub honours both flags now, which is the difference between the three
call sites in `trip.sh`: `-o /dev/null -w '%{http_code}'` sees only the status,
`-w '\n%{http_code}'` sees the body and then the status, and a plain `curl`
sees the body alone. With that, reverting `trip.sh` reproduces the output
above exactly.

**3 of the 4 new tests fail against the previous script.** The fourth
(`test_nothing_is_left_behind_when_nothing_was_stored`) passes either way,
since a refused upload stores nothing to clean up under both versions.

₹0. No new requests — the same two uploads, read properly.

## Item 9 — the door is checked before the meter starts

Found by running item 3, not by reading anything. The trip was started on
2026-10-07 with `--keep-up --no-deploy`, to bring the box up so the new key
could be installed on it. It:

1. reserved an address and started the instance — the meter on,
2. waited 24 × 5s for an ssh that could not arrive,
3. printed `ssh never came up` and exited 1,
4. and then, because `--keep-up` was typed, **did not park.**

The box was left billing at ~₹5.6/hour with nothing deployed. That is the
2026-09-28 ₹703 failure, in the script written to prevent it.

### The cause was free to read and nobody read it

Port 22 is open to exactly one `/32` on the `agenticrag-ssh` rule. It named
an address from a previous session; this machine's had moved to another
host inside the same ISP block, a dynamic home address doing what those do. The
VM itself was fine: the serial console showed a clean boot, `Startup finished
in 44.477s`, and `instances describe` said `RUNNING`.

Both halves of that answer are readable from the laptop before anything is
started: the rule's source ranges, and this machine's public address. Neither
was read. `ssh never came up` names the symptom and not one thing about the
cause, and it was the only thing on screen — so the natural next move is to
go looking at the box, which was the one part that was working.

This is the same shape as items 5–8 one more time. **A result produced and
not compared** — except here the result was never even produced. The
precondition had no check at all, and the message that stood in for one was a
restatement of the failure.

### Step 0

```
== 0 - the ssh door, before the meter starts
   port 22 is NOT open to this machine.
   agenticrag-ssh allows 203.0.113.9/32. this machine is 203.0.113.52.
   nothing has been started, so this has cost nothing. open the door:
   gcloud compute firewall-rules update agenticrag-ssh --project=agenticrag-rush --source-ranges=203.0.113.52/32
```

It runs **before step 1**, which is where the meter starts: a shut door found
there costs ₹0, and found one line later costs ₹2 and a second trip. The
address is read at run time from `checkip.amazonaws.com` (`VM_MY_IP_URL`) and
never stored — this repo is public, and an operator's home address is not
something to commit, the same rule that makes step 6 read `PUBLIC_URL` off
the box instead of hardcoding it.

Containment, not string equality: the range is allowed to be wider than one
address, and comparing the text would call an open `/24` shut. `ipaddress`
does the work.

(The addresses in that sample output are from `203.0.113.0/24`, the range
reserved for documentation — as are the ones in the tests. A real operator
address is not something this repo may hold, which is the same reason step 0
reads it at run time. The first draft of this write-up put the real pair in
three places, in a public repo; `TestTheRepoHoldsNoRealAddresses` now fails
the gate on that.)

**Three outcomes, not two.** Open, shut, or could-not-tell. A third-party
address service that is down, slow, or answering an HTML error page must not
be able to ground the box — those cases say `door not checked` and carry on,
and the ssh wait is still there to catch what step 0 missed. Only a
definite answer stops a trip.

### `--keep-up` does not keep up a box nothing can reach

The second half, and the expensive one. `--keep-up` means *leave it up, I am
going to work on it* — a sentence about a box you can reach. The flag was
exempt from parking unconditionally, so the one run that most needed parking,
the one that never got in, was the one that kept the box.

`SSH_UP` is set the moment ssh answers, and the exemption now requires it:

```
== parking anyway: --keep-up was typed but ssh never answered
   there is nothing up to keep. restarting costs ~Rs2; waiting cost Rs703 once.
```

Because it is a variable the trap reads rather than a branch at one call
site, this also covers Ctrl-C during the ssh wait and a step-0 failure
against an already-running box.

Two smaller things from the same run: the final `ssh` after the wait loop had
no `ConnectTimeout`, so it inherited the TCP default and hung for minutes
after the loop had given up — the run looked busy when it was already dead.
And the 24 × 5s wait is now `VM_SSH_TRIES` / `VM_SSH_SLEEP`, because the
offline gate exercises the path where ssh never answers and cannot spend two
minutes per test doing it.

### The harness was half the defect again

`test_nothing_is_started_when_the_door_is_shut` is the load-bearing pin —
step 0's entire value is that it is free — and in its first form it **passed
against the unfixed script.** The fixture starts the box already `RUNNING`,
and step 1 skips the start when it is, so `instances start` appeared in no
run of any version and the assertion could not fail. `_run_trip` takes
`vm_state` now, the test runs from `TERMINATED` — the only state in which a
start can happen — and the gcloud stub records every invocation so "nothing
was started" is something a test reads rather than something a comment
claims. The stub also moves to `RUNNING` on a start, for the same reason it
moves to `TERMINATED` on a stop.

**11 of the 12 new tests fail against the previous script.** The twelfth,
`test_keep_up_still_keeps_a_box_that_did_come_up`, passes either way on
purpose: the exemption is not being removed, it is being made true, and that
pin says so.

₹0 to fix. The run that found it cost about ₹1 of VM time before it was
parked by hand, and the firewall rule is one command the operator runs.

## Item 10 — the forged-name check counts

Found in the output of a real preflight run on 2026-10-07, after item 9 was
shipped and the box was brought up to install the key. Step 5 asks the api
container whether it believes a name the proxy did not vouch for:

```
   a name the proxy did not vouch for:
     got 200, expected 403 -- a client can name itself
```

On the box as it stands that answer is correct: it runs 0.8.1, which predates
the 0.8.3 middleware, and a client can indeed name itself. That is one of the
things this deploy exists to fix.

The defect is what the script did with the answer. It compared it, printed it
to stderr, and **discarded the verdict** — no counter, no effect on the exit
code. So a trip could deploy 0.8.3 or later, discover that a client can still
name itself, print that one line among forty, and exit **0** with the box
reported as shipped. The middleware whose entire job is that 403 would be
broken, and the trip that deployed it would say it was fine.

Compared, reported, and not counted. Items 5 through 9 were all a variant of
*a result produced and not compared*; this is the next notch along — compared
and then thrown away.

### It must not fail unconditionally

The reason it was only a print is real: on a `--no-deploy` run nothing was
built, so the answer describes whatever the box already was, and today that is
legitimately a 200. A check that failed every preflight run would be turned
off within a week.

So the verdict depends on whether a deploy happened. With `DEPLOY=1` the
preflight has already refused to build without `SEXTANT_PROXY_SECRET` and the
tree being built contains the middleware, so a non-403 is a failure and feeds
`GATE_FAILURES` like every other counted check. With `--no-deploy` it stays
informational and says so, which is the difference between a known gap and an
unread line:

```
     got 200, expected 403 -- a client can name itself
     (--no-deploy: this is the box as it stands, not a result of this run)
```

### The counter was in the wrong scope

`GATE_FAILURES=0` sat inside step 6. Step 5 runs before step 6. So even once
step 5 began counting, step 6 zeroed the count before anything read it — a
second defect hiding behind the first, and the one that would have made the
fix look like it worked while doing nothing. It is initialised once now,
beside `SSH_UP`, before any step can add to it.

`test_the_count_survives_step_6` is the pin for that, and it exports the gate
credentials on purpose: without them step 6 returns early, and the ordering
that loses the count is the one where step 6 really runs.

**3 of the 5 new tests fail against the previous script.** The other two are
the 403 happy paths, which were already right.

₹0. Found by reading output the script had already produced.

## Item 11 — step 5 judges what it prints

Item 10 fixed one unjudged result in step 5. This is the rest of them, found by
asking the obvious follow-up question instead of waiting for the next one to
bite: **of the six results step 5 produces, how many does it read?** One.

| What step 5 printed | What happened if it was wrong |
| --- | --- |
| the container table | nothing — a dead Caddy printed and the trip went on |
| `status=` | nothing |
| `mcp=` | nothing |
| `model=` | nothing |
| `budget_usd=` | a line on stderr, no effect on the exit code |
| `N chunks / N documents` | nothing |
| leftover `AGENTICRAG_*` names | the names printed, and the trip went on |

### The container table is the serious one

```
NAME                 STATUS
agenticrag-api-1     Up 15 minutes (healthy)
agenticrag-caddy-1   Up 15 minutes
```

That is the whole check: print what compose said. **A box whose Caddy had
exited would print `Exited (1)` there and pass step 5.** And every other check
in step 5 goes through `docker exec` to `localhost:8000` — inside the box,
behind Caddy — so not one of them can see that the gate is not in the path.

Step 6 exists for precisely that failure. But step 6 needs credentials the
operator has to export, and unset is a *skip*. So the default trip had no check
at all for the container that serves every real request.

Both services are now required to be present and `Up`, by name.

### `model=` was printed and never read

`model=True` is the key rotation's entire success criterion — the thing this
milestone's item 3 is waiting on a person for. A box with a bad or missing key
answers `model_configured: false`, and the trip printed it in the middle of a
healthy-looking line and exited 0 with the box reported as shipped.

Same for `status`, `mcp_connected`, and an empty store. The health verdict now
names every wrong thing at once rather than the first:

```
     status=degraded mcp=False model=False budget_usd=0
     NOT RIGHT: status is degraded; the tool server is not connected; no model
     key resolved, so the box cannot answer anything; the daily cap is 0, so
     the box is uncapped
```

The store check is a **floor, not a number**: what the corpus should hold is
not this script's business and hardcoding 21 would make every ingest a test
failure, but an empty store after a deploy is.

A leftover `AGENTICRAG_*` name is a counted failure too. It has not been read
since 0.8.1, so the container is running with its budget cap and CORS allowlist
at defaults — printing the names and carrying on is how an uncapped box ships.

### The harness was missing the thing the check is for

The `ps` stub printed **one** line, `agenticrag-api-1`. The real box runs two
containers. So no test could have noticed that Caddy went unchecked, because in
the fixture Caddy did not exist.

That is the fourth time in this milestone that the stub was half the defect:
the gcloud stub that always said `RUNNING` (item 5), the curl stub that ignored
`-o /dev/null` and `-w` (item 8), the fixture that started the box `RUNNING` so
nothing was ever started (item 9), and now a container table with one container
in it. The pattern is worth naming: **a stub that cannot represent the failure
makes every test about it a comment.**

**11 of the 13 new tests fail against the previous script.** The other two are
the happy paths.

₹0.

## Item 12 — CI had been red for 17 days and nobody looked

Items 5 to 11 were all the same shape inside `trip.sh`. The question that
closes the theme is where else the shape lives, and the answer was one level up
from the script: **the repository's own check.**

```
runs: 30  failures: 30
failure   2026-10-07  deploy: step 5 judges what it prints
failure   2026-10-07  deploy: count the forged-name check, do not ju
...
failure   2026-09-20  agent: report and price cached prompt tokens -
```

Thirty consecutive red runs, every push since 2026-09-20, all failing at the
same step on the same line:

```
tools/vector_db/ann/faiss_ref.py:62: error: Unused "type: ignore" comment
```

Because the type check runs before them, **`pytest` and `sextant-eval --check`
did not execute once in those seventeen days.** The workflow's own header says
why it exists — *"retrieval quality is a number, and a number that is not
checked drifts"* — and for seventeen days nothing checked it.

I pushed to `main` five times across two days inside that window and reported
"gate green" every time. That was true of the four commands in CLAUDE.md, which
I ran. I never looked at CI. The local gate passing is not the same claim as
the repository's check passing, and I had been treating it as if it were.

### One line, and an optional dependency

```python
try:
    import faiss
    HAVE_FAISS = True
except ImportError:
    faiss = None  # type: ignore[assignment]
    HAVE_FAISS = False
```

`faiss` is the `bench` extra. Installed, it is a typed module, so assigning
`None` to that name is an error and the ignore is required. Absent,
`ignore_missing_imports` makes it `Any`, the ignore is unnecessary, and
`warn_unused_ignores = true` turns *that* into an error. CI installs `[dev]`
and not `[bench]`.

So **whether an optional dependency was installed decided whether the code
type-checked**, and the two environments landed on opposite sides. Locally it
passed, which is why it survived seventeen days.

`follow_imports = "skip"` was the wrong fix — it types the module as `Module`,
not `Any`, so the assignment still fails. The name is annotated instead:

```python
faiss: Any = None
HAVE_FAISS = False
try:
    import faiss as _faiss_module

    faiss = _faiss_module
    HAVE_FAISS = True
except ImportError:
    pass
```

Verified both ways: `mypy` passes with faiss installed, and passes under
`--no-site-packages`, which is CI's condition applied to every import.

### CI ran three quarters of the gate

A second gap, found while reading the workflow. The gate is four commands; CI
ran three. `npm run build` runs `tsc -b` first, so **a type error in the
frontend failed only for whoever typed the gate by hand** and passed every
push. Added, with Node 22 because production builds on `node:22-alpine` — this
machine is on 20.12, which Vite 7 warns about and CI should not inherit.

### The pin

`TestCiRunsWhatTheGateRuns` reads the gate out of CLAUDE.md, extracts the
programs it invokes, and fails if any of them is absent from the workflow — so
the next command added to the gate cannot quietly skip CI. It also asserts the
frontend step *builds* rather than only installing, since `npm ci` alone would
satisfy the first check while checking nothing.

Verified by reverting the workflow: two of the four fail.

What it cannot pin is the thing that actually went wrong — nobody looked. A
test cannot read a dashboard. What it can do is make the gap between the two
claims smaller, so that looking matters less.

₹0.

## Item 13 — the offline trip harness only ran on a Mac

Fixing item 12 moved CI's failure rather than ending it, which is what should
happen when a check that never ran starts running. The type check passed; `Unit
tests` failed, for the first time since 2026-09-20:

```
tar: unrecognized option '--no-fflags'
Try 'tar --help' or 'tar --usage' for more information.
```

Step 3 shipped the working tree with `tar --no-xattrs --no-fflags
--no-mac-metadata`. The last two are BSD-only, and **GNU tar exits on an
unknown flag rather than ignoring it.** So step 3 died immediately on Linux and
took ten tests in `test_deploy_config.py` with it.

Which means the offline run of `trip.sh` — added on 2026-10-06 specifically so
the script could be exercised start to park without starting a box — **has
never once run anywhere but this laptop.** It was written to make the trip
checkable by something other than a person, and the only machine that could
check it was the machine that wrote it.

The flags are chosen by asking which tar this is:

```bash
if tar --version 2>/dev/null | head -1 | grep -qi gnu; then
  TAR_FLAGS=(--no-xattrs)
else
  TAR_FLAGS=(--no-xattrs --no-fflags --no-mac-metadata)
fi
```

Not dropped for everyone: on a Mac they are still passed, or `.DS_Store` and
resource forks ride along to the box. `test_macos_metadata_is_still_excluded_on_a_bsd_tar`
pins that, and passes on this machine because this machine has BSD tar.

### The harness needed a Linux tar it could fail against

A `tar` stub that answers `tar (GNU tar) 1.35` to `--version` and exits 64 on
the BSD-only flags, with GNU's exact message. `_run_trip(..., gnu_tar=True)`
puts it on PATH. That is the fifth time in this milestone that the stub was
half the defect, and this one gets its own pin —
`test_the_stub_really_rejects_the_bsd_flags` — because a stub that cannot say
no makes the test above a comment.

### And one of my own pins could not fail

`test_the_tree_is_still_shipped` **passed against the broken script.** The ssh
stub printed `synced 1 files` for whatever arrived on the pipe, including the
empty stream a dead `tar` produces, so "the tree was shipped" was not something
the test could get wrong. The stub counts the bytes it receives now, and the
test requires more than a thousand of them.

That is the same mistake as item 9's, two commits later: the assertion was on
the *message* rather than on the thing the message claims.

**2 of the 4 new tests fail against the previous script.** The other two are
the BSD regression guard and the stub's own pin, which pass either way on
purpose.

₹0.

### And CI went green

Run 37660824132 on `67dd89e` is the **first green run since 2026-09-20** — 30
of the previous 31 failed. All three steps that had not executed in those 17
days ran and passed: `Unit tests` (623), `Retrieval evaluation`
(`sextant-eval --check`, which uploaded `eval-results.json` for the first time
ever — 591 bytes), and `Frontend build`, which item 12 added because the
documented gate had four commands and CI ran three.

So the committed retrieval baseline is now enforced by something other than
this laptop. On the 65 questions: rerank hit@1 0.9273 / recall@5 0.9818 /
ndcg@5 0.9521, rrf 0.9091 / 0.9727 / 0.9315, dense 0.8727 / 0.9727 / 0.9044,
lexical 0.7818 / 0.9212 / 0.8506.

Two advisory annotations remain, neither of them ours: Node 20 actions forced
onto Node 24, and `ubuntu-latest` migrating to Ubuntu 26 on 2026-10-19. The
second one is worth watching now that the trip harness runs on whichever
Ubuntu CI picks.

## Item 14 — the gate on retrieval quality could not fail (unplanned)

Shipped 2026-10-08. ₹0.

CI went green on `sextant-eval --check` for the first time in 17 days, and the
next question is the one items 5–13 kept asking: **can it go red?** A pin that
cannot fail is a comment, and this one is the repository's entire claim about
retrieval quality. It had **no tests at all.**

The comparison itself was correct — the arithmetic, the tolerance, the epsilon
that keeps `0.97 - 0.99` from reading as `-0.020000000000000018`. What was
missing is that **nothing checked the comparison's own coverage.** Six ways to
pass it without grading anything:

| How | Why it passed |
| --- | --- |
| `--check --modes dense` | `--check` guarded `--store` and `--golden` but not `--modes`. The loop walks the *reports*, so three ungraded modes leave nothing behind to notice — a quarter of the gate, reported as "no regressions" |
| Delete 60 golden questions | `questions` was computed, printed, written into the artifact, and never compared. The easy questions survive, so every metric *rises* |
| Rename a metric | `previous.get(metric, value)` defaulted the missing name **to the value it was being compared against**, so the delta was always exactly zero |
| Rename a mode | `previous is None` printed "new configuration, no baseline" and continued. Renaming `rerank` un-checked the strongest mode |
| Drop a mode from `RETRIEVAL_MODES` | The baseline keeps an entry nobody grades; nothing reads the baseline's own key set |
| Delete `baseline.json` | "nothing to compare against" and **exit 0** |

Every one of those makes the numbers look better. That is the same shape as
items 5–13 — a result produced and not compared — one level further out: here
it is the *scope* of a comparison that was never compared.

Fixed on both sides. A parser guard refuses `--check` with a narrowed mode set
before a minute of grading is spent; and the check itself now fails when a
baseline mode was not graded, when a baseline metric is no longer reported,
when the run asked fewer questions than the baseline did, when the baseline
records no question count, or when there is no baseline at all. **Missing
baseline is a failure, not a pass** — `--check` is the claim that a committed
baseline was matched, and could-not-tell is a third outcome. Something
genuinely new — an added mode, an added metric — is still printed and still
passes; the guard is against silent *removal*, not against growth.

Two tests pin the committed baseline against the code rather than against
itself: its mode set must equal `RETRIEVAL_MODES`, and its `questions` must
equal `len(load_golden())`.

### The plant was dishonest the first time

Running the new 16 tests against the old file gave **12 failures** — and that
number was worthless. The signature changed to take the question count, so
most of those twelve were `TypeError`, not behaviour. A plant that fails for
the wrong reason proves nothing, which is the same trap as a pin that cannot
fail, inverted.

Re-planted with the **old body behind the new signature**, so the only
difference under test is the logic: **7 of 16 fail.** The other nine are
deliberate regression guards — the happy path, a real regression, the
exactly-at-tolerance boundary, a longer golden set, an added mode.

Also renamed `worst` to `best` in `print_table`'s caller: it is `max` by
`hit@1` and the message it prints says "best configuration". The behaviour was
right and the name was not, which is how a reader ends up flipping `max` to
`min`.

## Item 15 — the daily cap forgot the day on every restart (unplanned)

Shipped 2026-10-08. ₹0.

Came out of a plain question — *where do I see what the API cost?* — and the
honest answer turned out to be a defect. `/health` reports `budget.spent_usd`,
and it was **the process's spend, not the day's**: `DailyBudget` held the tally
in memory, so every `docker compose up -d --build` (which is every deploy, so
every trip) and every `restart: unless-stopped` bounce began the day again at
zero while Google's meter kept counting.

The class docstring already anticipated the *multi-replica* case — "a
deployment would move the tally to a shared store" — and said nothing about the
single-process case that actually happens several times a week. A cap that
forgets is not a cap on a day, it is a speed bump per process lifetime, and the
₹50–100/day ceiling this project is built around was resting on it.

The tally now persists to `.sextant-spend.json`, keyed by UTC date, so a
previous day's file is read and ignored rather than resumed. Per-owner shares
persist too, or the fairness ceiling resets on the same bounce.

Three design points worth keeping:

- **It lives inside the Chroma directory.** On the box the mount is
  `/data/chroma:/data/chroma`, so `/data` itself does **not** survive a
  container rebuild and `/data/chroma` does. The obvious-looking
  `/data/spend.json` would have been wiped by the very restart this exists for.
- **The ledger may never break a query.** Writes are atomic (tmp + replace, so
  a crash mid-write leaves the previous tally rather than a truncated file that
  reads as zero) and every failure is swallowed. The cap still holds in memory;
  the only thing lost is surviving a restart.
- **Three outcomes, not two.** `/health` now carries `budget.durable`. False
  means the number being read is this process's spend and not the day's —
  because a figure whose provenance nobody can tell is worse for tracking than
  an obviously fresh one.

One location resolved twice is the drift this repository keeps paying for, so
`spend_ledger_path()` is pinned against `vector_search.persist_dir()` in both
the default and the override case.

**8 of 14 new tests fail** against the previous behaviour, planted the honest
way — old body behind the new signature, so the logic is the only difference.
The six that pass either way are the path pins and the cap-is-off guard.

### My own defect: the tests shared one ledger on disk

The first full run after this change came back **8 failed, 648 passed**, and
the eight were all *pre-existing* budget tests. The default ledger path is
inside the collection directory, so the suite wrote a real
`chroma_db/.sextant-spend.json` and **every later `DailyBudget()` resumed it**:
`test_spend_accumulates_until_the_cap` constructed a $0.10 budget and found
$0.36 already spent by whoever ran before it.

Shared mutable state between tests, introduced by making state durable — and
the only pleasant way to find it, eight unrelated tests failing at once on the
first honest full run. An autouse fixture in `conftest.py` now gives every test
its own ledger; a test that wants persistence passes `ledger=` explicitly. The
pin is the eight tests themselves: remove the fixture and they fail again.

The stray file was gitignored (`chroma_db/`), so nothing was ever at risk of
being committed, but it had written into the real collection directory and was
deleted.

Also documented, since the question that started this deserves an answer in the
repository rather than in a chat: `CLAUDE.md` now has *Where the money shows
up* — the bill, `/health`, and the per-query log, with the four things
`/health` cannot see (CLI ingest and judging are separate processes; the price
table is hard-coded and dated; grounded search is priced without the free
allowance, so it overstates; VM time is a different line).

## Item 16 — the other door to the meter (unplanned)

Shipped 2026-10-08. ₹0.

Items 5–13 hardened `deploy/trip.sh`: a step 0 that reads the ssh firewall rule
for ₹0 *before* anything starts, an ssh wait that has to actually succeed, and
a park that is an **EXIT trap** rather than the last line of a checklist.

**`deploy/deploy.sh HOST start` is the other command that turns the meter on,
and it had none of it.** It started the box, looped thirty times for an ssh
that could not arrive, printed `>> up at <ip>` **either way**, and left the box
billing with a printed reminder to stop it by hand.

That is the 2026-09-28 ₹703 failure in full, sitting in the script the fix for
it never touched — and it is the same shape as this milestone's item 1, where
`/ann/*` reached the corpus without crossing `ScopedHost`. **Hardening one of
two paths to the same action hardens neither.**

### One copy of the check

`ssh_door()` moved to `deploy/lib.sh` and both scripts source it. The
extraction is behaviour-preserving: all 97 pre-existing deploy tests passed
against it before anything else changed. Two tests now fail the gate if either
script grows its own copy, because *a door check that exists in one of two
scripts is a door check in neither* — and item 15 had just finished arguing
that one location resolved twice is the drift this repository keeps paying for.

`start` checks the door before the meter, then asks ssh once more for real and
**stops the box if the answer is no**, naming the rate and the manual command
if the stop itself fails. It cannot park on exit the way a trip does — leaving
the box up is the whole point of running it — so it says out loud that nothing
parks it and that `trip.sh` does.

`VM_SSH_TRIES` and `VM_SSH_SLEEP` became knobs because `30 × 5s` hardcoded
meant **the old script could not be exercised offline in bounded time at all**:
the item 13 shape, where the harness could only ever run on one machine.

### A pin of mine could not fail — in the harness, again

The gcloud stub matched verbs as adjacent words, `*"instances describe"*`. But
`trip.sh` runs `compute instances describe …` while `deploy.sh` runs
`compute instances --project=X describe …`. **Every branch silently missed for
`deploy.sh`**: the stub answered nothing, the box read as neither `RUNNING` nor
`TERMINATED`, and `assert "instances start" not in calls` **passed for a run
that had started the box.**

The stub strips `--flags` and matches and logs the normalised args now. Sixth
time this milestone a stub was half the defect.

**5 of 9** tests fail against the previous `deploy.sh`.

### Second clause: `stop` performed the park without checking it

Found while reading the same file. `deploy.sh stop` issued the stop and printed
`>> stopped.` — a claim about the command, not about the box. Item 5's defect
in the other script, two days after item 5.

It reads the state back now and fails loudly when the box is still up, and it
names any **reserved address**, which bills roughly twice the in-use rate while
the box is off — about ₹21/day for nothing. The README has priced that
difference all along and the command that creates the situation never mentioned
it. Not released automatically: that changes the public IP, which is a DNS
decision, and `trip.sh` (which repoints DNS next trip anyway) is where it
belongs.

The stub gained the nastier failure it could not previously represent — gcloud
answering **0 while the box stays up** — which is the entire reason to read the
state back. **4 of 5** of those tests fail against the previous `stop`.

## 17 · The gate's environment was chosen by GitHub — ₹0

**Unplanned.** Item 16's own green run carried two annotations, and reading
them is the whole item.

Five actions target **Node 20**, which is deprecated, and the runner has been
force-running them on Node 24. And `ubuntu-latest` migrates from Ubuntu 24.04
to **26.04 gradually between 2026-10-19 and 2026-11-19**
(`actions/runner-images#14748`).

Gradual is worse than dated. For a month the same commit can pass or fail
depending on which image it drew — and a gate that is *sometimes* red teaches
people that red means nothing. This repository has already paid that bill:
thirty red runs went unread for seventeen days.

Items 12 and 13 were both the environment deciding whether the check ran — an
optional dependency deciding whether the code type-checked, then BSD-only tar
flags meaning the harness could only pass on a Mac. This is the third
instance, and the only one **announced in advance**. Announced on every single
run, in fact, and read by nobody: **item 11's defect in the repository's own
check** — a result produced and never compared.

So the answer is not to read the annotations harder. `.github/dependabot.yml`
turns the next deprecation into a pull request. The runner and all five actions
are pinned to versions checked against their release notes (setup-node v6
limited automatic caching to npm, which is what we ask for; setup-python v7
removed `pip-install`, which we never set; checkout v7 blocks fork checkouts
for `pull_request_target` and `workflow_run`, neither of which we trigger on).

### Probing the image first paid for itself immediately

Pinning to an untested image only moves the surprise, so the whole workflow was
run on `ubuntu-26.04` before anything was pinned. It came back **2 failed, 664
passed**.

`_run_deploy` never set `FAKE_BOX`, so the ssh stub's first line was `cd ""`.
**bash 5.2 accepts that as a no-op; bash 5.3 rejects it as a null directory.**
Ubuntu 24.04 ships 5.2.21 and 26.04 ships 5.3.9 — confirmed in a container, not
assumed. The stub therefore answered every command on this laptop and on 24.04,
and exited before reading its first argument on the image CI is migrating to.

**Two tests going red is how it was found. The four that stayed green are the
finding.** With the stub dead, the two that assert *an unreachable box is parked
rather than left billing* — item 16's clause, the ₹703 protection, the most
expensive guarantee in this repository — **passed with `FAKE_SSH_DEAD` forced to
0**, meaning ssh explicitly alive. Proven by running exactly that. They were
insensitive to the one variable they are built on.

Answering nothing is indistinguishable from answering correctly to any test
whose expectation is a failure. That is the narrow form of the item 13 lesson,
and it is the seventh time this milestone a stub was half the defect: **a stub
that cannot start must say so.** It uses `:?` now, and a pin checks that
`FAKE_SSH_DEAD` still decides the outcome.

**4 of 15** tests in that area fail against the pre-fix harness under the
bash 5.3 condition, including the two new pins that exist for it.

### Second clause: CI ran the gate's programs, not the gate's commands

`TestCiRunsWhatTheGateRuns` (item 12) asks whether the string `mypy` appears in
the workflow. So a CI step narrowed from `mypy mcp_server tools eval tests` to
`mypy mcp_server` keeps the green tick while type-checking **one tree of four**
— checked against the real pin, which passes it.

Same program, different claim. **The arguments are the claim.** Item 14 is this
shape one level out: `--check` guarded `--store` and `--golden` but not
`--modes`, so grading one retrieval mode of four printed *no regressions*.

CI may run *more* of a gate command — it runs `npm ci && npm run build`, and the
`cd frontend` is a `working-directory:` — and may not run less. Both plants
caught: narrowing mypy to one tree, and dropping `-q` from pytest. The item 12
pin passes the first of those, which is the proof the new clause is not a
duplicate of it.

## 18 · The one header whose other end nobody reads — ₹0

**Unplanned.** Three headers cross the boundary between four separate
programs — Caddy, FastAPI, the browser, and `trip.sh` — and each writes the
name by hand. Two of them, `X-Sextant-User` and `X-Sextant-Proxy-Auth`, were
pinned against `deploy/Caddyfile` the day they shipped, and
`tests/test_deploy_config.py` opens by saying exactly why:

> Rename `USER_HEADER` in Python and every Python test still passes; the proxy
> then forwards a header nobody reads, every authenticated user falls back to
> their browser id, and the only symptom is that uploads land in the wrong
> namespace.

The third header was left out of that file. `X-Sextant-Client`'s other end is
TypeScript, not a Caddyfile, so nothing in a Python suite reads it — and for
three versions it existed in **exactly two places in the whole repository**,
`mcp_server/identity.py` and `frontend/src/lib/api.ts`, with no test naming it
at all.

**Measured, not argued:** renaming `CLIENT_HEADER` to `X-Sextant-Browser`
leaves **143 tests green** across `test_api.py`, `test_observability.py` and
`test_scope.py` — every test that exercises the header takes the constant, so
all of them move with it. `tsc -b` and `vite build` do not know the server
exists. The browser goes on sending a header nobody reads, every request is
answered as `shared`, and that is not a feature going quiet: it is the return
of the defect **0.8.2** shipped against — two people behind one password
storing `notes.pdf` over each other, and an unnamespaced id that `shared` is
allowed to overwrite.

**A seam is pinned on the side you can read, which is the side that is not the
problem.** The two headers whose far end was a file the gate already parsed got
pinned immediately; the one whose far end needed reading a `.ts` file as text
waited three versions. The language of the far end decided whether the seam was
checked, which is items 12 and 13 again — the environment deciding whether the
check ran — and this is the fourth instance.

### Second half: a convention held up by a comment

`sent()` in `api.ts` carries this comment:

> One helper, used everywhere, so a call site added later does not have to
> remember.

Nothing made that true. A function added later that builds its own `headers`
object compiles, type-checks, lints and builds, and is answered as `shared` —
which since 0.8.4 means that call stops seeing the browser's own uploads, and
on `/upload` means the file lands where anyone can overwrite it. This is item
4's defect one side of the wire over: every M21 scoping defect was a *route*,
and nothing pinned the route list until something did.

`TestTheBrowserSendsWhatTheAppReads` pins four things: the name
`identity.py` declares appears in `api.ts`; it appears in **one** place, so a
rename has one site; every `fetch` in that file routes its headers through
`sent()`; and **no other frontend file calls `fetch` at all**. The scan is a
helper over source text with its own synthetic plant, the same shape as
`TestTheRepoHoldsNoRealAddresses`, plus an anti-vacuity test — it returns
nothing for a file with no `fetch` in it, so the call-site count is checked
too.

All three plants caught, each on its own assertion: the Python rename (2 of 7),
a call site that drops `sent()` (1 of 7), and a request built in a second file
(1 of 7).

### Third half: a linter configured, committed, and never run

`frontend/package.json` has defined `npm run lint` since the UI port, and
`.oxlintrc.json` is committed with a rules block someone chose. Neither the
gate nor the workflow has ever called it. The lint result for this tree was
not green — it was **unknown**, and nobody could have said whether it was zero
problems or a hundred.

It could not be established on this laptop: npm 10.5.0 does not install
oxlint's platform binding even though the lockfile carries it with matching
`os`/`cpu`, and oxlint's own error names npm/cli#4828. `npm ci`,
`npm install --save-optional` and a clean reinstall all leave
`node_modules/@oxlint` absent. So it was probed on CI, the same way the
`ubuntu-26.04` image was: **11 warnings, 0 errors, 47 files, 116 rules.**

**None of the eleven was a defect**, and one was the rule being right:

| What | Count | Decision |
| --- | --- | --- |
| shadcn files exporting a `cva` variants object beside the component | 6 | rule off for `src/components/ui/**` — vendored code, and the rule is about Vite's fast-refresh granularity |
| mount-time reads of `window` and of the server | 2 | in-line, with the reason: render cannot read either |
| a deliberately by-value dependency array | 2 | in-line: depending on `domain` would recompute every render and the memo would do nothing |
| `SERIES` exported from `sweep-chart.tsx` and imported by `lab.tsx` | 1 | **fixed** — moved to `components/lab/series.ts` |

So the finding is not a pile of unfixed problems. It is that **oxlint exits 0
on eleven warnings**: adding the step as it stood would have bought a green
tick that cannot go red, which is this milestone's subject from item 5 onward.
`denyWarnings` is in the committed config rather than the CI command, so a
hand run makes the same claim CI does.

Turning `only-export-components` off globally would have been the cheap way to
zero, and would have thrown away the one warning that was right. The override
is scoped to the vendored tree and a test pins that scope.

The pin also found three suppressions that were already there — three
`eslint-disable-next-line react-hooks/exhaustive-deps` in `App.tsx` with **no
reason given**. All three turned out to be deliberate and all three now say
why, because a silenced rule without a reason is a silence, not a decision.
`reportUnusedDisableDirectives` closes the loop: a suppression that stops being
needed is reported rather than left as a comment, which is item 11 applied to
the suppressions themselves.

#### What the step cost to make honest, and what that bought

Three runs, because the first two were red and both were informative.

**Run 1 — 14 warnings.** The scoped override worked: all six
`only-export-components` warnings were gone and `SERIES` moving closed the
seventh. But every one of the six disable directives came back as *Unused
oxlint-disable directive (no problems were reported)* with the underlying
warning still raised. A **multi-line reason breaks
`-disable-next-line`** — the "next line" was the second line of my own
comment, not the code.

**Run 2 — 7 warnings.** `set-state-in-effect` was suppressed; the dependency
rule was not. The remaining four said where: **oxlint reports a hook-dependency
problem at the closing `}, [deps])` line**, so the directive goes there and not
above the `useEffect`/`useMemo` call. sweep-chart had one in each position and
only the lower one had worked, which is the whole answer printed in the output.

That also corrects run 1's reading. The three `exhaustive-deps` directives
already in `App.tsx` were **not** dead — the probe's eleven warnings never
included those three sites, because they were suppressing exactly as intended.
What was wrong with them was that they gave no reason, and what broke them was
my own multi-line comment.

**Run 3 — 0 warnings, 0 errors, 48 files.**

Two things were bought that a green tick would not have been. A linter whose
result is now known rather than assumed, and a placement rule established from
the tool's own output twice over rather than from either project's convention —
which is the only reason a suppression in this tree means anything.

## 19 · The environment the subprocess does not get — ₹0

Unplanned. Items 12, 13, 17 and 18 were all the same sentence: the environment
decided whether the check ran. This one is the environment deciding whether the
*code* ran, and it had been doing so on the box since 2026-09-28.

The knowledge base is a separate process on purpose. `mcp_host.py` says why, in
a comment that predates all of this: importing `vector_search` into the agent
server "would pull chromadb and torch into the agent server's import graph, and
keeping the knowledge base out of this process is the whole point of speaking
to it over a protocol." So the embedder and the cross-encoder — 180 MB of
weights — load in the child, not in the server that holds the HTTP routes.

MCP's stdio client does not hand that child the parent's environment. It builds

```python
env=get_default_environment() | (server.env or {})
```

and on POSIX `get_default_environment()` is `HOME`, `LOGNAME`, `PATH`, `SHELL`,
`TERM`, `USER`. Nothing else. So `_FORWARDED_ENV` in `mcp_host.py` is not a
convenience list — it is the entire set of things the knowledge base knows
about the machine it is running on.

It held seven names, all `SEXTANT_*` retrieval knobs. The Dockerfile sets two
more, and says exactly why:

```dockerfile
# Bake the models into the image. Without this the first query after
# `docker compose up` silently downloads ~180 MB and appears to hang.
# ...
# HF_HUB_OFFLINE stops the runtime from phoning home to check for newer
# weights on every start -- the image is the pin.
ENV HF_HOME=/opt/models HF_HUB_OFFLINE=1
```

Both are set on the agent server. Neither crossed. Measured by assembling the
child's environment the way the client does:

| | resolves |
| --- | --- |
| the image's intent (`HF_HOME=/opt/models`) | `/opt/models/hub` |
| what the subprocess actually got | `/home/app/.cache/huggingface/hub` |

The baked cache the build pays for has never been read. Every `docker compose
up` downloads the weights again, into a container-local path that dies with the
container, and the offline pin meant to stop the runtime checking the hub for
newer weights on every start was never in force. The compose healthcheck's own
comment — "the embedder loads on first use, so this can take a minute on a cold
boot" — is consistent with a download rather than a load, and had been read as
normal for six weeks.

### The pin that existed, and why it could not see this

There was a guard. Its comment is the right sentence:

```python
def test_every_retrieval_knob_crosses_the_process_boundary(self, monkeypatch):
    # A knob the KB reads but the host does not forward is a silent no-op
    # in the app while working in every test and CLI.
```

It named three of the seven. And the name of the test is the specification:
`every_retrieval_knob`. A model cache path is not a retrieval knob, so it was
never in scope, and nothing was broken by leaving it out.

`CLAUDE.md` had the same blind spot in the same words — "new `SEXTANT_*` knobs
the KB needs must be added to `_FORWARDED_ENV`" — and that rule was written
after a different forwarding bug. The rule, the test name and the list all
agreed with each other and all excluded the variable that mattered.

**A pin named after the kind of thing you were thinking about cannot grow.**
The next thing to cross that boundary will not be of that kind, which is
precisely why nobody will notice.

### What replaced it

Three declared lists instead of one remembered one:

| | what it holds |
| --- | --- |
| `_FORWARDED_SETTINGS` | ours, read through `tools.settings`, so `SEXTANT_`-prefixed |
| `_FORWARDED_VERBATIM` | other people's, read by libraries only the child imports |
| `_NOT_FORWARDED` | set or read but deliberately not crossing, **with the reason** |

The six verbatim names are each cited to the line of the installed library that
reads them — `huggingface_hub/constants.py` for `HF_HOME`, `HF_HUB_CACHE`,
`XDG_CACHE_HOME`, `HF_HUB_OFFLINE` and `TRANSFORMERS_OFFLINE`;
`sentence_transformers/base/model.py` for `SENTENCE_TRANSFORMERS_HOME` — and a
test re-reads those two files, so a name nobody reads cannot sit in the list
looking careful.

`TestEveryVariableTheSubprocessNeedsCrosses` then scans **both sides of the
seam**, which is item 18's lesson applied to a boundary where both sides happen
to be readable:

- every variable named by code under `tools/` (the subprocess's own half —
  `python -m tools.vector_db.server` imports from nowhere else), and
- every variable the `Dockerfile` or the compose `api` service sets.

Anything in neither list fails the gate. The compose scan is narrowed to the
`api:` block on purpose: scanning the file whole dragged in the frontend's
`VITE_SERVER_URL` on the first run, and an exemption table that collects other
services' variables is a table nobody reads.

And, borrowed from oxlint's `reportUnusedDisableDirectives` in item 18: an
exemption whose variable no scan still finds **fails**. The four entries today
are `SEXTANT_MODEL` and `GEMINI_API_KEY` (read by `summaries.py`, whose
`summarise()` only runs in `sextant-ingest` in the operator's shell — the child
imports that module for its chunk-id helpers and never calls it),
`SEXTANT_LOG_FORMAT` (the subprocess calls `logging.basicConfig` itself) and
`SEXTANT_ALLOWED_ORIGINS` (CORS, two processes up).

### Two assertions that were being decided by the shell

The three existing tests compare the **whole** forwarded dict with `==`. They
passed here only because none of the six cache variables happens to be set on
this laptop — and `HF_HOME` is set in our own production image, so the tests
would have failed inside the very container they describe. They clear the
declared list first now. Fifth instance of the recurring subject, found while
fixing the fourth.

`test_every_retrieval_knob_crosses_the_process_boundary` is driven off
`_FORWARDED_SETTINGS`, so its name is now true.

### Plants

Seven, each failing on its own assertion and nothing else:

| plant | fails |
| --- | --- |
| a new `settings.getenv` under `tools/` | `…reads_is_decided` |
| a new `ENV` in the `Dockerfile` | `…deploy_sets_is_decided` |
| `HF_HOME` removed from the forwarded list | `…deploy_sets_is_decided` + both regression tests |
| an exemption for a variable nothing reads | `…stopped_being_needed_is_reported` |
| a name both forwarded and exempt | `…both_forwarded_and_exempt` |
| a verbatim name no loader reads | `…the_ones_the_loader_reads` |
| the reads scan's regex stops matching | `…scans_are_looking_at_something` |

The last one is the anti-vacuity check earning its place: both scan tests pass
against an empty set, so a regex that quietly stops matching is how this check
would have died.

### What this does not prove

That the box is now faster to start. The fix is verified at the seam and in the
resolver, not on the VM — the next trip is where `/health` answering before the
start period expires would show it. Worth watching rather than claiming.
