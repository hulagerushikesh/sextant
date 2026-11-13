# Next

The queue only. Direction, the milestones and the scoreboard live in
[`PLAN.md`](PLAN.md); where the two disagree, the plan wins. Finished rows for
milestones 17–22 are in
[`archive/queue-through-milestone-22.md`](archive/queue-through-milestone-22.md),
unedited.

## Now

Read [`PLAN.md`](PLAN.md) section 8 for the one item in progress. The order
after it is section 5, top to bottom — nothing is started out of order.

## Parked

One list, kept in [`PLAN.md`](PLAN.md) section 6, each line with the event
that would un-park it. A new idea is added there as one line and not started.

## Decided against

Each was measured or costed, so it is not argued again without a new fact.
The full reasoning is in the linked note or in the archived queue.

- **RAPTOR tree** — one level already saturates hit@5; the question a tree
  serves is a listing. [note](../learning/summary-chunks.md)
- **bge-small instead of MiniLM** — +0.09 dense on one set, −0.04 on the
  other, final ranking unmoved; kept as a knob. [note](../learning/embedder-swap.md)
- **150-token chunks** — helps the reranker, hurts dense; 200 has no known
  miss that 150 fixes. [note](../learning/chunk-size.md)
- **Dropping the reranker** — the only stage with a calibrated "I do not
  know" score. [note](../learning/reranker-decision.md)
- **A recorded always-on demo** — the owner chose screenshots only
  (2026-11-13): the product is the local install. [plan](PLAN.md)
- **Always-on hosting / scale-out** — the store is single-writer and the run
  policy is on demand. [milestone 15](milestone-15.md)
- **HyDE / query expansion** — dense worse on both sets, invisible after the
  reranker, and it invents confidence on unanswerable questions. [note](../learning/hyde.md)
- **Prompt caching** — 28% net saving at five questions an hour, under the
  30% rule. [note](../learning/prompt-caching.md)
- **Floor fallback as a cost feature** — safe, but fired on 1 question of 55.
  [note](../learning/floor-fallback-cost.md)
- **Floor fallback as a recall fix** — does not recover the one question it
  was built for. [note](../learning/floor-fallback.md)
- **Routing each question between two indexes** — the question text carries
  no signal for it. [note](../learning/ivfpq-100k.md)
- **A stricter type-check mode in the gate** — it would flag ignores that are
  legitimately needed; the gate's arguments are pinned instead.
- **Keeping a reserved address while parked** — ₹21 a day for nothing.
- **A trip probe whose filename needs escaping** — the server sanitises an
  upload's name first, so there is nothing for a trip to prove.
