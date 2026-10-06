# Next

The queue, in the order it should be taken. Each line says what it needs
before it can start and what it costs; anything with a ₹ or $ figure is
asked for before it runs. Move a line to [`PROGRESS.md`](PROGRESS.md) when it
ships; move it to the bottom section when it is decided against.

## Now — Milestone 21 ([`milestone-21.md`](milestone-21.md))

Planned 2026-10-06. Milestone 20 gave the box an identity and scoped what a
tool returns. This one closes the two doors that scoping does not reach —
both mine, both from this week, both reproduced against a running server —
fixes the two counters that still assume one person, and then puts three
versions of undeployed work on the box.

| # | Step | Needs | Cost | State |
| --- | --- | --- | --- | --- |
| 1 | Two doors the scope does not reach: `/ann/*` bypasses `ScopedHost` **and** `trim()` cannot see a `passages` map keyed by chunk id; `/ingest` lets any caller overwrite any owner's document | — | ₹0 | **shipped** 2026-10-06 (0.8.5) — all three clauses. `trim()` now recognises an **id** rather than a field: as a string value anywhere in an entry, as a mapping *key*, and as a bare string in a list. Every `/ann/*`, `/ingest` and `/upload` call crosses `ScopedHost`; a tool it cannot classify is refused, with `READ_TOOLS \| WRITE_TOOLS` pinned against the live server. Writes are an allow-list where reads are a deny-list (`writable_by` vs `visible_to`), checked *before* the store is touched. **One departure from the pre-registered rule**: an unnamespaced id is writable by `shared` only, not by every authenticated caller — see `milestone-21.md` |
| 2 | Key the rate limiter on the owner, not the IP; give the daily cap a per-owner share under the global ceiling | item 1 first | ₹0 | **shipped** 2026-10-06 (0.8.6) — all three clauses. The per-owner cap sits **under** the global one, never replacing it. Keyed on the owner only when the proxy vouched for the name: an unproven name is a bucket the caller can swap, which is *weaker* than the address it replaced, so that case still keys on the address. `SEXTANT_DAILY_BUDGET_SHARE` (default 1 = off) is the largest fraction of the day one name may take. `/ann/*` gained a rate limit it never had. The spend card shows your own share, or a refusal reads as a bug |
| 3 | Deploy it: 0.8.2 – 0.8.6 + the M19 key rotation | you create and paste the key; VM up | ≈₹2 VM | **ready, waiting on you for the key** — the preconditions are no longer a checklist: `deploy/trip.sh` refuses to build if `SEXTANT_PROXY_SECRET` is missing (every request would 403), prints how many `basic_auth` slots are filled and whether a share is set, and after the build checks a forged `X-Sextant-User` is refused and lists the store's document ids so a pre-0.8.2 `upload:<stem>` shows up by name. What is left is yours: create the Gemini key, and put it plus the second and third `basic_auth` users into the box's `.env`. Succeeds only if two real users upload the same filename from the public URL and both survive, each seeing only their own |
| 4 | Pin every route on one side of the scope boundary | — | ₹0 | **shipped** 2026-10-06 (0.8.7) — unplanned, from asking whether there were more doors while item 3 sat blocked. There were not: every corpus route scopes the host, `/query` included, and `restore()` never looks a client-supplied key up in the store. But nothing stopped the *next* one — the tool list was pinned, the route list was not, and all three defects this milestone fixed were routes. Adding an endpoint now fails the gate until it is declared; a corpus route must call `scoped(`, never `host.call(`, and must be rate limited. Each pin verified by planting the defect it is for. Found one: `/stats`, the last unlimited corpus route, which 0.8.4 had quietly made walk the corpus |
| 5 | Check the park, do not just perform it | — | ₹0 | **shipped** 2026-10-06 — `trip.sh` read the instance's state back and printed it; an offline run of the whole script ended `agenticrag is RUNNING` and exited **0**, and the happy-path test asserted that 0. The checklist became a trap and the trap's result became the new unread line. The stop is now retried once, then compared: a box still up, or an address still reserved at ₹21/day, prints the rate and the manual command on stderr and takes the 0 away — it may only turn a 0 into a 1, never mask a reason. The offline stub was half the defect, answering `RUNNING` to everything, so "the trip parked the box" was not an assertion anyone could write; it keeps state now, and 4 of the 7 new tests fail against the previous script |
| 6 | Check the gate from outside the box | — | ₹0 | **shipped** 2026-10-06 — every check in the trip ran through `docker exec` at `localhost:8000`, inside the box and behind Caddy, so the trip that exists to deploy the gate had never gone through it: a box whose Caddy was misconfigured or not running passed step 5 and reported green. Step 6 runs from the operator's machine against `PUBLIC_URL` — no credentials 401, wrong password 401, a real user 200, a **forged `X-Sextant-Proxy-Auth` 200** (Caddy *sets* the header, so a forged proof that still succeeds is the proxy working; a 403 means it appended and the header is worthless), naming yourself 401. Credentials come from the operator's environment, reach `curl` through a pipe not argv, and are never printed. 8 of 9 new tests fail against the previous script |
| 7 | Prove the isolation itself: two users, one filename, from the public URL | — | ₹0 to write; ≈$0.006 of summaries when it runs | **shipped** 2026-10-06 — milestone 21's pre-registered success criterion is now run by the script instead of by hand with the meter on. The only part of the trip that writes: both gate users upload the same filename through the public URL, each sees their own and not the other's, and the store is read directly to confirm two probe documents under two distinct owners. **Two defects of mine, found by running it:** the forged-name check sat after both uploads, where the two counts agree and it could not fail — it passed against a simulated proxy that forwarded the client's name, and now runs in the one window where the views differ, pinned by position; and the cleanup's failure was swallowed by `|| echo`, so a trip that left two documents in the production corpus exited 0 — item 5's defect in code written the day after item 5. Cleanup is in the EXIT trap, before the stop, and finds documents by scanning for the probe filename rather than rebuilding `upload:<owner>:<stem>`. All 8 new tests fail against the previous script |

**Every number in `learning/` is an unscoped number**: the eval harness builds
a `KnowledgeBase` directly and never crosses the host, so no eval run would
catch a scoping bug. That is correct — the scope is a boundary, not a
retrieval change — and it is why item 1's rule leans on tests.

## Done — Milestone 20 ([`milestone-20.md`](milestone-20.md))

Planned and closed 2026-10-06, ₹0 end to end. "Per-user upload" turned out to be three questions, not
one, plus a defect that exists today with a single corpus. Nothing here
costs money: no VM, no model calls, and `sextant-eval` does not spend.

| # | Step | Needs | Cost | State |
| --- | --- | --- | --- | --- |
| 1 | Namespace upload ids by owner — two people uploading `notes.pdf` destroyed each other's chunks | — | ₹0 | **shipped** 2026-10-06 (0.8.2) — `upload:<owner>:<stem>`, owner from the `X-Sextant-Client` header the frontend sets from a per-browser id; both halves pinned at the store. Namespacing, not isolation — nothing is hidden from search |
| 2 | Decide what a corpus is: metadata filter (A) vs collection-per-corpus (B) vs deployment-per-corpus (C) | — | ₹0 | **decided** 2026-10-06 — **A**, filter pushed inside the dense query. At a 3.1% tenant A is +0.0091 recall@5 behind B and *ahead* on hit@1; the rule passed and could not have failed (filtering only promotes; the answer is at global rank 1). Over-fetch is bounded at `CANDIDATES`=30 regardless. [`../learning/multi-corpus.md`](../learning/multi-corpus.md) |
| 3 | Identity: multiple Caddy `basic_auth` users, the authenticated name forwarded as a header | — | ₹0 | **shipped** 2026-10-06 (0.8.3) — three `basic_auth` slots; `X-Sextant-User` from `{http.auth.user.id}`, believed only alongside `X-Sextant-Proxy-Auth` matching `SEXTANT_PROXY_SECRET`; an unproven name is a 403 in middleware, not a quiet fallback. Verified against a real Caddy (`validate`, `adapt`, and a live two-user proxy rewriting a forged name) |
| 4 | Scope `kb_list` and `kb_stats` to the owner | — | ₹0 | **shipped** 2026-10-06 (0.8.4) — `scope.ScopedHost` trims every result carrying a `document_id` the asker may not see, above the tool boundary and below the model, so no schema ever names a corpus. Deny by default; the shared corpus stays everybody's; `kb_stats` recomputed from the scoped listing. The frontend sent its header on `/upload` only — now on every request, verified in a browser |

**Deploy precondition, new with item 3:** `SEXTANT_PROXY_SECRET` must be in
the box's `.env` **before** this tree is built there. Caddy has no
conditionals — it forwards `X-Sextant-User` regardless, and without the secret
the app cannot verify it and refuses every request with a 403 that names the
variable. The same trip adds the second and third `basic_auth` users.

**Invariant, not up for measurement:** the corpus is never a tool argument.
A `kb_search(corpus=…)` in a discovered schema lets a sentence inside an
uploaded PDF read another person's corpus. Isolation is enforced below the
tool boundary — pinned into the KB subprocess at spawn.

## Open — Milestone 19 ([`milestone-19.md`](milestone-19.md))

| # | Step | Needs | Cost | State |
| --- | --- | --- | --- | --- |
| 1 | Review `ui-redesign/sextant` and port it into `frontend/` | — | ₹0 | **shipped** 2026-09-27 — four post-scan gaps closed first (tables, Markdown export, `sextant.*` storage keys, growing composer); verified live against `:8100`; bundle 61.5 → 186.8 kB gzip after lazy-loading the Lab |
| 2 | Drop the `AGENTICRAG_` env fallback; a leftover is a printed warning, not a silent default | — | ₹0 | **shipped** 2026-09-28 (0.8.1) — done off the box so the trip below is shorter; `settings.legacy_warning()` names every stale variable at startup |
| 3 | Deploy it and rewrite the box's `.env` onto `SEXTANT_*` | VM up | ₹703 spent (≈₹2 of work, ₹701 of a VM left running five days) | **shipped** 2026-09-28 — `.env` rewritten first, tree shipped, stack rebuilt; `/health` reports `budget_usd: 0.6` under the new name, logs clean, new bundle served, two live queries |
| 4 | Rotate the `GEMINI_API_KEY` exposed in a screenshot 2026-09-23 | you create and paste the key; VM up to install it | ≈₹2 VM | **deferred by you 2026-10-03**, now folded into M21 item 3 so one trip carries both. The key is still live |

## Done — Milestone 18 ([`milestone-18.md`](milestone-18.md))

| # | Step | Needs | Cost | State |
| --- | --- | --- | --- | --- |
| 1 | Re-ingest the deployed store on the current pipeline; drop the résumé document | VM up | ₹8 spent (≈₹2 VM, ~$0.07 overviews) | **shipped** 2026-09-27 — 61 chunks/22 docs → 79 chunks/21 docs with 21 overviews, the box rebuilt onto the replacement `_store` first, résumé removed, one live query verified, VM parked and IP released |
| 2 | `--summaries` on by default when a key resolves | — | ₹0 to ship, $0.003/document at upload | **shipped** 2026-09-24 — the key is the switch; `--no-summaries` opts out, no key is a printed line — [`../learning/summary-chunks.md`](../learning/summary-chunks.md) |
| 3 | 0.8: drop the four `agenticrag-*` command aliases, bump the version | — | ₹0 | **shipped** 2026-09-24 — `AGENTICRAG_` env prefix kept, the box's `.env` still uses it |

## Done — Milestone 17 ([`milestone-17.md`](milestone-17.md))

| # | Step | Needs | Cost | State |
| --- | --- | --- | --- | --- |
| 1 | Per-document candidate cap | — | ₹0 | **shipped** 2026-09-17, default 2, guarded — [`../learning/candidate-cap.md`](../learning/candidate-cap.md) |
| 2 | `kb_list` tool: titles, overviews, chunk counts offered to the agent | — | $0.034 | **shipped** 2026-09-20 — lists first on 4/5 global + 3/3 starters, names 100% of expected docs — [`../learning/kb-list.md`](../learning/kb-list.md) |
| 3 | Composer fix deploy — already on `main`, not on the VM | VM start: re-reserve IP, `add-access-config`, new key on the VM | ≈₹4 (40 min up) | **shipped** 2026-09-23 — the box was on a pre-`kb_list` image, so this carried all of M17; live, gated, one query verified |

## Then — candidates, not yet planned

Each becomes a milestone section with a hypothesis and a rule before it
runs; none is started on a hunch.

| Idea | Why it is on the list | Needs | Cost |
| --- | --- | --- | --- |
| Request-level index tier (`exact` flat / `fast` hnsw / `lean` ivfpq_rerank) | caller states a budget, server maps to index + params; only meaningful past ~25k chunks, where HNSW overtakes flat (`../learning/ivfpq-100k.md`) | corpus ≥ 25k | ₹0 |
| Let a person delete their own upload | `sextant-forget` is an operator command on the box; re-uploading replaces but nothing takes a file back. A gap, not a defect — design it against a deployment that has actually had two users | M21 item 3 | ₹0 |

## Decided against (with the reason, so it is not re-litigated)

- **RAPTOR tree** — one level already saturates hit@5 on this corpus; the
  question a tree would serve is a listing (`kb_list`), not a retrieval.
  `../learning/summary-chunks.md`.
- **Swapping MiniLM for bge-small** — +0.09 dense on the survey, −0.04 on
  the handbook, rerank unmoved; opt-in via `SEXTANT_EMBEDDER`.
  `../learning/embedder-swap.md`.
- **150-token chunks** — helps the reranker, hurts dense; the cap has since
  removed the dense cost, so this could be re-measured, but 200 has no
  known miss that 150 fixes. `../learning/chunk-size.md`.
- **Dropping the reranker** — only stage with a calibrated abstention
  score; leads at 1,602 chunks. `../learning/reranker-decision.md`.
- **Cloud Run / scale-out / 24×7 hosting** — embedded Chroma is
  single-writer; run policy is on demand. `milestone-15.md`.
- **HyDE / query expansion** — the generator does not know a personal
  corpus's world: for the vocabulary-free question it wrote a passage about
  a different system; dense worse on both sets, invisible after the
  reranker, and a fabricated passage scores 0.70 against a corpus that
  cannot answer the question. `../learning/hyde.md`.
- **Prompt caching** — the 1,410-token prefix is under the implicit-cache
  minimum (0 of 22 turns hit); an explicit cache works and saves 40% gross
  but 28% net of storage at 5 queries/hour, under the 30% rule, and needs
  re-creating on every prompt or tool change while the deployment idles.
  `cached_tokens` is reported and priced so the number is honest if one is
  ever configured. `../learning/prompt-caching.md`.
- **Floor fallback as a cost feature** — measured on all 55 answerable
  handbook questions, both arms, judged: it is safe (false abstention 1 →
  0, faithfulness 0.936 → 0.960, citations valid in both arms) but it
  **fired on one question of 55**. The pre-registered exposure clause
  failed; every set-level number that moved is one-run nondeterminism, not
  the knob. Closed: the benefit is q29 and the cost is a flag, a branch, a
  prompt paragraph and a mode the model has to reason about.
  `../learning/floor-fallback-cost.md`.
- **Floor fallback as a recall fix** — handing the model the sub-floor
  dense order does not recover q48: the model's phrasing decides whether
  the answer chunk clears 0.01 by 0.003, and below the floor dense cosine
  picks a document's title chunk over its answer paragraph. The knob stays
  (default `none`) for the cost result above. `../learning/floor-fallback.md`.
- **Per-query routing between HNSW and IVF-PQ** — query text carries no
  signal for it, and holding both resident forfeits IVF-PQ's only win
  (memory) while HNSW beats it on recall and latency at every size
  measured. Tier per request, not route per query. `../learning/ivfpq-100k.md`.
- **Keeping the static IP while parked** — ₹21/day for nothing; released
  twice, most recently 2026-09-23 after the composer deploy.

## Shipped, moved out of the queue

- **Make the repo public** — done 2026-09-20, MIT. The standing
  consequence: the VM's IP never goes into a tracked file.
