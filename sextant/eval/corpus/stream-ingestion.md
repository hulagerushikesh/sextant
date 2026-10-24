# Stream Ingestion

Live sources fail in ways files do not.

## Reconnection

Network streams drop. The client must reconnect with exponential backoff and
must treat the reconnected stream as discontinuous: timestamps restart,
resolution may change, and any state keyed to frame index is invalid.

## Timestamps

Wall-clock arrival time and stream presentation time diverge under jitter.
Motion prediction should use presentation timestamps; anything user-facing
should use wall clock. Mixing them produces motion estimates that drift with
network conditions.

## Buffering

A small jitter buffer smooths network variance at the cost of latency. Too large
and the pipeline is analysing the past; too small and frames arrive out of order
or not at all.

## Multiple sources

Independent streams have independent clocks. Anything that compares across
sources needs an explicit synchronisation strategy, and drift between cheap
cameras is measured in seconds per hour, not milliseconds.
