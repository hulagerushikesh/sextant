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
- **Upload ids collide across people** (open defect, live on the box). An
  upload is stored as `upload:<filename stem>`, which is global, and `_store`
  clears a document's existing chunks first. Two people behind the shared gate
  who upload the same filename destroy each other's chunks, silently —
  `/upload` returns success. Fix is milestone 20 item 1; until then, treat the
  deployed store as single-owner.
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
