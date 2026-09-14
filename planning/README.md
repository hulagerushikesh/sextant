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

## Status (2026-09-14)

| Phase | What | State |
| --- | --- | --- |
| 0–8 | Foundation → MCP server → agent loop → hybrid retrieval → eval harness → hardening → interface → Gemini port | Done |
| 9–12 | Index Lab: flat/HNSW/IVF-PQ from scratch, FAISS reference, two-stage rerank, live `AGENTICRAG_ANN_INDEX` switch | Done |
| 13 | Production deploy: prod compose, Caddy edge, preflight, GCP provisioned, image built on VM | **Parked** — needs DNS A record + `set-secrets.sh` from the owner |
| 14 | Product-grade UI: ⌘K palette, shortcuts, empty states, onboarding, skeletons, toasts | Done |
| 15 | Ship + prove + rename | **Next** — see `milestone-15.md` |

Numbers that describe the system today: 318 tests, mypy clean, 60-question
golden set, hit@1 0.94 (rrf) on the committed corpus, ~$0.003/query on
`gemini-3.1-flash-lite`, 22 docs / 1,602 chunks in the local store.

## Cost position

GCP project `agenticrag-rush`, billing account in **INR**.

| Resource | State | ₹/month |
| --- | --- | --- |
| VM `agenticrag` e2-standard-2 | **stopped** 2026-09-14 | 0 (≈4,100 if running 24/7; ≈135/day) |
| Static IP `35.226.228.218` | reserved, VM stopped | ≈600 (idle IPs bill ~2× in-use) |
| Boot disk 30 GB pd-standard + data disk 20 GB pd-balanced | kept | ≈270 |
| Budget alert "agenticrag monthly" | ₹1,700 (≈$20), 50/90/100 % | — |
| Gemini | free tier at personal volume | ≈0 |

**Rule:** nothing that turns a meter on (VM start, resize, new resources, bulk
API calls) happens without an explicit OK on the amount.

## Open decisions

1. **Run policy once live** — 24/7 e2-standard-2 (≈₹4,100/mo), 24/7 e2-medium
   (≈₹2,100/mo, 4 GB — untested under torch + Chroma), or on-demand start/stop
   (≈₹5.6/hr while up). Default proposal: on-demand with a `deploy.sh
   start|stop` wrapper until usage justifies always-on.
2. **Keep or release the static IP while parked** — ₹600/mo for an address no
   DNS record points at yet. Decided 2026-09-14: keep.
3. **Reranker** — evidence says it does not earn its place at 52 chunks; unproven
   at 1,568. Milestone 15 settles it with data before the image is slimmed.
4. **Make the repo public** — requires stripping `ACME_EMAIL` from
   `deploy/env.example` and a final secret sweep of history.
