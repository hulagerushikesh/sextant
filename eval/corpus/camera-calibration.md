# Camera Calibration

Calibration relates pixels to the world. Tracking in image space can be done
without it; tracking in metric space cannot.

## Intrinsics

The intrinsic matrix `K` holds focal lengths `fx` and `fy` in pixels and the
principal point `cx`, `cy`. It maps camera-frame 3-D points to the image plane.
Intrinsics are a property of the lens and sensor and do not change unless the
lens zooms.

## Distortion

Real lenses bend straight lines. Radial distortion is modelled by coefficients
`k1`, `k2`, `k3` and tangential distortion by `p1`, `p2`. Wide-angle and
fisheye lenses need the higher-order terms; a narrow-field lens can often be
treated as distortion-free.

Uncorrected distortion is worst at the frame edges, which is precisely where
objects enter and leave. Tracks appear to accelerate as they approach the border
even at constant real-world speed.

## Extrinsics and the ground plane

Extrinsics give the rotation and translation from world to camera. With the
assumption that objects stand on a flat ground plane, a homography maps image
points to ground coordinates, which is what makes real speeds and real distances
recoverable from a single camera.

## Checkerboard calibration

The standard procedure captures twenty or more views of a checkerboard at
varied angles, detects corners to sub-pixel precision, and solves for intrinsics
and distortion together. A mean reprojection error below 0.5 pixels indicates a
good calibration; above one pixel, something is wrong — usually too few views or
all views at similar angles.
