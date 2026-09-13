# Benchmark Datasets

Public datasets differ enough that a result on one says little about another.

## MOT17

Pedestrian sequences from static and moving cameras, with three sets of public
detections supplied so that trackers can be compared independently of their
detector. Crowd density is moderate and motion is mostly linear.

## MOT20

Far denser crowds, largely static cameras, heavy mutual occlusion. Appearance
models struggle because pedestrians are small and similar; association leans on
motion.

## DanceTrack

Dancers in uniform costumes with highly nonlinear motion. Built specifically to
break appearance-based association: every target looks alike, so the dataset
isolates how well motion modelling and association work on their own.

## KITTI

Automotive sequences from a moving platform with calibrated stereo and LiDAR.
Ego-motion dominates, so camera motion compensation matters more here than on
pedestrian benchmarks.

## Reading results

A tracker tuned on MOT17 frequently degrades on DanceTrack, and the gap is
informative rather than embarrassing: it separates systems relying on appearance
from systems relying on motion.
