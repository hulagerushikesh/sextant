# History

The project as it was built, phase by phase.

> Moved here from the README on 2026-11-12 so the front page could open with a
> quickstart. The text is unchanged apart from link paths.

Formerly *AgenticRAG*; renamed in 0.7. The `agenticrag-*` commands were
dropped in 0.8, and the `AGENTICRAG_*` environment variables in 0.8.1, once the
deployed box's `.env` had been rewritten. A leftover one is now reported at
startup with its new name rather than quietly doing nothing.

## Roadmap

0. **Foundation** — dependency and repo hygiene *(done)*
1. **Generation** — grounded, cited, streamed answers *(done)*
2. **Protocol** — real MCP tool server, discovered not hard-wired *(done)*
3. **Agency** — model-driven tool-use loop, plus server-side web search as a
   second tier *(done)*
4. **Retrieval** — chunking, hybrid search, reranking, PDF ingestion *(done)*
5. **Evaluation** — golden set, metrics, ablations, CI gate *(done)*
6. **Hardening** — tests, types, structured logging, limits, Docker *(done)*
7. **Interface** — chat history, inline citation links, richer agent trace
   *(done)*
8. **Gemini** — generation ported from the Anthropic SDK to `google-genai` *(done)*
9. **Index Lab** — flat, HNSW and IVF-PQ written from scratch and measured on
   the real corpus; finding: exact search wins at personal scale
   (`learning/ann-comparison.md`) *(done)*
10. **Real-corpus proof + two-stage rerank** — IVF-PQ's recall ceiling broken
    by exact re-scoring at unchanged hot memory *(done)*; at 100k vectors the
    dial that lifts it is `oversample`, not `nprobe`
    (`learning/ivfpq-100k.md`) *(done)*
11. **FAISS reference column** — the pure-Python constant factor measured,
    10–280× *(done)*
12. **Live index switch** — `SEXTANT_ANN_INDEX` routes production dense
    retrieval through any of them *(done)*
13. **Production** — prod compose, Caddy TLS + Basic-auth gate, preflight,
    daily spend cap, GCP VM provisioned and image built; edge verified
    locally against a stub API *(done — live 2026-09-15; run on demand since)*
14. **Product-grade interface** — ⌘K palette, keyboard map, empty states,
    onboarding, skeletons, toasts *(done)*
15. **Ship, prove, rename** — `sextant` everywhere; reranker settled with
    data on 1,602 chunks (it stays); docs match the code; go-live; ops floor
    *(done 2026-09-15)*
16. **Milestones 16–22** — five retrieval experiments, a per-document cap,
    document overviews, the rebuilt interface, uploads kept apart per person,
    a published package (`sextant-kb`), and a person removing their own
    upload *(done 2026-11-04)*

What comes next is not more building: it is the first outside users. The plan
is [`planning/PLAN.md`](../planning/PLAN.md).
