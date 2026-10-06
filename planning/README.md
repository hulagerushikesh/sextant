# Planning

Where the project is, what it costs, and what comes next. Learning material
lives in [`../learning/`](../learning/); this folder is only about moving the
product.

| | Read |
| --- | --- |
| **Next** | [`NEXT.md`](NEXT.md) — the queue: what is in progress, what waits on a key or a go-ahead, what was decided against and why |
| **Now** | [`milestone-21.md`](milestone-21.md) — what else assumed there was one person: two doors the scope does not reach, two counters that still count one, and the trip that puts 0.8.2–0.8.4 on the box |
| **Progress** | [`PROGRESS.md`](PROGRESS.md) — what shipped, by date |
| **Past plans** | [`milestone-20.md`](milestone-20.md) — what a corpus belongs to; four items, ₹0, done · [`milestone-19.md`](milestone-19.md) — the redesigned UI is the UI; the key rotation is its one open item · [`milestone-18.md`](milestone-18.md) — re-ingest, summaries by default, 0.8, done · [`milestone-17.md`](milestone-17.md) — cap, `kb_list`, three candidates closed, done · [`milestone-16.md`](milestone-16.md) — five retrieval experiments, done · [`milestone-15.md`](milestone-15.md) — ship, prove, rename, done · [`go-live-proof.md`](go-live-proof.md) — what was observed when the site went live |
| **History** | [`trackers/`](trackers/) — HTML checklists from phases 9–13 · [`archive/`](archive/) — course-era docs describing features never built (`archive/README.md`) |

Operational runbooks stay next to what they operate: [`../deploy/README.md`](../deploy/README.md)
(GCP + Caddy), [`../eval/README.md`](../eval/README.md) (golden set + metrics).

## Status (2026-10-06)

| Phase | What | State |
| --- | --- | --- |
| 0–8 | Foundation → MCP server → agent loop → hybrid retrieval → eval harness → hardening → interface → Gemini port | Done |
| 9–12 | Index Lab: flat/HNSW/IVF-PQ from scratch, FAISS reference, two-stage rerank, live `AGENTICRAG_ANN_INDEX` switch | Done |
| 13 | Production deploy: prod compose, Caddy edge, preflight, GCP provisioned, image built on VM | **Live** 2026-09-15 at `agenticrag.hulage.in` (Basic-auth gate); VM run on demand |
| 14 | Product-grade UI: ⌘K palette, shortcuts, empty states, onboarding, skeletons, toasts | Done |
| 15 | Ship + prove + rename | **Done** 2026-09-15 — A–E; snapshot drill skipped. `go-live-proof.md` |
| 16 | Retrieval research: table chunking, agent-level eval, chunk size, embedder swap, summary nodes | **Experiments done** (5/5, $0.21) — table chunking shipped (+0.09 hit@1); decomposition prompt + last-turn note shipped; bge-small, chunk size, summaries measured and kept as knobs; PDF extractor moved to PyMuPDF. Table rendering + Markdown export shipped 2026-09-17; composer fix deployed 2026-09-23; see `milestone-16.md` |
| 17 | Per-document candidate cap; `kb_list` tool; three product candidates measured | **Done** 2026-09-23 — cap shipped 09-17 (default 2, dense r@5 +0.02 to +0.07, rerank unchanged); `kb_list` shipped 09-20 (lists first on 4/5 global questions, names 100% of expected documents); floor fallback, prompt caching and the fallback's cost claim measured and closed ($0.43 across the three); composer fix deployed 09-23. See `milestone-17.md` |
| 18 | Re-ingest the deployed store; `--summaries` by default; 0.8 | **Done** 2026-09-27 — 0.8 cut and summaries defaulted 09-24; a re-ingest made a replacement plus `sextant-forget` 09-25; the deployed store re-ingested 09-27 (61 chunks/22 docs → 79/21 with 21 overviews, résumé removed, ₹8). See `milestone-18.md` |
| 19 | Port the redesigned UI into `frontend/` | **Port done** 2026-09-27 — React 19 + TS + Tailwind v4 + shadcn replaces 747 lines of `App.jsx` and 1,952 of `App.css`; four post-scan gaps closed first, three more bugs found by running it; bundle 61.5 → 186.8 kB gzip. Deploy still open. See `milestone-19.md` |

| 20 | What a corpus belongs to: the upload collision, one-collection-vs-one-each, identity, the listing leak | **Done** 2026-10-06, ₹0 across all four — uploads namespaced by owner (0.8.2); **A, one collection filtered**, decided on a measurement that passed and could not have failed (`../learning/multi-corpus.md`); identity forwarded by Caddy and refused without proof (0.8.3); every tool result scoped to the asker (0.8.4). See `milestone-20.md` |
| 21 | What else assumed there was one person | **Planned** 2026-10-06 — two doors the scope does not reach (both reproduced), the limiter and cap that still count one person, and the VM trip carrying 0.8.2–0.8.4 plus the key rotation. See `milestone-21.md` |

Numbers that describe the system today: 488 tests, mypy clean (62 files), two
golden sets (65 questions / 58 chunks; 39 page-labelled / 1,608 chunks), hit@1
0.94 and 0.93 for the full pipeline, ~$0.0015/query on
`gemini-3.1-flash-lite`, 22 docs / 1,660 chunks in the local store. Package is
`sextant` 0.8.4; the deployed box is still on 0.8.1. The repo has been public
since 2026-09-20 (MIT).

## Cost position

GCP project `agenticrag-rush`, billing account in **INR**.

| Resource | State | ₹/month |
| --- | --- | --- |
| VM `agenticrag` e2-standard-2 | on demand — `deploy.sh HOST start\|stop` | ≈135/day while up (≈4,100 if left on) |
| Static IP | released again 2026-09-27 after the re-ingest; re-reserve on go-live | 0 |
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
