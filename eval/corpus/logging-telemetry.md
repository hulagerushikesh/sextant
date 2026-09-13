# Logging and Telemetry

An analytics pipeline that cannot explain itself cannot be operated.

## Structured logs

Free-text logs are unqueryable at volume. Structured records with stable field
names — frame index, stage, duration, queue depth — can be aggregated, and the
aggregate is where problems actually appear.

## Sampling

Per-frame logging at thirty frames a second overwhelms any sink. Log every
frame at debug level, aggregate to one record per second at info level, and let
the level decide which is emitted.

## Latency measurement

Measure per-stage latency at the stage boundary, not around the whole pipeline.
A single end-to-end number tells you something is slow and nothing about what.
Percentiles matter more than means: a p99 of two seconds behind a mean of
twenty milliseconds is a real user-visible stall.

## Counters worth keeping

Frames decoded, frames dropped, detections per frame, active tracks, and
association failures. Together these separate a detector problem from a
tracker problem without attaching a debugger.
