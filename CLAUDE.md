# sextant — working rules

Standing rules for anyone (human or agent) working in this repo. They exist
because each one was learned the expensive way.

## Scope

- This project is deliberately separate from `../atlas`. Do not read, copy
  from, or edit atlas as part of sextant work. The differentiator here is
  MCP-native tool servers plus retrieval you can measure; duplicating atlas
  would make the project pointless.
- Infra names (`agenticrag` VM, IP, `agenticrag.hulage.in`, `~/agenticrag` on
  the box) are unchanged after the rename — they name things that exist.

## Git

- `origin` = `github.com/hulagerushikesh/sextant` (public since 2026-09-20, MIT). `upstream` =
  the original course repo; **never push there**.
- Branch first, commit, fast-forward `main`. Autonomous commits are fine once
  an aim is stated; deploying to `main` in production is not autonomous.
- **Scan staged contents, not filenames, for secrets before every commit**
  and report the result (`git diff --cached | grep -ciE '...'` → 0 hits).

## Secrets

- `GEMINI_API_KEY` is the only key the code reads. `.env` is gitignored.
- Never type credentials. On the VM the owner runs `set-secrets.sh`; the
  gate password and key are never seen by the agent.
- `deploy/env.example` is placeholders only; keep it that way, the repo is
  public.
- Gemini billing is AI Studio **prepay** with a ₹500/month cap: a 402
  "prepayment credits are depleted" means the balance is empty, not that
  the key is bad. The owner tops up; nothing to fix in code.
- `SEXTANT_DAILY_BUDGET_USD=0.60` is set in the local `.env` and belongs on
  the VM's too; it caps the API server only — eval scripts bypass it.

## Cost

- **Ask before anything that turns on a meter** — VM start/resize, new cloud
  resources, paid builds, bulk model calls — and state the ₹ amount. The VM
  is ~₹135/day running; it is parked (stopped) by default, with **no external
  IP** since 2026-09-17 — `deploy.sh start` refuses until one is reattached.
- GCP billing account is INR: budget amounts are rupees (`1700` ≈ $20).
- **Park the box in the same turn it is started.** A trip that ends waiting on
  a human — a key to paste, a decision — parks first and restarts later.
  Restarting costs ₹2; on 2026-09-28 a box left running while waiting for a
  key rotation billed **₹703 over 125.5 hours**, against a ₹50-100/day cap.
- **Two doors to the meter, one check.** `deploy/deploy.sh HOST start` is the
  other command that starts the box. It had neither of `trip.sh`'s
  protections: no door check, and an ssh wait that ended either way and then
  printed `>> up at <ip>` regardless, leaving an unreachable box billing with
  a reminder to stop it by hand -- the 2026-09-28 shape in the script the fix
  for it never touched. `ssh_door` now lives in `deploy/lib.sh` and both use
  that one copy; `start` verifies ssh for real and stops the box if it never
  answers. **A door check that exists in one of two scripts is a door check in
  neither.**
- **Use `deploy/trip.sh`, not a sequence of gcloud commands.** It starts the
  box, deploys, verifies and parks — and parking is an `EXIT` trap, so it also
  happens on failure and on Ctrl-C. A checklist is what failed on 2026-09-28;
  this is the same checklist with the last step made unskippable. Leaving the
  box up takes `--keep-up`, which you have to decide to type.
- Kill CPU-heavy local jobs (eval runs, model loads) at the end of a session.

### Where the money shows up

Three places, and only one of them is the bill.

| Where | What it is |
| --- | --- |
| **AI Studio / Google billing** | the **actual** charge. Prepay with a Rs500/month cap; a 402 "prepayment credits are depleted" is an empty balance, not a bad key. The authoritative number for any month. |
| `/health` -> `budget` | sextant's own running total for the UTC day: `spent_usd`, `remaining_usd`, `budget_usd`, `resets_in_seconds`, plus `owner_*` when a share is set. `durable: false` means the ledger could not be read or written, so that figure is this process's spend and **not the day's**. |
| the structured log | `cost_usd` per query (and `agent_cost_usd`, `agent_cached_tokens`) -- the per-query breakdown behind the daily total. |

What `/health` does **not** include, so it always reads low against the bill:

- **CLI ingest and eval runs are separate processes.** `sextant-ingest` and
  `sextant-judge` spend real money and no cap or tally sees it. Summaries cost
  about $0.003/document at upload. `sextant-eval` spends nothing -- retrieval
  is local.
- It is an **estimate** from a hard-coded table, `PRICING_AS_OF` in
  `mcp_server/pricing.py`, currently `2026-08` and priced for
  gemini-3.1-flash-lite ($0.25 / $1.50 per Mtok). Bump `SEXTANT_MODEL` without
  bumping those and the number understates the bill.
- **Grounded search is priced per request** at $0.014, ignoring the
  5,000/month free allowance, so grounded answers *over*state early in a month.
  Wrong in the safe direction on purpose.
- **VM time is a different line entirely** -- GCP compute, ~Rs5.6/hour running,
  disks while parked. `deploy/deploy.sh HOST status` says what is billing.

The day's tally is persisted to `.sextant-spend.json` in the Chroma directory
so a deploy or a restart does not begin the day again at zero; before
2026-10-08 it was in memory only, which made the cap a limit per process
lifetime rather than per day.

## Local ports

- `:8100` — this project's API (safe to restart).
- `:8000` and `:8001` belong to other projects on this machine. Do not kill.
- `:3000` — Vite dev server via `.claude/launch.json` (`sextant-frontend`).
  `sextant-api` in the same file runs the agent server on `:8100`.

## Gate before a commit that touches code

```bash
./.venv/bin/pytest tests/ -q && ./.venv/bin/mypy mcp_server tools eval tests && ./.venv/bin/ruff check . && (cd frontend && npm run build)
```

## CI

- **Check CI after a push. The local gate passing is a different claim.** From
  2026-09-20 to 2026-10-07 every push was red on one line, 30 runs, and because
  the type check runs first `pytest` and `sextant-eval --check` never ran in
  those 17 days while five commits reported "gate green" from the local
  commands. `gh run list --repo hulagerushikesh/sextant --limit 5`.
- **An optional dependency must not decide whether the code type-checks.**
  `ignore_missing_imports = true` plus `warn_unused_ignores = true` means a
  `type: ignore` needed when a package is installed is an *error* when it is
  not. That is what broke the 30 runs: `faiss` is the `bench` extra, CI installs
  `[dev]`. Annotate the name `Any` rather than ignoring the assignment --
  `follow_imports = "skip"` types the module as `Module`, not `Any`, and does
  not help. Check both ways: plain `mypy`, and `mypy --no-site-packages`.
- **The frontend linter runs in CI only, and that is not a preference.**
  `npm run lint` (oxlint) was configured and committed at the UI port and
  invoked by nothing until 2026-10-09, so its result was *unknown*, not green.
  The first run said **11 warnings, 0 errors** across 47 files — and oxlint
  exits 0 on warnings, so adding the step as it stood would have bought a tick
  that cannot go red. `denyWarnings` is in `.oxlintrc.json` so a hand run makes
  the same claim CI does, each of the eleven is now a decision (a scoped
  override for the vendored `components/ui` tree, three in-line judgements with
  reasons, one constant moved to `components/lab/series.ts` because the rule
  was right), and `reportUnusedDisableDirectives` reports a suppression that
  stops being needed. It is **not in the local gate**: npm 10.5.0 on this
  machine will not install oxlint's platform binding even though the lockfile
  carries it with matching `os`/`cpu` (npm/cli#4828 — `npm ci`,
  `npm install --save-optional` and a clean reinstall all leave
  `node_modules/@oxlint` absent), and a gate must not claim a check the machine
  cannot run. A new suppression needs a `--` reason or
  `TestTheFrontendLinterRuns` fails.
- **An oxlint suppression goes on the line the rule reports, and the reason
  goes above it.** Established from three CI runs, not from convention. A
  multi-line reason breaks `-disable-next-line` — the "next line" becomes the
  second comment line — so the directive must be the *last* line before the
  code, with any explanation in plain comments above it. And
  `react/exhaustive-deps` reports at the closing `}, [deps])` line, where
  ESLint's convention also puts it, while `react/set-state-in-effect` reports
  at the statement. Put one in the wrong place and
  `reportUnusedDisableDirectives` says so — which is how this was found.
- **The offline `trip.sh` run is cross-platform now, and was not.** Step 3's
  tar used `--no-fflags` / `--no-mac-metadata`, which are BSD-only, and GNU tar
  *exits* on an unknown flag -- so the offline harness added 2026-10-06 could
  only ever pass on a Mac, and ten tests failed the moment CI reached them.
  Flags come from `tar --version`; the Mac ones are still passed there.
  `_run_trip(..., gnu_tar=True)` presents a GNU tar so the gate covers Linux.
- **CI must run every program the gate runs**, pinned by
  `TestCiRunsWhatTheGateRuns`, which reads the gate out of this file. CI ran
  three of its four commands until 2026-10-07: `npm run build` runs `tsc -b`,
  so a frontend type error failed only by hand.
- **And with the same arguments, which is the actual claim.** The pin above
  matches program *names*, so a CI step narrowed from
  `mypy mcp_server tools eval tests` to `mypy mcp_server` keeps the green tick
  while type-checking **one tree of four** -- checked, that pin passes it. Item
  14's shape exactly: same program, different claim.
  `TestCiRunsTheGateWithTheSameArguments` compares the arguments too. CI may run
  *more* of a command (`npm ci && npm run build`) and may not run less.
- **The gate's environment is chosen here, not by GitHub.** Items 12 and 13 were
  both the environment deciding whether the check ran. The third instance was
  the only one announced in advance, and announced on every single run: five
  actions targeted the deprecated Node 20 and were being force-run on Node 24,
  and `ubuntu-latest` migrates to Ubuntu 26.04 **gradually from 2026-10-19 to
  2026-11-19** (actions/runner-images#14748) -- which for a month makes the same
  commit pass or fail depending on which image it drew. Both warnings were
  produced by CI and read by nobody, which is item 11 in the repository's own
  check. The runner and every action are pinned to versions the gate has
  actually passed on; `.github/dependabot.yml` turns the next deprecation into a
  pull request rather than a line in a log; and
  `TestTheGatesEnvironmentIsChosenHere` fails the gate if any of that floats
  again. **Bumping is a decision someone records, so the pins are meant to be
  edited, not routed around.**
- **`sextant-eval --check` must grade the whole gate, and now proves it.**
  `--check` guarded `--store` and `--golden` but not `--modes`, so
  `--check --modes dense` graded one mode of four and printed "no regressions";
  and the baseline's `questions` count was never compared, so **deleting 60 of
  the 65 golden questions passed** (a shorter set raises every metric). It fails
  now on an ungraded baseline mode, a no-longer-reported baseline metric, a
  shorter golden set, or a missing `baseline.json` -- **no baseline is a
  failure, not a pass.** `tests/test_eval_gate.py`.
- **Plant the defect, and check the plant fails for the right reason.** A first
  plant here showed 12 of 16 tests failing, which was worthless: the signature
  had changed and most of them were `TypeError`. Revert the *body* behind the
  new signature so the logic is the only difference, then count.
- **A stub that cannot start must say so.** `_run_deploy` never set `FAKE_BOX`,
  so the ssh stub's first line was `cd ""` -- **bash 5.2 accepts that as a
  no-op, bash 5.3 calls it a null directory and fails.** Ubuntu 24.04 ships
  5.2.21, 26.04 ships 5.3.9, so the stub answered every command here and none
  on the image CI is migrating to. Two tests went red, which is how it was
  found; the worse half is the four that stayed **green while the stub was
  dead** -- including the two that assert an unreachable box gets parked rather
  than left billing, which passed with `FAKE_SSH_DEAD` forced to 0. Answering
  nothing is indistinguishable from answering correctly to any test whose
  expectation is a failure. The stub uses `:?` now, and
  `TestTheSshStubCannotFailQuietly` pins that `FAKE_SSH_DEAD` still decides the
  outcome. Third instance of the item 13 shape, after BSD vs GNU tar.
- **A counter that resets is not a cap on a day.** `DailyBudget` kept the UTC
  day's spend in memory, so every deploy and every `restart: unless-stopped`
  bounce began the day at zero. It persists to `.sextant-spend.json` in the
  Chroma directory now -- **inside** it, because the box mounts
  `/data/chroma:/data/chroma`, so `/data` does not survive a rebuild and
  `/data/chroma` does. `/health` reports `budget.durable`; `trip.sh` fails on
  false and only notes an absent key.

## Gotchas that recur

- Chroma segment goes stale after CLI ingest: restart `:8100` to see new
  chunks. To drop one document: `sextant-forget <id>` (`--list` for the ids,
  `-y` to skip the confirmation). To empty the store:
  `rm chroma_db/chroma.sqlite3` and restart.
- Re-ingesting a document is a replacement: `_store` clears its existing
  chunks first. Without that an upsert replaces `<doc>#<n>` one for one and a
  document that now makes fewer chunks leaves the surplus embedded and
  searchable (measured: 11 → 1 left ten stale chunks holding the top hits).
  Removal is a command, never an MCP tool — the model gets read tools only.
- Uploads are stored as `upload:<owner>:<stem>` since 0.8.2, not
  `upload:<stem>`. The owner comes from the `X-Sextant-Client` header the
  frontend sends (a random per-browser id in localStorage), or `shared` when
  nothing sends one — so curl, the eval harness and the CLI all land in one
  namespace, as before. **This is namespacing, not isolation**: it stops two
  people behind the shared gate silently deleting each other's chunks, and it
  hides nothing from anyone's search. That header stays untrusted by
  construction — it is the fallback when nothing better is available.
  `/ingest` is still not *namespaced* — its caller states the id outright —
  but since 0.8.5 the id it states has to be one it owns (see below).
- Since 0.8.3 there is a second, *trusted* name: `X-Sextant-User`, set by
  Caddy from `{http.auth.user.id}` and believed only when
  `X-Sextant-Proxy-Auth` matches `SEXTANT_PROXY_SECRET`. A name without the
  matching secret is a **403**, never a quiet fallback. **`SEXTANT_PROXY_SECRET`
  must be in the box's `.env` before this tree is built on it** — Caddy has no
  conditionals, so it forwards the name regardless and every request is refused
  until the secret exists. Same shape of prerequisite as the 0.8.1 rename, and
  the 403 names the variable. `deploy/Caddyfile` has three `basic_auth` slots;
  empty ones vanish before parsing (`caddy validate`), a user without its hash
  stops Caddy. `tests/test_deploy_config.py` pins the header names on both
  sides, because renaming one in Python breaks nothing a Python test can see.
- Since 0.8.4 what a tool returns is **scoped to the asker**:
  `mcp_server/scope.ScopedHost` wraps the process-global host per request and
  drops any entry carrying a `document_id` the owner may not see. Deny by
  default — it trims every result, not a named list of tools. A document is
  visible unless it is an `upload:<someone else>:*`, so the CLI-ingested
  corpus stays shared; `shared` is scoped like any other name or the whole
  thing is bypassable by dropping a header. `kb_stats` is *recomputed* from
  the scoped listing (so `/stats` now triggers a listing, which warms the
  index). The filter cannot move into the KB: an MCP tool's parameters become
  its discovered schema, and **the corpus must never be a tool argument** —
  `tests/test_scope.py::TestTheInvariant` pins that. `collection_size` on a
  *search* result is knowingly left whole-store; `agent.py` reads it.
- Since 0.8.5 the scope recognises an **id**, not a field: as a string value
  anywhere in an entry, as a *key* of a mapping (`kb_ann_compare`'s `passages`),
  and as a bare string in a list (`exact`, `missed`). 0.8.4 knew only the first,
  and only when the field was called `document_id` — so `/ann/compare` leaked
  every tenant's titles and opening 200 characters, and routing it through
  `ScopedHost` alone would not have stopped it. The check is anchored on
  `upload:<owner>:<stem>`, so prose mentioning an id is not an id; over-trimming
  would delete content and look like the feature working. Every `/ann/*`,
  `/ingest` and `/upload` call now crosses `ScopedHost`, and a tool it cannot
  classify is **refused** — `READ_TOOLS | WRITE_TOOLS` is pinned against the
  live server in `tests/test_scope.py`.
- **Writes are an allow-list where reads are a deny-list** (`identity.writable_by`
  vs `visible_to`), since 0.8.5. Re-using an id replaces that document, so a
  write is a delete first: before this, any gated user could `/ingest`
  `upload:<someone else>:<stem>` and the victim went on citing the forged text
  as their own file. A caller may write only its own namespace, and the check
  happens *before* the store is touched. `shared` — curl, the eval harness, a
  box with no identity — still owns the unnamespaced corpus, so nothing that
  worked before changed; an *authenticated* caller does not inherit it, and
  seeding the shared corpus stays `sextant-ingest`, which constructs
  `KnowledgeBase` directly on the box and never crosses the host.
- Every frontend request carries `X-Sextant-Client` via the `sent()` helper in
  `lib/api.ts`, not just `/upload`. Leave it off one call and that call is
  answered as the anonymous `shared` caller — which, since 0.8.4, means the
  browser stops seeing its own uploads.
  `tests/test_deploy_config.py::TestTheBrowserSendsWhatTheAppReads` pins it:
  the name `identity.py` declares appears in `api.ts`, in one place, every
  `fetch` in that file routes its headers through `sent()`, and no other
  frontend file calls `fetch` at all.
- **A seam is pinned on the side you can read, which is the side that is not
  the problem.** Three headers cross a process boundary; two had their other
  end in `deploy/Caddyfile` and were pinned the day they shipped.
  `X-Sextant-Client`'s other end is TypeScript, so for three versions it
  existed in exactly two files and no test named it. Renaming `CLIENT_HEADER`
  left 143 tests in `test_api.py`, `test_observability.py` and `test_scope.py`
  green — they take the constant — while every browser silently became
  `shared`, which is the defect 0.8.2 shipped to fix. Pin the seam in whatever
  language the far end is written in, even when that means reading it as text.
- Since 0.8.6 the rate limiter keys on the **authenticated** name
  (`user:<name>`) and on the client address (`ip:<addr>`) otherwise — prefixed
  so the two cannot collide. Not a fallback, a choice: an *unproven* name is a
  bucket the caller can swap by retyping a header, which is weaker than the
  address it would replace. `identity.resolve()` returns `Identity(name,
  trusted)`; `owner_of` is the name half.
- `SEXTANT_DAILY_BUDGET_SHARE` (0.8.6, default `1` = off) is the largest
  fraction of `SEXTANT_DAILY_BUDGET_USD` one authenticated name may spend in a
  day. It sits **under** the global cap, never replacing it — the cap is the
  wallet guarantee a leaked gate cannot get past, the share stops the first
  user of the day silencing everybody else. Applied only to a vouched-for
  name; an untrusted caller's spend still counts against the day but is not
  attributed. A share below 1 leaves part of the cap unspendable when one
  person is asking, which is why the default is off and the value belongs in
  the box's `.env`. `/health` reports the asker's own share, and the spend
  card tracks it — without that, being refused while the card shows money left
  reads as a bug.
- Every HTTP route is pinned on one side of the scope boundary since 0.8.7
  (`TestEveryRouteIsOnOneSideOfTheBoundary`): adding an endpoint fails the
  gate until it is declared as one that reaches the corpus or one that does
  not, and a corpus route must call `scoped(host, owner)` -- never the
  process-global `host` -- and must be rate limited. Both 0.8.5 doors and the
  0.8.6 one were *routes*; only the tool list had been pinned.
- `/stats` is rate limited since 0.8.7: scoping it in 0.8.4 made it recompute
  from a full listing, so it walks the corpus and is no longer the cheap read
  its missing limit assumed. The UI calls it once a page load, never polls.
- `/upload` answers **200 with `"success": false`** for an unreadable file, an
  unavailable tool or a failed ingest. The status code only says the request
  arrived, so anything checking an upload must read `success` /
  `documents_added` out of the body -- `trip.sh` step 7 compared the code and
  reported a tick for uploads that stored nothing.
- `deploy/trip.sh` **step 7 proves the isolation and is the only part that
  writes.** Both gate users upload the same filename through the public URL;
  each must see their own and not the other's; then the store is read directly
  for two probe documents under two distinct owners. **The forged-name check
  runs between the two uploads, never after** -- afterwards both counts are the
  same number and the check cannot fail, which is how the first draft passed
  against a proxy that forwarded the client's name. The probes are removed in
  the EXIT trap before the stop, found by *scanning* for the filename rather
  than rebuilding `upload:<owner>:<stem>`, and anything left behind exits
  non-zero. Needs `SEXTANT_TRIP_AUTH` and `_2`; costs ~$0.006 of summaries.
- `deploy/trip.sh` **checks the gate from outside the box** (step 6, since
  2026-10-06). Every other check in it runs through `docker exec` at
  `localhost:8000`, which is behind Caddy -- so the trip that deploys the gate
  had never gone through it, and a misconfigured or stopped Caddy reported
  green. The row that matters: a real user sending a **forged
  `X-Sextant-Proxy-Auth` must get 200**, because `header_up` is a *set* and the
  client's copy is replaced before the app sees it. A 403 there means Caddy
  appended instead, and the header is worthless. Credentials come from
  `SEXTANT_TRIP_AUTH` / `_2` in the operator's environment, reach curl through
  a pipe not argv, and are never printed; unset is a skip, a missing
  `PUBLIC_URL` is a failure. Still unproven: the isolation *behind* the gate --
  every check in step 6 is a read.
- `deploy/trip.sh` **step 5 judges every result it prints** (since
  2026-10-07). It used to produce six and read one. Both containers must be
  present and `Up` **by name** -- the table was printed and never read, so a box
  whose **Caddy had exited** passed step 5, and every other check there goes
  through `docker exec` at `localhost:8000`, behind Caddy, so none of them can
  see that. Step 6 covers it only when the operator exported credentials, and
  unset is a skip. `status` / `mcp` / `model` / `budget_usd` are each named when
  wrong, all at once rather than the first; `model=` in particular is the key
  rotation's success criterion and was printed and stepped over. The store check
  is a **floor, not a number** (hardcoding 21 would make every ingest a
  failure). A leftover `AGENTICRAG_*` name in the log is a counted failure, not
  a note.
- `deploy/trip.sh` **step 5's forged-name check is counted, not just printed**
  (since 2026-10-07). It asks the api container whether it believes an
  unvouched `X-Sextant-User`; the answer fed no counter, so a trip could deploy
  0.8.3+, find that a client can still name itself, and exit **0** with the box
  reported shipped. Counted only when a deploy happened — on `--no-deploy` the
  answer describes the box as it already is, and a pre-0.8.3 box answering 200
  is correct. `GATE_FAILURES` is initialised at the top of the script, not in
  step 6: step 6 runs *after* step 5 and used to zero the count before anything
  read it.
- `deploy/trip.sh` **step 0 checks the ssh door before the meter starts.**
  Port 22 is open to one `/32` on the `agenticrag-ssh` rule, and a home ISP
  moves that address whenever it likes. On 2026-10-07 a trip reserved an
  address, started the box, waited two minutes for an ssh that could not
  arrive, printed `ssh never came up` — the symptom, and nothing about the
  cause — and then, because `--keep-up` was typed, **left it billing with
  nothing deployed**. Both halves of the answer were readable from the laptop
  for free, before anything was started. Step 0 compares them by *containment*
  (a wider CIDR is still an open door) and prints the `firewall-rules update`
  that fixes it; the address is read at run time from `VM_MY_IP_URL` and never
  stored, because the repo is public. **Three outcomes, not two** — a dead
  address service says `door not checked` and the trip carries on, since a
  flaky third party must not be able to ground the box.
- **`--keep-up` does not keep up a box nothing can reach** (since 2026-10-07).
  It means *leave it up, I am going to work on it*, which presumes you can
  reach it; `SSH_UP` is set when ssh answers and the exemption requires it, so
  Ctrl-C during the ssh wait parks too. Changing a firewall rule is **the
  owner's command, not the agent's** — auto mode refuses it as an infra
  change, which is correct; the script prints the command to run.
- `deploy/trip.sh` **verifies the park, it does not just perform it.** The
  stop is `|| true` (a trap that aborts half way leaves the address reserved),
  so the state is read back, retried once if it is not `TERMINATED`, and then
  *compared*: a box still up, or an address still reserved, prints the rate and
  the manual command on stderr and makes the script exit non-zero. 0 is how a
  person reads "parked". Until 2026-10-06 the readback was only printed, and an
  offline run ended `agenticrag is RUNNING` with exit 0 -- the 2026-09-28 ₹703
  failure one level down. The check may only turn a 0 into a 1, never mask a
  reason. `--keep-up` is exempt: that one is typed on purpose.
- `/ann/benchmark` and `/ann/compare` are rate limited since 0.8.6. They were
  the only routes with no limit, and an index build over every vector is the
  heaviest thing the box does.
- faiss + torch OpenMP: `server.py` must import faiss before anything that
  pulls torch, or the KB subprocess segfaults (exit 139).
- PDFs go through PyMuPDF (`loaders._page_lines`), not pypdf: pypdf guesses
  word spacing from glyph gaps and fused 3% of arXiv 2303.18223v19. pypdf is
  the fallback only. PyMuPDF is AGPL — flag before a closed distribution.
- A Chroma collection is stamped with the embedding model that built it and
  refuses to open under another (`SEXTANT_EMBEDDER`). MiniLM and bge-small
  are both 384-d, so without the stamp a mismatch would be silent.
- Env names are `SEXTANT_*` only since 0.8.1 — the `AGENTICRAG_*` fallback is
  gone. A leftover is not read and not silent: `settings.legacy_warning()` is
  printed by the agent server and the ingest CLI with the name to move it to.
  **The deployed box's `.env` must be rewritten before this tree is built on
  it**, or the container loses its budget cap and CORS allowlist to defaults.
- MCP stdio strips the environment: anything the KB subprocess needs must be
  in `_FORWARDED_ENV` in `mcp_host.py` or it silently no-ops. The client builds
  `get_default_environment() | params.env`, and on POSIX that default is HOME,
  LOGNAME, PATH, SHELL, TERM, USER -- so that list is the whole of what the
  subprocess knows about the box. **The rule above used to read "new `SEXTANT_*`
  knobs", and the test guarding it was called `every_retrieval_knob` and named
  three of seven.** Both were true and both were too narrow, which is how
  `HF_HOME` was dropped for three versions: the image bakes 180 MB of weights
  into `/opt/models` and sets `HF_HUB_OFFLINE=1` so the first query does not
  download them, the models load *in the subprocess*, and neither name crossed
  -- so the child resolved `$HOME/.cache/huggingface`, found it empty, and
  downloaded them into a path that dies with the container. A cache path is not
  a retrieval knob, and the category in the rule decided what got checked.
  Three declared lists now, and `TestEveryVariableTheSubprocessNeedsCrosses`
  scans both sides of the seam: every variable named under `tools/`, and every
  variable the `Dockerfile` or the compose `api` service sets, must be
  forwarded or be in `_NOT_FORWARDED` **with a reason** -- and an exemption
  whose variable nothing reads or sets any more fails too, so the table cannot
  fossilise.
- **Name a pin after the boundary it guards, not after the kind of thing you
  were thinking about.** `every_retrieval_knob` is a test that cannot grow: the
  next variable to cross that boundary was not a retrieval knob, so nobody
  broke the test and nobody noticed. The same sentence is in `CLAUDE.md`'s own
  history -- `_FORWARDED_ENV` was documented as being for `SEXTANT_*` names.
  A scan driven off the declared list has no category to fall outside of.
- Results are capped at 2 chunks per document (`SEXTANT_MAX_PER_DOCUMENT`,
  dense + rerank only, score-guarded). Set it to `0` for any experiment's
  control, or dense numbers will not match notes written before 2026-09-17.
- Docker Compose interpolates `$` in `env_file` — bcrypt hashes need
  `format: raw` (already set in `docker-compose.prod.yml`). A side effect:
  every compose command on the box prints `The "ubyP" variable is not set`
  four times, because compose's *YAML* interpolation pass still reads `$ubyP`
  out of the hash. The container gets the raw value (checked: 60 chars, `$2a$`
  prefix, gate returns 401). Noise, not damage — pipe it through `grep -v ubyP`.
- The api container does not publish 8000 to the host. Verify it from inside:
  `docker exec agenticrag-api-1 curl -s localhost:8000/health`, not
  `curl localhost:8000` over ssh (that returns HTTP 000).
- `gemini-2.5-flash-lite` passes a one-shot probe and fails the tool loop
  (400 "tool call context circulation"); `gemini-3.1-flash-lite` is the
  cheapest model that actually runs it.
- `FunctionCallingConfigMode.NONE` does not stop gemini-3.1-flash-lite from
  calling a tool: the turn ends `MALFORMED_FUNCTION_CALL` with no text. The
  agent's turn cap uses a user-role note (`LAST_TURN_NOTE`) instead.
- `sextant-ingest` spends money when a key resolves: overviews are the default
  since 0.8 (one model call per document, ~$0.003 each; the 144-page survey is
  ~$0.05). `--no-summaries` for a free ingest; no key is also free, with a note.
- `sextant-eval-agent` spends money (~$0.04 / 29 questions); `sextant-eval`
  does not. Only the latter is in the gate.
- Browser-pane synthetic key presses don't fire the app's key handlers; test
  shortcuts by dispatching `KeyboardEvent`s from `javascript_tool`.
- The frontend is TypeScript + Tailwind v4 + shadcn since 2026-09-27; the gate's
  `npm run build` now runs `tsc -b` first, so a type error fails the gate.
- `frontend/.env.development` sets `VITE_MOCK` only. It deliberately does not set
  `VITE_SERVER_URL`: a tracked value there outranks a developer's gitignored
  `.env.local` and silently points the UI at the wrong port (it pointed this
  machine at `:8000` instead of `:8100` for exactly one commit). The default
  lives in `lib/api.ts`; the override lives in `.env.local`.
- `VITE_MOCK=1` renders the whole UI from `lib/mock.ts` with no server. Useful
  for design work, and the mock answer exercises every renderer construct on
  purpose — including a table — so a construct is never shipped unseen.
- Vite 7 warns `You are using Node.js 20.12.2. Vite requires Node.js version
  20.19+` on this machine. It builds anyway; production builds on
  `node:22-alpine`. The day that warning becomes an error, the gate breaks here
  before production does.
