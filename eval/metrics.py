"""
Retrieval metrics.

Pure functions over a ranked list of retrieved document ids and the set of ids
that are actually relevant. No model, no I/O, no state -- which is what makes
them testable, and they are tested, because an evaluation harness you cannot
check is just a more elaborate way of guessing.

All three answer different questions:

  recall@k  did the relevant material make it into the top k at all?
  MRR       how far down was the first useful result?
  nDCG@k    how well ordered is the whole top k?

A system can score well on recall and badly on nDCG by burying the right answer
at rank 10, and that difference is exactly what reranking is supposed to fix.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def hit_at_1(retrieved: Sequence[str], relevant: set[str]) -> float:
    """Is the single best-ranked chunk from a relevant document?

    The strictest metric here, and the one that still separates configurations
    once recall@5 has saturated on a small corpus. It is also the closest to
    what the agent experiences: it reads the passages in the order given.
    """
    if not relevant:
        return 1.0
    return float(bool(retrieved) and retrieved[0] in relevant)


def recall_at_k(retrieved: Sequence[str], relevant: set[str], k: int) -> float:
    """Fraction of the relevant documents that appear in the top k.

    Returns 1.0 when nothing is relevant: a query with no correct answer cannot
    fail to find one, and averaging 0.0 into the mean would punish the system
    for the golden set's shape rather than its own behaviour. Unanswerable
    queries are graded separately, by `abstention`.
    """
    if not relevant:
        return 1.0
    found = {doc for doc in retrieved[:k] if doc in relevant}
    return len(found) / len(relevant)


def reciprocal_rank(retrieved: Sequence[str], relevant: set[str]) -> float:
    """1/rank of the first relevant document, or 0.0 if none was retrieved."""
    if not relevant:
        return 1.0
    for rank, doc in enumerate(retrieved, start=1):
        if doc in relevant:
            return 1 / rank
    return 0.0


def ndcg_at_k(retrieved: Sequence[str], relevant: set[str], k: int) -> float:
    """Normalised discounted cumulative gain over binary relevance.

    Gains are binary because the golden set labels documents relevant or not,
    with no grades between. A document is counted once even if several of its
    chunks are retrieved -- otherwise a system that returns five chunks of the
    right document would score above one that returns the right document plus
    genuine supporting material, which is backwards.
    """
    if not relevant:
        return 1.0

    seen: set[str] = set()
    dcg = 0.0
    for rank, doc in enumerate(retrieved[:k], start=1):
        if doc in relevant and doc not in seen:
            seen.add(doc)
            dcg += 1 / math.log2(rank + 1)

    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0


def abstention(top_score: float | None, threshold: float) -> bool:
    """Would the system decline to answer, given its best score?

    The only metric here that is about *not* retrieving. Graded on the
    unanswerable split, where the correct behaviour is to return nothing worth
    citing rather than the least-bad chunk in the corpus.
    """
    return top_score is None or top_score < threshold


def summarise(rows: list[dict[str, float]]) -> dict[str, float]:
    """Mean of each metric across queries, rounded for reporting."""
    if not rows:
        return {}
    keys = rows[0].keys()
    return {key: round(sum(row[key] for row in rows) / len(rows), 4) for key in keys}
