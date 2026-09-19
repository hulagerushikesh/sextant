# Next

The queue, in the order it should be taken. Each line says what it needs
before it can start and what it costs; anything with a ₹ or $ figure is
asked for before it runs. Move a line to [`PROGRESS.md`](PROGRESS.md) when it
ships; move it to the bottom section when it is decided against.

## Now — Milestone 17 ([`milestone-17.md`](milestone-17.md))

| # | Step | Needs | Cost | State |
| --- | --- | --- | --- | --- |
| 1 | Per-document candidate cap | — | ₹0 | **shipped** 2026-09-17, default 2, guarded — [`../learning/candidate-cap.md`](../learning/candidate-cap.md) |
| 2 | `kb_list` tool: titles, overviews, chunk counts offered to the agent | — | ₹0 | **built** 2026-09-19; measurement (~$0.05, agent harness on 5 global + 3 starter questions) waits on a key |
| 3 | Composer fix deploy — already on `main`, not on the VM | VM start: re-reserve IP, `add-access-config`, new key on the VM | ≈₹5.6/hr while up, ~20 min | waiting on go-ahead |

## Then — candidates, not yet planned

Each becomes a milestone section with a hypothesis and a rule before it
runs; none is started on a hunch.

| Idea | Why it is on the list | Needs | Cost |
| --- | --- | --- | --- |
| HyDE / query expansion | q48 (agent-loop note): every phrasing scores ≈0 under the reranker; a hypothetical answer may embed where the question does not | key | ~$0.05 |
| Prompt caching on the system prompt + tool schemas | ~1,000 input tokens repeated every turn; Gemini bills cached context lower | key | ~$0.02 to measure |
| `--summaries` as the upload default | cap removed the dense cost (this milestone); only "needs a key at ingest" remains | decision | $0.003 / document at upload |
| Per-user upload (multi-corpus) | the app is one corpus per deployment; a hosted version needs `category` to mean a person | design | ₹0 |
| Request-level index tier (`exact` flat / `fast` hnsw / `lean` ivfpq_rerank) | caller states a budget, server maps to index + params; only meaningful past ~25k chunks, where HNSW overtakes flat (`../learning/ivfpq-100k.md`) | corpus ≥ 25k | ₹0 |
| IVF with an HNSW coarse quantizer (`IVF_HNSW`) at 1M synthetic | where graph and clusters genuinely combine: HNSW over ~65k centroids for routing, PQ codes for storage; learning path §9 item 6 | — | ₹0, RAM-bound on this laptop |
| Make the repo public | strip `ACME_EMAIL` from `deploy/env.example`; secret sweep of history | decision | ₹0 |
| Remove `agenticrag-*` command aliases | promised for 0.8 | 0.8 release | ₹0 |

## Decided against (with the reason, so it is not re-litigated)

- **RAPTOR tree** — one level already saturates hit@5 on this corpus; the
  question a tree would serve is a listing (`kb_list`), not a retrieval.
  `../learning/summary-chunks.md`.
- **Swapping MiniLM for bge-small** — +0.09 dense on the survey, −0.04 on
  the handbook, rerank unmoved; opt-in via `SEXTANT_EMBEDDER`.
  `../learning/embedder-swap.md`.
- **150-token chunks** — helps the reranker, hurts dense; the cap has since
  removed the dense cost, so this could be re-measured, but 200 has no
  known miss that 150 fixes. `../learning/chunk-size.md`.
- **Dropping the reranker** — only stage with a calibrated abstention
  score; leads at 1,602 chunks. `../learning/reranker-decision.md`.
- **Cloud Run / scale-out / 24×7 hosting** — embedded Chroma is
  single-writer; run policy is on demand. `milestone-15.md`.
- **Per-query routing between HNSW and IVF-PQ** — query text carries no
  signal for it, and holding both resident forfeits IVF-PQ's only win
  (memory) while HNSW beats it on recall and latency at every size
  measured. Tier per request, not route per query. `../learning/ivfpq-100k.md`.
- **Keeping the static IP while parked** — ₹21/day for nothing; released.
