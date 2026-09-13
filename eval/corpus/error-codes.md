# Error Code Reference

Codes emitted by the tracking runtime. The prefix identifies the subsystem:
`TRK` for the tracker, `DET` for the detector, `CAL` for calibration.

## TRK-101 — Cost matrix contains NaN

At least one entry in the association cost matrix is not a number. Almost always
a degenerate bounding box with zero width or height, which makes the IoU
denominator zero. Filter boxes with an area below one pixel before building the
matrix.

## TRK-104 — Assignment solve exceeded time budget

The Hungarian solve took longer than the configured per-frame budget. Occurs
when the cost matrix grows beyond roughly a thousand rows. Apply distance gating
before solving, or cap the number of detections carried into association.

## TRK-118 — Track state covariance not positive definite

The Kalman covariance matrix `P` has lost positive definiteness, usually through
accumulated floating-point error over a long-lived track. Symmetrise `P` after
each update by replacing it with `(P + Pᵀ) / 2`, and consider a Joseph-form
covariance update.

## TRK-127 — Maximum active track count reached

The tracker is holding the configured maximum number of simultaneous tracks and
is refusing to create more. Usually a symptom of `max_age` being too long
combined with a noisy detector producing spurious tracks.

## DET-203 — Input frame dimensions changed mid-stream

The detector received a frame whose dimensions differ from the previous one.
Resolution changes invalidate every track's state, since positions are in pixel
coordinates. Restart the tracker on resolution change.

## DET-207 — Confidence threshold above all detections

Every detection in the frame scored below the configured threshold, so nothing
was passed to association. Expected on empty frames; suspicious if sustained.

## CAL-301 — Reprojection error exceeds tolerance

Calibration finished but the mean reprojection error is above the configured
tolerance, by default one pixel. Recapture with more views at more varied
angles.

## CAL-305 — Homography is singular

The ground-plane homography could not be inverted. The four calibration points
are collinear or nearly so. Choose points spread across the ground plane.
