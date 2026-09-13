# Motion Models

The motion model is the `F` matrix in the Kalman filter's predict step. It
encodes what the filter assumes about how objects move between frames.

## Constant velocity

The default. State holds position and velocity; position advances by velocity
times the timestep, and velocity is assumed unchanged. For a timestep `dt`, each
position component gets `p = p + v·dt`.

Constant velocity is right often enough and wrong in predictable ways: it
overshoots on deceleration and undershoots on acceleration. Process noise `Q`
absorbs the error, which is why `Q` is effectively a statement about how much
the model is expected to be violated.

## Constant acceleration

Adds acceleration to the state. Better for genuinely accelerating objects,
worse for everything else — the extra state dimension is more uncertainty to
estimate from the same measurements, and it makes the filter jumpier under
noise. Rarely worth it for pedestrian tracking.

## Coordinated turn

Models constant speed with a constant turn rate. Standard in radar and aviation
tracking where turns are sustained and geometric. It is nonlinear, so it needs
an extended or unscented filter.

## Camera motion compensation

A moving camera makes every static object appear to move, and the filter has no
way to distinguish that from real motion. The usual fix is to estimate a global
affine or homography transform between consecutive frames from sparse feature
matches, then apply it to every track's predicted state before association.

Without compensation, a panning camera produces identity switches across the
whole frame simultaneously — a distinctive failure signature worth recognising.
