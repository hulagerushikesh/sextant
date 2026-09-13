# Data Annotation

Labels define what the system is being asked to do, and ambiguity in labelling
shows up later as unexplained metric variance.

## Box conventions

Whether a box covers the visible extent or the estimated full extent of a
partly occluded object changes both training and evaluation. The choice must be
written down; annotators will not converge on it by themselves.

## Identity continuity

For tracking, the hard part is not the boxes but the identities. An object that
leaves the frame and returns may or may not keep its original identity, and the
convention determines whether a re-identification system is being rewarded or
punished.

## Inter-annotator agreement

Measure it before trusting any label set. Agreement below about 0.8 on box IoU
means the guidelines are ambiguous, and no amount of model work will make the
metric stable.

## Edge cases to specify

Reflections, images of people on posters, partially visible limbs at the frame
edge, and groups too dense to separate. Each needs an explicit rule.
