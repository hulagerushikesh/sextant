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
