# Experiment 1 — Table-aware chunking

*Milestone 16, 2026-09-16. Cost: ₹0. Decision: shipped.*

## Hypothesis

A table row is a record, not prose. Embedded in a 200-token chunk with
fifteen sibling rows, "PaLM · RoPE · SwiGLU" is diluted past retrieval —
the mechanism behind the two misses left after Milestone 15 (L25, L26:
the prose page is found, the architecture-table page is not). Chunking each
row on its own with the table's caption and header prepended should make
"which position embedding does PaLM use" a one-chunk hit.

## What was built

`tools/vector_db/tables.py`, ~200 lines, no dependencies.

- **PDF text has no markup**, so a table is recognised by its caption: an
  IEEE-style `TABLE n:` line, continuing while the lines read as prose
  (mostly lowercase words). The header is the first line that does not,
  plus the lines after it until one carries a digit or an operator — pypdf
  emits a wrapped header one cell fragment per line. Rows run until a blank
  line, the next float's caption, a section heading, or prose again.
- **Markdown** pipe tables need no guessing: header row, `|---|` rule, rows.
- The chunker (`chunking.py`) takes the table spans and emits row chunks:
  `caption (≤240 chars) + "\n" + header + "\n" + rows`, a few rows at a
  time up to `row_tokens` of row text (120 by default; 0 means one row per
  chunk — the sweep below is why it is not 0). The chunk's
  `char_start/char_end` still point at the rows alone, so the citation is
  exact; the embedded text is the one place a chunk is not a plain slice
  of the document. Prose on either side is chunked as before and never
  merged across a table. Rows carry `kind: "row"` in their metadata.
- A group label sitting under the header ("Task", "Chat" in Table 3) is
  carried into each row beneath it.

Detection on the survey (arXiv 2303.18223): 18 of 21 tables, 404 rows.
The three missed (12, 13, 17) have prose bodies — prompt examples — and
belong in the prose stream anyway. Two headers are still imperfect
(Table 1's "Adaptation EvaluationModel Release Time Size (B) …" is what
pypdf gives; Table 11 absorbs its first group label). The survey grows
from 1,550 to 1,627 chunks at the shipped setting (+5%, 126 of them row
chunks); one row per chunk would have been 1,921 (+24%).

## Measurement

Both golden sets, same store layout as the Milestone 15 experiment: 21
handbook documents plus the survey, control (detection disabled) against
treatment, everything else identical. Six table questions added to
`golden-large.jsonl` (L33–L38: rows from Tables 2, 5, 6, 8, 9), kind
`table`. Survey text was rebuilt from the existing store's chunk spans
(exact to 14 characters in 866k) because the PDF was no longer on disk;
the control reproduces the Milestone 15 numbers on the original 32
questions, which validates the rebuild.

Rerank mode (the default pipeline), by rows-per-chunk budget:

| set | variant | hit@1 | recall@3 | recall@5 | MRR | nDCG@5 | misses |
| --- | --- | --- | --- | --- | --- | --- | --- |
| large, 38 q | control | 0.818 | 0.864 | 0.909 | 0.881 | 0.861 | L25 L26 L33 L38 |
| large, 38 q | one row per chunk | 0.879 | 0.924 | 0.985 | 0.932 | 0.929 | L25 |
| large, 38 q | rows ≤ 80 tokens | 0.909 | 0.909 | 0.955 | 0.936 | 0.925 | L25 L38 |
| large, 38 q | **rows ≤ 120 tokens** | **0.909** | **0.939** | **0.985** | **0.947** | **0.944** | L25 |
| handbook, 60 q, mixed store | control | 0.920 | 0.940 | 0.970 | 0.955 | 0.942 | q36 q47 q48 |
| handbook, 60 q, mixed store | any of the three | 0.940 | 0.940 | 0.970 | 0.965 | 0.947 | q36 q47 q48 |

The mixed store is the two corpora together (the survey's 1,600 chunks act
as distractors for the handbook questions). The CI gate grades the
handbook alone, and that is where one row per chunk failed:

| handbook alone, 60 q | dense hit@1 | dense recall@5 | rrf hit@1 | rerank hit@1 | rerank MRR |
| --- | --- | --- | --- | --- | --- |
| baseline (no tables) | 0.86 | 0.99 | 0.94 | 0.94 | 0.955 |
| one row per chunk | 0.82 | 0.94 | 0.92 | 0.94 | 0.970 |
| rows ≤ 80 tokens | 0.86 | 0.97 | 0.94 | 0.94 | 0.970 |
| **rows ≤ 120 tokens** | 0.86 | 0.97 | 0.94 | 0.94 | 0.970 |

**Why one row per chunk lost on dense.** `config-reference.md` has four
pipe tables, sixteen rows. As sixteen 30-token chunks they are all
near-identical to any question about a setting, so dense's top-5 for
"which two settings interact badly" was five `config-reference` rows and
nothing else — the second relevant document was crowded out of k, and
recall is graded per document. The reranker re-scores past it (rerank
never moved), but the ablation modes are part of the gate and the drop
was real. Packing four or five rows under one header is the middle
ground: each row is still one of five in its chunk rather than one of
fifteen, and one table is one or two chunks rather than sixteen.

**Why 120 over 80.** One question, L38. The budget decides which rows
share a chunk, and with it which chunks of Table 8 make the fused
candidate list: at 80, three other Table 8 chunks reach RRF's top ten and
PaLM's does not, so the cross-encoder never sees it; at 120 PaLM's chunk
is a candidate and the cross-encoder ranks it in the top five. That is a
sample of one and the number is not the finding. The shape of the result
— fewer, richer row chunks beat many thin ones — is.

An earlier detector version with a stricter header rule (continuation
lines had to be ≥3 header-like cells) also missed L38 at every budget:
Table 8's wrapped header had been chopped into group labels, so the PaLM
row said "Adafactor" but never "optimizer" or "learning rate", and the
cross-encoder scored it 0.02. Fixing the header rule was worth +0.03 hit@1
on its own — the header *is* the row's meaning.

## Decision

**Shipped** (`DEFAULT_ROW_TOKENS = 120`), with one deviation from the
rule written beforehand. The rule was "L25 and L26 hit at k=5, ≥4/6 table
questions hit, handbook does not drop by more than 0.02". L26 hits, 6/6
table questions hit, the handbook set is flat on the shipped pipeline and
within the gate on every ablation, and the large set gained +0.091 hit@1
and +0.076 recall@5 — but L25 still misses. Its row's chunk now ranks
10th (cross-encoder 0.07; not in RRF's top ten at all) behind three
pages of RoPE prose that legitimately answer the question's second half
("how does that method encode relative position through rotation"). The
row is retrievable; the question needs two searches. That is a multi-hop
problem and Experiment 2's job, not a chunking one — and the rule as
written was not met. This note is where that gets admitted rather than
the rule quietly rewritten.

Cost of the change: ~5% more chunks on a table-heavy paper, and a
heuristic detector that will find false tables in text that imitates a
caption. The fallback in every case is the
old behaviour: a span with nothing row-shaped in it is chunked as prose.

## What would change the decision

- A corpus where the detector fires on prose (a book with "Table 3:" in
  running text, say) and prose metrics drop. `find_pdf_tables` requires
  two rows and a non-prose header; the next guard would be a column-count
  consistency check across rows.
- A corpus of many-row tables where 120 tokens is too coarse again — the
  sweep had three points; a table-heavy golden set would justify a finer
  one, or a per-document cap on chunks in the top-k, which would fix the
  crowding at search time instead of ingest time.
- A layout-aware extractor (pdfplumber, `pymupdf` with `find_tables`)
  replacing pypdf. That would make the caption heuristic unnecessary and
  fix the garbled multi-line headers; it costs a dependency and a slower
  ingest, and should be measured against this note's table before it is
  adopted.

## Reproduce

```bash
./.venv/bin/sextant-eval --check                                   # handbook, rebuilt
./.venv/bin/sextant-eval --store ./chroma_db --golden eval/golden-large.jsonl
```

The second needs the survey ingested with this version of the loader
(`sextant-ingest path/to/2303.18223.pdf --category llm-survey`).
