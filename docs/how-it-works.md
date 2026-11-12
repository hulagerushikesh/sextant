# How it works

The server, the agent loop, each search stage and why it exists, and what
changed when the model was swapped.

> Moved here from the README on 2026-11-12 so the front page could open with a
> quickstart. The text is unchanged apart from link paths and one table, which
> now lives on the generated [results page](RESULTS.md).

## The MCP server

The knowledge base is a real MCP server: its own process, speaking JSON-RPC
over stdio, with no dependency on the FastAPI app in this repository. It is
published on its own so it can be used without any of the rest:

```bash
pip install sextant-kb
```

That installs the server and the two commands that feed it, and nothing
else — no web framework, no model client. Index some documents and mount it:

```bash
sextant-ingest ~/Documents/papers -r          # PDF, Markdown, text
```

```json
{
  "mcpServers": {
    "knowledge-base": {
      "command": "/absolute/path/to/sextant-kb"
    }
  }
}
```

That goes in `~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows); restart the
app afterwards. `which sextant-kb` gives the path. No `cwd` is needed — the
console script resolves the package on its own.

Two things happen on first use, both once. The embedding and reranking models
(~180 MB) are downloaded from Hugging Face, so the first query is slow and
needs a network. And the collection is created: in a checkout that is
`<repo>/chroma_db`, and from an installed wheel it is the platform's user-data
directory, because writing a person's corpus under `site-packages` would hand
it to the next `pip uninstall`. `SEXTANT_CHROMA_DIR` overrides both.

| Tool | Does |
| --- | --- |
| `kb_search` | Semantic search over the corpus, ranked, with source and page |
| `kb_list` | Every document with its title, size and what it is about — a listing, for "what do my documents cover?" |
| `kb_ingest` | Embed and store documents; re-using an id replaces it |
| `kb_stats` | Collection size, embedding model, storage path |
| `kb_ann_benchmark` | Build one index — flat, HNSW or IVF-PQ — and report recall against exact search |
| `kb_ann_compare` | The same query through every index, side by side |

Verified against MCP Inspector:

```bash
npx @modelcontextprotocol/inspector --cli $(which sextant-kb) --method tools/list
```

Everything else in this repository — the agent loop, the HTTP API, the
browser interface, the evaluation harnesses — is the system built *on* that
server, and installs with `pip install 'sextant-kb[app]'` or from a checkout.


## The agent loop

`sextant/mcp_server/agent.py` declares the discovered MCP schemas to the Messages API
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
with two embedders, [`learning/chunk-size.md`](../learning/chunk-size.md): bigger
chunks lose through dilution even with a 512-token model, 150 ranks slightly
better through the reranker at the cost of crowding dense retrieval, and 200
stays.

**Why summaries are on when a key is.** `sextant-ingest` adds one
model-written overview chunk per document. Measured on this corpus it moves
the reranked pipeline's hit@1 up (+0.02 local, 0.6 → 1.0 on "which
document…" questions) and gives `kb_list` a real overview to list. It was a
flag for a year of milestones for one reason — it cost dense recall@5
(−0.07, crowding) — and the per-document cap below took that back in full
(0.900 → 0.973, the same the no-summaries store scores), so it is now the
default whenever `GEMINI_API_KEY` resolves. No key, or `--no-summaries`, and
ingestion stores text only and says so; nothing in ingestion needs a model.
[`learning/summary-chunks.md`](../learning/summary-chunks.md).

**Why at most two chunks per document.** Three experiments lost dense
recall@5 the same way: siblings of the document already found filled the
five slots the second document needed. The returned list now holds each
document to two chunks — but only when the document that would take the
slot is competitive (at least half the score), and only where a score is a
relevance (cosine, cross-encoder), not a rank (BM25, RRF). A hard cap
without the guard pushed a survey page out for two chunks scoring 0.000.
Dense recall@5 +0.02 to +0.07 depending on the store, reranked pipeline
unchanged. [`learning/candidate-cap.md`](../learning/candidate-cap.md).

**Why tables are chunked differently.** A table row is a record whose meaning
lives in the header; packed into a 200-token chunk with fifteen siblings,
"PaLM · RoPE · SwiGLU" was diluted past retrieval (two measured misses on the
survey set). Loaders mark the tables they can see — `TABLE n:` captions in PDF
text, pipe tables in Markdown — and the chunker emits a few rows at a time
under one copy of the caption and header, spans still pointing at the rows
alone. Six table questions went from 4/6 to 6/6 at k=5 and large-set hit@1
rose 0.06; [`learning/table-chunking.md`](../learning/table-chunking.md) has the
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
configuration. Full method and results in [`sextant/eval/README.md`](../sextant/eval/README.md).
The numbers, the nine rejected ideas and the cost of a question are on one
generated page: [`docs/RESULTS.md`](RESULTS.md).

Two results worth stating plainly, because the second is smaller than it sounds.

**Fusion earns its place.** Hybrid beats either retriever alone by 4–13 points
of hit@1. They fail on different questions, which is the whole argument for
running both.

**Reranking earns one question — and the right to say "I do not know".** On
this corpus it leads fusion on hit@1 by 0.927 to 0.909, which is one
question of 55. On a 144-page PDF (39 questions, 34 answerable,
`sextant/eval/golden-large.jsonl`) it leads 0.912 to 0.882 — one question
again. That margin alone would not pay for a second model. What does is that
it is the only stage whose score can be abstained on: on the larger set every
off-corpus question scores 0.000 against a mean of 0.92 for answerable ones,
where RRF's rank reciprocals separate by 0.003. On the small corpus the same
floor blocks 8 of 10 unanswerable questions, not all ten (see
[Known issues](known-issues.md)).
The full argument is in [`learning/reranker-decision.md`](../learning/reranker-decision.md).

`sextant-eval --check` compares against the committed baseline and fails on
any drop over 0.02. That gate runs in CI on every push, and it has been tested
by injecting a regression to confirm it fires.


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


## On web search

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
