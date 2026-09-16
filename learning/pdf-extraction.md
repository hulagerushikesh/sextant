# PDF extraction: pypdf → PyMuPDF

*2026-09-16, between experiments 4 and 3 of Milestone 16. Cost: ₹0, one
24 MB wheel. Decision: PyMuPDF is the extractor; pypdf stays as fallback.*

## What went wrong

Re-downloading the survey the large golden set is built on
(arXiv 2303.18223) fetched **v19**, a newer build than the file the set
was labelled against. Through pypdf it came out with words fused —
`isgreedy searchthat`, `whent`, `TransformerO(H(T+H))O(TH(T+H))` — about
3% of the text. pypdf does not read spaces from the file; it infers them
from the gap between glyphs, and this LaTeX build's font metrics put the
gaps under its threshold. Layout mode (`extraction_mode="layout"`) was
worse: it interleaved the two columns line by line.

That is not a survey-specific problem. Any PDF a user uploads can have
those metrics, and fused words are invisible to BM25 and half-visible to
the embedder.

## Bake-off

The reference dictionary is the clean text from the earlier build (the
one already in the store, reconstructed exactly from its chunk spans).
"OOV" is the share of 5+-letter words not in that dictionary — merges
show up as new, non-words. Probes: a prose sentence spanning a column
break, a Table 5 row, a Table 6 math row, and a sentence with a citation.

| extractor | secs / 144 pp | words | OOV | column order | table row | math row |
| --- | --- | --- | --- | --- | --- | --- |
| pypdf 6.16 | 4.7 | 128,874 | 0.008 | fused words | ✓ | fused |
| pdfplumber 0.11, split at the column midline | 19.5 | 94,292 | 0.146 | lost text | ✗ | ✓ |
| **PyMuPDF 1.28**, text mode | 0.9 | 131,877 | 0.000 | ✓ | one cell per line | ✓ |
| **PyMuPDF + baseline rebuild** (shipped) | 2.6 | 131,597 | 0.001 | ✓ | ✓ | ✓ |
| reference (clean build, pypdf) | — | 132,954 | 0.000 | ✓ | ✓ | ✓ |

pdfplumber without the split interleaves columns like pypdf's layout
mode; with it, the crop loses anything straddling the midline. It was
not worth tuning further against a 20× slower extract.

PyMuPDF reads the layout and gets every word, but its plain text mode
emits a table one cell per line, which `tables.py` cannot see as rows.
The loader now asks for the `dict` structure and rebuilds lines itself:
within each text block, spans sharing a baseline become one line in x
order, joined without a space where they touch (a math run like
`O(H(N2 + H))` arrives as several spans). Sub- and superscripts — spans
under 0.8× the block's body size — are placed on the nearest line by
baseline and horizontal proximity, because a superscript's own baseline
sits above its line and a naive y-sort hands it to the line before
(`hyper-parameters−8` instead of `10−8`). Block-relative size, not
page-relative: a table set in `\small` is not a page of subscripts, and
the first attempt at page-relative sizing dropped two tables.

`find_tables()` finds nothing in this paper (no ruling lines), so the
caption heuristic in `tables.py` stays. Unchanged.

## Effect on the golden set

v19 moved one page break around p. 38: L07 and L27 relabelled. Everything
else was checked phrase by phrase and holds. Ingested through the new
loader, the large set scores (rerank) 0.909 / 0.955 / 0.985 / MRR 0.946 —
the same hit@1 and recall@5 as experiment 1's reconstructed run, with
recall@3 and nDCG@5 slightly up. Fusion gained the most: RRF hit@1
0.788 → 0.879, which is BM25 seeing whole words again.

`chroma_db` now holds v19 (1,608 survey chunks) and `baseline-large.json`
is regenerated from it. The pinned file:
`https://arxiv.org/pdf/2303.18223v19`, md5 `b0facc450634ab588d0cd82c8be15ace`.

## Cost and licence

PyMuPDF is a 24 MB wheel (the image grows by about that) and is
**AGPL-3.0** (or a commercial licence from Artifex). This repository is
private today; if it goes public it can stay AGPL-compatible, but a
closed fork could not ship it. pypdf (BSD) remains the fallback path, so
removing PyMuPDF is a one-line change with the extraction quality above
as the price.

## What would change the decision

- A PDF where MuPDF's block order is wrong (multi-column with floats
  that span columns). `pymupdf_layout` is the vendor's answer; it is a
  separate package and was not needed here.
- Ruled tables in user documents: `find_tables()` would then beat the
  caption heuristic and should be measured against it.
