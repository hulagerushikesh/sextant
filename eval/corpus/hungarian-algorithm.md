# The Hungarian Algorithm

The Hungarian algorithm, also called the Kuhn-Munkres algorithm, solves the
linear assignment problem exactly: given an `n × m` cost matrix, find the
one-to-one assignment of rows to columns that minimises total cost. It runs in
O(n³) time, which is what makes it practical inside a per-frame tracking loop.

## The assignment problem

In tracking, rows are existing tracks and columns are detections in the current
frame. Each cell holds the cost of associating that track with that detection.
The algorithm returns the pairing with the lowest total cost — crucially, a
global optimum, not the greedy nearest-neighbour choice made track by track.

Greedy matching fails in a specific and common way: an early track claims a
detection that a later track needed more, and the total cost is worse than it
had to be. Two objects crossing paths is the canonical case.

## Building the cost matrix

Cost is usually one minus IoU, sometimes blended with a motion term from the
Mahalanobis distance and an appearance term from re-identification embeddings.
A typical blend weights IoU at 0.7 and appearance at 0.3.

## Gating

Pairs that are implausible should never be assignable. The standard approach is
to set their cost to a large sentinel value before solving, so the optimiser
will only choose them if there is no alternative. A gate on the Mahalanobis
distance at the 95th percentile of the chi-square distribution — 9.4877 for four
degrees of freedom — is common.

Gating matters more than it looks. Without it, the algorithm will happily assign
a track to a detection on the other side of the frame simply because that was
the cheapest remaining option.

## Rectangular matrices

Track and detection counts rarely match. The algorithm handles rectangular
matrices by padding to a square with dummy rows or columns at high cost;
anything assigned to a dummy is treated as unmatched.

## After the solve

Assignments above the cost threshold are discarded even though the optimiser
chose them: a bad match is worse than no match, because it corrupts the track's
state estimate. Discarded pairs go back into the pool as an unmatched track and
an unmatched detection.
