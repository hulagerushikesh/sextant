# Public test sets (milestone 28, item 1)

The committed golden set was written alongside its corpus, so it cannot say
how sextant compares with anything. These are three of the BEIR sets: fixed
documents, fixed questions, relevance judged by people who never saw this
code. Figures are nDCG@10 on the `test` split, graded, linear gain — BEIR's
own measure. Raw output: `sextant/eval/public-sets.json`.

Downloaded 2026-11-15 with the owner's yes: 23 MB from the BEIR host,
checksums equal to the ones BEIR publishes.

## Results so far (2 of 3 sets)

| set | questions | dense | lexical | fused | full pipeline |
| --- | --- | --- | --- | --- | --- |
| NFCorpus (3,633 docs) | 323 | 0.312 | 0.299 | 0.338 | **0.364** |
| SciFact (5,183 docs) | 300 | 0.671 | 0.635 | 0.688 | **0.700** |
| FiQA (57,638 docs) | 648 | not run | | | |

Published, same measure and split:

| set | BM25 (paper) | MiniLM dense (MTEB) | BM25 + MiniLM cross-encoder (paper) |
| --- | --- | --- | --- |
| NFCorpus | 0.325 | 0.316 | 0.350 |
| SciFact | 0.665 | 0.645 | 0.688 |
| FiQA | 0.236 | 0.369 | 0.347 |

## What it says

- **The full pipeline beats the paper's BM25 + cross-encoder on both sets**
  (+0.014, +0.012), with a 25-candidate rerank against the paper's 100.
- **sextant's own BM25 loses to the published BM25 on both sets** (−0.026,
  −0.030). It is the weakest stage. The paper's BM25 is Elasticsearch with
  its own analyser and stemming; sextant's is hand-written. The page must say
  so on its first screen (the milestone's rule).
- Dense matches its published figure (−0.004 on NFCorpus, +0.026 on SciFact;
  sextant indexes chunks, MTEB whole documents truncated at 256 tokens).
- Fusion beats either half alone on both sets.

## Not like-for-like

- Recall is reported at 10, not BEIR's customary 100: each stage proposes at
  most 30 chunks, so recall@100 cannot be measured on this pipeline as built.
- Documents are chunked (≈2.5 chunks per SciFact abstract), and chunks
  collapse to their document for grading, first seen first.
- Product defaults throughout: 2 chunks per document, rerank depth 25.

## Cost of a run on this Mac (M2, 8 GB)

| set | chunks | indexing | whole run | peak memory | full-pipeline search |
| --- | --- | --- | --- | --- | --- |
| SciFact | 12,988 | 507 s | 812 s | 0.7 GB | 941 ms |
| NFCorpus | 9,578 | 239 s | 452 s | 0.9 GB | 636 ms |

Embedding is the whole of indexing (cProfile: 41 of 47 s). Batching texts
shortest first now cuts it by about a quarter (16.1 s against 21.9 s for 800
FiQA documents); the vectors are unchanged and a test holds the order.
SciFact ran before that change, NFCorpus after.
