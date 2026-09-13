# Detector Architectures

The detector sets the ceiling on tracking quality; no association strategy
recovers an object that was never detected.

## Two-stage

Region proposal followed by classification and box refinement. Historically the
most accurate family and the slowest, because the second stage runs per
proposal.

## One-stage

Dense prediction over a grid of locations in a single pass. Much faster, and the
accuracy gap has largely closed. The dominant choice for real-time pipelines.

## Anchor-free

Predicts box centres and extents directly rather than offsets from predefined
anchor boxes. Removes anchor tuning, which was scene-specific and easy to get
wrong, and behaves better on objects with unusual aspect ratios.

## Transformer detectors

Treat detection as set prediction with bipartite matching during training,
removing the need for suppression at inference. Slower to converge in training
and increasingly competitive at inference.

## Choosing

For tracking, recall matters more than precision: a spurious detection can be
rejected by association, while a missed one cannot be invented. Detector
thresholds for tracking are usually set lower than for standalone detection.
