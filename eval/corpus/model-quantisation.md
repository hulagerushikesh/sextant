# Model Quantisation

Reducing numeric precision cuts memory and raises throughput, at some cost in
accuracy.

## Half precision

Sixteen-bit floating point roughly halves memory and is close to lossless for
most vision models. It is the default on hardware with dedicated support and
usually needs no calibration.

## Eight-bit integer

Requires a calibration pass over representative data to choose per-tensor or
per-channel scales. Post-training quantisation is quick and sometimes loses
noticeable accuracy; quantisation-aware training recovers most of it at the cost
of a retraining cycle.

## What degrades

Small objects degrade first. Quantisation error is roughly constant in absolute
terms, so it matters more where activations are small, and detection confidence
for distant objects drops before anything else visibly changes.

## Measuring honestly

Compare quantised and full-precision models on the same evaluation split, not on
a vendor benchmark. A throughput number without the matching accuracy number is
not a result.
