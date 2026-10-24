# ByteTrack and Two-Stage Association

ByteTrack's observation is that discarding low-confidence detections throws away
most of what is known about occluded objects. A partially hidden person still
produces a detection, just a weak one, and the usual pipeline deletes it before
association ever sees it.

## The BYTE association method

BYTE keeps every detection and associates in two passes.

The first pass takes only high-scoring detections — above roughly 0.6 — and
matches them against all active tracks using IoU, solved with the Hungarian
algorithm. This is the ordinary association step.

The second pass takes the low-scoring detections, those between about 0.1 and
0.6, and matches them against only the tracks left unmatched by the first pass.
The reasoning is that a track which failed to find a confident detection is
exactly the track most likely to be occluded, and a weak detection in the right
place is better evidence than nothing.

Unmatched low-score detections are discarded rather than initialising new
tracks. A new track should never begin from a weak detection; that is how false
positives enter and persist.

## Why it works

Most identity switches happen during occlusion, when a track loses its detection
and is either deleted or coasts on prediction alone until it drifts far enough
to be re-associated with the wrong object. Keeping the weak detection keeps the
track anchored to real evidence.

## Cost

The second pass adds one more Hungarian solve per frame over a smaller matrix,
which is negligible against the cost of detection itself. ByteTrack needs no
appearance model, which is why it is fast and why it degrades where objects look
alike and move unpredictably.
