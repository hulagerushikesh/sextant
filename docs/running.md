# Running it

Setup, every setting, the HTTP routes and the repository layout.

> Moved here from the README on 2026-11-12 so the front page could open with a
> quickstart. The text is unchanged apart from link paths.

## Setup

### Docker

```bash
docker compose up --build
```

The API on `:8000`, the UI on `:3000`, and the collection on a named volume so
ingested documents survive `docker compose down`. The knowledge-base MCP server
is not a service — it is a stdio subprocess of the agent server, and giving it a
container would mean inventing a network transport the protocol does not need.

The image bakes both models in, so the first query does not silently download
180 MB and appear to hang. That makes the image large; the build is the slow
part, not the run.

### From source

Requires Python 3.11+ and Node 18+.

```bash
python3 -m venv .venv && ./.venv/bin/pip install -e ".[dev]"
```

```bash
cd frontend && npm install
```

Copy `.env.example` to `.env` and add your Gemini key. It is the only key the
project needs — web search runs server-side on the same credential.

```bash
cp .env.example .env
```


## Running

```bash
./start_all_services.sh
```

| Service | URL |
| --- | --- |
| Frontend | http://localhost:3000 |
| Agent API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| Discovered tools | http://localhost:8000/tools |

It waits for `/health` before printing that table, and exits non-zero —
having stopped whichever half did start — if either one does not come up.
Three knobs, because the defaults are right for the project and wrong for
somebody: `PY` (interpreter), `PORT` (if :8000 is taken, `PORT=8100
./start_all_services.sh`, and point the UI at it with `VITE_SERVER_URL` in
`frontend/.env.local`), and `HOST`.

`HOST` is `127.0.0.1` and should stay there. Nothing authenticates this
process: the gate is Caddy's `basic_auth` and Caddy only runs on the
deployed box, so without `SEXTANT_PROXY_SECRET` every caller is `shared` —
which owns the indexed corpus and can overwrite it. Binding wider hands
anyone who can reach the port your documents through `/query`, on your
Gemini key.

The knowledge-base server is not started here — the agent server launches it as a
stdio subprocess and owns its lifetime.

Index files — PDF, Markdown or plain text:

```bash
./.venv/bin/sextant-ingest ~/papers/survey.pdf --category paper
```

```bash
./.venv/bin/sextant-ingest ~/notes -r
```

```bash
./.venv/bin/sextant-ingest ~/papers -r --no-summaries   # text only; overviews are on when GEMINI_API_KEY resolves
```

Take one back out — a document ingested by mistake, or one that should never
have been in a shared store:

```bash
./.venv/bin/sextant-forget --list          # ids, chunk counts, titles
./.venv/bin/sextant-forget resume-2024     # asks first; -y for a non-interactive shell
```

File loading is a command rather than an MCP tool on purpose: a `kb_ingest_file`
tool would hand every client that mounts this server the ability to read
arbitrary paths. Indexing a corpus is something a person does deliberately, and
deleting from it more so — the model is offered read tools only, so mounting
"search my notes" never also grants "delete my notes".

Re-ingesting a file replaces the document rather than layering over it. That
distinction is not free: chunk ids are `<document>#<n>`, so an upsert alone
replaces them one for one, and a document that used to make eleven chunks and
now makes one would leave ten chunks of deleted text embedded and searchable —
ranking, in a test of exactly this, ahead of the document that replaced them.
Each document's existing chunks are cleared before its new ones are written.

Or upload a file over HTTP and let the server parse it — this is what the
browser's drop zone does, and it is the only path that gives a PDF its page
numbers without shell access:

```bash
curl -sX POST http://localhost:8000/upload -F files=@~/papers/survey.pdf
```

Or post a document that is already text:

```bash
curl -sX POST http://localhost:8000/ingest -H 'Content-Type: application/json' -d '{"documents":[{"id":"d1","title":"Kalman Filter","content":"A Kalman filter estimates hidden state from noisy measurements.","source":"notes.md","page":3}]}'
```

Or take one back out. `sextant-forget` on the box is the operator's version of
this; over HTTP a caller may remove only documents in their own namespace, and
an id that is not theirs is a 403 rather than a quiet no-op:

```bash
curl -s http://localhost:8000/documents
curl -sX DELETE http://localhost:8000/documents/upload:shared:survey
```

The listing says which rows are yours to remove, because the server is the only
thing that knows: behind the gate your name is the one the proxy vouched for,
not the client id your browser made up.

Watch the agent work, tool calls and all:

```bash
curl -sN -X POST http://localhost:8000/query/stream -H 'Content-Type: application/json' -d '{"query":"how do you estimate state from noisy measurements"}'
```

The SSE stream carries `tool_call`, `tool_result`, `sources`, `token`,
`citation` and `done`.
Note that `sources` now arrives *during* the answer and can arrive more than
once, because the model decides what to retrieve as it goes; each frame carries
the complete list rather than a delta.


## Operating it

```bash
pytest tests/ -q          # about six minutes (two models load once)
mypy sextant tests
ruff check .
pre-commit install
```

**Request ids.** Every response carries `X-Request-ID`, and every log line
caused by that request carries it too. A caller-supplied id is honoured, so a
trace can span the browser, this server and whatever sits in front of it. Set
`SEXTANT_LOG_FORMAT=json` for one JSON object per line.

**Cost.** Each `/query` response reports `usage.cost_usd`. A six-turn agent loop
is only a decision you can make if you can see what it cost.

**Limits at the edge.** 20 requests per minute per client on `/query`,
`/query/stream` and `/ingest` — not on `/health`, since rate-limiting the thing
that reports liveness turns a busy minute into a false outage. Query length,
document count and payload size are bounded in the request schema, so they
appear in `/docs` and are rejected before a handler runs.

| Variable | Default | |
| --- | --- | --- |
| `GEMINI_API_KEY` | — | Required for generation and web search; retrieval works without it |
| `SEXTANT_MODEL` | `gemini-3.1-flash-lite` | Cheapest model that runs the tool loop; `gemini-3.7-flash` for stronger synthesis |
| `SEXTANT_CHROMA_DIR` | `./chroma_db` | Where the collection lives |
| `SEXTANT_CHUNK_TOKENS` | `200` | Chunk target in the embedder's tokens (overlap follows at a fifth); refused past the embedder's window. Sweep in [`learning/chunk-size.md`](../learning/chunk-size.md) |
| `SEXTANT_EMBEDDER` | `all-MiniLM-L6-v2` | Any sentence-transformers model; a store remembers the model that built it and refuses another (see [`learning/embedder-swap.md`](../learning/embedder-swap.md)) |
| `SEXTANT_MAX_PER_DOCUMENT` | `2` | Chunks of one document in a result list; `0` turns the cap off. Measured in [`learning/candidate-cap.md`](../learning/candidate-cap.md) |
| `SEXTANT_ANN_INDEX` | `chroma` | `flat` / `hnsw` / `ivfpq` / `ivfpq_rerank` to route live dense retrieval through the hand-written indexes |
| `SEXTANT_WEB_SEARCH` | off | `on` offers Google Search grounding by default (billed per grounded request) |
| `SEXTANT_DAILY_BUDGET_USD` | `0` (off) | Hard per-UTC-day spend cap; `/query` returns 429 once hit |
| `SEXTANT_ALLOWED_ORIGINS` | `http://localhost:3000` | CORS allowlist, comma-separated |
| `SEXTANT_LOG_FORMAT` | `text` | `json` for structured logs |
| `SEXTANT_LOG_LEVEL` | `INFO` | |
| `SEXTANT_RATE_LIMIT` | `20` | Requests per window, `0` disables |
| `SEXTANT_RATE_WINDOW` | `60` | Window in seconds |

Each variable has exactly one name. An `AGENTICRAG_*` leftover from before
the rename is not read; the server and the ingest CLI print it at startup
with the name to move it to.


## Layout

```
frontend/            React 19 + Vite + TypeScript UI, Tailwind v4 + shadcn:
                     transcript, inline citations, trace, drag-and-drop
                     ingestion, saved conversations, ⌘K, the Index Lab
sextant/mcp_server/
  main.py            FastAPI agent server (:8000) — HTTP surface only
  agent.py           The tool-use loop: declares tools, runs turns, emits events
  mcp_host.py        MCP client: connects, discovers tools, calls them
  sources.py         Numbered citable sources, shared by both retrieval tiers
  conversation.py    Bounds a client transcript into replayable model turns
  uploads.py         Uploaded bytes → text plus page/section spans
sextant/vector_db/
  server.py          The MCP server (stdio) — the reusable artifact
  vector_search.py   Orchestration: chunk on ingest, hybrid search on query
  loaders.py         PDF (PyMuPDF; lines rebuilt from span baselines; pypdf fallback), Markdown, text → text plus page, section and table spans
  chunking.py        Token-aware splitting with overlap and exact char offsets
  tables.py          Finds tables (PDF captions, Markdown pipes) for row chunks
  summaries.py       One model-written overview per document, stored as a chunk (on when a key resolves; `--no-summaries` off)
  embeddings.py      The embedding backend, and the token budget it implies
  retrieval.py       BM25, reciprocal rank fusion, cross-encoder reranking
  ann/               flat, HNSW, IVF-PQ (+rerank) in NumPy; FAISS reference; benchmark
  ingest_cli.py      `sextant-ingest` — index files from disk
  forget_cli.py      `sextant-forget` — take a document and its chunks back out
sextant/settings.py    `SEXTANT_*` env names; reports pre-rename leftovers
chroma_db/           Persistent vector store (gitignored)
sextant/eval/
  corpus/            21 committed documents — the fixed evaluation corpus
  golden.jsonl       65 labelled questions, 55 answerable and 10 not
  golden-large.jsonl 39 questions over a 144-page PDF, 34 answerable
  metrics.py         hit@1, recall@k, MRR, nDCG@k
  harness.py         `sextant-eval` — grades every retrieval mode
  judge.py           `sextant-judge` — faithfulness and abstention
  agent_harness.py   `sextant-eval-agent` — grades what the loop retrieved
  baseline.json      Committed results; the CI gate compares against these
  baseline-large.json Results on the 144-page store (reranker decision)
tests/               chunking, retrieval, ANN, agent loop, API, regressions
deploy/              Caddyfile, prod Dockerfile for the edge, GCP runbook
  trip.sh            one VM trip: start, deploy, verify, park (parking is an EXIT trap)
  deploy.sh          the individual steps: preflight, ship, build, start/stop
learning/            Study path + measured notes (ANN comparison, reranker decision)
planning/            Status, cost, milestone plans, trackers, archived docs
```
