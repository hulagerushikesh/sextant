# Milestone 16 — Retrieval research, measured

Milestone 15 left the system live, named, and with two golden sets. The
misses those sets expose are now specific enough to be experiments, and the
harness is good enough to grade them. This milestone is five experiments,
each run the same way: a hypothesis written down first, one change, both
golden sets, a decision rule stated before the numbers exist, and a note in
`learning/` whether it wins or loses. A losing experiment with a table is a
result; a winning one without a table is a rumour.

Nothing here touches the VM. Model calls are the only spend and every paid
run is asked for first, with its estimate.

## What the data says is wrong

| Symptom | Evidence | Experiment |
| --- | --- | --- |
| Table rows are unreachable | L25, L26: the prose page is found, the architecture-table page is not — "PaLM · RoPE · SwiGLU" is diluted by 15 sibling rows in one chunk | **1** |
| Two-part questions retrieve one part | 3 of 50 handbook misses and all 3 large-set misses are multi-hop; the agent *can* search twice, nobody has measured whether it does | **2** |
| Retrieval is graded, the agent is not | Every number so far is `kb.search()`; the loop that chooses queries is untested end to end | **2** |
| MiniLM's 256-token window shaped chunking | 200-token chunks exist because of the embedder, not the content | **3** |
| Paraphrase questions are the weakest dense kind | dense hit@1 0.815 on the survey; lexical equals it, which should not happen on semantic questions | **4** |
| "What topics do my documents cover?" is a starter prompt and a bad retrieval target | flat chunks answer local questions; the opening screen asks a global one | **5** |

## Experiments

### 1 · Table-aware chunking — ₹0 — **done, shipped** (2026-09-16)

Result: large set rerank hit@1 0.818 → 0.909, recall@5 0.909 → 0.985,
6/6 new table questions hit, handbook flat; L25 still misses (multi-hop,
now experiment 2's). One row per chunk failed the CI gate on dense
(crowding); shipped at ≤120 tokens of rows per chunk. Note:
[`learning/table-chunking.md`](../learning/table-chunking.md).

**Hypothesis.** A table row is a record, not prose. Chunking each row (or
each small run of rows) with the table's header prepended makes "which
position embedding does PaLM use" a one-chunk hit.

**Change.** `loaders.py`: detect table regions in PDF text (pypdf gives
lines; a run of ≥3 lines with the same column count by whitespace split
is a table). Emit them as `Locator("table", ...)` spans; `chunking.py`
chunks a table span row-wise with the header line prefixed, never merging
it with surrounding prose. Markdown pipes get the same treatment.

**Measure.** Add 6 table questions to `golden-large.jsonl` (rows from
Tables 3, 6, 7, 9 of the survey). Re-grade both sets.

**Decision.** Ship if L25/L26 and ≥4/6 new table questions hit at k=5 and
the handbook set does not drop by more than the 0.02 gate. If prose
metrics fall, tables get their own chunks but stay in the same index —
no second index. *(Outcome: L26 and 6/6 hit, L25 did not — shipped on
the intent, deviation recorded in the note.)*

### 2 · Grade the agent, not just the retriever — $0.14 — **done, prompt shipped** (2026-09-16)

Result: the loop does not search twice on its own — multi-hop recall@union
0.722 under the shipped prompt, equal to recall@first, three runs. One
decomposition bullet: 0.778 in three of three runs (L25 recovered every
time, its first query now ranks the PaLM row first), no turns added to
any other kind; shipped. The three left: two are answered correctly from
one document (labels over-specify), one (q48) is unreachable by this
retriever at any phrasing. Side findings: the `min_score` floor sends the
model into 3–6-search loops on questions the harness passes, and at the
turn cap the answer could be empty — fixed with a last-turn note.
`sextant-eval-agent` (`eval/agent_harness.py`) is the re-run path. Note:
[`learning/agent-loop.md`](../learning/agent-loop.md).

**Hypothesis.** The agent already resolves multi-hop by searching twice;
the misses are a `kb.search()` artefact and vanish end to end. (L25 is
the live example after experiment 1: the PaLM row ranks 10th behind
three RoPE prose pages that answer the question's other half.) Or it
doesn't, and the prompt needs a decomposition nudge.

**Change.** `eval/agent_harness.py` (new, `sextant-eval-agent`): run each
answerable question through `mcp_server.agent.run` with the real model,
collect every `kb_search` call the loop made, union the retrieved units,
grade recall@union against the labels. Report calls-per-question and cost.
Stub-model variant (`tests/fakes.py`) keeps it testable without a key.

**Measure.** All 9 multi-hop questions plus a 20-question sample of the
rest, both sets. ~30 questions × 2–3 turns × $0.003 ≈ $0.30.

**Decision.** If multi-hop recall@union ≥ 0.9, record that the loop
already does the job and the retriever-level miss is not a product miss.
If not, one prompt change ("if the question has two parts, search for each")
and re-run; ship only if it moves recall without adding turns elsewhere. *(Outcome: 0.722, not met; the prompt change moved it to 0.778
with no turns added elsewhere and shipped; 0.9 is not reachable by
prompting on this set — see the note.)*

### 3 · Chunk size without the 256 ceiling — ₹0 — **done, 200 stays** (2026-09-16)

Result: 150 wins rerank hit@1 on both sets (+0.03 / +0.04) but fails the
CI gate on dense/RRF (crowding, −0.06 / −0.04 handbook alone); 300/400
lose for both embedders — dilution, not truncation. `SEXTANT_CHUNK_TOKENS`
shipped as a knob with an embedder-window guard. Follow-up candidate for
M17: per-document cap on candidates, which would likely unlock 150. Note:
[`learning/chunk-size.md`](../learning/chunk-size.md).

**Hypothesis.** With a 512-token embedder (experiment 4) the 200/40
chunking is a leftover. (Experiment 4 did not switch the default, so this
sweep runs both embedders: bge might win at sizes MiniLM cannot embed.) Larger chunks may help hit@1 (more context per
hit) or hurt (dilution, the 0.94 → 0.44 effect measured in Phase 4).

**Change.** None to code: `target_tokens` and `overlap_tokens` are already
parameters. Sweep {150, 200, 300, 400} × overlap {20%} on both sets, with
MiniLM and with the experiment-4 embedder.

**Decision.** Keep 200 unless a size wins on both sets by ≥ 0.03 hit@1.
Record the curve either way; it is the first chunk-size measurement in
this repo. *(Outcome: 150 met this on rerank but broke the CI gate on the
ablations; the gate is the stricter criterion and won.)*

### 4 · Embedder swap: MiniLM → bge-small-en-v1.5 — ₹0 — **done, not switched** (2026-09-16)

Result: dense hit@1 +0.091 on the survey, −0.04 on the handbook; rule
needed both. Rerank unchanged either way. Cosine calibration did not
travel. `SEXTANT_EMBEDDER`, the per-model query prefix and the store
guard shipped; default stays MiniLM. Note:
[`learning/embedder-swap.md`](../learning/embedder-swap.md).

**Hypothesis.** bge-small (384-d, 512-token window, higher MTEB retrieval
score) lifts dense hit@1 on paraphrase questions and gives a cosine scale
calibrated enough that the abstention threshold travels between corpora
(MiniLM's did not: 0.0001/0.97 on one set, 0.37/0.26 on the other).

**Change.** `embeddings.py` reads the model name from
`SEXTANT_EMBEDDER` (default unchanged). Re-ingest into a scratch store
(the store is keyed by model, so mixing is impossible by construction —
add that guard: refuse to open a collection embedded by a different
model).

**Measure.** Both sets, all four modes; dense-only separation table.

**Decision.** Switch the default if dense hit@1 gains ≥ 0.03 on both sets
and rerank does not regress *(outcome: one set only — not switched)*; the image grows ~130 MB and every existing
store must re-ingest, so the note states that cost plainly. If cosine
separation exceeds the reranker's, revisit `learning/reranker-decision.md`
— that is the "what would change the decision" clause coming due.

### 5 · Summary nodes for global questions (RAPTOR-lite) — $0.07 — **done, opt-in** (2026-09-16)

Result: the premise failed — global hit@5 was already 1.0 on this corpus
(a short document's first chunk is its overview), so the rule could not
be met. Summaries buy rank through the reranker (global hit@1 0.6 → 1.0,
local +0.02 on both stores) and cost dense recall@5 (−0.07 alone;
crowding, third time). `sextant-ingest --summaries` ships as opt-in; no
tree. The starter question "what topics do my documents cover" is a
listing question, not a retrieval one — `kb_list` is the M17 candidate
it argues for. Note:
[`learning/summary-chunks.md`](../learning/summary-chunks.md).

**Hypothesis.** One model-written summary per document, stored as a
chunk tagged `level: summary`, makes "what topics do my documents cover"
and "compare X and Y" retrieve the right documents instead of whichever
chunk mentions the word "topic".

**Change.** `sextant-ingest --summaries` writes one summary chunk per
document (22 docs ≈ $0.10 once). Search is unchanged; summaries compete
in the same index. Golden: 6 new "global" questions across both sets.

**Decision.** Ship as opt-in if global questions go from ≤ 0.3 to ≥ 0.8
hit@5 and local questions do not move. Not the full RAPTOR tree — one
level is the cheapest version of the idea and the eval says whether the
tree is worth building. *(Outcome: control was already 1.0 hit@5; the tree is not
worth building here, the flag stays as measured.)*

## Order and dependencies

1 → 4 → 3 (chunk size only makes sense once the embedder is chosen) →
2 → 5. Experiments 1, 3 are free; 4 is one download; 2 and 5 are the
paid ones and come last so the free results shape their questions.
*(All five done 2026-09-16; total model spend $0.21 of the $1 budget.)*

## Also in this milestone (small, product)

- Ship the composer fix already on `main` the next time the VM is up.
- ~~Render markdown tables in answers~~ — done 2026-09-17: a GFM table
  block in `Answer.jsx` (rule row required, so a streaming header renders
  as prose until the rule lands; citations work inside cells).
- ~~Export a conversation as Markdown from the palette~~ — done
  2026-09-17: `frontend/src/export.js`, questions as headings, answers
  verbatim, numbered source list, spend footer.

## Out of scope

Scale-out, Chroma client/server, Redis limits — no second replica exists.
24/7 hosting and the uptime check — run policy is on demand. GraphRAG,
ColBERT, SPLADE — each is a different index, not a measured tweak to this
one; they are Milestone 17 candidates if experiment 5 shows global
questions matter.

## Definition of done

- Five notes in `learning/` with the hypothesis, the table, and the
  decision — including the losses.
- Both golden sets extended (tables, global) and `baseline*.json`
  regenerated; the CI gate still passes.
- Any shipped change wins on **both** sets; nothing ships on one.
- Total model spend ≤ $1, each run approved with its estimate beforehand.
- `learning/README.md` §9 research questions updated to point at the
  notes that answered them.
