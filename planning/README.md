# Planning

Where the project is, what it costs, and what comes next. Learning material
lives in [`../learning/`](../learning/); this folder is only about moving the
product.

- [`milestone-15.md`](milestone-15.md) — **current plan**: ship, prove, and
  make the name true.
- [`trackers/`](trackers/) — self-contained HTML checklists from earlier
  phases (open in a browser; state lives in localStorage).
  - `deployment-tracker.html` — Phase 13 track A/B checklist.
  - `index-lab-tracker.html` — Phase 9–12 ANN follow-ups, 24/24 done.
- [`archive/`](archive/) — the original course-era docs. They describe
  features that were never built (see `archive/README.md`). History only.

Operational runbooks stay next to what they operate: [`../deploy/README.md`](../deploy/README.md)
(GCP + Caddy), [`../eval/README.md`](../eval/README.md) (golden set + metrics).

## Status (2026-09-15)

| Phase | What | State |
| --- | --- | --- |
| 0–8 | Foundation → MCP server → agent loop → hybrid retrieval → eval harness → hardening → interface → Gemini port | Done |
| 9–12 | Index Lab: flat/HNSW/IVF-PQ from scratch, FAISS reference, two-stage rerank, live `AGENTICRAG_ANN_INDEX` switch | Done |
| 13 | Production deploy: prod compose, Caddy edge, preflight, GCP provisioned, image built on VM | **Live** 2026-09-15 at `agenticrag.hulage.in` (Basic-auth gate); VM run on demand |
| 14 | Product-grade UI: ⌘K palette, shortcuts, empty states, onboarding, skeletons, toasts | Done |
| 15 | Ship + prove + rename | **Done** 2026-09-15 — A–E; snapshot drill skipped. `go-live-proof.md` |

Numbers that describe the system today: 320 tests, mypy clean, two golden
sets (60 questions / 52 chunks; 32 page-labelled / 1,602 chunks), hit@1 0.94
and 0.93 for the full pipeline, ~$0.003/query on `gemini-3.1-flash-lite`,
22 docs / 1,602 chunks in the local store. Package is `sextant` 0.7.0.

## Cost position

GCP project `agenticrag-rush`, billing account in **INR**.

| Resource | State | ₹/month |
| --- | --- | --- |
| VM `agenticrag` e2-standard-2 | on demand — `deploy.sh HOST start\|stop` | ≈135/day while up (≈4,100 if left on) |
| Static IP `35.226.228.218` | reserved, VM stopped | ≈600 (idle IPs bill ~2× in-use) |
| Boot disk 30 GB pd-standard + data disk 20 GB pd-balanced | kept | ≈270 |
| Budget alert "agenticrag monthly" | ₹1,700 (≈$20), 50/90/100 % | — |
| Gemini | free tier at personal volume | ≈0 |

**Rule:** nothing that turns a meter on (VM start, resize, new resources, bulk
API calls) happens without an explicit OK on the amount.

## Open decisions

1. ~~**Run policy once live**~~ — decided 2026-09-15: on demand.
   `deploy.sh HOST start|stop`; stop after each testing session.
2. **Keep or release the static IP while parked** — ₹600/mo for an address no
   DNS record points at yet. Decided 2026-09-14: keep.
3. ~~**Reranker**~~ — settled 2026-09-15: it stays. Only stage with a
   calibrated abstention score; leads ranking at 1,602 chunks. See
   `../learning/reranker-decision.md`.
4. **Make the repo public** — requires stripping `ACME_EMAIL` from
   `deploy/env.example` and a final secret sweep of history.
