# IoU and Its Variants

Intersection over Union measures the overlap of two boxes as the area of their
intersection divided by the area of their union. It is bounded in [0, 1], is
scale-invariant, and is the default association metric in tracking.

## The vanishing gradient problem

IoU has one serious flaw: for boxes that do not overlap at all it is exactly
zero, and stays zero no matter how far apart they move. As an association cost
this means two non-overlapping candidates are indistinguishable, even when one
is plainly closer.

## GIoU

Generalised IoU adds a penalty based on the smallest enclosing box `C`:

    GIoU = IoU - |C \ (A ∪ B)| / |C|

GIoU is bounded in [-1, 1] and keeps decreasing as boxes separate, which
restores the ordering IoU loses. It equals IoU when one box contains the other.

## DIoU and CIoU

Distance-IoU adds a term for the normalised distance between box centres, which
converges faster than GIoU because it moves centres together directly rather
than shrinking the enclosing box. Complete-IoU adds a third term for aspect
ratio consistency.

## Thresholds in practice

For association, a cost of `1 - IoU` with a rejection threshold around 0.7 —
that is, a minimum IoU of about 0.3 — is a common starting point. For evaluation
against ground truth, an IoU of 0.5 is the conventional definition of a correct
detection.

These are different numbers doing different jobs and are frequently confused. A
0.5 association threshold is far too strict for fast-moving objects, where a
box can move most of its own width between frames.
