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
- **Use `deploy/trip.sh`, not a sequence of gcloud commands.** It starts the
  box, deploys, verifies and parks — and parking is an `EXIT` trap, so it also
  happens on failure and on Ctrl-C. A checklist is what failed on 2026-09-28;
  this is the same checklist with the last step made unskippable. Leaving the
  box up takes `--keep-up`, which you have to decide to type.
- Kill CPU-heavy local jobs (eval runs, model loads) at the end of a session.

## Local ports

- `:8100` — this project's API (safe to restart).
- `:8000` and `:8001` belong to other projects on this machine. Do not kill.
- `:3000` — Vite dev server via `.claude/launch.json` (`sextant-frontend`).
  `sextant-api` in the same file runs the agent server on `:8100`.

## Gate before a commit that touches code

```bash
./.venv/bin/pytest tests/ -q && ./.venv/bin/mypy mcp_server tools eval tests && ./.venv/bin/ruff check . && (cd frontend && npm run build)
```

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
- MCP stdio strips the environment: new `SEXTANT_*` knobs the KB needs must
  be added to `_FORWARDED_ENV` in `mcp_host.py` or they silently no-op
  (`test_every_retrieval_knob_crosses_the_process_boundary` pins the latest).
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
