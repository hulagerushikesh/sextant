# The Kalman Filter

A Kalman filter estimates the hidden state of a linear system from a stream of
noisy measurements. It is the minimum-variance estimator when the process and
measurement noise are both Gaussian, and it is recursive: each update needs only
the previous estimate and the new measurement, never the full history.

## State and covariance

The filter carries two things forward. The state vector `x` holds the quantities
being estimated — for a tracked object, typically position, velocity and box
dimensions. The covariance matrix `P` holds the filter's own uncertainty about
that state, including how the errors in different components correlate.

A common tracking state is eight-dimensional: centre `u`, centre `v`, aspect
ratio `a`, height `h`, and the time derivatives of each.

## The predict step

Prediction advances the state to the next timestep using the motion model:

    x = F x
    P = F P Fᵀ + Q

`F` is the state transition matrix and `Q` is the process noise covariance.
Prediction always increases uncertainty — `Q` is the admission that the motion
model is wrong in ways the filter cannot see.

## The update step

Update folds in a measurement `z`:

    y = z - H x                    innovation
    S = H P Hᵀ + R                 innovation covariance
    K = P Hᵀ S⁻¹                   Kalman gain
    x = x + K y
    P = (I - K H) P

`H` is the measurement matrix, mapping state space into measurement space, and
`R` is the measurement noise covariance. The Kalman gain `K` decides how much to
trust the measurement over the prediction: large when `P` is large relative to
`R`, small when the filter is already confident.

## Tuning Q and R

`R` is a property of the sensor and can often be measured directly. `Q` is a
modelling choice and is almost always tuned. A `Q` that is too small makes the
filter sluggish and slow to follow manoeuvres; too large and it chases noise.

In tracking pipelines both are frequently scaled by the object's height, so that
a distant, small object is not held to the same positional precision as a near
one.

## Limits

The filter assumes linear dynamics and Gaussian noise. Neither holds exactly for
objects that turn, accelerate or are partially occluded. The extended and
unscented variants relax the linearity assumption; neither fixes the Gaussian
one. When the noise is genuinely multi-modal — two plausible interpretations of
the same measurement — a particle filter is the honest choice.
