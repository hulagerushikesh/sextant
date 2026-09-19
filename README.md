# sextant

A retrieval system built on the Model Context Protocol. The knowledge base is a
real MCP server — it runs as its own process and works in any MCP client, not
just this app. A FastAPI agent server discovers its tools over MCP, hands them to
the model alongside web search, and lets the model decide what to retrieve.
Every retrieval stage is there because a measurement said so.

Formerly *AgenticRAG*; renamed in 0.7. The `agenticrag-*` commands and
`AGENTICRAG_*` variables still work as aliases for one release.

## Honest status

The model chooses its own tools, and the numbers below are reproducible.

| Capability | State |
| --- | --- |
| Vector retrieval (ChromaDB + MiniLM, persistent, cosine) | Working |
| Document ingestion | Working |
| Answer generation (Gemini, grounded + cited, streamed) | Working |
| MCP protocol (JSON-RPC, tool discovery, stdio transport) | Working |
| Agentic tool selection (model-driven loop, two retrieval tiers) | Working |
| Web search (Google Search grounding, citations included) | Working |
| Chunking, hybrid search, reranking, PDF ingestion | Working |
| Evaluation harness (golden set, metrics, CI gate) | Working |
| Tests, types, structured logging, rate limits, Docker | Working |
| Multi-turn conversation with stable citation labels | Working |
| Interface: inline citations, agent trace, drag-and-drop upload | Working |
| Index Lab: flat / HNSW / IVF-PQ from scratch, FAISS reference, live switch | Working |
| Daily spend cap, per-query cost, cheapest model that runs the loop | Working |
| Command palette, keyboard-first, empty states, onboarding, Markdown export | Working |
| Production stack: Caddy TLS + Basic-auth gate, prod compose, preflight | Built, verified locally; VM provisioned, parked |

Study material lives in [`learning/`](learning/) (a levelled path from
foundations to the research papers) and project status, cost and the next
milestone in [`planning/`](planning/). The original course-era docs are in
[`planning/archive/`](planning/archive/) — they describe features that were
never built and are kept for history only.

## The MCP server

`tools/vector_db/server.py` exposes four tools over stdio:

| Tool | Does |
| --- | --- |
| `kb_search` | Semantic search over the corpus, ranked, with source and page |
| `kb_list` | Every document with its title, size and what it is about — a listing, for "what do my documents cover?" |
| `kb_ingest` | Embed and store documents; re-using an id replaces it |
| `kb_stats` | Collection size, embedding model, storage path |

It has no dependency on the FastAPI app. Verified against MCP Inspector:

```bash
npx @modelcontextprotocol/inspector --cli .venv/bin/sextant-kb --method tools/list
```

To mount it in Claude Desktop, add this to
`~/Library/Application Support/Claude/claude_desktop_config.json` and restart the
app. No `cwd` is needed — the console script resolves the package on its own.

```json
{
  "mcpServers": {
    "knowledge-base": {
      "command": "/absolute/path/to/sextant/.venv/bin/sextant-kb"
    }
  }
}
```

## The agent loop

`mcp_server/agent.py` declares the discovered MCP schemas to the Messages API
next to Google's built-in `google_search`, then runs until the model stops asking
for tools. Two tiers with very different execution paths:

| Tier | Runs | Cited by |
| --- | --- | --- |
| `kb_search`, `kb_list`, `kb_stats` | our MCP subprocess, over stdio | `[n]` labels written into the passage the model reads |
| `google_search` | Google's servers | the API, returned as grounding metadata |

Both land in one numbered list. A knowledge-base passage reaches the model
already labelled `[3]`, and that is the number the browser prints — which is the
only reason a citation means anything to a reader.

`kb_ingest` is discovered but deliberately **not** offered to the model. Writes
belong to `/ingest`, where a human asked for them; answering a question should
not be able to change the corpus it is answering from.

The loop is written out rather than delegated to `client.beta.messages.tool_runner`
because this app needs three things from inside it: text deltas forwarded to the
browser as they arrive, passages numbered before the model sees them, and
`pause_turn` resumed in place. It is capped at six turns.

## Retrieval

Documents are split into overlapping chunks, indexed twice, and reranked.

```
file ──▶ loader ──▶ chunker ──▶ embed ──▶ ChromaDB (cosine)
         page,      ~200 tokens          │
         section,   40 overlap;          │
         table      table rows           │
         spans      under header         ▼
query ─────────────────────────┬──▶ dense top-30 ─┐
                               │                  ├─▶ RRF ─▶ cross-encoder ─▶ top-k
                               └──▶ BM25 top-30 ──┘
```

**Why chunk.** `all-MiniLM-L6-v2` truncates at 256 word pieces *silently*. A
622-token document embeds to the same vector as its first 256 tokens — measured,
not assumed: a query about that document's final sentence scored `-0.0156`
against the whole document and `0.9438` against the sentence alone. Storing
documents whole did not make retrieval coarse, it made most of every long
document unreachable. Chunks are sized from the embedder's own tokenizer, so the
budget moves if the model does. The size itself was swept — 150/200/300/400
with two embedders, [`learning/chunk-size.md`](learning/chunk-size.md): bigger
chunks lose through dilution even with a 512-token model, 150 ranks slightly
better through the reranker at the cost of crowding dense retrieval, and 200
stays.

**Why summaries are opt-in.** `sextant-ingest --summaries` adds one
model-written overview chunk per document. Measured on this corpus it moves
the reranked pipeline's hit@1 up (+0.02 local, 0.6 → 1.0 on "which
document…" questions), and a short document's first chunk already is its
overview — so it is a flag, not the default. It also cost dense recall@5
(−0.07, crowding) until the per-document cap below removed that.
[`learning/summary-chunks.md`](learning/summary-chunks.md).

**Why at most two chunks per document.** Three experiments lost dense
recall@5 the same way: siblings of the document already found filled the
five slots the second document needed. The returned list now holds each
document to two chunks — but only when the document that would take the
slot is competitive (at least half the score), and only where a score is a
relevance (cosine, cross-encoder), not a rank (BM25, RRF). A hard cap
without the guard pushed a survey page out for two chunks scoring 0.000.
Dense recall@5 +0.02 to +0.07 depending on the store, reranked pipeline
unchanged. [`learning/candidate-cap.md`](learning/candidate-cap.md).

**Why tables are chunked differently.** A table row is a record whose meaning
lives in the header; packed into a 200-token chunk with fifteen siblings,
"PaLM · RoPE · SwiGLU" was diluted past retrieval (two measured misses on the
survey set). Loaders mark the tables they can see — `TABLE n:` captions in PDF
text, pipe tables in Markdown — and the chunker emits a few rows at a time
under one copy of the caption and header, spans still pointing at the rows
alone. Six table questions went from 4/6 to 6/6 at k=5 and large-set hit@1
rose 0.06; [`learning/table-chunking.md`](learning/table-chunking.md) has the
tables, including the one-row-per-chunk version that crowded dense top-5.

**Why both retrievers.** Embeddings match meaning and lose exact tokens; BM25
does the opposite. On the 144-page paper used to test this, the best passage for
*"What is InstructGPT?"* was found by **BM25 alone** — dense retrieval did not
return it at all.

**Why fuse on ranks.** A cosine similarity and a BM25 score share no scale.
Reciprocal rank fusion only asks how near the top each retriever put a chunk,
which is the one comparison that is actually defined.

**Why rerank.** Chunking dilutes: a sentence that scores 0.94 on its own scores
0.44 once it shares a chunk with three neighbours. The cross-encoder reads query
and passage together instead of comparing two independent vectors. It is also
what makes abstention possible — on an off-corpus query every candidate scores
`0.0000`, where fusion alone still returns a confident-looking ranking.

Every result reports `scored_by`, `matched` and `dense_score`, so a number is
never separated from what produced it.

## Evaluation

```bash
./.venv/bin/sextant-eval
```

65 labelled questions over a committed 21-document corpus, graded per
configuration. Full method and results in [`eval/README.md`](eval/README.md).

| mode | hit@1 | recall@3 | MRR | nDCG@5 |
| --- | --- | --- | --- | --- |
| dense (vectors only) | 0.873 | 0.885 | 0.915 | 0.904 |
| lexical (BM25 only) | 0.782 | 0.876 | 0.864 | 0.851 |
| rrf (fused) | 0.909 | 0.921 | 0.950 | 0.931 |
| rerank (full pipeline) | 0.909 | 0.949 | 0.955 | 0.938 |

Two results worth stating plainly, because one of them is unflattering.

**Fusion earns its place.** Hybrid beats either retriever alone by 4–13 points
of hit@1. They fail on different questions, which is the whole argument for
running both.

**Reranking does not, on this corpus — and does on a larger one.** At 52
chunks it ties fusion on hit@1 and MRR and gains 0.001 on nDCG@5; fusion
already ranks correctly and the cross-encoder has nothing to fix. On a
1,602-chunk store (a 144-page PDF, 32 page-labelled questions,
`eval/golden-large.jsonl`) it leads on hit@1 0.926 vs 0.889 and nDCG@5 0.931
vs 0.904, and it is the only stage whose score is calibrated enough to
abstain on: 0.000 on every off-corpus question, ~0.95 on in-corpus ones,
where RRF's rank reciprocals separate by 0.003. That is why it stays.
The full argument is in [`learning/reranker-decision.md`](learning/reranker-decision.md).

`sextant-eval --check` compares against the committed baseline and fails on
any drop over 0.02. That gate runs in CI on every push, and it has been tested
by injecting a regression to confirm it fires.

## Operating it

```bash
pytest tests/ -q          # 320 tests, ~140s (two models load once)
mypy mcp_server tools eval tests
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
| `SEXTANT_CHUNK_TOKENS` | `200` | Chunk target in the embedder's tokens (overlap follows at a fifth); refused past the embedder's window. Sweep in [`learning/chunk-size.md`](learning/chunk-size.md) |
| `SEXTANT_EMBEDDER` | `all-MiniLM-L6-v2` | Any sentence-transformers model; a store remembers the model that built it and refuses another (see [`learning/embedder-swap.md`](learning/embedder-swap.md)) |
| `SEXTANT_MAX_PER_DOCUMENT` | `2` | Chunks of one document in a result list; `0` turns the cap off. Measured in [`learning/candidate-cap.md`](learning/candidate-cap.md) |
| `SEXTANT_ANN_INDEX` | `chroma` | `flat` / `hnsw` / `ivfpq` / `ivfpq_rerank` to route live dense retrieval through the hand-written indexes |
| `SEXTANT_WEB_SEARCH` | off | `on` offers Google Search grounding by default (billed per grounded request) |
| `SEXTANT_DAILY_BUDGET_USD` | `0` (off) | Hard per-UTC-day spend cap; `/query` returns 429 once hit |
| `SEXTANT_ALLOWED_ORIGINS` | `http://localhost:3000` | CORS allowlist, comma-separated |
| `SEXTANT_LOG_FORMAT` | `text` | `json` for structured logs |
| `SEXTANT_LOG_LEVEL` | `INFO` | |
| `SEXTANT_RATE_LIMIT` | `20` | Requests per window, `0` disables |
| `SEXTANT_RATE_WINDOW` | `60` | Window in seconds |

Every variable also answers to its `AGENTICRAG_` spelling.

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
./.venv/bin/sextant-ingest ~/papers -r --summaries   # + one overview chunk per document; needs GEMINI_API_KEY
```

File loading is a command rather than an MCP tool on purpose: a `kb_ingest_file`
tool would hand every client that mounts this server the ability to read
arbitrary paths. Indexing a corpus is something a person does deliberately.

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

Watch the agent work, tool calls and all:

```bash
curl -sN -X POST http://localhost:8000/query/stream -H 'Content-Type: application/json' -d '{"query":"how do you estimate state from noisy measurements"}'
```

The SSE stream carries `tool_call`, `tool_result`, `sources`, `token`,
`citation` and `done`.
Note that `sources` now arrives *during* the answer and can arrive more than
once, because the model decides what to retrieve as it goes; each frame carries
the complete list rather than a delta.

## Layout

```
frontend/            React + Vite UI: transcript, inline citations, trace,
                     drag-and-drop ingestion, saved conversations
mcp_server/
  main.py            FastAPI agent server (:8000) — HTTP surface only
  agent.py           The tool-use loop: declares tools, runs turns, emits events
  mcp_host.py        MCP client: connects, discovers tools, calls them
  sources.py         Numbered citable sources, shared by both retrieval tiers
  conversation.py    Bounds a client transcript into replayable model turns
  uploads.py         Uploaded bytes → text plus page/section spans
tools/vector_db/
  server.py          The MCP server (stdio) — the reusable artifact
  vector_search.py   Orchestration: chunk on ingest, hybrid search on query
  loaders.py         PDF (PyMuPDF; lines rebuilt from span baselines; pypdf fallback), Markdown, text → text plus page, section and table spans
  chunking.py        Token-aware splitting with overlap and exact char offsets
  tables.py          Finds tables (PDF captions, Markdown pipes) for row chunks
  summaries.py       One model-written overview per document, stored as a chunk (`sextant-ingest --summaries`, opt-in)
  embeddings.py      The embedding backend, and the token budget it implies
  retrieval.py       BM25, reciprocal rank fusion, cross-encoder reranking
  ann/               flat, HNSW, IVF-PQ (+rerank) in NumPy; FAISS reference; benchmark
  ingest_cli.py      `sextant-ingest` — index files from disk
tools/settings.py    `SEXTANT_*` env names, with `AGENTICRAG_*` fallback
chroma_db/           Persistent vector store (gitignored)
eval/
  corpus/            21 committed documents — the fixed evaluation corpus
  golden.jsonl       65 labelled questions, 55 answerable and 10 not
  golden-large.jsonl 39 questions over a 144-page PDF, 38 page-labelled
  metrics.py         hit@1, recall@k, MRR, nDCG@k
  harness.py         `sextant-eval` — grades every retrieval mode
  judge.py           `sextant-judge` — faithfulness and abstention
  agent_harness.py   `sextant-eval-agent` — grades what the loop retrieved
  baseline.json      Committed results; the CI gate compares against these
  baseline-large.json Results on the 1,602-chunk store (reranker decision)
tests/               392 tests: chunking, retrieval, ANN, agent loop, API, regressions
deploy/              Caddyfile, prod Dockerfile for the edge, deploy.sh, GCP runbook
learning/            Study path + measured notes (ANN comparison, reranker decision)
planning/            Status, cost, milestone plans, trackers, archived docs
```

## The interface

The frontend is not a demo page for the API; it is where the two things this
system claims — that retrieval is real, and that every claim is traceable — are
either visible or unproven.

**Citations are controls, not decoration.** Every `[3]` in an answer opens the
passage the model actually read. A label with nothing behind it renders struck
through in red rather than as plain text: that is the dangling citation
`eval/judge.py` counts, and it should be as visible to a reader as it is to the
metrics. The passage shipped to the browser is the whole chunk — the old
400-character excerpt was sized for whole documents and outlived the reason for
it by three phases.

**The trace reports outcomes, not just calls.** A search that returns nothing is
labelled *nothing found*, in a different colour, next to the search that follows
it. Before this the loop's most interesting behaviour was invisible: rephrasing
after an empty search looked exactly like searching twice for no reason.

**Conversations are real.** A follow-up carries the transcript back to the model,
so "and how are detections assigned?" is a follow-up rather than a fresh
question. What is *not* replayed is the tool transcript — the passages retrieved
in earlier turns stay behind. Replaying them would resend every passage ever
retrieved on every question; the model searches again instead, which is the
cheap half. See [`mcp_server/conversation.py`](mcp_server/conversation.py).

**Citation labels survive the round trip.** `[3]` means the same passage in the
fifth answer as in the first. The server keeps no session state, so the client
sends back the labels it holds and `SourceRegistry.restore` resumes numbering
after them. Without it, one transcript ends up containing two different `[1]`s
and inline citations cannot resolve at all.

**Uploads are parsed server-side.** Drop a PDF into the browser and it keeps its
page numbers. The first version of this panel read files in JavaScript, which
silently limited it to formats a browser can read as text — so PDFs, the format
people actually have, were refused with a note to go and run a terminal command.
`POST /upload` takes the bytes, runs the same loaders `sextant-ingest` uses,
and hands the knowledge base text plus a list of page and section spans. It is
data over the protocol, not a path: a `kb_ingest_file` tool would give every
client that mounts the server the ability to read arbitrary local files.

**Conversations live in the browser.** localStorage, thirty of them, evicting
oldest-first when the quota complains. The trade is stated rather than hidden:
clearing site data loses them and they do not follow you to another machine.
Right for a tool you run yourself, wrong for a hosted product.

**`/health` distinguishes "reachable" from "can answer".** Retrieval works
without an API key and generation does not, so `model_configured` is reported
separately and the UI shows a banner instead of an empty answer box. This exists
because a stubbed model was mistaken for the real one for an afternoon: the
corpus was live, the sources were real, and the prose was hardcoded.

## Known issues

- `min_score` is `0.01`, set from the golden set: it blocks 8 of 10 unanswerable
  queries and costs 2 of 50 answerable ones. It cannot do better than 8 in 10,
  and no threshold can — the two survivors ask for a fact absent from a passage
  genuinely about that subject. Only reading the passage catches those, which is
  why the agent prompt carries an abstention rule.

  This corrects a claim made in Phase 4. On five queries over one PDF the
  reranker looked like it separated relevant from irrelevant cleanly; across 60
  questions it does not. That is what the golden set was for.
- The BM25 index is rebuilt in memory from the collection on first search and
  the chunk text is held resident. Fine at this scale (1,568 chunks from a
  144-page PDF), and the thing to revisit when it stops being fine.
- Cold start is roughly 20 seconds: the embedder, the cross-encoder and the
  lexical index all load on first use. Warm searches run in about 0.1 s.
- Embeddings are still local, so `torch` keeps ~900 MB in the virtualenv. Moving
  to an API embedding model would not remove it while the reranker is local —
  see the note in `embeddings.py`.
- The source list shows everything the agent retrieved, including passages the
  answer never cited. That is deliberate — it is a record of what was looked at.
- Web results have no excerpt in the panel. The API returns page content
  encrypted for the model's use, not for display; only title and URL are ours.
- The rate limiter is in-process and approximate. It protects a single-process
  deployment from a runaway loop; it is not a substitute for a gateway once
  there is more than one replica.
- An unbroken token longer than 100 characters — a base64 blob, a long URL —
  becomes `[UNK]` to the tokenizer and contributes nothing to its chunk's
  embedding. A property of the model, not something chunking can fix.
- `ruff format` is not enforced. Line length is already checked by the linter,
  and adopting a formatter would rewrite sixteen files whose wrapping was chosen
  for readability.
- Conversations are per-browser. There is no account and no sync; clearing
  site data clears them. "Export as Markdown" in the palette is the way out.
- A follow-up cannot re-read a passage from two turns ago without searching for
  it again. Deliberate — see `conversation.py` — but it means an unusually
  specific follow-up may retrieve rather than remember.
- A scanned PDF with no text layer is rejected rather than OCR'd. It is
  reported as such instead of being stored as a document that matches nothing.
- The answer renderer handles paragraphs, lists, headings, bold and inline code.
  It is not a markdown parser, and a table in an answer renders as its source
  text. Gemini reaches for LaTeX unprompted, so the system prompt asks for
  equations as inline code instead.
- A web source's title is the site's domain and its link is a Google redirect.
  That is the shape of the grounding metadata, not a choice.
- The judge and the agent now share one model family, so `sextant-judge`
  grades Gemini's answers with Gemini. Same-family grading is a known bias; the
  deterministic citation check is unaffected by it, and is the half that catches
  the failure that matters most.

## The Gemini port

Phase 8 replaced the Anthropic SDK with `google-genai`. Everything below
generation survived untouched — the MCP server, chunking, hybrid retrieval,
reranking, the eval metrics — which is the argument for having kept the model at
the edge. Four things in the generation layer were genuine differences, not
renames:

**Citations are spans, not events.** Anthropic streamed a citation the moment it
closed, so `[n]` could be appended mid-answer. Gemini attaches
`grounding_metadata` to the *last* chunk of a turn, describing ranges over the
finished text. The turn is therefore relabelled once it ends and sent back as an
`answer` event that replaces what streamed. Those ranges are **UTF-8 byte
offsets** — on ASCII they agree with character offsets, which is exactly what
makes the bug worth pinning: one em dash shifts every later label.

**Built-in tools and function declarations do not mix by default.** Sending both
is a 400 unless `tool_config.include_server_side_tool_invocations` is set. The
API says so plainly, which is better than the silent degradation it could have
been.

**Thinking is billed as output and spends `max_output_tokens`.** The first port
truncated a three-sentence answer at 42 characters, because the budget looked
generous and the model thought through most of it.

**History must be echoed back verbatim.** Gemini 3 attaches a `thought_signature`
to the parts it returns; rebuilding those parts by hand drops it. The model's own
`Content` objects are appended unmodified.

The risk that did not materialise: schema translation. `parameters_json_schema`
takes the MCP server's JSON Schema exactly as the server publishes it — titles,
defaults, bounds and enums included — so `declare_tools()` is still a filter and
a rename. The older `parameters` field takes a restricted subset and would have
needed a conversion layer between the protocol's contract and the model's.

## Roadmap

0. **Foundation** — dependency and repo hygiene *(done)*
1. **Generation** — grounded, cited, streamed answers *(done)*
2. **Protocol** — real MCP tool server, discovered not hard-wired *(done)*
3. **Agency** — model-driven tool-use loop, plus server-side web search as a
   second tier *(done)*
4. **Retrieval** — chunking, hybrid search, reranking, PDF ingestion *(done)*
5. **Evaluation** — golden set, metrics, ablations, CI gate *(done)*
6. **Hardening** — tests, types, structured logging, limits, Docker *(done)*
7. **Interface** — chat history, inline citation links, richer agent trace
   *(done)*
8. **Gemini** — generation ported from the Anthropic SDK to `google-genai` *(done)*
9. **Index Lab** — flat, HNSW and IVF-PQ written from scratch and measured on
   the real corpus; finding: exact search wins at personal scale
   (`learning/ann-comparison.md`) *(done)*
10. **Real-corpus proof + two-stage rerank** — IVF-PQ's recall ceiling broken
    by exact re-scoring at unchanged hot memory *(done)*; at 100k vectors the
    dial that lifts it is `oversample`, not `nprobe`
    (`learning/ivfpq-100k.md`) *(done)*
11. **FAISS reference column** — the pure-Python constant factor measured,
    10–280× *(done)*
12. **Live index switch** — `SEXTANT_ANN_INDEX` routes production dense
    retrieval through any of them *(done)*
13. **Production** — prod compose, Caddy TLS + Basic-auth gate, preflight,
    daily spend cap, GCP VM provisioned and image built; edge verified
    locally against a stub API *(built; go-live parked on DNS + secrets)*
14. **Product-grade interface** — ⌘K palette, keyboard map, empty states,
    onboarding, skeletons, toasts *(done)*
15. **Ship, prove, rename** — `sextant` everywhere; reranker settled with
    data on 1,602 chunks (it stays); docs match the code; go-live; ops floor
    *(in progress — see `planning/milestone-15.md`)*

### On web search

The Brave / SerpAPI / Exa client was removed in Phase 2 and replaced by a
server-side search tool: one credential instead of three, and citations built in
rather than reconstructed from snippets. Phase 3 used Anthropic's
`web_search_20260209`; Phase 8 replaced it with Google's `google_search`. The old
client is in git history if it is ever wanted back.

Two differences the Google tier brings, both visible in the UI:

- A grounded source's link is a `vertexaisearch.cloud.google.com` redirect, not
  the page's own address, and its title is the site's domain. Google requires the
  redirect be the link displayed, so "wikipedia.org" is as specific as a web
  source card gets.
- Search is billed per request, on top of tokens. `pricing.py` prices every
  grounded request at the post-allowance rate, because it cannot see the
  account's month-to-date usage — so the reported cost is an upper bound early
  in a month and never an understatement.
