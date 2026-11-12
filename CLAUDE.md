# sextant — working rules

Rules only, one line each. The story behind every rule is in [`planning/LESSONS.md`](planning/LESSONS.md) under the same heading — read it when a rule is about to be bent, not every session.

## Start here

Read [`planning/PLAN.md`](planning/PLAN.md) first: the goal, the current milestone, the one item in progress, and the reply shape. On direction and length, the plan wins.

## Scope

- Separate from `../atlas` on purpose: never read, copy from, or edit atlas as part of sextant work.
- Infra names (`agenticrag` VM, `agenticrag.hulage.in`, `~/agenticrag` on the box) are unchanged by the rename.

## Git

- `origin` = `github.com/hulagerushikesh/sextant` (public, MIT). `upstream` = the course repo; **never push there**.
- **Every `gh` command needs `--repo hulagerushikesh/sextant`** — `gh` picks `upstream` in this checkout.
- CI runs on `push` to `main` and on `pull_request` only; dispatch a branch with `gh workflow run ci --repo hulagerushikesh/sextant --ref <branch>`.
- Branch first, commit, fast-forward `main`. Commits are autonomous once an aim is stated; deploying is not.
- **Scan staged contents, not filenames, for secrets before every commit** and report the result.

## Secrets

- `GEMINI_API_KEY` is the only key the code reads. `.env` is gitignored and never staged.
- Never type, create or read a credential. The owner runs `deploy/set-secrets.sh`: values on stdin, passwords hashed on the box, a ready-made `BASIC_AUTH_HASH` refused.
- The repo is public: `deploy/env.example` is placeholders only, and the VM's IP, the owner's home IP and the DNS zone id never go into a tracked file.
- `SEXTANT_PROXY_SECRET` must be in the box's `.env` before this tree is built there, or every request is a 403.
- Gemini is prepay with a ₹500/month cap: a 402 "credits are depleted" is an empty balance, not a bad key.
- `SEXTANT_DAILY_BUDGET_USD=0.60` caps the API server only; eval scripts and the ingest CLI bypass it.

## Cost

- **Ask before anything that turns on a meter** — VM start, new cloud resources, paid builds, bulk model calls, downloads — and state the ₹ amount. Billing is in INR.
- The VM is ~₹135/day running, parked by default with no external IP. **Park it in the same turn it is started**; never wait on a human with it up.
- **Use `deploy/trip.sh`, never a sequence of gcloud commands** — it parks on an EXIT trap. `--keep-up` is a decision someone types.
- Start a trip in a Terminal tab, never the chat command box (it kills the process tree, so the trap never fires and the box keeps billing).
- A trip needs `CF_ZONE_ID`, `CF_API_TOKEN`, `SEXTANT_TRIP_AUTH` and `_2` in the owner's environment; the owner types them. Changing a firewall rule is the owner's command.
- `deploy/deploy.sh HOST status` says what is billing. `down` stops serving; `stop` stops paying.
- `sextant-ingest` (with a key), `sextant-judge` and `sextant-eval-agent` spend money and no cap sees it; `sextant-eval` is free and is the only one in the gate.
- `/health` → `budget` is an estimate that reads low against the bill; `durable: false` means the figure is this process's, not the day's. Details: [where the money shows up](planning/LESSONS.md#where-the-money-shows-up).
- Kill CPU-heavy local jobs (eval runs, model loads) at the end of a session.

## Packaging

- One top-level import package, `sextant`; the distribution is `sextant-kb`.
- **Build a wheel and launch it** before trusting a packaging change — an editable install cannot see a packaging defect.
- `settings.repo_root()` is the only thing that knows the tree's shape; it is `None` inside a wheel, where no `.env` is read and the store goes to the user-data directory.
- Versions come from `sextant.__version__`, never a literal. The Dockerfile installs `.[app]`.
- **Publishing to PyPI is the owner's command, never the agent's.**

## Local ports

- `:8100` — this project's API (safe to restart). `:3000` — the Vite dev server (`sextant-frontend` in `.claude/launch.json`).
- `:8000` and `:8001` belong to other projects on this machine. **Do not kill them.**

## Gate before a commit that touches code

```bash
./.venv/bin/pytest tests/ -q && ./.venv/bin/mypy sextant tests && ./.venv/bin/ruff check . && (cd frontend && npm run build && npm test)
```

- Never pipe a gate stage through `tail` — the chain's exit code becomes `tail`'s. Redirect to a log file and read the exit code.

## CI

- **Check CI after every push; a green local gate is a different claim.** Never report a fix from the commit that attempts it — watch the run.
- The frontend linter runs in CI only (it cannot install on this machine), and one warning is a red: **a new frontend file's result is unknown until CI runs.** Read it for unsafe optional chaining first.
- An oxlint suppression goes on the line the rule reports, as the last line before the code, with a `--` reason.
- CI must run every gate command with the same arguments; the runner and every action are pinned. Bumping one is a recorded decision, not a workaround.
- An optional dependency must not decide whether the code type-checks: annotate the name `Any` instead of a `type: ignore`.
- `sextant-eval --check` must grade every baseline mode and the full question count; a missing baseline is a failure.
- When testing a fix, plant the defect back and check the test fails for the right reason.

## Gotchas that recur

**Store and retrieval**

- Chroma goes stale after a CLI ingest: restart `:8100`. Drop one document with `sextant-forget <id>`; empty the store with `rm chroma_db/chroma.sqlite3` and a restart.
- Re-ingesting an id replaces that document: its old chunks are cleared first.
- A collection is stamped with its embedding model and refuses to open under another (`SEXTANT_EMBEDDER`).
- Results are capped at 2 chunks per document (`SEXTANT_MAX_PER_DOCUMENT`); set it to `0` for any experiment's control.
- `server.py` must import faiss before anything that pulls torch, or the subprocess segfaults (exit 139).
- PDFs go through PyMuPDF, with pypdf as fallback only. PyMuPDF is AGPL — flag it before any closed distribution.
- `/upload` answers **200 with `"success": false`** on failure: read the body, not the status code.

**Identity and scope**

- Uploads are stored as `upload:<owner>:<stem>`; `safe_name` and `safe_owner` allow only `A-Za-z0-9._ -`. An id stated through `/ingest`, `kb_forget` or the CLI is not sanitised.
- `X-Sextant-User` (set by Caddy) is trusted only with a matching `X-Sextant-Proxy-Auth`; a name without the secret is a 403, never a fallback. `X-Sextant-Client` is the untrusted fallback.
- **`shared` owns the unnamespaced corpus and may write it.** Anything that defaults to that name defaults to ownership — grep for defaults whenever a name's authority changes.
- Every frontend request sends `X-Sextant-Client` through `sent()` in `lib/api.ts`; no other frontend file calls `fetch`.
- Reads are a deny-list (`visible_to`), writes an allow-list (`writable_by`); a caller writes only its own namespace.
- Every corpus route calls `scoped(host, owner)`, never the global `host`, and is rate limited. A new route must be declared on one side of the scope boundary or the gate fails.
- A tool the scope cannot classify is refused; a new write tool also needs an entry in `scope._WRITE_ARGUMENTS`. **The corpus is never a tool argument.**
- `kb_forget` is registered only when the launcher sets `SEXTANT_REMOVAL_TOOL`; a third-party mount of `sextant-kb` never gets it.
- The rate limiter keys on the authenticated name, else the client address. `SEXTANT_DAILY_BUDGET_SHARE` sits under the global cap, never replacing it.

**Seams between programs**

- **A new HTTP route needs a line in `deploy/Caddyfile`**, or behind the gate it answers `index.html` with a 200. Four path lists are pinned against `main.py`.
- A value inside a URL is escaped as data, per segment (`asPath()`), never with `encodeURI`.
- MCP stdio strips the environment: a variable the subprocess needs goes in `_FORWARDED_ENV` in `mcp_host.py`, or in `_NOT_FORWARDED` with a reason.
- The KB subprocess is sealed (`SEXTANT_ENV_SEALED=1`) and reads no `.env`. Settings are read through `sextant.settings`, never `os.environ` at import time.
- Env names are `SEXTANT_*` only; a leftover `AGENTICRAG_*` is a startup warning and a trip failure.
- Pin a seam in the language its far end is written in, even if that means reading the file as text. A list that mirrors another by hand gets computed or pinned.

**The box and the trip**

- Compose interpolates `$` in `env_file`: bcrypt hashes need `format: raw` (already set). The `"ubyP" variable is not set` lines are noise.
- The api container does not publish 8000: check it with `docker exec agenticrag-api-1 curl -s localhost:8000/health`.
- Trip step 0 checks the ssh door before the meter starts; step 5 judges the box; step 6 checks the gate from outside; step 7 proves isolation and the delete, and is the only step that writes.
- The trip verifies the park and exits non-zero if the box or an address is left billing.

**Model and frontend**

- `gemini-3.1-flash-lite` is the cheapest model that runs the tool loop; `gemini-2.5-flash-lite` passes a probe and fails the loop.
- `FunctionCallingConfigMode.NONE` does not stop a tool call; the turn cap uses the user-role `LAST_TURN_NOTE` instead.
- `frontend/.env.development` sets `VITE_MOCK` only, never `VITE_SERVER_URL`. `VITE_MOCK=1` renders the whole UI with no server, and the mock must always say it is one.
- The gate's `npm run build` runs `tsc -b`, so a type error fails the gate. The Node 20.12 warning from Vite 7 is expected here.
- Browser-pane key presses do not reach the app's handlers: dispatch a `KeyboardEvent` from `javascript_tool`.

## Habits behind the rules

- A check nobody can run, or that nothing calls, is not a check. Run it once before relying on it.
- A printed banner is a claim: read the state back and let it change the exit code.
- A stub must fail loudly on what it cannot represent, so a broken harness never turns a test green.
- A function that can keep less than it was given returns what it kept; a loss that only reaches a log has not been reported.
- A fallback is only as safe as what it falls back to.
- Check a claim before writing it down — including who a fix saved, and including a "not done" note.
- A red CI run is a question: find the cause, and if the mechanism is not understood, write that down as not understood.
