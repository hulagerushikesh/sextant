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

- `origin` = `github.com/hulagerushikesh/sextant` (private). `upstream` =
  the original course repo; **never push there**.
- Branch first, commit, fast-forward `main`. Autonomous commits are fine once
  an aim is stated; deploying to `main` in production is not autonomous.
- **Scan staged contents, not filenames, for secrets before every commit**
  and report the result (`git diff --cached | grep -ciE '...'` → 0 hits).

## Secrets

- `GEMINI_API_KEY` is the only key the code reads. `.env` is gitignored.
- Never type credentials. On the VM the owner runs `set-secrets.sh`; the
  gate password and key are never seen by the agent.
- `deploy/env.example` carries a real `ACME_EMAIL`; strip it before the repo
  goes public.

## Cost

- **Ask before anything that turns on a meter** — VM start/resize, new cloud
  resources, paid builds, bulk model calls — and state the ₹ amount. The VM
  is ~₹135/day running; it is parked (stopped) by default.
- GCP billing account is INR: budget amounts are rupees (`1700` ≈ $20).
- Kill CPU-heavy local jobs (eval runs, model loads) at the end of a session.

## Local ports

- `:8100` — this project's API (safe to restart).
- `:8000` and `:8001` belong to other projects on this machine. Do not kill.
- `:3000` — Vite dev server via `.claude/launch.json` (`sextant-frontend`).

## Gate before a commit that touches code

```bash
./.venv/bin/pytest tests/ -q && ./.venv/bin/mypy mcp_server tools eval tests && ./.venv/bin/ruff check . && (cd frontend && npm run build)
```

## Gotchas that recur

- Chroma segment goes stale after CLI ingest: restart `:8100` to see new
  chunks. To empty the store: `rm chroma_db/chroma.sqlite3` and restart.
- faiss + torch OpenMP: `server.py` must import faiss before anything that
  pulls torch, or the KB subprocess segfaults (exit 139).
- PDFs go through PyMuPDF (`loaders._page_lines`), not pypdf: pypdf guesses
  word spacing from glyph gaps and fused 3% of arXiv 2303.18223v19. pypdf is
  the fallback only. PyMuPDF is AGPL — flag before a closed distribution.
- A Chroma collection is stamped with the embedding model that built it and
  refuses to open under another (`SEXTANT_EMBEDDER`). MiniLM and bge-small
  are both 384-d, so without the stamp a mismatch would be silent.
- MCP stdio strips the environment: new `SEXTANT_*` knobs the KB needs must
  be added to `_FORWARDED_ENV` in `mcp_host.py` or they silently no-op.
- Docker Compose interpolates `$` in `env_file` — bcrypt hashes need
  `format: raw` (already set in `docker-compose.prod.yml`).
- `gemini-2.5-flash-lite` passes a one-shot probe and fails the tool loop
  (400 "tool call context circulation"); `gemini-3.1-flash-lite` is the
  cheapest model that actually runs it.
- `FunctionCallingConfigMode.NONE` does not stop gemini-3.1-flash-lite from
  calling a tool: the turn ends `MALFORMED_FUNCTION_CALL` with no text. The
  agent's turn cap uses a user-role note (`LAST_TURN_NOTE`) instead.
- `sextant-ingest --summaries` spends money too (one model call per document,
  ~$0.003 each; the 144-page survey is ~$0.05) and needs the key in `.env`.
- `sextant-eval-agent` spends money (~$0.04 / 29 questions); `sextant-eval`
  does not. Only the latter is in the gate.
- Browser-pane synthetic key presses don't fire the app's key handlers; test
  shortcuts by dispatching `KeyboardEvent`s from `javascript_tool`.
