# Planning

Where the project is, what it costs, and what comes next. Learning material
lives in [`../learning/`](../learning/); this folder is only about moving the
product.

| | Read |
| --- | --- |
| **Next** | [`NEXT.md`](NEXT.md) — the queue: what is in progress, what waits on a key or a go-ahead, what was decided against and why |
| **Now** | [`milestone-17.md`](milestone-17.md) — candidate cap (shipped), `kb_list` tool (built; measurement waits on a key) |
| **Progress** | [`PROGRESS.md`](PROGRESS.md) — what shipped, by date |
| **Past plans** | [`milestone-16.md`](milestone-16.md) — five retrieval experiments, done · [`milestone-15.md`](milestone-15.md) — ship, prove, rename, done · [`go-live-proof.md`](go-live-proof.md) — what was observed when the site went live |
| **History** | [`trackers/`](trackers/) — HTML checklists from phases 9–13 · [`archive/`](archive/) — course-era docs describing features never built (`archive/README.md`) |

Operational runbooks stay next to what they operate: [`../deploy/README.md`](../deploy/README.md)
(GCP + Caddy), [`../eval/README.md`](../eval/README.md) (golden set + metrics).

## Status (2026-09-17)

| Phase | What | State |
| --- | --- | --- |
| 0–8 | Foundation → MCP server → agent loop → hybrid retrieval → eval harness → hardening → interface → Gemini port | Done |
| 9–12 | Index Lab: flat/HNSW/IVF-PQ from scratch, FAISS reference, two-stage rerank, live `AGENTICRAG_ANN_INDEX` switch | Done |
| 13 | Production deploy: prod compose, Caddy edge, preflight, GCP provisioned, image built on VM | **Live** 2026-09-15 at `agenticrag.hulage.in` (Basic-auth gate); VM run on demand |
| 14 | Product-grade UI: ⌘K palette, shortcuts, empty states, onboarding, skeletons, toasts | Done |
| 15 | Ship + prove + rename | **Done** 2026-09-15 — A–E; snapshot drill skipped. `go-live-proof.md` |
| 16 | Retrieval research: table chunking, agent-level eval, chunk size, embedder swap, summary nodes | **Experiments done** (5/5, $0.21) — table chunking shipped (+0.09 hit@1); decomposition prompt + last-turn note shipped; bge-small, chunk size, summaries measured and kept as knobs; PDF extractor moved to PyMuPDF. Table rendering + Markdown export shipped 2026-09-17; composer fix deployed 2026-09-23; see `milestone-16.md` |
| 17 | Per-document candidate cap; `kb_list` tool | **In progress** — cap shipped 2026-09-17 (default 2, dense r@5 +0.02 to +0.07, rerank unchanged); `kb_list` built 2026-09-19, its measurement waits on a key; see `milestone-17.md` |

Numbers that describe the system today: 320 tests, mypy clean, two golden
sets (60 questions / 52 chunks; 32 page-labelled / 1,602 chunks), hit@1 0.94
and 0.93 for the full pipeline, ~$0.003/query on `gemini-3.1-flash-lite`,
22 docs / 1,602 chunks in the local store. Package is `sextant` 0.7.0.

## Cost position

GCP project `agenticrag-rush`, billing account in **INR**.

| Resource | State | ₹/month |
| --- | --- | --- |
| VM `agenticrag` e2-standard-2 | on demand — `deploy.sh HOST start\|stop` | ≈135/day while up (≈4,100 if left on) |
| Static IP | released 2026-09-17; re-reserve on go-live | 0 |
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
4. **Make the repo public** — requires stripping `ACME_EMAIL` from
   `deploy/env.example` and a final secret sweep of history.
