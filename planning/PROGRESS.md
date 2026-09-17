# Progress

What shipped, by date, newest first. One line per change that moved the
product or a number; the commit message is the detail. Phases 0–14 are
summarised at the bottom — they were built in one rebuild week and their
story is the root README.

## 2026-09-17

- **Per-document candidate cap** shipped as default 2 — dense recall@5
  +0.018 (CI store) to +0.073 (stores with summaries), rerank unchanged,
  both baselines regenerated. Three rounds: hard cap lost a survey page,
  score guard fixed it, restricted to modes whose score is a relevance.
  `learning/candidate-cap.md`. Milestone 17 opened.
- **Markdown tables render** in answers (`Answer.jsx`, one block added);
  **Export as Markdown** in the palette (`frontend/src/export.js`).
- **Static IP released** — ₹22 day on a stopped VM traced to it. Parked
  cost now disks only (~₹270/mo). `deploy.sh start` refuses without an
  address and prints the reattach commands.
- Gemini key deleted by the owner; model-backed paths off until a new one.

## 2026-09-16 — Milestone 16, five experiments, $0.21

- **Exp 5, summary chunks** — opt-in `sextant-ingest --summaries`; global
  hit@1 0.6 → 1.0 under rerank, cost dense recall (fixed 09-17).
- **Exp 2, agent-level eval** — `sextant-eval-agent`; the loop did not
  decompose multi-hop questions (0.722); one prompt bullet → 0.778;
  last-turn note replaces the tool-mode cap that did not work.
- **Exp 3, chunk size** — 200 stays; `SEXTANT_CHUNK_TOKENS` knob.
- **PDF extraction** moved to PyMuPDF (lines rebuilt from span baselines).
- **Exp 4, embedder swap** — bge-small measured, opt-in
  `SEXTANT_EMBEDDER`.
- **Exp 1, table-aware chunking** — shipped; survey rerank hit@1
  0.818 → 0.909.

## 2026-09-15 — Milestone 15, live

- Milestone 16 planned. Compact composer. Go-live proof written.
- Park/unpark from the laptop; non-root container; uptime runbook.
- README made true through M15; `CLAUDE.md` added.
- Reranker question settled on a 1,602-chunk store — it stays.
- Package, CLIs and settings renamed to `sextant`.
- **Live** at `agenticrag.hulage.in` behind the Basic-auth gate; VM run on
  demand.

## 2026-09-13 / 14 — the rebuild

- Rebuilt as an MCP-native agentic RAG with measured retrieval (one
  commit, phases 0–14). `learning/` and `planning/` split out.

## Phases 0–14, in one table

| Phase | What |
| --- | --- |
| 0–8 | Foundation → MCP server → agent loop → hybrid retrieval → eval harness → hardening → interface → Gemini port |
| 9–12 | Index Lab: flat / HNSW / IVF-PQ from scratch, FAISS reference, two-stage rerank, live `ANN_INDEX` switch |
| 13 | Production deploy: prod compose, Caddy edge, preflight, GCP provisioned |
| 14 | Product-grade UI: ⌘K palette, shortcuts, empty states, onboarding, skeletons, toasts |
