# Appearance and Re-Identification

Motion alone cannot recover an identity after a long gap. Appearance
embeddings can.

## The embedding

A re-identification network maps a cropped detection to a fixed-length vector —
128 or 256 dimensions is typical — trained so that crops of the same identity
are close under cosine distance and crops of different identities are far apart.

## The gallery

Each track keeps a gallery of embeddings from the frames where it was matched.
Association cost is the cosine distance to the nearest gallery entry, or to a
running average.

Keeping a short history rather than a single vector matters: a person turning
around looks very different from the front and the back, and a single averaged
vector represents neither well.

## Exponential moving average

Many trackers keep one vector updated as an exponential moving average:

    e = α·e + (1 - α)·e_new

with α around 0.9. This is cheap and stable, and it loses multi-view
information. Whether that matters depends on how much objects rotate.

## Combining with motion

Appearance and motion costs are usually combined linearly, weighted around 0.3
appearance to 0.7 IoU, with motion gating applied first so appearance is only
consulted for geometrically plausible pairs.

Appearance-only association fails badly on uniformed crowds, where the network
genuinely cannot distinguish two people. Motion-only fails on crossing paths.
Neither is sufficient alone.
