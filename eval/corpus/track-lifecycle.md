# Track Lifecycle Management

A track is a hypothesis about an object's continued existence. Lifecycle rules
decide when to create one, when to trust it, and when to give up.

## States

A track is **tentative** when newly created from an unmatched detection. It is
not yet reported to the consumer, because a single detection is as likely to be
a false positive as a new object.

It becomes **confirmed** after being matched in `min_hits` consecutive frames —
three is the usual default. Confirmed tracks are reported and keep their
identity.

It becomes **deleted** after going unmatched for `max_age` consecutive frames.
Thirty frames, about one second at 30 fps, is a common default.

## Coasting

Between losing a detection and being deleted, a track coasts: the Kalman filter
keeps predicting without any update. Coasting is what lets a track survive a
brief occlusion, but the position estimate degrades quickly because there is no
measurement to correct it, and covariance grows every frame.

Some pipelines stop reporting a coasting track after a few frames while keeping
it alive internally for re-association. This separates "where do I believe this
object is" from "what am I confident enough to show".

## The tuning trade-off

A short `max_age` deletes tracks through occlusions and produces identity
switches when the object reappears. A long `max_age` keeps ghost tracks alive
after objects have genuinely left, and those ghosts steal detections from real
new objects.

A high `min_hits` suppresses false tracks but delays reporting real ones,
which matters when the consumer is counting objects crossing a line.

There is no correct setting independent of the scene. A stationary camera on a
crowded pavement wants different numbers from a drone over sparse traffic.
