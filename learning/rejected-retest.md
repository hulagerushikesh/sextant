# The two closest rejected ideas, re-tested on the public sets

*Milestone 28, item 3, started 2026-11-16. Cost: ₹0, no download (both
models were already in the local cache from milestone 16).*

## Which two, and why these

Of the nine rejected ideas, two came within one question of passing on our
own test sets, and both can be measured on the public sets for free:

- **Smaller passages (150 tokens instead of 200)** — [`chunk-size.md`](chunk-size.md).
  It *met* its own rule (the full pipeline up ≥ 0.03 hit@1 on both sets, the
  survey by exactly one question) and was rejected only by the stricter gate:
  meaning search alone fell past the 0.02 tolerance. That note named the cause
  (several passages from one document crowding the top five) and the fix
  (a per-document cap), and the cap has shipped since (at most 2 passages per
  document). That is the new fact that justifies asking again.
- **A newer embedding model (bge-small-en-v1.5)** — [`embedder-swap.md`](embedder-swap.md).
  It gained 0.091 first-result hit rate on one set and lost 0.04 on the
  other; the rule asked for both.

The other seven are further away or not measurable here: HyDE and the two
fallbacks need paid model calls and were tied or rarely fired; prompt
caching is a cost question the public sets cannot see; the summary tree had
nothing to gain; dropping the reranker is already answered by item 1 (the
full pipeline beats fusion alone on all three sets); and choosing an index
per question is a speed question item 2 closed.

## Rules, written before any public-set run

Same kind of rule as each original, translated to the public sets'
standard measure (nDCG@10, graded) and the same 0.03 / 0.02 margins.
"All three sets" means NFCorpus, SciFact and FiQA, so one failing set is
enough to keep an idea rejected, and the sets are run smallest first.

**150-token passages are adopted only if** the full pipeline's nDCG@10 rises
by **≥ 0.03 on all three sets**, **and** no stage (meaning, keyword, fused,
full) falls by more than **0.02** on any set.

**bge-small is adopted only if** meaning search's nDCG@10 rises by
**≥ 0.03 on all three sets**, **and** the full pipeline does not fall by
more than **0.02** on any set.

The control for both is the committed run in
[`public-sets.json`](../sextant/eval/public-sets.json): all-MiniLM-L6-v2,
200-token passages, same settings otherwise. Each candidate changes one
thing.

## Results

Both stay rejected. Raw runs: [`retest.json`](../sextant/eval/retest.json);
the rules above are code in `sextant/eval/retest.py`, and a test fails if
this note's verdicts stop matching what that code computes from the runs.

**150-token passages** — stopped after the first set, which settles it:

| NFCorpus, nDCG@10 | 200 (control) | 150 | change |
| --- | --- | --- | --- |
| meaning | 0.3116 | 0.3225 | +0.011 |
| keyword | 0.2993 | 0.2952 | −0.004 |
| fused | 0.3377 | 0.3372 | −0.001 |
| full pipeline | 0.3635 | 0.3588 | **−0.005** |

The full pipeline had to gain 0.03 and lost 0.005 instead. The per-document
cap did what the old note predicted for meaning search (it no longer falls;
it rises 0.011), but the reranked gain that made the idea interesting on our
own sets does not appear on a public one. It costs 37% more passages
(13,167 against 9,578) for nothing.

**bge-small** — all three sets, because the first two passed:

| nDCG@10 | meaning: MiniLM → bge | change | full pipeline: MiniLM → bge | change |
| --- | --- | --- | --- | --- |
| NFCorpus | 0.3116 → 0.3477 | +0.036 | 0.3635 → 0.3743 | +0.011 |
| SciFact | 0.6713 → 0.7203 | +0.049 | 0.7004 → 0.6990 | −0.001 |
| FiQA | 0.3722 → 0.3865 | **+0.014** | 0.3752 → 0.3747 | −0.0005 |

Meaning search gains on every set but FiQA misses the 0.03 bar, so the rule
says rejected. The more useful finding is the right-hand column: **after the
reranker, the better embedder changes the answer by at most 0.011**, the
same pattern as on our own sets in milestone 16. The reranker decides the
final order; a stronger first stage mostly changes which passages it is
handed, not which one wins. Swapping would also force every existing
library to be re-indexed.

## What would change these decisions

- **A product mode without the reranker** (a speed tier, say). Then the
  first stage is the answer, and bge's +0.014 to +0.049 is worth having.
- For passage size: a test set whose questions are about one sentence each,
  where the old reranked gain came from. None of the three public sets is.

## Cost

₹0. No download: bge-small was already cached from milestone 16 and ran
offline. About 49 minutes of laptop load across four runs (the longest 30), each under a
watchdog (memory, swap, battery, 30 minutes); peak memory 0.9 GB. The FiQA
run hit the 30-minute stop while deleting its throwaway index, a few
seconds after its results were written; nothing was lost.
