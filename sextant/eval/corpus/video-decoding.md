# Video Decoding

Frames reach the pipeline through a decoder, and decoder behaviour shapes what
the tracker sees before any model runs.

## Keyframes and seeking

Compressed video stores full keyframes periodically and encodes intermediate
frames as differences. Seeking to an arbitrary timestamp requires decoding from
the preceding keyframe forward, so seek cost depends on keyframe interval, not
on distance. A two-second interval at 30 fps means up to sixty frames of
decoding for a random seek.

## Hardware decode

Dedicated decode hardware frees the CPU and keeps frames in device memory,
avoiding a copy before inference. It supports fewer codecs and profiles than a
software decoder, and falls back silently on unsupported streams, which is a
common cause of unexplained throughput collapse.

## Colour and pixel format

Decoders emit planar YUV; most models expect packed RGB. The conversion is
cheap but easy to get wrong, and a channel-order mistake produces a model that
runs happily and detects almost nothing.

## Frame pacing

Wall-clock pacing and frame-index pacing diverge whenever decoding cannot keep
up. A pipeline that assumes a fixed timestep will silently mis-time motion
prediction if the decoder drops frames.
