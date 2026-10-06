# Progress

What shipped, by date, newest first. One line per change that moved the
product or a number; the commit message is the detail. Phases 0–14 are
summarised at the bottom — they were built in one rebuild week and their
story is the root README.

## 2026-10-06 — an upload is judged by what it stored (₹0)

- **Milestone 21 item 8, shipped, ₹0.** Item 7 shipped with a check that could
  not fail for the thing it named.
- **`/upload` answers HTTP 200 with `"success": false`** when the file was
  unreadable, the tool was unavailable, or the ingest failed. The status code
  says the request arrived, not that anything was stored — and step 7 compared
  the status code. Against a box refusing both uploads it printed two ticks on
  the lines describing the action, then two unexplained count mismatches, with
  the box's own reason (*No readable files in the upload*) nowhere on screen.
- **The trip still failed**, so this was a reporting defect rather than a
  correctness one — but an operator reading that output goes looking in the
  wrong place with the meter running.
- **The verdict comes out of the body now:** `stored 1` on success, `refused:
  <the box's own reason>` otherwise, `http <code>` when the request did not
  return 200, and `200 with an unreadable body` when it did but said nothing
  parseable.
- **The harness was lying too.** The first attempt to plant this against the
  previous script failed: the curl stub printed the body regardless of
  `-o /dev/null` and appended a status line regardless of `-w`, so the old
  code path could not be simulated. It honours both flags now — which is
  precisely what separates the three call sites in `trip.sh` — and reverting
  the script reproduces the bad output exactly.
- **3 of the 4 new tests fail against the previous script.** The fourth passes
  either way: a refused upload stores nothing to clean up under both versions.
- 583 passed, mypy clean (62 files), ruff clean, frontend builds. No VM.

## 2026-10-06 — the success criterion is the script's job now (₹0)

- **Milestone 21 item 7, shipped, ₹0 to write.** Item 6 proved the gate; every
  check in it is a read, so it proved nothing about what is behind the gate —
  and that half is this milestone's pre-registered success criterion, which was
  otherwise going to be done by hand on the box with the meter running.
- **Step 7 runs it.** Both gate users upload a file of the same name through
  the public URL; each must see their own and not the other's; a
  client-supplied `X-Sextant-User` must change nothing. Then the store is read
  directly — two probe documents, two distinct owners — because `/stats`
  reports what the asker can *see* and that is not the same question as what is
  actually there.
- **It is the only part of the trip that writes**, and only with both
  credentials exported. ≈$0.006 of summaries when a model key is configured.
- **Two defects of my own, found by running it rather than reading it.** The
  forged-name check was after both uploads, where both counts are the same
  number and the check's two sides agree whichever identity the request
  resolved as — it passed against a simulated proxy that forwarded the client's
  name, the exact failure it exists for. It now runs in the one window where
  the views differ, and the test pins its *position*, not just its outcome.
- **The second is item 5's defect, in code written the day after item 5.**
  `forget_probes || echo "..."` printed a loud warning and returned 0, so a
  trip that left two documents in the production corpus exited successfully. A
  result read and not compared. It takes the 0 away now, like the park.
- **The cleanup is in the EXIT trap**, before the box stops, not at the end of
  step 7 — the run that most needs it is the one that died half way. It finds
  the documents by scanning the store for the probe filename rather than
  rebuilding `upload:<owner>:<stem>` from the usernames, so a name spelled
  differently by `safe_owner()` cannot leave documents the trip reports as gone.
- **All 8 new tests fail against the previous script.** Four simulated boxes run
  end to end offline: correct, pre-0.8.2 ids, a proxy that forwards the name,
  and a `sextant-forget` that does not take.
- With this the whole of item 3's criterion is something the script decides.
  What is left for a person is the key and the second gate user.
- 579 passed, mypy clean (62 files), ruff clean, frontend builds. No VM.

## 2026-10-06 — the trip had never touched the gate (₹0)

- **Milestone 21 item 6, shipped, ₹0.** Found by reading step 5 after item 5.
- **Every check in the trip ran through `docker exec` at `localhost:8000`** —
  inside the box, behind Caddy. The trip that exists to deploy the gate 0.8.3
  built had never once gone through it. A box whose Caddy was misconfigured,
  pointed at the wrong upstream, or not running passes every check in step 5
  and reports green. Even the forged-name check was the easy half: `docker
  exec` to localhost always skips the proxy, so it proves the *app* refuses an
  unvouched name and says nothing about whether the *proxy* would let one
  through.
- **Step 6 runs from the operator's machine** against `PUBLIC_URL`, read off
  the box rather than hardcoded because the repo is public: no credentials →
  401, wrong password → 401, a real user → 200, a forged
  `X-Sextant-Proxy-Auth` → **200**, naming yourself with no password → 401, a
  second user → 200.
- **The forged-proof row reads backwards and is the one worth having.**
  `header_up` in Caddy is a *set*: the client's copy is replaced before the app
  sees it, so a forged proof that still succeeds is Caddy doing its job. A 403
  means it appended instead, or is not in the path — and then anyone can send
  the header themselves. No test in the suite could catch that; it is a
  property of the deployment, not of the code.
- **Credentials are the operator's**, exported as `SEXTANT_TRIP_AUTH` /
  `SEXTANT_TRIP_AUTH_2`, handed to `curl` through a config file on a pipe
  rather than argv so they are not in `ps`, and never printed. Unset is a skip
  that says the gate is unproven; a missing `PUBLIC_URL` is a failure, because
  that is the box being wrong rather than the operator declining.
- **Any failed check exits non-zero** and the park still happens — it is a
  trap, not a step.
- **An unreachable box counts as a failed check, not a crash.** curl exits
  non-zero on a refused connection and `set -o pipefail` would have made that
  the script's problem; it prints `000`, which is not the code wanted, so it
  counts like any other failure.
- **8 of the 9 new tests fail against the previous script.** The ninth passes
  trivially when nothing uses a password; it is a no-regression clause.
- **What it still does not prove:** the isolation behind the gate. Every check
  in step 6 is a read. Two users uploading the same filename is now item 7.
- 571 passed, mypy clean (62 files), ruff clean, frontend builds. No VM.

## 2026-10-06 — the park is checked now, not just performed (₹0)

- **Milestone 21 item 5, shipped, ₹0.** Also unplanned, and the same shape as
  item 4: not a new door, but the thing that would notice one.
- **`deploy/trip.sh` did not do what its own header claims.** It exists
  because of 2026-09-28, when a checklist's last step — park the box — was
  never reached and ₹703 went to a VM nobody was using; the fix made parking
  an `EXIT` trap so that *"the script returned"* means *"the box is parked"*.
  An offline run of the current script ends `agenticrag is RUNNING;
  reserved addresses: 0` and **exits 0**. The state was read back and printed,
  never compared. The checklist became a trap, and the trap's result became
  the new line nobody read.
- **Half the reason it stayed invisible was the test stub.** The offline
  harness answered `RUNNING` to every `instances describe` and ignored
  `instances stop`, so the happy-path test asserted `code == 0` against a box
  that never parked, and "the trip parked the box" was not an assertion
  anybody could have written. The stub keeps state now: `RUNNING` until a stop
  succeeds, the address present until a delete succeeds, and either can be
  told to refuse.
- **`park()` now compares.** The stop is retried once — a single transient API
  error is the dullest explanation for a bad readback and the cheapest to rule
  out. A state that is not `TERMINATED`/`STOPPED` prints the hourly rate, the
  daily rate and the manual command on stderr and **takes the 0 away**. The
  reserved address is checked by name rather than counted, because ₹21/day for
  an address attached to nothing is the same silence in smaller type. The
  check may only turn a 0 into a 1, so a trip that already failed keeps its own
  reason. `--keep-up` is untouched — that one is typed on purpose.
- **4 of the 7 new tests fail against the previous script.** The other three
  are the no-regression clauses; the happy path reaching `TERMINATED` only
  became a real assertion once the stub could say otherwise.
- 562 passed, mypy clean (62 files), ruff clean, frontend builds. No VM was
  started.

## 2026-10-06 — every route is now on one side of the boundary (0.8.7)

- **Milestone 21 item 4, shipped, ₹0.** Unplanned. It came from asking, while
  item 3 sat blocked on a key, whether there were more doors like the two
  0.8.5 closed.
- **There were not.** Every route that reaches the corpus hands the host to
  `scoped()`, `/query` included — the agent is handed a `ScopedHost` — and
  `SourceRegistry.restore()` sets `content=""` rather than resolving a
  client-supplied key against the store, so replaying prior sources cannot
  pull another owner's text. A result worth recording rather than leaving as
  silence.
- **What it found is that nothing stopped the next one.** The tool list was
  pinned; the route list was not. All three defects this milestone fixed —
  `/ann/compare` holding an unscoped host, `/ingest` writing without asking
  whose document it was, `/ann/*` with no rate limit — were *routes*, and each
  was caught only because somebody went looking.
- **The route table is now read off the live app** and every path must be
  declared. A corpus route must call `scoped(`, must never contain
  `host.call(`, and must be rate limited; a route declared harmless must call
  no tool; a handler whose source cannot be read counts as unclassified and
  fails, the same fail-closed rule `scope.py` applies to a tool.
- **Each of the five pins was verified by planting the defect it is for** — an
  undeclared `/leak` route calling the process-global host — and watching it
  fail. A pin that cannot fail is a comment.
- **One real finding, mine again:** `/stats` was the last corpus route with no
  rate limit. Defensible when it was a cheap count; 0.8.4 scoped it by
  recomputing from a full listing, which made it walk the corpus on every
  call, and the limit was never revisited. The same defect as `/ann/*`,
  introduced by the fix for something else. Now limited — the UI calls it once
  a page load and never polls.
- 555 passed, mypy clean, ruff clean, frontend builds. No VM was started.

## 2026-10-06 — the trip's preconditions are the script's job now (₹0)

- **Milestone 21 item 3 preflight, shipped, ₹0.** Item 3 itself is blocked on
  a key only the owner can create. Its preconditions were prose in three
  documents, so they moved into [`../deploy/trip.sh`](../deploy/trip.sh).
- **New hard stop:** an empty or missing `SEXTANT_PROXY_SECRET`. Caddy has no
  conditionals — it forwards `X-Sextant-User` on every proxied request whether
  or not the app can verify it — so this is not a degraded mode, it is *every*
  request refused with a 403, discovered after the build. The remediation line
  it prints generates the value with `openssl` **on the box**, so the secret
  never crosses this machine.
- **Reported, not enforced:** filled `basic_auth` slots, model key present,
  per-owner share set. Each changes what the trip can *prove*, not whether it
  runs. No value is ever printed.
- **After the build:** a forged `X-Sextant-User` sent straight at the api
  container must be refused — going direct skips Caddy, which is exactly the
  forged case — and the store's document ids are listed so a pre-0.8.2
  `upload:<stem>` shows up by name. The audit reads chroma metadata only: no
  embedder, no model, nothing to pay for.
- **19 new tests, and the script now runs start-to-park offline.** A fake `ssh`
  and `gcloud` on `PATH` let the real greps run against a fixture `.env`; the
  id audit is extracted from the heredoc and run against a real store, which
  pins that the two stay in step. A script that only ever executes with the
  meter on was never once executed before being relied on.
- **Three defects the dry run found**, none of which a reading had: two
  stopped the verify step outright, and the `.env` names listing used
  `[A-Z_]*`, so `BASIC_AUTH_USER_2` and `_3` — the users this trip exists to
  add — were silently never shown.
- **Corrections:** item 1 added **24** tests, not 16 (its own breakdown summed
  to 22); item 2 added **19**, not 21. `pyproject.toml` still claimed the
  `AGENTICRAG_` prefix "still stands" and that the box's `.env` used those
  names; untrue since 0.8.1 and 2026-09-28.
- 550 passed, mypy clean, ruff clean, frontend builds. No VM was started.

## 2026-10-06 — two ceilings, and only one of them is the wallet (0.8.6)

- **Milestone 21 item 2, shipped, ₹0.** The design question the plan said to
  settle first: the per-owner cap sits **under** the global one, it does not
  replace it. `check` is the wallet — the thing a leaked gate can never get
  past — and `check_owner` is the fairness. A query passes both.
- **The plan guessed "one line" and was wrong.** Keying the limiter on the
  owner is only right for an owner something *checked*. Without the proxy
  secret the name is a header the caller types, so a bucket keyed on it is one
  the caller empties by typing another — **weaker than the client address it
  replaced**. So: `user:<name>` when the proxy vouched for it, `ip:<address>`
  otherwise, prefixed so the two can never collide.
  `identity.resolve()` returns `Identity(name, trusted)` now.
- **`SEXTANT_DAILY_BUDGET_SHARE`**, default 1 (off): the largest fraction of
  the day's cap one authenticated name may spend. Not a division between
  whoever turns up — this process cannot see the user list, which is in
  Caddy's `.env`. `cap ÷ owners-seen-today` was rejected for shrinking a share
  retroactively; an absolute figure for drifting out of step with the cap.
- **Scope added deliberately:** `/ann/benchmark` and `/ann/compare` are rate
  limited. Building two ANN indexes over every vector is the heaviest call the
  box serves and they were the only routes with no limit at all.
- **The UI had to change or the fix reads as a bug:** refused at 60% of a cap
  the spend card shows as 40% unspent is a bug report. `/health` carries the
  asker's own share; the card labels itself *Your daily share*, tracks
  whichever figure is closer to stopping them, and shows the box's beside it.
- **19 new tests**, one named for each pre-registered clause, plus
  `test_an_unproven_name_does_not_buy_a_fresh_bucket` — the one the plan did
  not ask for and needed most.

## 2026-10-06 — an id is an id wherever it appears (0.8.5)

- **Milestone 21 item 1, shipped, ₹0.** Both doors the scope did not reach,
  and — the part that matters more — the rule that let them exist.
- **`trim()` recognises an id, not a field.** An id can reach a caller three
  ways and 0.8.4 knew one of them: as a string value anywhere in an entry (it
  checked only `document_id`), as a **key** of a mapping (`kb_ann_compare`'s
  `passages`), and as a **bare string** in a list (`exact`, `missed`). The
  check is anchored on `upload:<owner>:<stem>`, so prose that mentions an id
  is not an id — over-trimming would delete content and look exactly like the
  feature working.
- **Every `/ann/*`, `/ingest` and `/upload` call crosses `ScopedHost`.** The
  benchmark route returns only aggregates and is routed anyway: *"nothing to
  leak yet"* is how `/ann/compare` came to be the one route on the global host.
  A tool `scope.py` cannot classify is **refused**, and `READ_TOOLS |
  WRITE_TOOLS` is pinned against the live server's tool list — the only honest
  way to keep a list, after a docstring claimed `kb_ann_compare` was covered.
- **Writes are an allow-list where reads are a deny-list.**
  `identity.writable_by` is not `visible_to`: a document everyone may read is
  not one everyone may *replace*, because `_store` clears a document's chunks
  as the first step of writing it. So a write is a delete first, and it is
  checked before the store is touched. `shared` still owns the unnamespaced
  corpus — curl, the CLI, the eval harness are unchanged.
- **One departure from the pre-registered rule**, written up in the milestone:
  clause 2 said "an unnamespaced id still works for everybody". It does not —
  an authenticated caller is refused `handbook`, because letting ada overwrite
  the shared corpus is the same vandalism with a wider blast radius. Nothing
  real loses: `sextant-ingest` never crosses the host.
- **24 new tests**, including one that runs a real `ann_compare` over a real
  three-document store and asserts the *serialised* payload holds nothing of
  the other owner — after first asserting that it did before trimming.

## 2026-10-06 — milestone 21 planned: what else assumed there was one person

- **Planned [`milestone-21.md`](milestone-21.md), ₹0 to plan.** Milestone 20
  closed the same day; writing down what it left behind found two defects, and
  both are from this week rather than inherited.
- **`/ann/compare` hands out other people's text**, and routing it through
  `ScopedHost` would not fix it: `passages` is a mapping keyed by *chunk* id
  whose values carry no `document_id`, and `trim()` only drops a list entry
  with that field. Reproduced against a running server — asking as `ada`
  returned grace's chunk verbatim. The finding is not a missed endpoint; it is
  that deny-by-default only denies the shapes it recognises, while `scope.py`
  names `kb_ann_compare` in its own docstring as covered.
- **`/ingest` lets any authenticated user overwrite any other's document.**
  Ids pass straight through and `_store` clears a document's chunks first.
  Reproduced: grace replaced `upload:ada:notes`, the call returned success, and
  ada's own scoped listing now serves grace's text under ada's title. Milestone
  20 item 1's collision again, deliberate instead of accidental, and worse —
  the victim cites the forgery as their own.
- **The limiter and the cap still count one person**, which M20 deferred by
  name. The limiter keys on client IP, so one NAT shares a bucket and the
  authenticated name is ignored; the daily cap is one global figure, so the
  first user to spend it silences everybody until 00:00 UTC. A design choice,
  so the milestone pre-registers behaviour rather than a number.
- **Recorded while writing it:** every number in `learning/` is an unscoped
  number. `eval/harness.py` builds a `KnowledgeBase` directly and never crosses
  the host, so no eval run would catch a scoping bug. Correct — the scope is a
  boundary, not a retrieval change — but it means tests are the only guard.
- Item 3 is the VM trip, ≈₹2, carrying 0.8.2/0.8.3/0.8.4 and the M19 key
  rotation. It succeeds only if two real `basic_auth` users upload the same
  filename from the public URL and both survive, each seeing only their own.

## 2026-10-06 — the listing was the leak (0.8.4), and milestone 20 closes

- **Milestone 20 item 4, shipped: every result is trimmed to what the asker
  may see.** Item 2's measurement said A's retrieval holds up; reading the
  code to write that up said the retrieval filter was never the hard part.
  `kb_list` returns every document's title, overview and opening 240
  characters, so under one shared collection a tenant asking "what do my
  documents cover?" was handed everybody's.
- **The filter sits above the tool boundary and below the model**, in
  `mcp_server/scope.py`. It cannot go into the knowledge base: anything an MCP
  tool accepts appears in its discovered schema, and the milestone's hard
  invariant is that the model can never name a corpus — otherwise a sentence
  inside an uploaded PDF can. It cannot go into the subprocess either without
  one process per owner, which is arm B. So the knowledge base stays
  owner-agnostic and the host trims on the way out.
- **Deny by default**, like item 3's refusal: it trims *anything* in *any*
  result carrying a `document_id` the asker may not see, rather than naming
  the tools that leak. `kb_ann_compare` returns passages too.
- **A deny-list, not an allow-list.** A document is visible unless it is an
  upload naming somebody else, so the corpus the operator ingested stays
  everybody's — an allow-list would have hidden every shared document from
  every user. `shared` is scoped like any other name, or any tenant could read
  any other's uploads by deleting one header.
- **`kb_stats` is recomputed, not trimmed.** Telling someone the store holds
  1,660 chunks when they can search 52 is a wrong answer before it is a leak,
  and it is the number the UI prints. Derived from the scoped listing, so the
  knowledge base still needs no notion of an owner.
- **Scoping exposed a half-wired frontend.** It sent `X-Sextant-Client` on
  `/upload` only; once the server scoped `/stats` and `/query`, a browser would
  have stopped seeing its own uploads. One `sent()` helper now puts it on every
  request. Verified in a browser against a scratch store: four documents
  stored, the UI showed **2 documents · 2 chunks**, `ada` saw 2, no header saw 1.
- **Not closed, deliberately:** `collection_size` riding along on a search
  result — a count of the whole store, read by `agent.py` to tell the model
  "the knowledge base is empty" apart from "nothing matched". Recomputing it
  costs a listing per search; dropping it makes that message wrong.
- **Milestone 20 is closed**, all four items, ₹0 end to end. Nothing deployed.

## 2026-10-06 — a name is worth what set it (0.8.3)

- **Milestone 20 item 3, shipped: identity arrives from the transport.**
  Caddy's `basic_auth` grew three slots, and `reverse_proxy` forwards
  `X-Sextant-User {http.auth.user.id}` — the name of whoever actually
  authenticated — beside `X-Sextant-Proxy-Auth`, the shared secret that proves
  this proxy is what set it. `identity.py` believes the first only alongside
  the second, compared constant-time. Precedence: authenticated name, then the
  browser's own id, then `shared`.
- **An unproven name is a 403, in middleware.** The pre-registered rule was
  that this lands only with a test refusing a client-supplied identity header;
  it refuses the whole request, not just the name, and nothing is stored under
  anybody. Middleware rather than per-route so a route added later inherits the
  refusal instead of having to remember it — and declared inside the
  request-tagging middleware so a refusal still carries a request id.
- **Three Caddy facts checked against a real Caddy, none assumed.** `caddy
  validate` accepts the file with the optional user slots empty (an unset
  `{$VAR}` is substituted before tokenising, so the line becomes whitespace).
  `caddy adapt` shows both headers as `set`, not append. A live two-user proxy
  in front of a header-echoing server rewrote a request that authenticated as
  `ada` while carrying `X-Sextant-User: grace` so the backend saw `ada`.
- **A fourth probe changed the design.** With `SEXTANT_PROXY_SECRET` unset,
  Caddy forwards the name anyway, with an *empty* proof — so the first deploy
  of this tree onto a box without the secret refuses every request. Kept rather
  than softened: ignoring an unprovable name would turn deleting one `.env`
  line into every user silently collapsing into one namespace, which is item
  1's collision back with no symptom. The 403 names the missing variable.
  **`SEXTANT_PROXY_SECRET` is a deploy prerequisite**, like 0.8.1's rename.
- **The seam nothing can test end to end is pinned by string.**
  `tests/test_deploy_config.py` asserts the Caddyfile's header names are the
  constants `identity.py` declares; rename one in Python and every Python test
  still passes while the box quietly loses its identities.

## 2026-10-06 — a corpus is a filter, and the filter was never the hard part

- **Milestone 20 item 2, decided: A — one collection, filtered.** Full note
  [`../learning/multi-corpus.md`](../learning/multi-corpus.md), harness
  `eval/tenancy.py`. At a **3.1%** tenant share -- smaller than the rule asked
  about -- A reaches recall@5 0.9727 against collection-per-owner's 0.9818, a
  gap of +0.0091 inside the 0.02 tolerance, and *beats* it on hit@1 (0.9455 vs
  0.9273).
- **The rule passed and could not have failed, which is the real result.**
  Filtering removes only documents the owner does not have, so it never
  demotes one they do -- their answer keeps its order and moves up. A can lose
  a question in exactly one way: the answer falling outside the budget in the
  global ranking. Measured, the tenant's own answer sits at global rank **1**
  (median; max 3 with the per-document cap, 14 without). There was nothing for
  a bigger budget to recover, which is why every over-fetch column is
  identical. The milestone's arithmetic -- *10% share, so over-fetch 10x* --
  was about filling k slots, not about finding the answer.
- **Two facts that decide more than the table does.** The over-fetch budget
  does not exist past 30: both runs asked for 200 and got exactly 25, because
  `RERANK_DEPTH = 25` is fed by `CANDIDATES = 30`. And the filter need not be
  post-hoc at all -- the default dense backend is `chroma`, whose path is
  `collection.query(...)`, which takes a `where`, so the shortlist can hold 30
  of the *tenant's* chunks. What was measured is the pessimistic bound on A,
  and it passed. The BM25 half and the four hand-written ANN backends have no
  filter and keep the post-hoc behaviour.
- **The work A needs is not the filter -- it is the listing tools.** `kb_list`
  and `kb_stats` report the whole collection, so under A every tenant's
  document titles are handed to the model in its prompt. A leak, not a recall
  problem, and no retrieval experiment would have found it. Queued as item 4;
  it is a correctness bug the moment a second person has documents.
- **The first attempt was invalid and was thrown away.** A synthetic partition
  of `eval/corpus/`: 58 chunks, so an over-fetch of 200 returns the whole
  store; and 11 of its 17 labelled documents are chained into one component by
  questions labelling two at once, so the smallest achievable "10% owner" held
  **62%** -- the printed `share 0%-62%` is what gave it away. The golden set
  cannot describe a small tenant. The mixed store can without inventing one:
  the handbook's 52 chunks beside the survey's 1,608.
- **The arms differ in one thing by construction.** Arm B is the same chunks
  with the same embeddings, copied out of the mixed store rather than
  re-ingested -- re-ingesting would have regenerated the overviews and
  re-chunked, and either difference would have read as though it were about
  tenancy.
- **Not measured:** behaviour past ~25k chunks with many tenants, where a
  30-candidate shortlist may not contain a small tenant at all and
  `CANDIDATES` would have to grow with the tenant count. That is where B
  wins, and nothing here touches it.
- Cost ₹0 -- four local runs, ~20 minutes of laptop CPU, no model calls. The
  real store was never written to; the runs used a copy.

## 2026-10-06 — an upload belongs to someone (0.8.2)

- **Milestone 20 item 1.** Uploads were stored as `upload:<filename stem>`,
  which is global across the store, and `_store` clears a document's existing
  chunks before writing its new ones. Both are right alone -- a re-ingest
  *should* be a replacement -- and together they meant two people behind the
  one shared Basic-auth password who each uploaded `notes.pdf` destroyed each
  other's chunks, with `/upload` answering success and no symptom but
  citations that stopped appearing. The id is now `upload:<owner>:<stem>`.
- **The owner comes from the transport, not the payload.** `/upload` reads
  `X-Sextant-Client`, which the frontend sets from a random per-browser id
  kept in localStorage; anything that sends no header -- the CLI, curl, the
  eval harness, a browser with storage switched off -- lands in
  `upload:shared:<stem>`, which is exactly the old behaviour. So the fix is
  invisible to every non-browser caller.
- **It is namespacing, and `mcp_server/identity.py` says so in the file.** The
  header is untrusted by construction: anything can send it, so an owner is a
  name people pick, not one they prove, and one owner's chunks are still
  returned by another's search. Nothing was hidden, because hiding is item 2
  and it has a measurement attached. The trusted source -- Caddy forwarding
  `{http.auth.user.id}` -- is item 3, and the module deliberately does **not**
  read a proxy header yet: reading one before anything sets it would let any
  caller claim any identity by typing it.
- **Both halves are pinned at the store, not only on the id.** Two owners
  uploading `notes.md` keep their chunks and both stay findable by search; the
  same owner re-uploading still collapses a many-chunk document to one with
  the old text gone from the index. A fix that only separated the two people
  would have broken the replacement the stable id was for. The owner is
  sanitised on the way in: it reaches a document id and from there a chunk id
  (`<document_id>#<n>`), so an owner carrying `:` or `#` could otherwise name
  a document that is not theirs.
- **The old ids: a documented one-way break, no migration.** A store written
  before 0.8.2 keeps its `upload:<stem>` documents -- searchable, and
  `sextant-forget` still removes them -- but a re-upload lands beside them
  rather than replacing them. The deployed store should hold none: the
  2026-09-27 re-ingest rebuilt it from `/data/corpus` through the CLI, whose
  ids are bare stems, and dropped the one `upload:` document it had. To be
  confirmed with `kb_list` on the next trip rather than assumed.
- **Found while fixing it:** the test rate limiter is module-level state keyed
  on client IP, and every API test arrives as the same `testclient`. Adding
  two tests 429'd an unrelated one, and the failure pointed at the wrong file.
  The `client` fixture resets it now, so test order stops mattering.
- **Verified in the browser, not only in tests**, because the frontend half
  has none: `clientId()` returned `bmuwdv257cib2ds2z`, stable and persisted;
  the real `uploadFiles` posted a real file to the real server on `:8100`
  with `VITE_MOCK=0`; the store held
  `upload:bmuwdv257cib2ds2z:ownership-check`. Removed afterwards -- the local
  store is back to 22 documents / 1,660 chunks.
- Gate green: 449 passed, mypy clean on 58 files, ruff clean, frontend builds.
- Cost ₹0 -- local, no VM, no model calls. Not deployed; it rides the next
  trip with the key rotation. Frontend bundle 186.8 -> 186.9 kB gzip.

## 2026-10-06 — milestone 20 planned, and "one corpus per deployment" turns out to hide a live defect

- **Milestone 20 is planned, not started** ([`milestone-20.md`](milestone-20.md)).
  The candidate line said *"a hosted version needs `category` to mean a
  person."* Reading the code, that is three questions of different sizes --
  isolation (a retrieval question, measurable), identity (nothing in the repo
  answers it), concurrency (already `milestone-15.md`'s decided-against) --
  and they are not in that order.
- **A defect found while planning, live on the deployed box today.** Upload
  ids are `upload:<filename stem>`, global across the store
  (`mcp_server/uploads.py`), and since 2026-09-25 `_store` clears a document's
  existing chunks before writing new ones -- correct on its own, and the right
  behaviour for a re-ingest. Together: two people behind the shared Basic-auth
  password who both upload `notes.pdf` destroy each other's chunks, with
  `/upload` returning success and no symptom but citations that stop
  appearing. Everyone behind one password is already a tenant in the only
  sense that matters. The fix is item 1 and stands alone, whatever the rest of
  the milestone decides.
- **The measurable question is isolation, and the rule is pre-registered.**
  `search()` has no filter parameter and the dense ANN index is built once
  over every chunk, so a metadata filter can only post-filter -- `k` in, fewer
  than `k` out, and the over-fetch needed grows as a tenant's share of the
  corpus shrinks. A collection per corpus is today's pipeline over a smaller
  store, so its recall needs no measuring; its cost is ~180 MB of models per
  corpus, because `get_embedder()` is not cached and each `KnowledgeBase`
  builds its own cross-encoder too. Rule: the filter is accepted only if at a
  10% corpus share with a 10x k over-fetch budget it reaches the
  collection-per-corpus hit@5 within 0.02.
- **One invariant that is not up for measurement**: the corpus must never be a
  tool argument. Tool schemas are discovered and handed straight to the model,
  so a `kb_search(corpus=...)` lets a sentence inside an uploaded PDF read
  another person's corpus. Isolation is enforced below the tool boundary.
- **Identity is scoped down on purpose.** Caddy's `basic_auth` takes more than
  one user and exposes `{http.auth.user.id}` for `reverse_proxy` to forward,
  so identity can arrive from the transport rather than from the client or the
  model -- which is what the invariant above requires anyway. Public signup,
  OAuth and password reset are written down as out of scope with that reason,
  not omitted.
- Cost: ₹0. No VM, no model calls; the measurement runs on `sextant-eval`,
  which does not spend.

## 2026-09-28 — the box is on the current tree, and a VM left running cost Rs703

- **Milestone 19 item 3, two of three jobs.** The box's `.env` was rewritten
  onto `SEXTANT_*` **before** anything was built on it (backup kept as
  `.env.pre-0.8.1`), then the working tree was shipped and the stack rebuilt.
  The deployed UI is now the React 19 + TypeScript + Tailwind v4 + shadcn one,
  and the deployed code is 0.8.1 with no `AGENTICRAG_` fallback.
- **The rename is proven, not assumed.** `/health` reports
  `budget.budget_usd: 0.6` -- the cap is being read under its new name. Had
  the order been reversed, that field would read `0` and the box would have
  been uncapped. The api logs contain no `AGENTICRAG_*` line, which is
  `settings.legacy_warning()` saying the environment is clean.
- **Verified from inside the box, no DNS needed**: containers healthy; the
  served `assets/` carries `lab-*.js` (419 kB) and `command-palette-*.js`
  (19.6 kB) as separate chunks, which is the code-splitting the port
  introduced and proof the new bundle is live; `index-*.js` is 580,198 bytes,
  byte-identical in size to the local build; `PUBLIC_URL` baked correctly;
  Caddy's Let's Encrypt cert still in the `caddy_data` volume; the gate
  answers 401 without credentials.
- **Two live queries.** An unanswerable one (`per-document candidate cap`, a
  sextant concept the tracker corpus does not hold) correctly said so instead
  of inventing an answer. An answerable one (ByteTrack's two-pass association)
  came back with `bytetrack#summary` at **0.9994**, three valid citations and
  2 turns. $0.0086 total.
- **The key rotation did not happen.** The owner reports the exposed key is
  now wired into several places, so revoking it is not a one-line job; it
  waits on that work. The key exposed on 2026-09-23 is therefore still live.
- **Cost: Rs703, and almost none of it was the work.** The trip itself was
  ~20 minutes (~Rs2). The VM was then left RUNNING from 2026-09-28 00:06 to
  2026-10-03 12:37 -- **125.5 hours** -- because the session ended waiting on
  the key rotation and nothing parked the box. The daily cap is Rs50-100; this
  was ~Rs134/day for five days. Parked and the IP released on 2026-10-03.
  **The rule this earns: the box is parked in the same turn it is started.
  A trip that ends waiting on a human parks first and restarts later --
  restarting costs Rs2, waiting cost Rs700.**
- One pre-existing oddity, confirmed harmless: `docker compose` prints
  `The "ubyP" variable is not set` four times. That is compose's YAML
  interpolation pass reading `$ubyP` out of the bcrypt `BASIC_AUTH_HASH`. The
  container gets the raw value through `env_file: format: raw` -- checked, 60
  chars, `$2a$` prefix, and the gate returns 401 -- so the warning is noise,
  not damage.

## 2026-09-28 — every setting has one name again

- **The `AGENTICRAG_` environment fallback is gone** (0.8.1). It was kept
  through the 0.7 rename and the 0.8 CLI cut for one reason: the deployed
  box's `.env` used the old spelling, and removing the fallback would have
  dropped its budget cap, its CORS allowlist and its store path to defaults
  without saying a word.
- **What replaces it is louder than what it replaced.** `settings.getenv`
  reads `SEXTANT_*` and nothing else; `settings.legacy_warning()` scans the
  environment for pre-rename names and the agent server and the ingest CLI
  print it at startup — `AGENTICRAG_ANN_INDEX -> SEXTANT_ANN_INDEX`, with a
  count and the sentence that those settings are on their defaults. The
  failure mode the fallback guarded against is now a line on stderr instead
  of a silent default, which is the outcome the fallback was a proxy for.
- `mcp_host._FORWARDED_ENV` halves: it forwarded both spellings of seven
  knobs and now forwards seven names. `settings.env_names()` is deleted with
  its only caller.
- Three tests pin it: the old spelling is not read, a leftover is reported
  with the name to move it to, and a clean environment says nothing.
- **This is the local half of milestone 19 item 2**, done ahead of the VM
  trip so the trip is shorter. The order on the box matters and is fixed:
  rewrite `.env` onto `SEXTANT_*` *first*, then ship this tree and rebuild.
  Gate green — 431 tests, mypy 57 files, ruff, frontend build.

## 2026-09-27 — the redesigned UI is the UI

- **Milestone 19.** `ui-redesign/sextant` had been finished and unmerged since
  2026-09-13 under one instruction: *port only after review*. This was the
  review and the port. `frontend/` is now React 19 + TypeScript + Tailwind v4 +
  shadcn, replacing 747 lines of `App.jsx` and 1,952 lines of hand-written
  `App.css`.
- **The review was the work, not the copy.** The redesign was pinned to the
  2026-09-13 contract and four things had shipped after it: GFM tables in the
  answer renderer, Markdown export of a conversation, the `sextant.*` storage
  keys with their one-time migration, and the composer that grows one line to
  six. All four were closed before the port landed; porting without them would
  have been a silent feature regression, which is the one way a redesign that
  looks better is worse.
- **Three more found by running it, not reading it**: the onboarding card still
  named `agenticrag-ingest`, deleted in 0.8; the new tracked `.env.development`
  outranked the developer's gitignored `.env.local` and pointed the UI at the
  wrong port; and the mock never rendered a table, so the construct would have
  gone unseen in design work.
- **Bundle: 61.5 kB → 186.8 kB gzip, 3.0×.** Lazy-loading the Index Lab moved
  Recharts into its own 123.4 kB chunk (315.3 → 192.7) and the ⌘K palette took
  another 6. The pre-registered budget was 120 kB and was missed; the rule said
  record it and land the port, so that is what happened. What is left is React,
  Radix, Motion and the shadcn primitives — the design system that was chosen.
- Not deployed. That needs a VM trip, which should carry the `.env` rewrite,
  the `AGENTICRAG_` fallback removal and the key rotation with it.

## 2026-09-27 — the deployed store is on the current pipeline

- **Milestone 18 item 1 shipped.** The VM's store was written 2026-09-15,
  three milestones behind: before table chunking, before the PyMuPDF
  extractor, before the per-document cap, and with no overviews at all. The
  box was also still running the pre-2026-09-25 `_store`, so the re-ingest
  was shipped and rebuilt first — running it on the old image is the exact
  upsert case that leaves stale chunks searchable.
- **61 chunks / 22 documents → 79 chunks / 21 documents, 21 overviews.**
  Every document was re-chunked (`config-reference` 3 → 10 on the table
  chunker, `kalman-filter` 4 → 5) and every one got an overview, the first
  time the deployed store has had them. Chunk ids verified contiguous per
  document: no stale leftovers, which is the fix doing its job.
- **The résumé is out.** `sextant-forget -y upload:Rushikesh_Hulage_Resume_Rubrik`
  removed its nine chunks; the store is now the 21-document corpus only.
- One live query verified against the rebuilt store through the API, and the
  overview chunk (`bytetrack#summary`) took rank 1 — the thing the deployed
  store could not do before today.
- `/data/chroma-backup-2026-09-27.tgz` (334K) holds the pre-ingest store.
- **₹8 total**: ~20 minutes of VM (≈₹2) plus 21 overviews and one query
  (~$0.07, ≈₹6). VM stopped, access config deleted, static IP released
  again; no DNS record was created, so there is none to remove.

## 2026-09-25 — a re-ingest was not a replacement

- **Found while preparing the deployed re-ingest, and it would have
  corrupted it.** Chunk ids are `<document>#<n>` and `_store` upserted them,
  so a document whose chunk count fell left the surplus behind. Measured on
  a real store: a document went from eleven chunks to one, and the ten
  chunks of deleted text stayed embedded and took the top three hits for
  their own subject. The VM re-ingest re-chunks every document with a
  different chunker, which is exactly the trigger. `_store` now clears each
  document's existing chunks before writing its new ones, and only the
  documents being written are touched.
- **`sextant-forget`** — removes a document and all its chunks, overview
  included. `--list` to find ids, a confirmation by default, `-y` for
  `docker compose exec -T`. A command, never an MCP tool: the model is
  offered read tools only, and mounting "search my notes" must not also
  grant "delete my notes". This is how the résumé leaves the deployed store.
- 12 tests, including the eleven-chunks-to-one regression.

## 2026-09-24 — milestone 18 opens, 0.8

- **Milestone 17 closed, 18 planned.** The plan turned up the thing that
  was never on a list: the deployed store was written 2026-09-15, before
  table chunking, the PyMuPDF extractor and the per-document cap. The
  re-ingest is item 1 and waits on a go-ahead — it needs the VM up.
  `planning/README.md` was two milestones stale and is now true.
- **Summaries are the default when a key resolves.** They were opt-in for
  exactly one reason — 21 overview chunks crowded the graded slots and cost
  dense recall@5 0.970 → 0.900 — and the cap took that back in full
  (0.900 → 0.973). `sextant-ingest` summarises when `GEMINI_API_KEY` is
  there, `--no-summaries` says don't, `--summaries` says do and fails loudly
  if it cannot, and no key prints a line and stores text. A model failure
  under the default degrades to text for the rest of the run instead of
  aborting it. No new measurement: the numbers were already taken, and both
  baselines are untouched.
- **0.8.** The four `agenticrag-*` command aliases are gone, one release
  after the rename as promised. The `AGENTICRAG_` *environment* prefix
  stays — the deployed `.env` still uses it, and dropping the fallback
  would silently reset the box's daily budget cap.

## 2026-09-23

- **Composer fix deployed — and with it the whole of M17** (≈₹4 of VM
  time) — the VM had been parked since 2026-09-17 and was still serving a
  pre-`kb_list` image, so shipping the compact composer carried `kb_list`,
  sub-floor ordering, the floor-fallback knob, cached-token reporting and
  the table/export work with it. A fresh static IP was reserved and
  attached, DNS repointed, the working tree shipped and both images
  rebuilt on the box; the key and the daily cap were replaced in the VM's
  `.env` by hand. Verified: TLS valid on the new address, Basic-auth gate
  returns 401, `/health` reports `budget_usd: 0.6` and offers
  `kb_search, kb_stats, kb_list`, and one live query answered from the
  corpus with a citation in two turns ($0.002). Store on `/data` untouched
  (22 documents) and still ingested under the pre-table-chunking pipeline —
  a re-ingest is ₹0 and not yet run.

- **Floor fallback as a cost feature measured, candidate closed** ($0.25)
  — all 55 answerable handbook questions, both arms, judged on
  flash-lite. The fallback is safe (false abstention 1 → 0, faithfulness
  0.936 → 0.960, citations valid throughout) and it fired on **one**
  question: the pre-registered exposure clause failed, and every
  set-level number that moved is one-run nondeterminism (40 of 55
  questions asked a different query between arms). `SEXTANT_FLOOR_FALLBACK`
  stays `none` and the candidate leaves the queue. The agent harness now
  records `below_floor` on every search and counts it in the grade, so
  the exposure number comes out of the record instead of a replay script.
  `learning/floor-fallback-cost.md`.

## 2026-09-20

- **Prompt caching measured, no knob** ($0.027) — implicit caching never
  fires on the agent's 1,410-token prefix; an explicit cache is accepted
  and saves 40% gross per question, 28% net of storage at 5 queries/hour
  (rule: 30%). `usage.cached_tokens` and the cached rate in `pricing.py`
  ship. `learning/prompt-caching.md`.
- **Floor fallback measured, not shipped** ($0.12) — returning the dense
  order when nothing clears 0.01, marked `below_floor`, does not help the
  answerable questions it was built for (q48 is phrasing luck at the floor
  either way; the dense order picks the wrong config chunk), so by the
  pre-registered rule the knob stays `none`. What it did: 15/15
  unanswerable still declined and the loop stopped flailing on them —
  searches 2.9 → 1.2, cost halved — queued as its own claim. The agent
  harness gained `--unanswerable` and `--judge` (answers graded in the
  same run), `SEXTANT_JUDGE_MODEL`, and the trace shows a below-floor
  result. `learning/floor-fallback.md`.
- **Sub-floor ordering by dense cosine shipped** (₹0) — chunks the
  cross-encoder scores under the 0.01 floor are ordered by dense
  similarity instead of fusion noise; handbook rerank recall@5 0.964 →
  0.982, hit@1 0.909 → 0.927 (q47, q48, g03), survey unchanged, nothing
  above the floor moves. Baselines regenerated. The agent still filters
  at 0.01, so its answers are unchanged. `learning/subfloor-order.md`.
- **HyDE measured, decided against** ($0.010) — hypothetical-answer
  embedding hurts dense on both sets, is erased by the 25-deep rerank
  pool, and breaks the abstention floor when it replaces the question
  (unanswerable max 0.00 → 0.70 on the survey). `learning/hyde.md`.
- **`kb_list` measured and its prompt bullet shipped** ($0.034, two agent
  runs) — the model lists first on 4/5 global questions and 3/3 starters
  and names every expected document; the "which of my documents cover X"
  phrasing needed one added sentence. Agent harness records the tool
  sequence and grades listings by `named`. `learning/kb-list.md`.
- Repo public; new Gemini key under a ₹500/month prepaid cap.

## 2026-09-19

- **IVF_HNSW at 1M** (learning §9 item 6, ₹0, ~50 min CPU) — HNSW over
  65k centroids returns 99% of brute force's cells at a quarter of the
  coarse cost; whole query 1.6–1.8× faster, not the 2× claimed, because
  the coarse step was 45% of the query, not most of it. 65k cells at 1M
  costs 0.05 recall against 4,096. Nothing ships. `learning/ivf-hnsw-1m.md`.
- **IVF-PQ at 100k** (learning §9 item 5, ₹0, ~45 min CPU) — latency
  parity with flat at ≈100k but recall stalls at 0.73 under `nprobe`;
  `oversample` 32–64 lifts it to 0.91–0.99, so that is the dial at scale.
  HNSW beats flat from ≈25k at recall 1.0. Nothing ships.
  `learning/ivfpq-100k.md`.
- **`kb_list` tool** — every document with title, size, overview (when
  summarised) and opening lines; offered to the agent for "what do my
  documents cover?" questions, which no search answers. Built and
  verified over stdio; agent-level measurement waits on a key.

## 2026-09-17

- **Per-document candidate cap** shipped as default 2 — dense recall@5
  +0.018 (CI store) to +0.073 (stores with summaries), rerank unchanged,
  both baselines regenerated. Three rounds: hard cap lost a survey page,
  score guard fixed it, restricted to modes whose score is a relevance.
  `learning/candidate-cap.md`. Milestone 17 opened.
- **Markdown tables render** in answers (`Answer.jsx`, one block added);
  **Export as Markdown** in the palette (`frontend/src/export.js`).
- **Static IP released** — ₹22 day on a stopped VM traced to it. Parked
  cost now disks only (~₹270/mo). `deploy.sh start` refuses without an
  address and prints the reattach commands.
- Gemini key deleted by the owner; model-backed paths off until a new one.

## 2026-09-16 — Milestone 16, five experiments, $0.21

- **Exp 5, summary chunks** — opt-in `sextant-ingest --summaries`; global
  hit@1 0.6 → 1.0 under rerank, cost dense recall (fixed 09-17).
- **Exp 2, agent-level eval** — `sextant-eval-agent`; the loop did not
  decompose multi-hop questions (0.722); one prompt bullet → 0.778;
  last-turn note replaces the tool-mode cap that did not work.
- **Exp 3, chunk size** — 200 stays; `SEXTANT_CHUNK_TOKENS` knob.
- **PDF extraction** moved to PyMuPDF (lines rebuilt from span baselines).
- **Exp 4, embedder swap** — bge-small measured, opt-in
  `SEXTANT_EMBEDDER`.
- **Exp 1, table-aware chunking** — shipped; survey rerank hit@1
  0.818 → 0.909.

## 2026-09-15 — Milestone 15, live

- Milestone 16 planned. Compact composer. Go-live proof written.
- Park/unpark from the laptop; non-root container; uptime runbook.
- README made true through M15; `CLAUDE.md` added.
- Reranker question settled on a 1,602-chunk store — it stays.
- Package, CLIs and settings renamed to `sextant`.
- **Live** at `agenticrag.hulage.in` behind the Basic-auth gate; VM run on
  demand.

## 2026-09-13 / 14 — the rebuild

- Rebuilt as an MCP-native agentic RAG with measured retrieval (one
  commit, phases 0–14). `learning/` and `planning/` split out.

## Phases 0–14, in one table

| Phase | What |
| --- | --- |
| 0–8 | Foundation → MCP server → agent loop → hybrid retrieval → eval harness → hardening → interface → Gemini port |
| 9–12 | Index Lab: flat / HNSW / IVF-PQ from scratch, FAISS reference, two-stage rerank, live `ANN_INDEX` switch |
| 13 | Production deploy: prod compose, Caddy edge, preflight, GCP provisioned |
| 14 | Product-grade UI: ⌘K palette, shortcuts, empty states, onboarding, skeletons, toasts |
