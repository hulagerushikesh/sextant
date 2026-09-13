# Multi-Object Tracking Metrics

Tracking has no single score. Different metrics reward different behaviour, and
a system tuned for one will usually look worse on another.

## MOTA

Multi-Object Tracking Accuracy combines three error counts against the number of
ground-truth objects:

    MOTA = 1 - (FN + FP + IDSW) / GT

It is dominated by detection quality, because false negatives and false
positives almost always outnumber identity switches. MOTA can be negative. Its
main weakness is that it barely penalises identity switches, so a tracker that
constantly swaps identities can still score well.

## MOTP

Multi-Object Tracking Precision averages the localisation error over matched
pairs. It measures box quality, not association quality, and is largely a
property of the detector.

## IDF1

The F1 score over identity-preserving matches: a global bipartite matching
between ground-truth trajectories and predicted ones, scored on how much of each
trajectory carries the correct identity. IDF1 rewards long, consistent tracks
and punishes fragmentation, which is exactly what MOTA underweights.

## HOTA

Higher Order Tracking Accuracy decomposes into detection accuracy and
association accuracy and averages them geometrically over a range of IoU
thresholds. It was designed because MOTA and IDF1 disagree so often that papers
could pick whichever favoured them. HOTA is now the primary metric on most
benchmarks.

## Identity switches

An ID switch is counted when a ground-truth object matched to track A in one
frame is matched to track B later. Fragmentation counts interruptions in
coverage without an identity change. Both are association failures, and both are
usually caused by occlusion or by a `max_age` that is too short.
