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

## 20 · The report with a gap — ₹0

Unplanned. `CLAUDE.md` names one command as the answer to "what is billing":
`deploy/deploy.sh HOST status`. Item 16 fixed `start`, item 5 fixed the park.
Nothing had ever read `status`.

Measured against every state the compute API documents an instance can be in:

| state | what `status` said | bills? |
| --- | --- | --- |
| `RUNNING` | `billing: VM ~₹5.6/hour + disks + IP` | yes |
| `TERMINATED` | `billing: disks + reserved IP only (VM meter off)` | no |
| `STOPPING` | *nothing* | **yes** |
| `SUSPENDING` | *nothing* | **yes** |
| `SUSPENDED` | *nothing* | **yes** (preserved memory) |
| `STAGING` | *nothing* | **yes** |
| `REPAIRING` | *nothing* | **yes** |
| `PROVISIONING` | *nothing* | **yes** |

All of them exit 0. The billing line was a `case` with two arms and no default,
so six states printed the instance line and stopped.

`STOPPING` is the one that matters. It is what a person sees when a stop has
been issued and has not finished — the moment right after a trip, which is
exactly when somebody checks — and silence there is indistinguishable from the
parked case. **A `case` with no default is a list of the states somebody
thought of.**

### The worse half: a failed read looked like a parked box

`vm_status` is a `gcloud describe`. When it fails — wrong project, expired
credentials, an API error — the `read` gets an empty line, and `status` printed

```
agenticrag (, us-central1-a):
```

and exited **0**. The ₹703 incident was a box nobody checked. This is the check
answering nothing and reporting success, which is worse, because it looks like
an answer. It exits 1 now, on stderr, naming the `describe` to run by hand and
saying to assume the meter is on until it answers.

### Third clause: the stub could not produce what the command prints

`deploy.sh` asks for `value(status,machineType.basename(),natIP)` — three
tab-separated fields. `trip.sh` asks for `value(status)` — one. The stub
ignored `--format` and answered one field to both, so the machine type and the
address in `status`'s own output line were produced by nothing, and the
`(, us-central1-a)` visible in every test's output *was* the stub's gap being
printed.

It honours the format now, and emits nothing at all for a blank state, which is
what the real thing does. **Third time in this harness**, after the curl stub's
`-o`/`-w` in item 8 and the ssh stub's `cd ""` in item 17.

### Plants

| plant | fails |
| --- | --- |
| the default arm removed (`bash -n` still passes) | `…assumed_to_be_billing` + `…keeps_a_default` |
| `STOPPING` loses its named arm | `…states_the_script_knows` only |
| an unreadable state exits 0 again | `…not_a_parked_box` |
| the stub forgets the extra fields | `…machine_type_and_the_address` |

Two things worth recording about these.

The first attempt at plant 1 **did not apply** — a quoting error meant the
file was unchanged and all seven tests passed. Seven green tests against an
unplanted plant is the item-14 lesson arriving again: a plant must be verified
to have landed before its result means anything. The second attempt also
over-applied, breaking the script so six tests failed on syntax rather than on
the defect. `bash -n` is in the loop now.

Plant 2 is the interesting one: removing `STOPPING`'s named arm does **not**
break the behaviour test, because the default arm correctly catches it and says
to assume the meter is on. Only the drift test notices. That is the right
outcome — precision was lost, safety was not — and it is why both tests exist.

### Considered and left

`start` does not detect "already running" when `describe` fails, so it will
issue a start against a box that may already be up. Left alone: starting is
what was asked for, the cost line is printed and `--yes` is required before
anything happens, and the real `gcloud start` is idempotent. Noted rather than
silently judged out of scope.

---

## 21 · The check nobody had run — ₹0

`deploy/deploy.sh HOST preflight` is the only thing between a misconfigured box
and twenty minutes of building torch on two vCPUs. Its own comment says so:

> Check the box BEFORE spending twenty minutes building torch. Every one of
> these has a failure mode that only shows up at the very end.

Nothing had ever executed it. Not in the suite, not in the offline trip
harness, not once — and it could not be, because it calls GNU `stat -c`,
`getent hosts` and `docker`, and tests `/data/chroma`, none of which exist on
the laptop that wrote it. Items 5, 16 and 20 fixed `start`, the park and
`status`; `preflight` was the command in this file that nothing had measured.

Run for the first time, against a fixture box, it reports thirteen checks.

### First clause: none of them is about `SEXTANT_PROXY_SECRET`

Five places in this repository call it required:

| where | what it says |
| --- | --- |
| `deploy/env.example` | "**REQUIRED** from the first deploy that carries the `header_up` lines … the app refuses every request with a 403 that says so. Set it before building this tree on the box." |
| `deploy/README.md` | one of the **two** failures that stop the trip before the build |
| `CLAUDE.md` | a deploy prerequisite |
| `deploy/trip.sh:260` | a hard stop, since 2026-10-06 |
| `planning/NEXT.md` | step 1 of the open row, before anything else |

Caddy has no conditionals. `header_up X-Sextant-User {http.auth.user.id}` goes
out on every proxied request whether or not the app can verify where it came
from, so with the secret empty `identity.resolve()` raises `ForgedIdentity`
and the box answers **403 to everything** — not some requests, not only the
authenticated ones. `deploy.sh up` runs the preflight, prints
`-- preflight passed`, ships the tree, builds for twenty minutes, and then the
box serves nothing.

### Second clause: the bcrypt check reads one slot of three

The `.env` reader was one hand-written `case` alternation:

```bash
case "$key" in SITE_ADDRESS|PUBLIC_URL|BASIC_AUTH_USER|BASIC_AUTH_HASH|GEMINI_API_KEY|ACME_EMAIL|APP_UID)
```

Seven names. The Caddyfile has interpolated **nine** since 0.8.3 — three
`basic_auth` slots and the proxy secret — and compose two more. A variable this
reader skips is a variable no check below can ask about, which is why the
failure the script's own comment puts *first* ("a mangled hash rejects every
password … Cheap to check, expensive to discover") was only ever checked for
slot 1.

The worse half is a slot filled on one side. `env.example` records what Caddy
does with it: "fill a user without its hash and Caddy refuses to start, which
is the right way round." Refuses to *start* — so the box serves nothing at all,
and it refuses after the build. And this is not a hypothetical slot: the open
row's own criterion needs slot 2, because `trip.sh` step 7 uploads as two gate
users to prove the isolation.

Same shape as item 19, one directory over. **A list of variables that mirrors
another file by hand falls behind it silently.**

### The fix

| | |
| --- | --- |
| the key list | every name `deploy/Caddyfile` or `docker-compose.prod.yml` interpolates, held there by `TestEveryDeployTimeVariableReachesThePreflight` — add a `{$VAR}` and the gate fails until the preflight knows about it |
| the gate | checked slot by slot: both halves empty is reported unused (that is how `env.example` ships, and a check that fails on the documented default is one people learn to ignore), one half filled names the missing half and says Caddy will refuse to start, both filled runs the bcrypt shape check — which is a function now, because it used to be run against one slot |
| the secret | present or a FAIL, with `trip.sh`'s remedy: generated on the box so the value never crosses a laptop |
| `DATA_DIR` | an override that exists only so the script can be executed off the VM. Defaults to `/data/chroma`; the box never passes it. Same arrangement `VM_SSH_TRIES` already has |
| no value printed | the item-5 invariant, now that this script reads a secret and three hashes. Lengths are reported; the secret, the hashes, the key and the user names are not — pinned |

### The harness

Three new stubs, because without them no assertion about this script is worth
more than a comment: GNU `stat -c` (`%a` and `%u`, and a loud exit for any
other format), `getent hosts` (glibc, absent from macOS entirely), and
`docker`/`docker compose version`. `_CURL_STUB` gained the address service the
preflight asks — without it the call fell through to the gate logic and
answered `401`, which the DNS compare then read as "this VM is 401". And
`_SSH_STUB` learned the one call shape that arrives on **stdin**:
`ssh host VAR=v 'bash -s'`. Real ssh joins everything after the host into one
command line, so the env assignments reach the script; the stub's convention of
reading only the last argument would have dropped `APP_DIR` and the preflight
would have `cd`-ed to `"$HOME/"`.

### Plants

| plant | fails |
| --- | --- |
| the secret leaves the key list | the Caddyfile scan, **and** the three good-box tests — an uncaptured variable reads as empty |
| the secret's *check* deleted, the capture kept | the three secret tests only; **the scan passes** |
| the slot loop collapsed to slot 1 | all four slot tests |
| the bcrypt length floor removed | `…truncated_hash_in_a_later_slot` only, the shape check still catches a mangled one |
| `DATA_DIR`'s in-script default removed | **nothing** — see below |

Plant 2 is the one worth keeping. A static pin on a list and a test of what the
list is *used for* are two different claims, and the scan cannot see a name
that is read and then ignored. Both halves stay.

Plant 5 found a line of my own: the `DATA_DIR="${DATA_DIR:-/data/chroma}"`
inside the heredoc was unreachable, because `deploy.sh` always passes the
assignment. Removed. One declaration, and `set -u` makes a future edit that
drops it loud rather than silently defaulting.

### Considered and left

`deploy.sh HOST down` stops the containers and says nothing about the VM meter,
which keeps running at ~₹5.6/hour. The usage header is honest ("stop the stack
(containers only)") but the command prints no epilogue — it is an `exec ssh`,
so there is nowhere after it to print one. Left for a separate item rather than
restructured here: the fix is small but it is about `down`, not about the
preflight, and item 20's finding came precisely from asking which commands
nothing had measured. Shipped 2026-10-23 as § 22 below.

### What CI found that the local gate could not

The local gate was 729 passed, mypy clean, ruff clean, frontend built. CI
failed, and both failures were real.

**The `stat` stub was written with BSD flags.** It delegated to
`/usr/bin/stat -f '%OLp'`. On Linux `-f` means *file system* status and `%OLp`
is read as a filename, so the stub answered an entire tmpfs report and the
preflight printed it where the permission bits go:

```
FAIL   .env is chmod   File: ".env"
    ID: 65dc5fc28167b933 Namelen: 255     Type: tmpfs
Block Size: 4096       Fundamental block size: 4096
...
, want 600
```

Item 13 was BSD-only `tar` flags meaning the offline trip harness only ever
ran on a Mac. This is the same defect **inside the stub whose entire job is to
stand in for the GNU tool** — written, in the same commit, as part of making a
Linux-only script runnable. It is now `python3`, which is on both platforms and
has no flags to get wrong, and its output was checked against the platform's
own `stat` (`600 / 502` either way).

**Fourteen of the seventeen tests were green for the wrong reason.** With the
stub broken every check FAILed, so every test that asserts a non-zero exit
passed. Only the three asserting a *pass* noticed — which is the whole of the
margin that caught this. The stubs now print `STUB FAULT` and exit 95 on
anything they cannot represent, and `_run_preflight` asserts that string is
absent before it returns anything. Verified by re-breaking the stub: 13 of 13
fail instead of 3.

**CI's second failure was a lie about the frontend.** `if: always()` sat on
`Frontend build` to keep it independent of the lint, per its own comment. It
reached further than that: the failing `Unit tests` step skipped
`Frontend install`, the build ran anyway without `node_modules`, and CI
reported `Frontend build -> failure` with `tsc: not found` for a tree whose
frontend was fine. Two failures, one cause, and the second pointing at the
wrong half of the repository.

The frontend half of the gate does not depend on the Python half, and a gate
command skipped because an unrelated step failed is a gate command that did
not run (item 12). Every step from `setup-node` down now carries
`if: ${{ !cancelled() }}` — not `always()`, which would also burn minutes on a
run somebody stopped on purpose. **A step's `if:` must not reach past its own
prerequisite.**

## 22 · The command that could not speak — ₹0

Queued at the end of item 21 and left there deliberately: the finding was
about `down`, not about the preflight, and folding it in would have hidden
it inside a commit about something else.

### The arm

```bash
down)
  exec ssh -t "$REMOTE" "cd $APP_DIR && $COMPOSE down"
  ;;
```

`exec` replaces this shell with ssh. Nothing can run after it — not a
warning, not a reminder, not a question. So the one command in this script
whose name reads like *I am finished paying for this* was **structurally
incapable of saying anything** once the containers were gone.

Run against a RUNNING box, before the fix:

```
Container agenticrag-api-1  Removed
Container agenticrag-caddy-1  Removed
rc=0
```

The e2-standard-2 behind those two lines goes on charging ~₹5.6/hour —
₹135/day, the same as one serving traffic. The usage header was honest
("containers only") and the README said "stop the containers", but the
place a person actually looks is the output of the command they just ran,
and there the number was absent.

This is the 2026-09-28 ₹703 failure with the believing moved one level up.
That box was left running while waiting on a human. This one is left
running by a script that reported it shut down.

### Where it sits among the other two

| Command | Stops serving | Stops paying | Says which |
| --- | --- | --- | --- |
| `down` | yes | **no** | now |
| `stop` | (already) | yes | yes, since item 20 |
| `trip.sh` | yes | yes, in an `EXIT` trap | yes, verified since item 5 |

`down` deliberately still does not park the box. `down` stops serving and
`stop` stops paying; a `down` that parked would take the next deploy's
restart away from whoever typed it, and `trip.sh` already exists for the
case where the box should go away at the end. The fix is to the sentence,
not to the verb.

### The fix

| Was | Is | Why |
| --- | --- | --- |
| `exec ssh ...` | `ssh ... \|\| rc=$?`, then the epilogue, then `exit "$rc"` | `exec` preserved the exit status for free, which is its only merit here; that is now done by hand |
| nothing after the containers | `meter_epilogue` reads the instance state and names what is still billing | the number belongs where the person is looking |
| `vm_target` `exit 2` on an unresolvable host | `return 2`, callers `\|\| exit 2` | **an epilogue must never overrule the command it reports on** — a `down` that worked must not become exit 2 because gcloud is absent |
| `status` held the eight-state billing table | `billing_line` holds it; `status` and both epilogue arms call it | a second hand-written table of the same states is `_FORWARDED_ENV` and the preflight key list a third time |

Three outcomes, the same shape as `ssh_door`:

```
>> containers stopped, but the VM is NOT: agenticrag is RUNNING.
   billing: VM ~INR 5.6 (~USD 0.067)/hour + disks + IP
>>   park it:  deploy/deploy.sh <host> stop

>> containers stopped, and the VM is TERMINATED.
   billing: disks + reserved IP only (VM meter off)

>> containers stopped. This does NOT stop the VM, and its state
>>   could not be read -- assume it is billing ~INR 5.6 per hour.
>>   check:  deploy/deploy.sh <host> status
>>   park:   deploy/deploy.sh <host> stop
```

The third is a machine with no gcloud, no credentials, or a plain ssh
alias. It is loud, it is wrong in the safe direction, and it exits 0.

It is reached two ways, pinned separately. An unresolvable host never gets as
far as reading a state. A `describe` that *fails* — wrong project, expired
credentials — returns an empty one, which is item 20's worse half reached from
here, and is also where `set -euo pipefail` would abort the script before the
warning printed if the read were written any other way.

### The harness

`_SSH_STUB` gained a `*"prod.yml down"*` arm that prints what compose
prints and takes its exit status from `FAKE_DOWN_RC` — a stub that could
only succeed would make "the exit status survives the epilogue" an
assertion that cannot fail. `_run_deploy` gained `host=` and
`resolvable=False`, which removes `VM_INSTANCE`/`VM_ZONE`/`VM_PROJECT` so a
test can present the case the script cannot answer, and `parents=True` on
the bin directory so one test can run the script twice under one
`tmp_path`.

### Plants

| # | Plant | Fails |
| --- | --- | --- |
| 1 | `exec ssh` restored — the original defect | 12 of 15 |
| 2 | the unreadable-state arm emptied | the loud-and-still-zero test, on the message |
| 3 | `vm_target` back to `exit 2` | the same test, on `code == 0` |
| 4 | a billing line copied back into the epilogue | the count, and the 5 states that then disagree |
| 5 | `\|\| true` instead of `\|\| rc=$?` | the exit-status test |
| 6 | `status` stops calling the shared table and inlines a line | the new `test_status_still_calls_it`, and 5 states |
| 7 | the epilogue made to abort on a blank state (`set -e`) | the describe-answers-nothing test |

Plant 4 is the one worth keeping: the static count and the per-state
comparison are two different claims. Pasting a copy raises the count; a
copy that happens to agree on `RUNNING` passes the behavioural test for
`RUNNING` and fails it for the five states it got wrong.

### What the existing pins caught

Item 20's `TestStatusSaysWhatIsBilling` read the arms out of the `status)`
block by text. Moving them into `billing_line` failed two of its tests on the
first full run — the pin working exactly as intended: the decision is still
being read, now at its one address. It gained a second half at the same time,
`test_status_still_calls_it`, because a shape pinned on a function nothing has
to call is a shape pinned on nothing.

### Considered and left

`logs` is also an `exec ssh`, and correctly so: it is a tail the operator
Ctrl-Cs, it makes no claim about having stopped anything, and an epilogue
after an interrupted tail would be noise.

## 23 · The script that starts nothing and says it did — ₹0

Item 22 left `deploy.sh` measured for every command but `logs`. The question
that found items 20, 21 and 22 — *which claim has nothing ever checked?* —
pointed next at the only shell script in the repository that is not under
`deploy/`: `start_all_services.sh`, which `README.md` presents as **the** way
to run this project.

Nothing had ever executed it. Not the suite, not CI.

### First clause — the banner is unconditional

```bash
"$PY" -m uvicorn mcp_server.main:app --host 0.0.0.0 --port 8000 &
SERVER_PID=$!
(cd frontend && npm run dev) &
FRONTEND_PID=$!
...
cat <<INFO
  Frontend    http://localhost:3000
  Agent API   http://localhost:8000
  ...
  Ctrl+C to stop.
INFO
wait
```

Run with both children failing on their first line:

```
Starting agent server on :8000 ...
Starting frontend on :3000 ...

  Frontend    http://localhost:3000
  Agent API   http://localhost:8000
  API docs    http://localhost:8000/docs
  Tool list   http://localhost:8000/tools

  Ctrl+C to stop.

ModuleNotFoundError: No module named 'uvicorn'
npm ERR! Missing script: dev
rc=0
```

Four URLs, an invitation to press Ctrl+C, and **exit 0**, with the two real
reasons printed *after* the banner where they read as noise. `deploy.sh start`
printing `>> up at <ip>` regardless (item 16) and `trip.sh` ending
`agenticrag is RUNNING` with exit 0 (item 5), in the script that is somebody's
first contact with the project.

It waits on `/health` now — the question the app ships an endpoint to answer —
names which half failed, stops the other rather than leaving it half-running,
and exits 1.

### Second clause — `--host 0.0.0.0`

There is no authentication in front of this process. The gate is Caddy's
`basic_auth`, and Caddy exists only on the box. Confirmed from the app's own
startup log:

```
identity: no SEXTANT_PROXY_SECRET set, so X-Sextant-User is refused and
uploads are namespaced by X-Sextant-Client (or 'shared')
```

Every caller is `shared`. Since 0.8.5 `shared` owns the unnamespaced,
CLI-ingested corpus **and may write it**. So a wide bind meant anyone who
could reach the port could read the corpus through `/query` — spending the
Gemini key against a ₹500/month prepay — and replace a document through
`/ingest`. CORS does not help; it is not a browser that would do this.

`HOST` defaults to `127.0.0.1`. A wider bind is a decision and says what it
means. The loopback case prints nothing: a warning on the documented default
is one people learn to skip.

### What the fix got wrong, found by running the fix

| Defect | How it showed |
| --- | --- |
| the frontend liveness check was one `kill -0` immediately after the API came up — with a stubbed `curl` that is milliseconds, so a frontend exiting 400ms later was still alive when asked | the frontend-dead probe printed the banner and exited 0 — the defect being fixed, reintroduced by the fix |
| `cleanup` killed `$FRONTEND_PID`, the `( cd frontend && npm run dev )` **subshell**; npm and Vite under it survived | `pgrep` after a run found the grandchild still alive |

A check whose answer depends on how fast the step before it finished is not a
check: there is a settle loop now. And `set -m` plus `kill -- -$PID` kills the
job's process group, not just the shell that forked it.

### The harness, and a bystander it nearly killed

Four stubs: a live interpreter, a dead one, a live npm, a dead one, plus a
slow-dead npm written specifically for the race above. The `curl` stub's first
version answered 200 unconditionally, so `ready=1` for a server that had
already exited and the dead-server test reached the *frontend* branch instead
— the harness deciding the outcome, item 21's lesson one more time. The live
interpreter touches a marker file now and `curl` answers only if it exists, so
the stub can fail; the happy-path test proves it can still succeed, which is
what pins it on both sides.

The orphan check first grepped for `sleep 30`, and its cleanup `pkill`ed the
same pattern — which would have matched, and killed, any unrelated `sleep 30`
belonging to whoever was running the tests. The stubs rename themselves with
`exec -a` to a sentinel that belongs to this suite.

### Plants

| # | Plant | Fails |
| --- | --- | --- |
| 1 | the original script, whole | 8 of 10 |
| 2 | `HOST` default back to `0.0.0.0` | the static scan and the quiet-on-loopback test |
| 3 | the `/health` wait removed | dead-server and never-answers |
| 4 | the settle removed | both frontend-death tests |
| 5 | `cleanup` kills the pid, not the group | the orphan fixture, in teardown |
| 6 | the `curl` stub made unable to fail | the dead-server test |

Plant 2 needed the scan to strip comments first: the script explains the old
`--host 0.0.0.0` in prose, and a scan counting the explanation as the code
fails on the fix. The preflight's variable scan learned the same thing.

### Considered and left

The frontend is never probed over HTTP. Vite moves off 3000 when 3000 is busy
and its own output is the only authority on which port it took, so the script
checks that it is alive and says so, rather than printing a URL it cannot
stand behind.

## 24 · The verdict with no consequence — ₹0

Item 23 closed the last unchecked shell script. The same question — *which
claim has nothing ever checked?* — pointed next at the Python entry points.
Seven modules define a `main()`; exactly one of them, `eval/harness.py`, is
ever invoked by a test. Of the other six, one decides an architecture
question: `eval/tenancy.py`, which settled milestone 20 item 2 (one filtered
collection, or one per owner) and is the harness you re-run when the store
changes and the answer might flip.

Nothing had ever executed it. Four of its claims were false.

### First clause — it prints REJECTED and exits 0

```python
        payload = asyncio.run(run(args.store, args.mode, args.golden))
        print_table(payload)
        line = verdict(payload)          # "... -> A is ACCEPTED" | "... REJECTED"
        payload["verdict"] = line
        print(f"\n{line}")
```

`main()` then returns. Driven over a result far below the ceiling:

```
rule: at 3.1% share and 10x k, A recall@5 0.1000 vs B 0.9000, gap +0.8000
(tolerance 0.02) -> A is REJECTED

>> main() returned normally -- shell sees exit 0
```

This is item 14 — *the gate on retrieval quality could not fail* — in the one
eval harness item 14 did not reach. Item 14 gave `sextant-eval` a `--check`
that exits on regression. Here there is no flag to add: the verdict is
computed on every run and is the entire output of the command. It now decides
the exit code.

The decision and the sentence come back from **one** function, not two. A
caller that needed the decision and recovered it by matching `"ACCEPTED"` in
the printed line would be deciding twice, and the second decision would be a
string match on prose this file is free to reword — the same reason item 22
gave `deploy.sh` one `billing_line` that two commands call.

### Second clause — the name it tells you to type does not exist

```
$ ./.venv/bin/python -m eval.tenancy
usage: sextant-eval-tenancy [-h] --store STORE [--mode MODE] ...
sextant-eval-tenancy: error: the following arguments are required: --store

$ command -v sextant-eval-tenancy
NO -- command not found
```

`prog="sextant-eval-tenancy"` names a console script that is not in
`[project.scripts]` and never was. Every usage line and every argparse error
hands the operator a command that does not exist. The five other `prog=`
strings in the tree are all registered; this was the only one. `prog` is now
`python -m eval.tenancy`, which is what `learning/multi-corpus.md` has always
told people to run, and a test pins every `prog=` in the tree to either a
registered script or a module that exists.

### Third clause — the docstring promises a temporary directory

> The store is opened read-only; the subset collection is written to a
> temporary directory and deleted.

It is written **into the caller's store**. `subset()` builds a
`KnowledgeBase(collection_name=SUBSET_COLLECTION)` with no directory, and
that class resolves its path from `CHROMA_DIR` — which `main()` set to
`--store` four lines earlier. A run killed partway leaves the collection
behind in a store the reader was told would not be touched.
`learning/multi-corpus.md` had it right all along ("written beside it and
deleted. Run it against a copy if that matters"); the module docstring did
not.

What made the false claim look true was a `scratch = mkdtemp(...)` in
`main()` that **nothing was ever written to** — created and removed empty on
every run, with `shutil` and `tempfile` imported for it alone. It is gone,
and the docstring now describes the code.

### Fourth clause — found by the test for the first one

The pre-registered rule reads *"within 0.02"*, and `gap <= RULE_TOLERANCE`
does not implement it:

```
rule: at 3.1% share and 10x k, A recall@5 0.8800 vs B 0.9000, gap +0.0200
(tolerance 0.02) -> A is REJECTED
raw gap: 0.020000000000000018
```

A result exactly at the pre-registered tolerance was rejected, while the line
printed `gap +0.0200 (tolerance 0.02)` immediately beside the word — the
numbers and the verdict contradicting each other in one sentence. The gap is
now rounded to 4 places, the precision `pooled()` already rounds its metrics
to, and compared there. This was not on the list when the item started; the
boundary test written for the first clause failed and the reason was real.

### What was deliberately not done

`sextant-judge` also always exits 0. It is left alone: it has no
pre-registered rule to gate on, and inventing thresholds for faithfulness and
abstention is a design decision, not a defect fix. `eval.yml` records it as a
human pre-release step, which is a person reading numbers — a coherent
posture, unlike a command that computes a verdict and discards it.

### Harness faults in this item's own tests

The docstring scan matched nothing and passed on the very docstring it was
written to catch: the claim was wrapped as `temporary\ndirectory`, so the
substring was never present. Normalised before scanning — the same fault as
item 23's `0.0.0.0` scan matching a comment, in the opposite direction.

### Rules

- **A verdict with no consequence is not a verdict.** A command that computes
  a decision must spend it on the exit code, or it has only told whoever was
  reading.
- **The name a program prints must be a name you can type.** `prog=` is the
  one string every usage line and every error message hands the operator.
- **An unused variable can be load-bearing for a lie.** The empty `mkdtemp`
  was the only evidence for a docstring claim that was false.
- **A static scan must normalise before it matches.** A line break is not a
  difference in meaning, and a scan that thinks it is passes silently.

## 25 · The flag that reaches nobody — ₹0

Shipped 2026-10-24. Unplanned, from the same question as 20–24, pointed at the
one tree it had not been pointed at: **the frontend**. 767 Python tests and,
until this item, **not one test of the code a person actually reads the
numbers off**.

Five clauses.

### The flag the server computes and nobody reads

`/health` has carried `budget.durable` since item 15, which added it so that
"a figure nobody can date is not mistaken for the day's". It is false when the
spend ledger cannot be read or written — a full disk, or `/data/chroma` not
writable by `APP_UID`, which is the exact failure `trip.sh` step 5 tells the
operator to watch for. When it is false the tally restarts with the process
while Google's meter keeps counting, so `spent_usd` is this process's spend
and not the day's.

`SpendCard` printed that number under **Daily cap**, followed by
`· resets 00:00 UTC`, with `$1.5700 left` beside it. Three claims, all of them
the day's, from a figure the server had already said was not. The flag reached
`/health`, reached the browser, and stopped there: nothing in `frontend/`
mentions the word.

The headroom matters as much as the caption. `remaining_usd` is the cap minus
a spend figure that is too low, so it is an upper bound — hedging the caption
and leaving the amount unqualified would have been half a fix. `dayFigure()`
returns the caption, the prefix for the amount and the explanation together,
so there is one place that can be wrong about it, the same shape as item 24's
`rule_verdict` and item 22's `billing_line`.

### One diagnosis for two faults

`App` collapsed the health payload to `'ok' | 'degraded' | 'down'` and the
sidebar printed, for every `degraded`:

```
Degraded — no model key
```

Two different faults land in that state. The server reports them separately on
purpose — retrieval works without a key and answering does not — and a box
whose key is fine and whose MCP subprocess failed to start was told its key was
missing. `mcp_error`, the server's own sentence about the real fault, is in the
payload, is declared in the type, and was shown to no one.

`healthLine()` now returns the tone, the label and the detail together, and the
sidebar renders what it is given. The prop's type changed with it, so the
footer can no longer re-derive a cause from a tone.

### "Unreachable" about a server that answered

Found while reviewing the fix above, which would otherwise have shipped
breaking its own rule. `checkHealth` returned `Health | null`, and `null`
meant both *the fetch threw* and *the server answered 4xx/5xx*. The footer
printed `Server unreachable` for both, so a box returning 503 sent whoever
read it to the network instead of to the server's own log.

`checkHealth` now returns a `HealthProbe` that keeps the two apart, and the
refused case prints the status it was refused with.

### A type that said it mirrored the server and did not

`frontend/src/lib/types.ts` opens with *"Shapes the agent server sends. Mirrors
mcp_server/main.py + agent.py."* Nothing checked that, and it had drifted:
`durable`, `resets_in_seconds` and `share` are all sent and none was declared.
A field the type omits is a field no component can read without the compiler
objecting — which is *why* clause one survived sixteen days.

`tests/test_frontend_contract.py` asks the running endpoint what it sends and
the file what it declares. `timestamp` is exempted by name, in a comment, so
the exemption is a decision somebody can see rather than a silent subtraction.

### Nothing could have caught any of it

The frontend had **no test runner**. `npm run lint` and `npm run build` ran in
CI; nothing executed a line of it. Added vitest + jsdom +
`@testing-library/react`, a `test` script, `Frontend test` in CI, and `npm
test` in the gate — which `TestCiRunsTheGateWithTheSameArguments` immediately
failed on until CI was taught the new command, working exactly as item 12
intended.

22 frontend tests. **7 fail against the original**, all of them the ones that
read the rendered screen; the 15 in `health.test.ts` and `spend.test.ts` test
modules this item introduces, so they are new coverage rather than regression
proof, and are counted as such. 2 of the 3 Python contract tests fail against
the original `types.ts`.

### What was deliberately not done

`VITE_MOCK=1` builds a UI that answers from `mock.ts`. Deferred here as a
build-flag decision rather than a defect.

> **Corrected by item 27.** This paragraph originally said the mock build had
> "no mark on screen saying so". That was false and asserted without looking:
> `App.tsx` did render a `mock` badge. What is true is narrower and worse --
> the badge was `hidden sm:inline-flex`, so the one mark saying every figure
> on screen is invented was absent below 640px. Item 27 has it.

`npm run lint` cannot run on this laptop and never could: oxlint's native
binding declares `engines.node: ^20.19.0 || >=22.12.0`, this machine is on
20.12.2, and npm silently skips an optional dependency whose engine does not
match. The lockfile entry is byte-identical to the one on `main`, so this
predates the item. CI is on node 22 and runs it.

### Rules

- **A flag the server computes and the UI never reads is a flag that does not
  exist.** `durable` was correct, tested, deployed, and invisible for sixteen
  days.
- **Hedge every figure that comes off the number you hedged.** A careful
  caption beside an unqualified amount is a more convincing lie than either
  alone.
- **A message that names a cause must have been told which cause.** One label
  for two faults sends the reader to the wrong half of the system. Twice in
  one item: the degraded label, and then `null` for both *nothing answered*
  and *answered 503*, which the first fix would have shipped intact.
- **"Mirrors X" is a claim; a type that makes it needs a test.** The drift is
  silent by construction — the compiler enforces the type, and the type is the
  thing that is wrong.
- **An untested tree is where the untested bugs are.** The count was 767 to 0.

## 26 · The save that reports success — ₹0

Shipped 2026-10-24, on the runner item 25 added. Four clauses, three of them
in `store.ts` and `storage.ts` — the two files that stand between a person's
saved conversations and losing them, and the two that had never been executed.

### `saveAll` reported a success it had not achieved

```ts
for (const attempt of attempts) {
  try { localStorage.setItem(CONV_KEY, ...); return attempt } catch { continue }
}
return ordered          // every attempt threw
```

When storage is full or blocked, all three writes throw and the function
returns **the full list** — the same value it returns on a clean save. `App`
did `setSaved(saveAll(...))`, so the sidebar showed thirty conversations as
kept, and the next page load had none of them. That is item 22's `deploy.sh
start` printing `>> up at <ip>` regardless, and item 23's banner, in the one
place where the thing being claimed is a person's data.

It is worse one rung up. When the ten-item attempt succeeded, twenty
conversations were dropped and the function returned the ten with no word
said — data loss delivered as a successful save.

`saveAll` now returns `{ saved, failed, note }`: what is actually in storage,
whether nothing could be written, and the sentence for the person. One
function decides and words it, so no caller re-derives "did it degrade?" by
comparing lengths. `App` renders `saved` rather than what it passed in, and
the note sits in the sidebar beside the list it is about — a toast is gone in
four seconds and the list is still on screen.

### A ladder whose last rung was not the smallest

The attempts were: everything, then the ten most recent, then **everything
again** with the passage text stripped. Rung three can be larger than rung
two, so the ladder did not shrink, and the cheapest combination — ten, no
text — was never tried at all. A quota that only that would have fit lost the
lot. The rungs are now strictly shrinking: all with text, all without, ten
without, three without, and a test measures the serialised length of every
attempt and asserts each is smaller than the last.

### Four headers pointing at files that are not there

```
api.ts      "A TypeScript port of frontend/src/api/client.js in the main repo"
export.ts   "Ported from the current UI's export.js; the output is byte-for-byte the same"
storage.ts  "Ported from the current UI's storage.js; the two must agree"
store.ts    "Ported from conversations.js + usage.js"
```

`frontend/src/api/` does not exist, there is no "main repo" distinct from this
one, and "the current UI" **is** this code — the redesign replaced the thing
those headers were written beside. The worst of them is `storage.ts`'s: *the
two must agree* is an instruction to the next reader to go and diff against a
file they cannot open, and it was the only assurance that file had.

Each now says what actually has to hold, and `export.ts` names the test that
holds it instead of a file nobody can open — which is itself a claim, so
`export.test.ts` exists.

### The migration nobody had ever run

`storageKey()` carries a person's saved conversations, spend ledger and
first-run flag from the `agenticrag.*` keys to `sextant.*`, once per browser.
`clientId()` is the per-browser namespace that stopped two people behind one
shared password overwriting each other's uploads in 0.8.2 — and its own
docstring says a fresh id per page load would mean a duplicate document on
every re-upload. Neither had a test. Both do now, including the branch where
`localStorage` throws, which is the one that must not take the page down.

### Rules

- **A function that can keep less than it was given must return what it
  kept.** Handing the input back is how a UI shows thirty conversations that
  a reload does not have.
- **A fallback ladder has to shrink.** A rung that can be larger than the one
  above it means the cheapest option is never reached, and the ladder reads as
  thorough while being strictly worse than two rungs would be.
- **"Must agree with X" is only an instruction if X exists.** Four headers
  cited files deleted with the UI they belonged to; one of them was the sole
  assurance on a data migration.
- **A docstring that names its own test is a claim too.** Write the test.

## 27 · The warning that hides on a phone — ₹0

Shipped 2026-10-24. Found by checking a claim items 25 and 26 had both made
without looking — and the claim was wrong, which is how the real defect
surfaced.

### The only warning in the app was the only element hidden at a breakpoint

```tsx
{MOCK && <Badge className="ml-1 hidden h-5 ... text-muted-foreground sm:inline-flex">mock</Badge>}
```

`hidden sm:inline-flex` is absent below 640px. A phone running a
`VITE_MOCK=1` build got the invented answers, the invented spend against the
daily cap, the invented recall curves and a toast saying a document had been
indexed — with no mark at all, on the screen with the least room to work it
out from context.

`frontend/.env.development` states the principle in its own comment: *"a UI
that silently shows invented answers is worse than one that says the server
is unreachable."* The element implementing that principle was the one thing
the layout gave up for space. Every other `hidden sm:` in the app is a
convenience — the word "Commands" beside its icon, the `⌘K` hint — and those
are correctly gated. The survey found exactly one load-bearing element among
them, and it was the warning.

It is `MockNotice` now: never breakpoint-hidden, warning-coloured rather than
muted, `shrink-0` so the conversation title beside it truncates first. The
notice is the thing that may not be given up for space.

### "mock" is a label, not a warning

A ten-pixel mono badge reading `mock` tells somebody who built this what it
means and tells nobody else anything. The sentence is now the notice —
`MOCK_NOTICE`, one constant in `api.ts`, reachable on hover and to a screen
reader: *"every answer, figure and source on this screen is invented. No
server is being queried."*

### The toast that said a document was stored

```ts
if (MOCK) return { success: true, message: `Indexed ${n} files — ${n * 37} chunks.` }
```

Of everything mock mode fabricates, this is the one a person *acts* on: they
read "Indexed 2 files — 74 chunks", believe the document is in the corpus,
and close the tab. It reads `Mock: pretended to index 2 files. Nothing was
stored.` now, from the same constant's posture.

### The claim this item started as

Items 25 and 26 both recorded that the mock build had "no mark on screen
saying so" / was an "unmarked fake UI". Neither was true — the badge existed
— and neither had been checked before being written into the milestone, the
progress log, the queue row and memory. All four are corrected in place
rather than quietly edited, because a repository that documents other
people's unchecked claims should show its own.

The irony is the finding: the false claim was *almost* right, and looking at
the thing it described turned a deferred non-defect into a real one.

### Rules

- **A warning may not be responsive.** Everything else in a header can be
  given up for width. The one element saying the screen is lying cannot, and
  `hidden sm:` on it is the defect in its purest form: correct, present,
  invisible to the reader who most needs it.
- **A label is not a warning.** `mock` names a mode; it does not say that
  every figure beside it is invented. If the only mark has to be small, the
  sentence goes in `title` and in `sr-only`, not nowhere.
- **The fabricated response a person acts on is the one that must say so.**
  A fake chart is looked at; a fake "Indexed 2 files" is believed and acted
  on.
- **Check the claim before you write it down, including in a "not done"
  note.** Two items asserted "unmarked" without opening the file. The
  correction is the item.

## 28 · The page that went missing quietly — ₹0

Shipped 2026-10-24. Back to the Python side, and to the worst thing a
retrieval system can do: be missing something and not know it is.

### The principle was already written in the file that breaks it

`mcp_server/uploads.py`, `to_document`, its own docstring:

> Raises UnsupportedDocument … for a file that parses to nothing — a scanned
> PDF with no text layer is the common case, and **it should be reported
> rather than stored as an empty document that silently matches nothing.**

That is enforced at 100% loss and nowhere else. At 1%–99% it is this, in
`loaders.py`:

```python
except Exception as e:
    # One malformed page should not lose the other ninety-nine.
    logger.warning("Page %d of %s could not be extracted: %s", number, path.name, e)
    pages.append("")
```

The comment is right and the behaviour stays. What followed it was not. The
empty string goes into `_load_pdf`, which does `if not text: continue` — so a
page that *failed* and a page that is *blank* become the same thing, no
locator is written, and the text is not in the document. The file is then
stored, and the person who uploaded it is told `Indexed 1 file — 240 chunks`.

Three pages of a hundred are not in the corpus. Every later search misses
them. The agent says *"the corpus does not mention that"* about something in
the PDF you uploaded, and there is nothing — in `/upload`, in
`sextant-ingest`, in `/stats`, in the answer — that could tell you why. The
only trace was a `logger.warning` going to a Docker log on a box nobody
reads: item 25's `durable` exactly, one layer down and with worse
consequences, because a wrong spend figure is read and a missing page is not.

### What it does now

`LoadedDocument` gains `unreadable_pages: list[int]`, and both PDF backends
fill it — MuPDF and the pypdf fallback, the second of which only runs where
the MuPDF wheel is missing, which is exactly where a defect goes unnoticed.
`_add_documents_sync` carries it across the dict boundary that `/upload`
crosses, so `_store` is the one place that decides whether anything went
missing and the one place that says so:

```
Stored 1 document(s) as 240 chunk(s). 2 pages could not be read and are not
in the corpus: paper.pdf p. 7, 41.
```

`unreadable_line()` returns that sentence and nothing else does, for the same
reason `eval/tenancy.py` has one `rule_verdict` and `deploy.sh` one
`billing_line`: `/upload` and `sextant-ingest` must not be able to disagree
about it, and neither may re-derive "was anything lost?" from a chunk count
it cannot check. It returns the empty string for no loss, so every caller
appends it unconditionally.

`sextant-ingest` prints it under the `ok` line. `/upload` does not build it
at all — the message arrives already carrying it.

### What was deliberately not done

The fact is reported, not **stored**. Putting `unreadable_pages` into chunk
metadata would let a citation say "from a document with two pages missing",
which is better — and it is a store-schema change with a migration behind it,
which is a decision and not a defect fix.

### Rules

- **A detected loss that only reaches a log has not been reported.** The
  warning was correct, accurate and seventeen months old. Nobody has ever
  read it.
- **Enforce a principle at every degree, not only at the easy boundary.**
  "Report it rather than store something that silently matches nothing" was
  checked at total loss because total loss is one `if`. Partial loss is the
  same sentence and the more likely case.
- **A failure and an absence must not reduce to the same value.** `""` for a
  page that raised and `""` for a page that is blank made the two
  indistinguishable to everything downstream.
- **Fix it in the fallback too.** The pypdf path runs only where the primary
  wheel is missing — the one environment where nobody is watching.

## 29 · The check that measured the machine — ₹0

Shipped 2026-10-24, on item 28's branch because item 28 could not merge
until this was fixed. CI went red on a test neither of item 28's commits
touches:

```
AssertionError: loop was starved: 16 ticks in 0.469s
assert 16 > (46.91622459999962 * 0.5)
```

### Re-running until it passes is the posture this project keeps removing

The reflex is to call it flaky and press the button again. A re-run failed
too, so that was not it either. Five workflow runs over trimmed branches
established what was actually true:

| what was in the tree | result |
| --- | --- |
| full branch (item 28 source + tests) | **fail** ×3 |
| `main`, untouched | pass |
| `main` + the hardened check only | pass |
| `main` + item 28's **source** only | pass |
| full branch minus three new tests in `test_knowledge_base.py` | pass |

So the shipped code of item 28 is innocent — proven, not argued — and the
test flips when three unrelated tests are added to the same file **below**
it. The mechanism by which later tests affect an earlier one is **not
understood**, and is recorded here as not understood rather than guessed at.

### Three wrong assertions before the right one

**One.** `ticks > (elapsed / 0.01) * 0.5`. `elapsed / 0.01` is the count a
10ms heartbeat reaches *if `asyncio.sleep(0.01)` sleeps exactly 10ms*, which
it never does — measured idle with nothing blocking, the real ratio is
**0.84**. The threshold's entire headroom was 0.84 → 0.50 and all of it went
to machine speed.

**Two.** Measure an idle baseline on the same machine and compare against
it. Better, and it produced the number that mattered: CI reported **31.9
ticks/s busy against 98.0 idle**. The runner was at nominal speed — not slow
at all — and the loop genuinely was getting a third of its ticks.

**Three — the realisation that fixed it.** A loop ticking every 31ms answers
`/health` perfectly well. Throughput was never the property. The regression
in the comment is *"ticked zero times during half a second"*: **one stall
spanning the whole search**. Thirty-one milliseconds is not that.

### What it does now

`_tick_gaps()` returns the gaps between ticks, and the assertion is on the
longest one as a fraction of the work:

```python
longest = max(gaps, default=elapsed)
assert longest < elapsed * 0.25
```

Scale-free, so core count, runner speed and whatever else the suite is doing
all drop out — which is the one thing none of the previous three versions
achieved. The regression gives a ratio near 1.0 and fails by the entire
margin. `test_the_starvation_check_can_fail` blocks the loop with
`time.sleep` in a coroutine and asserts the assertion trips; it is the only
`ASYNC251` waiver in the repository.

### Rules

- **A red CI run is a question, not a dice roll.** Re-running first and
  asking afterwards is how a real defect becomes "flaky" in everyone's
  memory. Five trimmed runs cost less than one wrong merge.
- **Say "not understood" when it is not understood.** The code is exonerated
  by experiment; the ordering effect is not explained, and writing a
  plausible mechanism into the record would make it true forever.
- **Assert on the property, not on a proxy for it.** Throughput was a proxy.
  The property is "no request waits", and that is the longest stall.
- **A threshold that moves when unrelated load is added is measuring the
  machine.** Make it scale-free and it stops mattering whose runner it lands
  on.
- **A timing assertion needs a test that it can fail.** Otherwise a threshold
  loose enough never to be flaky is also loose enough never to catch the
  regression.

## Item 30 — the knob that was set and never read

Unplanned, found by asking items 20–29's question of the five `main()`
functions item 24 left untouched: *can this be run, and does anyone check?*
`eval/judge.py` could not be run at all.

### What was wrong

**`.env` was loaded after the code that reads it.** `mcp_server/main.py`
imported twenty modules and then called `load_dotenv()` on line 55. Python
runs the imports first, so every module-level constant in the import graph
had already been evaluated:

| constant | from | default it was stuck on |
| --- | --- | --- |
| `observability.DAILY_BUDGET_USD` | `SEXTANT_DAILY_BUDGET_USD` | `0` — **disabled** |
| `observability.DAILY_BUDGET_SHARE` | `SEXTANT_DAILY_BUDGET_SHARE` | `1` — off |
| `observability.RATE_LIMIT_REQUESTS` / `_WINDOW_SECONDS` | `SEXTANT_RATE_LIMIT` / `_WINDOW` | `20` / `60` |
| `agent.MODEL` | `SEXTANT_MODEL` | `gemini-3.1-flash-lite` |
| `configure_logging()`'s format | `SEXTANT_LOG_FORMAT` | `text` |

Measured rather than reasoned about. With `SEXTANT_DAILY_BUDGET_USD=0.60` in
`.env`, importing the app left `os.environ` holding `0.60` and
`DAILY_BUDGET_USD` holding `0.0`. `DailyBudget`'s own docstring: *"Disabled
when the cap is <= 0."* The operator had set a daily spend ceiling on a
prepaid key and did not have one, and `CLAUDE.md` states the cap is set.

It bit the local run only. The box takes those names from compose's
`env_file`, so they are real environment variables before Python starts —
the pypdf-fallback shape from item 28: the path that is wrong is the one
nobody is watching, because the one being watched happens to take a
different route.

**`sextant-judge` had never started.** It does not load `.env` at all. Run
from a checkout it prints `GEMINI_API_KEY is not set` and exits 1 — against
a key sitting in the file every other entry point reads it from. It is this
project's only measurement of faithfulness, which its own docstring calls
*"the failure this project most needs to catch"*. Confirmed by typing
`sextant-judge -n 1`, which costs nothing because it exits before it
connects. Item 21 one directory over: **a check nobody can run is a check
nobody has read** — and the numbers in `learning/floor-fallback-cost.md`
came from `sextant-eval-agent --judge`, which loads `.env`, so nothing in
the record was wrong, only unreachable.

**The judge let the model search the web.** `eval.agent_harness` passes
`web_search=False` and says why: a web hit makes a corpus miss invisible,
and a grounded request is billed per call. The judge left it to
`web_search_default()`, which reads `SEXTANT_WEB_SEARCH`. Fixing the load is
what made this live — a setting that had never reached the process suddenly
could. And the harm here is larger than in `agent_harness`: the unanswerable
split asks whether the system *declines* when the corpus cannot answer, and
a model allowed to search answers those questions well, so
`correct_abstention` would have measured Google's coverage and
`faithfulness` would have graded answers against passages the corpus never
held.

**Two facts the loop reports were dropped on the floor.** `done` carries
`truncated` and `usage.cost_usd`. `agent_harness` counts both; the judge
recorded neither. A truncated answer is one the token cap cut off mid-claim;
graded with no marker it lands in the faithfulness mean as though the model
had chosen to stop there — a budget charged to the model's judgement. And a
harness that spends real money reported no cost at all.

### What shipped

`load_dotenv` moved into `tools/settings.py`, at import, and the three
scattered copies (`main.py`, `ingest_cli.py`, `agent_harness.py`) are gone.
This is not tidiness. A module cannot call `settings.getenv` without
importing `settings`, so **there is no longer an order in which a setting
can be read before the file that sets it** — the ordering is fixed by
construction rather than by remembering. `load_dotenv` never overrides a
name already present, so compose, CI and a shell export all still win.

The judge passes `web_search=False` explicitly, records `turns`,
`truncated` and `usage`, prints `cut` before the grade on a truncated
answer, and reports `truncated` and `cost_usd` in the summary.

`tests/test_judge.py`, ten tests. The ordering claim is proved on a **copy**
of `settings.py` in a temp tree with its own `.env` and a generated module
that reads a constant at import: `.env` is gitignored, so the machine that
most needs the test to run is CI, which has none, and a test that skips
there is the shape this item exists to delete. One test asserts the file
does *not* override an existing variable, because that is what keeps the box
correct. Two scans hold the arrangement: `load_dotenv` appears in one file,
and no module-level environment **read** happens outside `settings.py` —
reads only, because `faiss_ref.py` has to *write* `KMP_DUPLICATE_LIB_OK`
before `import faiss`, and exempting that file by name would leave a hole
shaped like whatever is behind it.

All four defects were planted back; each failed its own test for its own
reason.

### Rules

- **A setting read at import time must see `.env`, and only the import graph
  decides whether it does.** An entry point cannot load the file early
  enough — its own imports run first.
- **Fix an ordering by construction, not by being careful.** One load, in
  the module every read must go through, has no order to get wrong.
- **A config knob that is set and not read fails silently and in the
  operator's favour-sounding direction.** Nothing logs it, nothing warns,
  and the number that would have told you is the default.
- **A measurement whose meaning depends on an environment variable it never
  reports is not a measurement.** Pass the setting the harness depends on,
  do not inherit it.
- **A scan that cannot tell a read from a write has to exempt files by
  name**, and an exemption by name is a hole shaped like whatever is behind
  it.

## Item 31 — the key that crossed anyway

Unplanned, and a defect item 30 created eight hours earlier. ₹0.

### What was wrong

The knowledge-base server runs as a subprocess of the agent, and MCP's stdio
client does not hand a child its parent's environment: it builds
`get_default_environment() | params.env`, and on POSIX that default is six
names — `HOME`, `LOGNAME`, `PATH`, `SHELL`, `TERM`, `USER`. So
`mcp_host._FORWARDED_ENV` is not a convenience. It is the entire list of
things the child knows about the box it runs on, and its companion
`_NOT_FORWARDED` is a table of deliberate refusals, each with a written
reason so that — in that file's own words — *an entry is a claim somebody can
check rather than an omission nobody can see*. One of the four entries:

> `GEMINI_API_KEY`: nothing the subprocess can be asked to do generates text.
> **A key that does not cross cannot leak from here.**

Item 30 moved `load_dotenv` into `tools/settings.py` so that no module could
read a setting before the file that sets it. The child imports
`tools.vector_db.server`, which imports `vector_search`, which imports
`tools.settings` — so from a checkout the child read the repository's `.env`
itself, and every name in that file arrived in a process its parent had
curated down to six.

Measured, launching the child exactly as `kb_server()` specifies:

| | names in the child's environment | `GEMINI_API_KEY` |
| --- | --- | --- |
| at `exec` | `HOME LOGNAME PATH SHELL USER` | absent |
| after `import tools.vector_db.server` | the above **+ everything in `.env`** | **present** |

The parent withheld it and the child fetched it itself.

Two things make this worth an item rather than a footnote. The first is that
the practical exposure is small — same user, same machine, a file that
process could read anyway — but the stated boundary was simply not in force,
and `_NOT_FORWARDED`'s entire design is that its entries are checkable. The
second is that **nine tests existed for this seam and not one of them would
ever have noticed.** `TestEveryVariableTheSubprocessNeedsCrosses` compares
sets of names scraped out of source files: what is forwarded, what the
subprocess reads, what the deploy sets, what is exempt and why. Every one of
them passed while the thing they describe was not happening, because all nine
read dictionaries and none of them started a process. Item 18's finding, one
layer in: *a seam is pinned on the side you can read, which is the side that
is not the problem.*

The container was never affected. The image copies `pyproject.toml`,
`README.md`, `mcp_server/`, `tools/` and `eval/` — not `.env`, which is
gitignored — and compose injects `env_file` as real environment variables
before Python starts, so `/app/.env` does not exist and the load is a no-op
there. Local only, which is items 28 and 30 again: **the wrong path is the
unwatched one** — except that here the unwatched path is the one where the
agent is mounted in a desktop client.

### What shipped

`tools/settings.py` learns one word, `SEXTANT_ENV_SEALED`. A sealed process
takes the environment it was given and reads no file. The check is made
before the load and straight off `os.environ`, so a `.env` cannot unseal
itself — were the order the other way round, a file naming that variable
would hide every other name in it.

`kb_server()` sets the seal in the child's environment. Its `env=` argument
was `forwarded or None`, and the empty case is the common one — nothing in an
ordinary shell overrides a retrieval knob — so the dictionary is now never
empty and there is no arm in which the seal goes missing.

Seven tests, in `test_deploy_config.py` beside the nine they repair, and they
launch interpreters. The mechanism is proved on a copied `settings.py` in a
temp tree with an invented variable in its own `.env`, for the reason
`test_judge.py` copies it: CI has no `.env`, and the machine with none is the
one that must still run the check. Unsealed, the child has the invented name;
sealed, it does not; with the seal written *into* the `.env`, the child has
it anyway, which is the ordering. One scan requires every
`StdioServerParameters(` in the repository to seal its child, so the second
MCP server somebody adds does not inherit the hole whole. And one end-to-end
runs the real `kb_server()` against this machine's real `.env`, reading
**names only**, skipped where there is no `.env` — the one environment in
which the defect cannot occur.

Also corrected: `tools/vector_db/server.py` opened by saying it exposes the
store as *three* MCP tools. There are six.

Three defects planted back — the seal removed from `kb_server`, the check
removed from `settings`, and a variant in which the file may unseal itself —
each failing its own tests and nothing else.

### What the suite said about the fix

Three tests in `test_regressions.py::TestTheStoreOverrideReachesTheServer`
went red, and all three were right to: they assert on the *whole* dictionary
`kb_server()` returns, which is the correct shape of assertion for a function
whose entire output is a child's environment. One of them was
`test_no_override_means_no_forced_environment`, named after the behaviour
this item deliberately removes — with nothing to forward there used to be
nothing to force, and the empty case is the common one, which is precisely
where the seal would have gone missing. It is
`test_no_override_still_forces_the_seal` now, and its docstring says what
changed and why rather than quietly taking the new number.

The fourth test in that class is the one that starts a real subprocess and
reads the store back out of `kb_stats`. It stayed green: a sealed child still
receives every forwarded knob, because the parent is the thing that loaded
`.env` and forwarding is read from the parent. Confirmed live as well — the
host connects, discovers six tools, and `kb_stats` answers 22 documents /
1660 chunks.

### Rules

- **An allowlist the listed process can go behind is not an allowlist.** The
  parent decides a child's environment, or it does not; a child that reads a
  file for the rest has only the appearance of being curated.
- **A fix can make another defect reachable, and that belongs in the same
  queue, not in a later one.** Item 30 broke this and item 31 is item 30's
  bill.
- **Pin a process by launching it.** Nine tests over the same seam compared
  names in source files; the one thing none of them did was run the child,
  and that is where the claim was false.
- **A documented refusal is a claim with a date on it.** `_NOT_FORWARDED`
  entries are written to be checkable — so the check has to observe the
  refusal taking effect, not the sentence describing it.

## Item 34 — the trip reserved an address and nothing told DNS

Found by looking at what the 2026-10-27 trip actually left behind, rather
than at what it reported. The box was `TERMINATED`, and `agenticrag-ip` was
still reserved and still attached — ~₹21/day for an address nothing uses.
The script had already caught that: the park reads the address back, prints
the rate and the release command on stderr, and takes the 0 away. It did all
three. The terminal it ran in was closed, so nobody read any of it.

That is the small half. The large half is why the trip was worth running at
all and what it could not prove.

### The window nobody could hit

`trip.sh` reserves a **new** external address in step 1 and releases it in
the park. Steps 6 and 7 are the only checks in the whole script that go
through `PUBLIC_URL`. Between them sat nothing: `grep -i 'dns\|dig\|hulage'`
over the script found not one line. So the name could only point at the box
if a human opened the Cloudflare dashboard and edited an A record inside the
twenty minutes the box was up, with an address the script had printed — and
the script never said so, the README said so only in B3, as a one-time
provisioning step, and B3's table says `<static IP from B1>` as though the
address were stable.

Step 6 was written on 2026-10-06 against exactly the failure it could not be
run for. On 2026-10-28, three weeks and several trips later, it had never
once executed against a live box. `dig +short agenticrag.hulage.in
@tricia.ns.cloudflare.com` returned blank — asked of Cloudflare's own
authoritative nameserver, so that is non-existence and not a stale cache.
The record had never been created at all.

This is *a check nobody can run is a check nobody has read*, in its most
expensive form yet: not a line printed and discarded (items 5–10), but a
whole step whose precondition was a human action nothing asked for.

### What step 1b does

Between step 1 and step 2, so a `--no-deploy` verification pass gets it too —
that run is steps 5 to 7 and nothing else, which makes it the run that needs
the name most, not least.

The address comes from `addresses describe --format='get(address)'`. The
**name** is read off the box's `.env`, the same way step 6 reads
`PUBLIC_URL`. `CF_ZONE_ID` and `CF_API_TOKEN` come from the operator's
environment and are never in this repo, which is public; the token reaches
`curl` on a config file on a pipe, never argv, so it is not in `ps` on this
machine while the trip runs.

Unset, it is a skip like step 6's credentials — but a skip that still *says
something*, because the comparison is free: it resolves the name and prints
where it points against where this trip is. That is the line that would have
made the 2026-10-27 trip legible from its first minute.

### Read back, not assumed

Cloudflare answers `200` with `"success": false` for a token that cannot
write the zone — the same shape as `/upload` answering 200 for a file it
could not read, which is item 8. So the verdict comes out of the body, and
three different wrong outcomes each fail the trip with their own sentence: a
refusal, a record that landed on a **different address**, and a record that
is **proxied**. The third is worth stating: the orange cloud terminates TLS
and rewrites headers, so step 6's forged `X-Sextant-Proxy-Auth` check — the
one whose 200 proves Caddy *sets* rather than appends — stops meaning
anything while still printing a number. A check that cannot fail is the
thing this milestone keeps finding.

Resolution is a fourth, separate question, with three outcomes like the ssh
door: the address, nothing, or `?` on a machine with no `dig`. "The name
points nowhere" is a thing to act on; "I could not look" is not, and reading
the second as the first sends you to fix DNS that was never broken. A
resolver that lags is reported and **not** counted — the failure it causes is
step 6's, and step 6 counts it.

### The park takes the name down first

Before the address, not after, and that ordering is the item's point. The
park hands the address back to GCP's pool. A name still pointing at it
belongs to whoever reserves it next — a subdomain takeover, from a public
repo that names the subdomain. No hazard exists today only because the
record was never created; the moment step 1b starts creating it, the park
owes a delete. The delete is read back, because the API returning and the
record being gone are different claims, and only the second one makes the
address safe to release. A delete that did not take takes the 0 away and
prints where to finish it by hand.

### The harness

Two new stubs. The Cloudflare one keeps the record's content in one file so
that "the trip wrote the record" and "the name resolves" are one story — the
`dig` stub answers out of that same file, which means a resolve agreeing with
a write that never happened is not a thing this harness can produce. Both
follow the lesson from items 5, 8 and 20: a stub that can only succeed makes
the check unfalsifiable, so the knobs are failures — `FAKE_CF_REFUSES`,
`FAKE_CF_WRITES_WRONG`, `FAKE_CF_PROXIED`, `FAKE_CF_DELETE_FAILS`,
`FAKE_DNS_LAGS`, `FAKE_DNS_ANSWER`.

13 tests. Two plants to confirm they are not decorative: deleting the
content comparison in `cf_verdict` fails
`test_a_record_written_to_the_wrong_address_fails_the_trip` and nothing else;
moving the name's release to *after* the address fails
`test_the_name_is_released_before_the_address_it_points_at` and nothing else.

### Rules

- **A step whose precondition is an unasked-for human action is a step that
  does not run.** Step 6 existed for three weeks, was correct, and proved
  nothing, because the twenty-minute window it needed was never named.
- **Infrastructure a script creates, it owns — including the things that
  point at it.** `trip.sh` reserved and released an address while a name
  pointing at that address was somebody else's problem. There was no
  somebody else.
- **Release what points at a resource before releasing the resource.** The
  dangling direction is the dangerous one.
- **A skip can still answer the question.** Reading where the name points
  costs nothing and is worth printing even when the trip is not managing it.
