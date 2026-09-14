# Milestone 15 — Ship, prove, and make the name true

Phases 0–14 built a working, measured, MCP-native RAG with a product-grade
interface. What is missing is small and concrete: it is not live, the README
stops at Phase 8, the package still calls itself `agentic_rag`, and one
retrieval stage ships on faith. This milestone closes all four without adding
features.

Ordered so that everything free happens first and the only paid step comes
last, gated on an explicit OK.

## Goals

| # | Goal | Cost | Done when |
| --- | --- | --- | --- |
| A | Identity: `sextant` everywhere | ₹0 | package, CLIs, README, UI title all say sextant; tests green |
| B | Settle the reranker with data | ₹0 (local CPU) | eval row on a 1.5k-chunk corpus; decision recorded; image slimmed if dropped |
| C | Docs match the code | ₹0 | README roadmap through 15, links fixed, `learning/` + `planning/` referenced |
| D | Go live behind the gate | **≈₹135/day while up** — ask first | `https://agenticrag.hulage.in/health` → `healthy` through Basic auth; one cited `/query` proof |
| E | Ops floor | ₹0–small | uptime check, non-root container, start/stop wrapper, snapshot restore tested once |

## A — Identity (free)

1. Rename Python package `agentic_rag` → `sextant`; console scripts
   `agenticrag-kb/ingest/eval/judge` → `sextant-kb/ingest/eval/judge`. Keep
   the old names as aliases for one release so muscle memory and docs do not
   break at once.
2. Env vars: keep `AGENTICRAG_*` working, add `SEXTANT_*` as the documented
   names (read both, prefer `SEXTANT_`). Changing env names silently breaks
   the VM `.env`; aliasing does not.
3. UI: `<title>`, masthead, `agenticrag.onboarded` localStorage key (migrate,
   don't reset onboarding).
4. Docker image names in both compose files; `deploy/README.md` paths.
5. Gate: `pytest -q`, `mypy`, `ruff`, `npm run build`, `docker compose config`.

Risk: the editable install in `.venv` was repaired by path after the folder
rename; a package rename needs `pip install -e .` again and the egg-info
directory removed.

## B — Reranker decision (free, local CPU — kill when done)

The README says reranking ties fusion on 52 chunks and "changed the top hit"
on a 1,568-chunk corpus. That is a hypothesis, not a result.

1. Ingest arXiv 2303.18223 (144 pp, the Phase 4 fixture) into an isolated
   store (`AGENTICRAG_CHROMA_DIR` in the scratchpad — never the live
   `chroma_db`).
2. Write 30 golden questions over it (10 lexical-heavy, 10 semantic, 5
   multi-hop, 5 unanswerable) in a second `golden-large.jsonl`.
3. Run the four ablations; add the table to `eval/README.md`.
4. Decide with a stated threshold: keep the cross-encoder if it gains ≥ 0.03
   hit@1 or ≥ 0.02 nDCG@5, or if unanswerable-query rejection gets worse
   without it. Otherwise make it opt-in (`AGENTICRAG_RERANK=0` default), drop the model
   from the default image (−90 MB, faster cold start), and keep the code.
5. Record the outcome in `learning/` as a note with the numbers.

## C — Docs (free)

1. Root README: title `sextant`, roadmap rows 9–15, status table gains Index
   Lab + deploy + palette rows, "Known issues" pruned of the ones since fixed
   (Docker now built, CORS env-driven).
2. Replace the two `docs/` references with `learning/` and `planning/`.
3. `deploy/README.md`: add the stopped-VM resume path (`instances start` →
   wait for ssh → `deploy.sh up`).
4. Root `CLAUDE.md` (project-level) with the standing rules: never touch
   atlas, never push upstream, secret-scan staged contents, ask before cost.

## D — Go live (paid — gated)

Preconditions owned by the project owner, verified before anything starts:

- Cloudflare `A` record `agenticrag` → `35.226.228.218`, proxy **off** (grey
  cloud). Verify: `dig +short agenticrag.hulage.in @nicolas.ns.cloudflare.com`.
- Secrets on the box: `~/agenticrag/set-secrets.sh` run once. Verify (VM up):
  `grep -c '^BASIC_AUTH_HASH=\$2' ~/agenticrag/.env` → `1`.

Then, **after an explicit OK on ≈₹5.6/hr**:

1. `gcloud compute instances start agenticrag --zone=us-central1-a --project=agenticrag-rush`
2. `deploy/deploy.sh agenticrag.us-central1-a.agenticrag-rush preflight` — all green.
3. `deploy/deploy.sh … up` — image already built on the boot disk, so this is
   sync + `compose up` + cert issuance (~2 min).
4. Corpus: `docker compose -f docker-compose.prod.yml exec api agenticrag-ingest eval/corpus -r`
   then `restart api`.
5. Proof: gated `/health` → `healthy`, one `/query` with citations, one 401
   without credentials. Screenshot + response bodies into `planning/`.
6. Decide run policy (see `README.md` → Open decisions). If on-demand: stop
   the VM the same day. Cost of the proof itself: well under ₹50.

## E — Ops floor (mostly free)

1. `deploy/deploy.sh start|stop|status` wrapping `gcloud compute instances
   …` — the thing that makes on-demand cheap to actually do.
2. Uptime check with Basic-auth header on `/health` (GCP Monitoring; free
   tier covers one) — only meaningful if 24/7 is chosen.
3. Non-root user in the API Dockerfile; verify `HF_HOME` cache and
   `/data/chroma` are writable by it (the untested risk noted in Phase 13).
4. Restore a nightly snapshot to a scratch disk once and read the Chroma
   sqlite from it — a backup is a theory until restored. Small one-off cost
   (≈₹10) — ask first.

## Out of scope for 15

Retrieval research (HyDE, RAPTOR, embedder swap) — those are `learning/`
§9 experiments and become Milestone 16 once B has produced the larger golden
set they all need. Scale-out (Chroma client/server, Redis limits) — not until
there is a second replica to justify it.

## Definition of done

- `sextant --help` style names work; old names still work.
- Reranker decision recorded with a table; default image reflects it.
- README roadmap ends at 15 with every row true.
- One authenticated, cited answer served from `agenticrag.hulage.in`, and the
  VM's run policy chosen and applied.
- Total new cloud spend for the milestone ≤ ₹200 unless 24/7 is chosen.
