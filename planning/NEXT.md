# Next

The queue, in the order it should be taken. Each line says what it needs
before it can start and what it costs; anything with a ₹ or $ figure is
asked for before it runs. Move a line to [`PROGRESS.md`](PROGRESS.md) when it
ships; move it to the bottom section when it is decided against.

## Now — Milestone 19 ([`milestone-19.md`](milestone-19.md))

| # | Step | Needs | Cost | State |
| --- | --- | --- | --- | --- |
| 1 | Review `ui-redesign/sextant` and port it into `frontend/` | — | ₹0 | **shipped** 2026-09-27 — four post-scan gaps closed first (tables, Markdown export, `sextant.*` storage keys, growing composer); verified live against `:8100`; bundle 61.5 → 186.8 kB gzip after lazy-loading the Lab |
| 2 | Drop the `AGENTICRAG_` env fallback; a leftover is a printed warning, not a silent default | — | ₹0 | **shipped** 2026-09-28 (0.8.1) — done off the box so the trip below is shorter; `settings.legacy_warning()` names every stale variable at startup |
| 3 | Deploy it and rewrite the box's `.env` onto `SEXTANT_*` | VM up | ₹703 spent (≈₹2 of work, ₹701 of a VM left running five days) | **shipped** 2026-09-28 — `.env` rewritten first, tree shipped, stack rebuilt; `/health` reports `budget_usd: 0.6` under the new name, logs clean, new bundle served, two live queries |
| 4 | Rotate the `GEMINI_API_KEY` exposed in a screenshot 2026-09-23 | you create and paste the key; VM up to install it | ≈₹2 VM | **deferred by you 2026-10-03** — the key is wired into several places, so revocation waits on that work. It is still live until then |

## Done — Milestone 18 ([`milestone-18.md`](milestone-18.md))

| # | Step | Needs | Cost | State |
| --- | --- | --- | --- | --- |
| 1 | Re-ingest the deployed store on the current pipeline; drop the résumé document | VM up | ₹8 spent (≈₹2 VM, ~$0.07 overviews) | **shipped** 2026-09-27 — 61 chunks/22 docs → 79 chunks/21 docs with 21 overviews, the box rebuilt onto the replacement `_store` first, résumé removed, one live query verified, VM parked and IP released |
| 2 | `--summaries` on by default when a key resolves | — | ₹0 to ship, $0.003/document at upload | **shipped** 2026-09-24 — the key is the switch; `--no-summaries` opts out, no key is a printed line — [`../learning/summary-chunks.md`](../learning/summary-chunks.md) |
| 3 | 0.8: drop the four `agenticrag-*` command aliases, bump the version | — | ₹0 | **shipped** 2026-09-24 — `AGENTICRAG_` env prefix kept, the box's `.env` still uses it |

## Done — Milestone 17 ([`milestone-17.md`](milestone-17.md))

| # | Step | Needs | Cost | State |
| --- | --- | --- | --- | --- |
| 1 | Per-document candidate cap | — | ₹0 | **shipped** 2026-09-17, default 2, guarded — [`../learning/candidate-cap.md`](../learning/candidate-cap.md) |
| 2 | `kb_list` tool: titles, overviews, chunk counts offered to the agent | — | $0.034 | **shipped** 2026-09-20 — lists first on 4/5 global + 3/3 starters, names 100% of expected docs — [`../learning/kb-list.md`](../learning/kb-list.md) |
| 3 | Composer fix deploy — already on `main`, not on the VM | VM start: re-reserve IP, `add-access-config`, new key on the VM | ≈₹4 (40 min up) | **shipped** 2026-09-23 — the box was on a pre-`kb_list` image, so this carried all of M17; live, gated, one query verified |

## Then — candidates, not yet planned

Each becomes a milestone section with a hypothesis and a rule before it
runs; none is started on a hunch.

| Idea | Why it is on the list | Needs | Cost |
| --- | --- | --- | --- |
| Per-user upload (multi-corpus) | the app is one corpus per deployment; a hosted version needs `category` to mean a person | design | ₹0 |
| Request-level index tier (`exact` flat / `fast` hnsw / `lean` ivfpq_rerank) | caller states a budget, server maps to index + params; only meaningful past ~25k chunks, where HNSW overtakes flat (`../learning/ivfpq-100k.md`) | corpus ≥ 25k | ₹0 |

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
- **HyDE / query expansion** — the generator does not know a personal
  corpus's world: for the vocabulary-free question it wrote a passage about
  a different system; dense worse on both sets, invisible after the
  reranker, and a fabricated passage scores 0.70 against a corpus that
  cannot answer the question. `../learning/hyde.md`.
- **Prompt caching** — the 1,410-token prefix is under the implicit-cache
  minimum (0 of 22 turns hit); an explicit cache works and saves 40% gross
  but 28% net of storage at 5 queries/hour, under the 30% rule, and needs
  re-creating on every prompt or tool change while the deployment idles.
  `cached_tokens` is reported and priced so the number is honest if one is
  ever configured. `../learning/prompt-caching.md`.
- **Floor fallback as a cost feature** — measured on all 55 answerable
  handbook questions, both arms, judged: it is safe (false abstention 1 →
  0, faithfulness 0.936 → 0.960, citations valid in both arms) but it
  **fired on one question of 55**. The pre-registered exposure clause
  failed; every set-level number that moved is one-run nondeterminism, not
  the knob. Closed: the benefit is q29 and the cost is a flag, a branch, a
  prompt paragraph and a mode the model has to reason about.
  `../learning/floor-fallback-cost.md`.
- **Floor fallback as a recall fix** — handing the model the sub-floor
  dense order does not recover q48: the model's phrasing decides whether
  the answer chunk clears 0.01 by 0.003, and below the floor dense cosine
  picks a document's title chunk over its answer paragraph. The knob stays
  (default `none`) for the cost result above. `../learning/floor-fallback.md`.
- **Per-query routing between HNSW and IVF-PQ** — query text carries no
  signal for it, and holding both resident forfeits IVF-PQ's only win
  (memory) while HNSW beats it on recall and latency at every size
  measured. Tier per request, not route per query. `../learning/ivfpq-100k.md`.
- **Keeping the static IP while parked** — ₹21/day for nothing; released
  twice, most recently 2026-09-23 after the composer deploy.

## Shipped, moved out of the queue

- **Make the repo public** — done 2026-09-20, MIT. The standing
  consequence: the VM's IP never goes into a tracked file.
