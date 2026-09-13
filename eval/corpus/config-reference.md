# Configuration Reference

Every parameter the tracker reads, with its default.

## Association

| Parameter | Default | Meaning |
| --- | --- | --- |
| `iou_threshold` | 0.3 | Minimum IoU for a track-detection pair to be assignable |
| `high_score_threshold` | 0.6 | Detections at or above this enter the first association pass |
| `low_score_threshold` | 0.1 | Detections below this are discarded entirely |
| `appearance_weight` | 0.3 | Weight of appearance cost against IoU cost |
| `mahalanobis_gate` | 9.4877 | Chi-square gate at 95% for four degrees of freedom |

## Lifecycle

| Parameter | Default | Meaning |
| --- | --- | --- |
| `min_hits` | 3 | Consecutive matches before a track is confirmed |
| `max_age` | 30 | Frames a track may go unmatched before deletion |
| `max_active_tracks` | 1000 | Hard cap on simultaneous tracks |

## Kalman filter

| Parameter | Default | Meaning |
| --- | --- | --- |
| `process_noise_scale` | 0.05 | Multiplier on `Q`, scaled by object height |
| `measurement_noise_scale` | 0.1 | Multiplier on `R`, scaled by object height |
| `initial_velocity_variance` | 1000.0 | Diagonal of `P` for unobserved velocity terms |

## Detection

| Parameter | Default | Meaning |
| --- | --- | --- |
| `nms_iou_threshold` | 0.45 | IoU above which the lower-scoring box is suppressed |
| `class_agnostic_nms` | false | Suppress across classes rather than within each |
| `max_detections_per_frame` | 300 | Detections retained after suppression |

## Notes on tuning

`process_noise_scale` and `max_age` interact. Raising process noise makes the
filter follow manoeuvres more readily but widens the gate, so a long `max_age`
with high process noise will re-associate a coasting track to almost anything.
Change one at a time.
