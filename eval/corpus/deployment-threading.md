# Pipeline Threading and Deployment

Throughput is usually lost to scheduling, not to arithmetic.

## Stage separation

Decode, inference and tracking have different resource profiles and belong on
separate threads connected by bounded queues. Bounded is the operative word: an
unbounded queue in front of a slow stage converts a throughput problem into a
memory problem, and the process dies rather than degrading.

## Backpressure

When a downstream stage falls behind, the pipeline must choose between blocking
the source and dropping frames. Live streams want dropping; recorded files want
blocking. This should be configuration, not a hard-coded assumption.

## Batching

Batching detections across frames raises GPU utilisation and raises latency by
the batch fill time. For live analytics the latency budget usually caps the
batch at two or four frames.

## Warm-up

The first inference on a fresh process is far slower than steady state, because
kernels are compiled and memory pools allocated on demand. Any measurement taken
before warm-up is meaningless, and any health check that runs before it will
report a false failure.
