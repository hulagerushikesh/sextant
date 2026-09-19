# Learning path

Everything needed to understand, defend and extend this system — from "what is
an embedding" to the papers the design decisions were argued from. Each level
says why the topic matters *for this repo*, where the idea lives in the code,
what to read, and one question to answer before moving on. The questions are
not rhetorical: if the answer is not obvious, the level is not done.

The single most useful habit: for every claim in the root README, find the
measurement that backs it. This codebase was rebuilt around numbers rather than
library folklore, and the numbers are the curriculum.

| Level | Topic | Repo home |
| --- | --- | --- |
| 0 | Foundations: Python async, HTTP/SSE, Docker, git | `mcp_server/main.py`, `Dockerfile` |
| 1 | Text to vectors: tokens, embeddings, similarity | `tools/vector_db/embeddings.py` |
| 2 | Search: BM25, dense, hybrid, fusion, reranking, chunking | `tools/vector_db/retrieval.py`, `chunking.py` |
| 3 | Vector indexes: flat, HNSW, IVF-PQ, FAISS, Chroma | `tools/vector_db/ann/` |
| 4 | Generation: grounding, citations, streaming, cost | `mcp_server/agent.py`, `pricing.py` |
| 5 | Agents and MCP: tool loops, the protocol | `tools/vector_db/server.py`, `mcp_server/mcp_host.py` |
| 6 | Evaluation: IR metrics, golden sets, judges, gates | `eval/` |
| 7 | Production: event loops, limits, TLS, gates, GCP | `deploy/`, `observability.py` |
| 8 | Interface craft: SSE clients, keyboard-first, motion | `frontend/src/` |
| 9 | Research frontier: the papers | this file, §9 |

## Notes — experiments done the level-6 way

Each is one hypothesis, one change, both golden sets, a rule written before
the numbers, and a decision. Read them in this order; each later one
depends on a number in an earlier one.

| Note | Question | Decision |
| --- | --- | --- |
| [`pdf-extraction.md`](pdf-extraction.md) | Which PDF extractor keeps table rows and headings intact? | PyMuPDF, lines rebuilt from span baselines |
| [`ann-comparison.md`](ann-comparison.md) | Flat vs HNSW vs IVF-PQ on this corpus — where does ANN start paying? | Exact search until ~100k vectors |
| [`reranker-decision.md`](reranker-decision.md) | Does the cross-encoder earn its place at 1,602 chunks? | Stays — only calibrated abstention score, leads ranking |
| [`table-chunking.md`](table-chunking.md) | M16 exp 1 — can a table row be found on its own? | Shipped: rows under their header, +0.09 hit@1 |
| [`agent-loop.md`](agent-loop.md) | M16 exp 2 — does the agent search twice for two-part questions? | No (0.722); one prompt bullet → 0.778, shipped |
| [`chunk-size.md`](chunk-size.md) | M16 exp 3 — is 200 tokens the content's size or MiniLM's? | 200 stays; bigger loses, 150 helps rerank and hurts dense |
| [`embedder-swap.md`](embedder-swap.md) | M16 exp 4 — MiniLM → bge-small? | Not switched; opt-in `SEXTANT_EMBEDDER` |
| [`summary-chunks.md`](summary-chunks.md) | M16 exp 5 — one overview chunk per document for global questions? | Opt-in `--summaries`; wins rank, cost dense recall |
| [`candidate-cap.md`](candidate-cap.md) | M17 exp 1 — was the dense loss in exps 1, 3, 5 crowding? | Yes; shipped, cap 2 with a score guard, dense only |
| [`ivfpq-100k.md`](ivfpq-100k.md) | §9 item 5 — at 100k vectors, does IVF-PQ's memory win become a latency win? | Not in Python at recall ≥ 0.9; its recall dial at scale is `oversample`, not `nprobe` |

---

## Level 0 — Foundations

**Why here.** The server is `async` FastAPI streaming SSE; the knowledge base is
a separate process spoken to over stdio; everything ships as two containers.
Without these, the rest reads as magic.

**Topics**
- Python typing and `asyncio`: what the event loop is, why a sync CPU call
  inside `async def` freezes every other request. Phase 6 found exactly this —
  the SSE heartbeat ticked 0 times in 558 ms until CPU work moved to
  `asyncio.to_thread`.
- HTTP semantics: status codes (`401` vs `403`, `429`), CORS, `multipart/form-data`.
- Server-Sent Events: one long response, `data:` frames, why proxies must not
  buffer them (`deploy/Caddyfile` skips gzip on `text/event-stream`).
- JSON-RPC 2.0: request/response/notification shapes. MCP is JSON-RPC.
- Docker: image vs container, layers, `env_file`, why the bcrypt hash got
  truncated by variable interpolation (`docker-compose.prod.yml` comment).
- git: branches, rebase vs merge, what a remote is, why `upstream` here is
  read-only.

**Read / do**
- Python docs: *asyncio — Developing with asyncio*, especially "Running Blocking Code".
- MDN: *Using server-sent events*.
- jsonrpc.org/specification (short).
- Docker docs: *Compose file reference → env_file → format*.
- Do: run `pytest tests/test_api.py -q` and read `tests/fakes.py` — the stubbed
  model is how the whole stack is tested without a key.

**Check yourself.** Why does `/query/stream` send heartbeat events, and what
would you observe in the browser if the embedder ran on the event loop thread?

---

## Level 1 — Text to vectors

**Why here.** Retrieval quality is bounded by what the embedder can see.
The most expensive lesson in this repo: `all-MiniLM-L6-v2` silently truncates
at 256 word pieces, so a 622-token document embedded as its first two
paragraphs. Measured: the last sentence scored `-0.0156` against the whole doc
and `0.9438` alone.

**Topics**
- Tokenization: WordPiece/BPE, why a 100-char base64 blob becomes `[UNK]`.
- Embeddings: sentence-transformers, mean pooling, unit-normalisation, why
  cosine on unit vectors equals a dot product and orders the same as squared L2
  (`ann/base.py` relies on this).
- Similarity scales: cosine ∈ [-1,1], BM25 ∈ [0,∞) — they share no scale,
  which is why fusion happens on ranks (level 2).
- Model choice: MiniLM (fast, 384-d) vs bge/e5 (better, larger) vs API
  embeddings (no torch, but the local reranker still needs it).

**Read / do**
- Reimers & Gurevych 2019, *Sentence-BERT* (arXiv:1908.10084).
- sbert.net → "Pretrained Models" table; note max sequence length column.
- MTEB leaderboard (huggingface.co/spaces/mteb/leaderboard) — read the
  *retrieval* column, not the average.
- Do: `python -c` embed a long paragraph and its last sentence; reproduce the
  truncation finding with your own text.

**Check yourself.** `embeddings.py` sizes chunks from the model's own
tokenizer. What breaks if you swap the embedder without re-ingesting?

---

## Level 2 — Search

**Why here.** The pipeline is dense top-30 ∥ BM25 top-30 → RRF → cross-encoder
→ top-k. Each stage exists because a measurement said so, and one of them
(reranking) is *not* justified on the current corpus. Understanding why is the
point.

**Topics**
- Lexical: TF-IDF → BM25 (k1, b, length normalisation). Why "InstructGPT" was
  found by BM25 alone and missed by dense retrieval.
- Dense: bi-encoder retrieval, top-k by cosine.
- Hybrid + fusion: Reciprocal Rank Fusion, `1/(k+rank)`, why ranks not scores.
- Reranking: cross-encoders read query+passage jointly; why they enable
  abstention (`0.0000` on off-corpus queries) yet added ~0 on 52 chunks.
- Chunking: fixed-token windows with overlap, page/section spans, dilution
  (a 0.94 sentence scores 0.44 once it shares a chunk with three neighbours).
- Thresholds: `min_score = 0.01` chosen from the golden set, and the ceiling it
  cannot beat (2 of 10 unanswerables need reading, not scoring).

**Read / do**
- Robertson & Zaragoza 2009, *The Probabilistic Relevance Framework: BM25 and Beyond*.
- Cormack, Clarke & Buettcher 2009, *Reciprocal Rank Fusion* (SIGIR, 2 pages).
- Karpukhin et al. 2020, *Dense Passage Retrieval* (arXiv:2004.04906).
- Nogueira & Cho 2019, *Passage Re-ranking with BERT* (arXiv:1901.04085).
- Do: `agenticrag-eval` — read the four ablation rows and `eval/README.md`.
  Then remove RRF and re-run; watch hit@1 drop 8 points.

**Check yourself.** Under what corpus property would you expect the
cross-encoder to start earning its 90 MB and latency? Answer it before
reading [`reranker-decision.md`](reranker-decision.md), then check.

---

## Level 3 — Vector indexes

**Why here.** `tools/vector_db/ann/` implements flat, HNSW and IVF-PQ from
scratch in NumPy so their tradeoffs could be measured on *this* corpus. The
honest result: at a few thousand vectors, exact search wins on every axis; ANN
is a pessimisation until ~100k vectors or a RAM ceiling.

**Topics**
- Flat/exact search: the ground truth every recall number is against.
- HNSW: navigable small-world graphs, layers, `M`, `efConstruction`,
  `efSearch`, Malkov's neighbour-selection heuristic.
- IVF-PQ: k-means coarse quantizer (`nlist`, `nprobe`), product quantization
  (`m` subspaces × 256 centroids), asymmetric distance tables, residual
  encoding; memory: 48 B/vector codes vs 1,536 B float32 (32×).
- Two-stage rerank (`ann/rerank.py`): oversample from a lossy index, re-score
  exactly — breaks PQ's recall ceiling at unchanged hot memory.
- Hot vs cold bytes: `hot_bytes_per_vector` (what must be in RAM) vs amortised.
- Library reality: FAISS is 10–280× faster than the Python versions
  (`faiss_ref.py`, dashed reference lines) — constant factors, same recall curves.
- Chroma: what it is (SQLite + hnswlib), single-writer local disk, why that
  forced a VM over Cloud Run.
- OpenMP gotcha: faiss + torch both bundle a runtime; load order decides
  whether the process segfaults (`server.py` preloads faiss).

**Read / do**
- Malkov & Yashunin 2016, *HNSW* (arXiv:1603.09320).
- Jégou, Douze & Schmid 2011, *Product Quantization for Nearest Neighbor Search*.
- Johnson, Douze & Jégou 2017, *Billion-scale similarity search with GPUs* (FAISS).
- Subramanya et al. 2019, *DiskANN* — what to read when RAM becomes the limit.
- ann-benchmarks.com — how recall/QPS curves are conventionally drawn.
- Do: open the Index Lab (⌥L), run a sweep, then read
  [`ann-comparison.md`](ann-comparison.md) with the chart beside it.

**Check yourself.** IVF-PQ rerank is a no-op on the 52-chunk corpus. Why,
mechanically? What corpus size would make it matter?

---

## Level 4 — Generation

**Why here.** The model sits at the edge deliberately: Phase 8 swapped
Anthropic for Gemini and nothing below generation changed. The generation layer
still has four Gemini-specific facts that cost real debugging time.

**Topics**
- Grounded answering: passages numbered before the model sees them, `[n]`
  citations, abstention rule in the system prompt.
- Citations as spans vs events: Gemini attaches `grounding_metadata` as UTF-8
  *byte* offsets over the finished text — one em dash shifts every later label.
- Streaming: deltas, then a final `answer` event that replaces the streamed text.
- Thinking tokens: billed as output and they spend `max_output_tokens`
  (4096 truncated a 3-sentence answer at 42 chars).
- `thought_signature`: echo the model's own `Content` objects back verbatim.
- Model economics: `pricing.py`; `gemini-3.1-flash-lite` ($0.25/$1.50) is the
  cheapest model that *works* — `2.5-flash-lite` 400s on tool-call context
  circulation and a one-shot probe hides that. ~$0.003/query.
- Server-side tools: Google Search grounding as an opt-in second tier
  (`AGENTICRAG_WEB_SEARCH`), billed per grounded request.

**Read / do**
- Gemini API docs: *Function calling*, *Grounding with Google Search*,
  *Thinking* — specifically `include_server_side_tool_invocations`.
- Lewis et al. 2020, *Retrieval-Augmented Generation for Knowledge-Intensive
  NLP* (arXiv:2005.11401) — where the acronym comes from.
- Do: read `mcp_server/agent.py` top to bottom with `tests/test_agent.py`
  open; trace one query through `SourceRegistry` (`sources.py`).

**Check yourself.** A follow-up turn cites `[3]` and it still means the same
passage as last turn. Which two pieces of state make that true, and where do
they live (server or client)?

---

## Level 5 — Agents and MCP

**Why here.** This is the project's differentiator. The knowledge base is a
real MCP server (`agenticrag-kb`) usable from any MCP client; the FastAPI app
discovers its tools over stdio and lets the model choose. The ANN benchmark is
also an MCP tool — `main.py` never imports the knowledge base.

**Topics**
- Tool use / function calling: schemas, the request → tool_call → tool_result
  → loop, stop reasons, multi-hop.
- ReAct-style loops and why this one is hand-written (mid-turn deltas,
  pre-numbered passages, `pause_turn` resume) rather than a library runner.
- MCP: hosts, clients, servers; transports (stdio, streamable HTTP);
  primitives (tools, resources, prompts); capability negotiation; JSON Schema
  as the tool contract (`parameters_json_schema` takes it verbatim).
- Process boundaries: stdio strips the environment, so `mcp_host.py` forwards
  variables by hand (`_FORWARDED_ENV`) — a silent no-op otherwise.
- Filesystem as a trust boundary: ingestion is a CLI, deliberately *not* a
  tool.
- `READABLE_TOOLS`: what the model may see vs what the app may call.

**Read / do**
- modelcontextprotocol.io → *Specification* (architecture, transports, tools).
- Yao et al. 2022, *ReAct* (arXiv:2210.03629).
- Schick et al. 2023, *Toolformer* (arXiv:2302.04761).
- Do: add `agenticrag-kb` to Claude Desktop's MCP config and search the corpus
  from there — proves the server is not app-shaped.

**Check yourself.** Why is `kb_ann_benchmark` an MCP tool but hidden from the
model, and what would go wrong if `main.py` imported `KnowledgeBase` directly?

---

## Level 6 — Evaluation

**Why here.** `eval/` is the reason the README can say "fusion earns its place"
and "reranking does not" instead of assuming both. 60 labelled questions, 21
committed documents (8 distractors, added because recall saturated at 1.0
without them), four ablations, CI gate at 0.02.

**Topics**
- IR metrics: hit@k, recall@k, MRR, nDCG@k — what each rewards and hides.
- Golden sets: answerable vs unanswerable, distractors, label leakage.
- Ablations: change one stage, keep everything else fixed.
- Regression gates: baseline JSON, tolerance, proving the gate fires by
  injecting a regression (it was).
- LLM-as-judge: faithfulness/citation checks; same-family bias (Gemini grading
  Gemini); deterministic checks as the half that matters.
- Statistical honesty: 60 questions is small; a 0.01 difference is noise.

**Read / do**
- Manning, Raghavan & Schütze, *Introduction to Information Retrieval*, ch. 8
  (free online).
- Thakur et al. 2021, *BEIR* (arXiv:2104.08663); Muennighoff et al. 2022,
  *MTEB* (arXiv:2210.07316).
- Es et al. 2023, *RAGAS* (arXiv:2309.15217); Saad-Falcon et al. 2023, *ARES*.
- Zheng et al. 2023, *Judging LLM-as-a-judge* (arXiv:2306.05685).
- Do: write 5 new golden questions for a document you add, run
  `agenticrag-eval --check`, then deliberately break `min_score` and watch CI's
  gate logic fail.

**Check yourself.** Why did recall saturate at 1.0 before distractors, and
what does that say about evaluating on a corpus the questions were written from?

---

## Level 7 — Production

**Why here.** One warm VM was chosen over Cloud Run on purpose: embedded
Chroma is single-writer local disk, and a 2 GB torch image cold-starts badly.
The edge is Caddy (auto-TLS, Basic-auth gate, path routing). Cost is capped
twice: a per-day USD cap in-process and a ₹ budget on the billing account.

**Topics**
- FastAPI internals: dependency injection, background threads, request ids,
  structured JSON logs.
- Rate limiting and spend caps: token bucket, per-process limits, why they are
  not a gateway; `DailyBudget` UTC rollover.
- TLS and ACME: Let's Encrypt rate limits (why preflight checks DNS → this VM
  first), HSTS.
- Basic auth: bcrypt hashes, `$` interpolation hazards, `format: raw`.
- Containers: CPU-only torch wheels (3 GB CUDA libs otherwise), healthchecks,
  log rotation, persistent disk mounts, non-root (deferred).
- GCP: projects, static IPs (unused ones cost 2×), firewall source ranges,
  snapshots, budgets (account currency is INR), stop vs delete.
- Transport gotchas: macOS `openrsync` mangles `host:path`; tar-over-ssh.

**Read / do**
- `deploy/README.md` — the runbook, then `deploy/deploy.sh` preflight block.
- Caddy docs: *basic_auth*, *reverse_proxy* (flush_interval), *Automatic HTTPS*.
- Google Cloud: *Compute Engine pricing*, *External IP address pricing*.
- Do: read the `PREFLIGHT` heredoc in `deploy/deploy.sh` and write one
  sentence per check on what outage it prevents. (Running it needs the VM up,
  which costs money — reading it does not.)

**Check yourself.** Why is the API container `expose`d but not `ports`-mapped,
and what attack does that close?

---

## Level 8 — Interface craft

**Why here.** The UI is keyboard-first (⌘K palette, `/`, ⌥N/W/L/T) and built
on design-engineering rules rather than taste: no animation on high-frequency
keyboard UI, `scale(0.97)` press feedback, hover gated to fine pointers,
reduced-motion honoured, skeletons instead of spinners.

**Topics**
- SSE in the browser: `EventSource` vs `fetch` + reader, replacing streamed
  text with the final `answer` event.
- React state shape: server stateless, client holds transcript + labels.
- Citation UI: `[n]` as controls, struck-through dangling labels.
- Motion: easing tokens, transitions over keyframes for interruptible UI,
  `@starting-style`, frequency-based "should this animate at all".
- Accessibility: `role="status"`, `aria-live`, focus rings, `kbd`.

**Read / do**
- Emil Kowalski, animations.dev — the free articles on easing and duration.
- web.dev *Rendering performance* (why only `transform`/`opacity`).
- Do: open `frontend/src/components/Palette.jsx` and remove the
  `requestAnimationFrame` in `run`; observe why it was there.

**Check yourself.** The palette opens with no animation and the toast enters
with one. State the rule that makes both correct.

---

## Level 9 — Research frontier

What to read once the above is solid, grouped by the question each paper
answers for this project. Newest-first within a group is *not* the order to
read them; start with the one marked ★.

**Should retrieval be smarter than "top-k then answer"?**
- ★ Asai et al. 2023, *Self-RAG* (arXiv:2310.11511) — the model decides when
  to retrieve and critiques its own citations. Closest ancestor of the
  abstention rule here.
- Yan et al. 2024, *Corrective RAG* (arXiv:2401.15884) — grade retrieved docs,
  fall back to web search. This repo's two-tier design is a manual version.
- Jiang et al. 2023, *FLARE* (arXiv:2305.06983) — retrieve when the model's
  confidence drops mid-generation.
- Gao et al. 2022, *HyDE* (arXiv:2212.10496) — embed a hypothetical answer
  instead of the question. Cheap to try in `retrieval.py`.

**Is chunk-then-embed the right unit?**
- ★ Sarthi et al. 2024, *RAPTOR* (arXiv:2401.18059) — recursive summaries as
  a tree; answers "what topics do my documents cover?" better than flat chunks.
- Edge et al. 2024, *GraphRAG* (arXiv:2404.16130) — entity graphs + community
  summaries for global questions.
- Khattab & Zaharia 2020, *ColBERT* (arXiv:2004.12832); Santhanam et al.
  2021, *ColBERTv2* — late interaction: token-level vectors, a middle path
  between bi- and cross-encoders.
- Formal et al. 2021, *SPLADE* (arXiv:2107.05127) — learned sparse retrieval,
  a modern BM25.

**Better embedders / retrievers**
- ★ Wang et al. 2022, *E5* (arXiv:2212.03533); Xiao et al. 2023, *BGE / C-Pack*
  (arXiv:2309.07597) — what to swap MiniLM for, and why re-ingestion follows.
- Izacard et al. 2021, *Contriever* (arXiv:2112.09118) — unsupervised dense
  retrieval.

**Does long context make RAG obsolete?**
- ★ Liu et al. 2023, *Lost in the Middle* (arXiv:2307.03172) — models
  under-use facts placed mid-context; argues for retrieval + small k.
- Li et al. 2024, *Retrieval Augmented Generation or Long-Context LLMs?*
  (arXiv:2407.16833) — a routing answer, not a winner.

**Agents**
- ★ Yao et al. 2022, *ReAct* (arXiv:2210.03629).
- Shinn et al. 2023, *Reflexion* (arXiv:2303.11366) — self-feedback loops.
- Anthropic, *Building effective agents* (2024, blog) — workflows vs agents;
  the "start simple" argument this repo followed.

**Indexes at scale**
- ★ Malkov & Yashunin 2016, *HNSW*; Jégou et al. 2011, *PQ*.
- Guo et al. 2020, *ScaNN* (arXiv:1908.10396) — anisotropic quantization.
- Subramanya et al. 2019, *DiskANN* — SSD-resident graphs.

**Evaluation**
- ★ Es et al. 2023, *RAGAS*; Thakur et al. 2021, *BEIR*.
- Chen et al. 2023, *Benchmarking LLMs in RAG* (arXiv:2309.01431) — noise
  robustness, negative rejection, the abstention problem measured.

**Protocol**
- Model Context Protocol specification (modelcontextprotocol.io/specification)
  — read *Transports* and *Tools* end to end; the rest is reference.

**Research questions this repo is positioned to answer** (each is a
level-6-style experiment, zero cloud cost; the open ones are scheduled as
`planning/milestone-16.md`):
1. ~~At what corpus size does the cross-encoder start beating RRF alone?~~
   Done — [`reranker-decision.md`](reranker-decision.md). ~~Follow-up it
   raised: tables embed badly; try a row-per-chunk loader and re-grade
   L25/L26.~~ Done — [`table-chunking.md`](table-chunking.md): rows under
   a header, +0.09 hit@1 on the survey set, and why one row per chunk
   crowded dense retrieval.
2. Does HyDE help on a technical personal corpus, or hurt (hallucinated
   jargon)? One function in `retrieval.py`, one eval row.
2b. ~~Is 200 tokens the right chunk size, or MiniLM's?~~ Done —
   [`chunk-size.md`](chunk-size.md): bigger loses for both embedders,
   150 helps the reranker and hurts dense through crowding; 200 stays.
   ~~A per-document candidate cap is the next question.~~ Done —
   [`candidate-cap.md`](candidate-cap.md): crowding confirmed, cap 2 with
   a score guard shipped, dense recall@5 back on every store.
2c. ~~Does the agent loop already resolve multi-hop by searching twice?~~
   Done — [`agent-loop.md`](agent-loop.md): it did not (0.722 = single
   search); one prompt bullet takes it to 0.778 with no extra turns; the
   rest are label over-specification or q48, which needs question 2.
3. ~~RAPTOR-style summaries vs flat chunks for "overview" questions — the
   starter prompts in `Opening.jsx` are exactly this class.~~ Done —
   [`summary-chunks.md`](summary-chunks.md): one level, opt-in; short
   documents already retrieve their overview, summaries buy rerank
   hit@1 and cost dense recall, and the starter prompt is a listing
   question no summary tree answers.
4. ~~Swap MiniLM → bge-small: recall delta vs re-ingest cost vs image
   size.~~ Done — [`embedder-swap.md`](embedder-swap.md): +0.09 dense
   hit@1 on the survey, −0.04 on the handbook, rerank unmoved; not
   switched, opt-in via `SEXTANT_EMBEDDER`.
5. ~~IVF-PQ at 100k synthetic vectors: the point where the memory story turns
   into a latency story.~~ Done — [`ivfpq-100k.md`](ivfpq-100k.md): latency
   parity with flat at ≈100k but only at recall 0.6; the ceiling is PQ
   ordering, and `oversample` (not `nprobe`) lifts it to 0.99. HNSW crosses
   flat at ≈25k with recall 1.0. Flat stays.
6. IVF with an HNSW coarse quantizer at 1M vectors: the point where
   finding the cells is itself a search problem, and graph and clusters
   stack instead of compete.

---

## How to use this folder

- Work one level at a time; each "Do" is an hour, not a week.
- Write findings back into this folder as short notes with numbers, like
  `ann-comparison.md`. A note without a measurement is a blog post.
- Anything that changes the product goes in `planning/`, not here.
