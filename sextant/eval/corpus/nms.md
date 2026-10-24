# Non-Maximum Suppression

Detectors emit many overlapping boxes for one object. Non-maximum suppression
reduces them to one.

## The greedy algorithm

Sort all boxes by confidence. Take the highest, add it to the output, and
discard every remaining box whose IoU with it exceeds a threshold — typically
0.45 to 0.5. Repeat with the highest-scoring survivor until none remain.

## The crowd failure

Greedy NMS cannot distinguish two overlapping boxes on one object from two
overlapping boxes on two genuinely overlapping objects. In crowds it deletes
real detections, and those deletions become false negatives no tracker can
recover from.

## Soft-NMS

Instead of deleting overlapping boxes, decay their confidence in proportion to
the overlap, usually with a Gaussian penalty. Boxes that heavily overlap the
winner drop far down the ranking but survive to be reconsidered. This recovers
a meaningful fraction of detections in crowded scenes at essentially no cost.

## Class-aware suppression

Suppression should normally run per class, so a box labelled "person" never
suppresses one labelled "bicycle" at the same location. Class-agnostic NMS is
occasionally wanted when classes are known to be mutually exclusive.

## Interaction with tracking

Aggressive NMS starves the tracker of exactly the weak, overlapping detections
that two-stage association is designed to exploit. Pipelines using BYTE-style
association usually loosen the NMS threshold deliberately.
