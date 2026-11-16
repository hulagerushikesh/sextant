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
