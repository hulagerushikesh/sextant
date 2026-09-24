# Planning

Where the project is, what it costs, and what comes next. Learning material
lives in [`../learning/`](../learning/); this folder is only about moving the
product.

| | Read |
| --- | --- |
| **Next** | [`NEXT.md`](NEXT.md) — the queue: what is in progress, what waits on a key or a go-ahead, what was decided against and why |
| **Now** | [`milestone-18.md`](milestone-18.md) — re-ingest the deployed store, `--summaries` by default, cut 0.8 |
| **Progress** | [`PROGRESS.md`](PROGRESS.md) — what shipped, by date |
| **Past plans** | [`milestone-17.md`](milestone-17.md) — cap, `kb_list`, three candidates closed, done · [`milestone-16.md`](milestone-16.md) — five retrieval experiments, done · [`milestone-15.md`](milestone-15.md) — ship, prove, rename, done · [`go-live-proof.md`](go-live-proof.md) — what was observed when the site went live |
| **History** | [`trackers/`](trackers/) — HTML checklists from phases 9–13 · [`archive/`](archive/) — course-era docs describing features never built (`archive/README.md`) |

Operational runbooks stay next to what they operate: [`../deploy/README.md`](../deploy/README.md)
(GCP + Caddy), [`../eval/README.md`](../eval/README.md) (golden set + metrics).

## Status (2026-09-24)

| Phase | What | State |
| --- | --- | --- |
| 0–8 | Foundation → MCP server → agent loop → hybrid retrieval → eval harness → hardening → interface → Gemini port | Done |
| 9–12 | Index Lab: flat/HNSW/IVF-PQ from scratch, FAISS reference, two-stage rerank, live `AGENTICRAG_ANN_INDEX` switch | Done |
| 13 | Production deploy: prod compose, Caddy edge, preflight, GCP provisioned, image built on VM | **Live** 2026-09-15 at `agenticrag.hulage.in` (Basic-auth gate); VM run on demand |
| 14 | Product-grade UI: ⌘K palette, shortcuts, empty states, onboarding, skeletons, toasts | Done |
| 15 | Ship + prove + rename | **Done** 2026-09-15 — A–E; snapshot drill skipped. `go-live-proof.md` |
| 16 | Retrieval research: table chunking, agent-level eval, chunk size, embedder swap, summary nodes | **Experiments done** (5/5, $0.21) — table chunking shipped (+0.09 hit@1); decomposition prompt + last-turn note shipped; bge-small, chunk size, summaries measured and kept as knobs; PDF extractor moved to PyMuPDF. Table rendering + Markdown export shipped 2026-09-17; composer fix deployed 2026-09-23; see `milestone-16.md` |
| 17 | Per-document candidate cap; `kb_list` tool; three product candidates measured | **Done** 2026-09-23 — cap shipped 09-17 (default 2, dense r@5 +0.02 to +0.07, rerank unchanged); `kb_list` shipped 09-20 (lists first on 4/5 global questions, names 100% of expected documents); floor fallback, prompt caching and the fallback's cost claim measured and closed ($0.43 across the three); composer fix deployed 09-23. See `milestone-17.md` |
| 18 | Re-ingest the deployed store; `--summaries` by default; 0.8 | **In progress** — see `milestone-18.md` |

Numbers that describe the system today: 409 tests, mypy clean, two golden
sets (65 questions / 58 chunks; 39 page-labelled / 1,602 chunks), hit@1 0.94
and 0.93 for the full pipeline, ~$0.0015/query on `gemini-3.1-flash-lite`,
22 docs / 1,602 chunks in the local store. Package is `sextant` 0.7.0. The
repo has been public since 2026-09-20 (MIT).

## Cost position

GCP project `agenticrag-rush`, billing account in **INR**.

| Resource | State | ₹/month |
| --- | --- | --- |
| VM `agenticrag` e2-standard-2 | on demand — `deploy.sh HOST start\|stop` | ≈135/day while up (≈4,100 if left on) |
| Static IP | released again 2026-09-23 after the composer deploy; re-reserve on go-live | 0 |
| Boot disk 30 GB pd-standard + data disk 20 GB pd-balanced | kept | ≈270 |
| Budget alert "agenticrag monthly" | ₹1,700 (≈$20), 50/90/100 % | — |
| Gemini | free tier at personal volume | ≈0 |

**Rule:** nothing that turns a meter on (VM start, resize, new resources, bulk
API calls) happens without an explicit OK on the amount.

## Open decisions

1. ~~**Run policy once live**~~ — decided 2026-09-15: on demand.
   `deploy.sh HOST start|stop`; stop after each testing session.
2. ~~**Keep or release the static IP while parked**~~ — reversed 2026-09-17:
   released. A ₹22 day on a stopped VM traced to the idle IP (~₹21/day, the
   largest line); nothing pointed at it. Re-reserve the day the VM goes live
   (`deploy/README.md`, "Parking the VM"). Parked cost is now disks only,
   ~₹270/mo.
3. ~~**Reranker**~~ — settled 2026-09-15: it stays. Only stage with a
   calibrated abstention score; leads ranking at 1,602 chunks. See
   `../learning/reranker-decision.md`.
4. ~~**Make the repo public**~~ — done 2026-09-20. Secret sweep of 28
   commits found no key-shaped strings; email, gate username, the released
   IP and a home path were scrubbed from tracked files; MIT `LICENSE` and
   upstream attribution added. Left in history knowingly: the released IP,
   the author email, and `node_modules` from the pre-rebuild upstream
   commit `3a19674`. **Consequence, standing:** the VM's current IP never
   goes into a tracked file.
