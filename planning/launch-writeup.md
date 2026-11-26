# DRAFT: launch write-up (milestone 31, item 1)

> Not published. Milestone 30 is done, so it is ready for the owner to edit and
> publish. Every figure is copied from [`docs/RESULTS.md`](../docs/RESULTS.md);
> `tests/test_launch_writeup.py` fails if any of them stops appearing there.
> The install lines below name release 0.12.9 (checked 2026-11-26); if a newer
> release is current on the day, change them.

---

## Nine ideas I measured and rejected while building a local document search, and what the public numbers said

sextant is a document search that runs on your own machine and plugs into
Claude Desktop, Claude Code, Cursor or VS Code as an MCP server. You point it
at a folder of PDFs, Markdown and text files, and your assistant gets back
passages with the page or section they came from. Searching runs on your
machine, over the folder you choose, and needs no key. Your assistant reads
only the passages that answer the question, and sextant hides card numbers,
passwords, keys and identity numbers in them first. It is free and
MIT-licensed.

This post is not about the features. It is about how each part of the search
got in, or didn't.

### The rule

Every idea got a pass rule written down **before** it ran: which test set,
which number, how much it had to move. Then one change, both test sets, and a
decision that is not argued again without a new fact.

The two home test sets are small and I wrote them myself: 65 questions over 21
documents, and 39 questions over one long research paper. That is their
weakness, and the reason for the public sets further down.

On the first set, the shipped search puts the right passage first **93%** of
the time; plain meaning search alone manages 87%.

### What was rejected

1. **A tree of summaries (RAPTOR).** The questions a tree would serve already
   scored 1.000 hit@5 without one. Nothing left to win.
2. **A newer embedding model (bge-small).** It gained 0.091 on one test set and
   lost 0.04 on the other; the rule asked for both. Re-tested on the public
   sets, the full search moved by at most 0.011.
3. **Smaller passages (150 tokens instead of 200).** Meaning search fell from
   0.820 to 0.720 on the handbook set. On a public set the full search fell
   0.005 where it had to gain 0.03.
4. **Dropping the reranker.** It looked like the expensive stage to cut. On the
   long-paper set it scores 0.000 on every off-topic question, and no other
   stage separates them, so it is what lets the search say "not in your
   documents".
5. **HyDE (let the model imagine an answer, then search for that).** Meaning
   search fell from 0.873 to 0.800, and after reranking the score was 0.909
   either way. The model also tended to imagine the wrong document.
6. **Prompt caching.** A 28% net saving, against the 30% the rule asked for.
   Close, and still a no.
7. **A fallback below the confidence floor, as a cost saving.** Across all 55
   answerable questions it fired once.
8. **The same fallback, as a way to find missed answers.** The question it was
   built for scored 0.5 with it and 0.5 without.
9. **Choosing a different index per question.** One index already reaches
   0.996 recall in 1.48 ms at 100k passages.

Most of these are ideas that papers and blog posts recommend. On this kind of
library they did not pay. That does not mean they never pay; it means each
needs a measurement on the library in front of you.

### What the public numbers said

Home-made test sets flatter whoever made them, so the four search stages were
scored on three public BEIR sets (NFCorpus, SciFact, FiQA), with the field's
standard measure (nDCG@10), beside the published figures. The losses first:

- **Meaning search loses to the published score of the same model** on
  NFCorpus: 0.312 against 0.316.
- **The keyword stage loses to the BEIR paper's plain BM25 on all three
  sets:** 0.299 against 0.325, 0.635 against 0.665, 0.216 against 0.236.
- **On FiQA, fusing keyword with meaning search makes things worse** than
  meaning search alone: 0.341 against 0.372.

And the result that matters to a user: **the full search, as shipped, beats the
paper's BM25 + reranker baseline on all three sets**: 0.364 against 0.350,
0.700 against 0.688, 0.375 against 0.347.

So the shipped pipeline holds up, and two of its stages are weaker than they
should be. The results page says so in its first screen, and it is generated
from the measurement files, so a re-run that changes a number changes the page.

Speed, on a MacBook Air with 8 GB: at 85,362 passages a full search takes about
582 ms (650 ms for the slowest 1 in 20), peaking at 1.0 GB of memory.

### A self-test for your own library

Public sets still aren't your library. So sextant has a self-test: your
assistant writes a question for each of a sample of your passages, and sextant
counts how often search brings back the passage the question came from. The
report ends with one suggestion backed by a number, for example "these files
are scanned and have no text".

Is that count honest? I checked it on the public sets, where the true answers
are known, with a rule written first: across 12 setups, it had to rank them the
way the true score does (rank correlation at least 0.6). One question writer
scored 0.65 and passed; the other scored 0.58 and failed. So it ships labelled
**a rough guide**: good for comparing your library with itself, not with
someone else's.

### What the first people to install it stopped at

Three people outside the project installed it before this post. What stopped
them was rarely the search: it was installing Python, a network that timed
out fetching it, two files with the same name, scanned PDFs with no text, and
one book too long for a single batch. Each became a fix. On a Mac with Apple
silicon, the Claude Desktop file now carries its own Python and the search
models, so installing it and its first start download nothing, and it keeps
the chosen folder in sync while the assistant is open.

### What this does not show

The home test sets were written alongside the code, and the public sets are
three particular collections. Neither says how the search will do on your
library, which is why the self-test exists, and why it is labelled rough.

### Try it, or check it

In Claude Desktop on a Mac with Apple silicon: download
`sextant-0.12.9-macos-arm64.mcpb` from the
[releases page](https://github.com/hulagerushikesh/sextant/releases),
double-click it, and pick the folder to search. Other computers take
`sextant-0.12.9.mcpb` from the same page, which installs Python and the
libraries on the first run.

Claude Code, VS Code and Cursor take one pasted line each, given in the
[README](https://github.com/hulagerushikesh/sextant#readme); it installs
`sextant-kb` from PyPI.

Reproduce one public set yourself, no key, nothing spent:

```bash
python -m sextant.eval.public_sets --set nfcorpus --check
```

It downloads NFCorpus, checks BEIR's published checksum, scores all four
stages, and fails if any lands more than 0.005 from the published table.

Results page: https://github.com/hulagerushikesh/sextant/blob/main/docs/RESULTS.md
