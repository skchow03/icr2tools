"""1995 CART/IndyCar speed-envelope model for generated RACE lines.

This is deliberately a compact engineering approximation, not a full vehicle
simulation.  It turns the generated XY path into a continuous speed profile
using a speed-dependent lateral-grip envelope plus forward acceleration and
backward braking passes around the closed lap.
"""

from __future__ import annotations

import math
import numpy as np

MPH_TO_FPS = 5280.0 / 3600.0
G_FPS2 = 32.174
MAX_SPEED_MPH = 230.0
SAFETY_FACTOR = 0.96

# Period-informed engineering envelopes used by the candidate-line generator.
# Intermediate values are modeled, not direct measurements.
_LATERAL_G = np.array([
    (0.0, 1.60), (40.0, 1.70), (60.0, 1.90), (80.0, 2.10),
    (100.0, 2.35), (120.0, 2.65), (140.0, 3.00), (160.0, 3.35),
    (180.0, 3.70), (200.0, 3.95), (220.0, 4.00), (230.0, 4.00),
])
_ACCEL_G = np.array([
    (0.0, 0.75), (40.0, 0.90), (60.0, 1.05), (80.0, 1.05),
    (100.0, 0.95), (120.0, 0.75), (140.0, 0.58), (160.0, 0.43),
    (180.0, 0.30), (190.0, 0.20), (200.0, 0.12), (220.0, 0.04),
    (230.0, 0.0),
])
_BRAKE_G = np.array([
    (0.0, 1.40), (40.0, 1.50), (60.0, 1.60), (80.0, 1.80),
    (100.0, 2.00), (120.0, 2.30), (140.0, 2.60), (160.0, 2.90),
    (180.0, 3.20), (200.0, 3.40), (220.0, 3.50), (230.0, 3.50),
])


def _interp(table: np.ndarray, mph: float) -> float:
    return float(np.interp(mph, table[:, 0], table[:, 1]))


def _curvature(points: np.ndarray) -> np.ndarray:
    """Signed three-point curvature (1/ft) on a closed, unevenly spaced path."""
    prev = np.roll(points, 1, axis=0)
    nxt = np.roll(points, -1, axis=0)
    a = np.linalg.norm(points - prev, axis=1)
    b = np.linalg.norm(nxt - points, axis=1)
    c = np.linalg.norm(nxt - prev, axis=1)
    cross = ((points[:, 0] - prev[:, 0]) * (nxt[:, 1] - points[:, 1])
             - (points[:, 1] - prev[:, 1]) * (nxt[:, 0] - points[:, 0]))
    denom = np.maximum(a * b * c, 1e-9)
    k = 2.0 * cross / denom
    # Suppress single-record numerical spikes without erasing real corners.
    return (np.roll(k, 1) + 2.0 * k + np.roll(k, -1)) * 0.25


def _corner_speed_mph(curvature: float) -> float:
    """Solve v^2*|k|/g <= available lateral g at v."""
    k = abs(float(curvature))
    if k < 1e-7:
        return MAX_SPEED_MPH
    lo, hi = 0.0, MAX_SPEED_MPH
    for _ in range(32):
        mph = (lo + hi) * 0.5
        fps = mph * MPH_TO_FPS
        required_g = fps * fps * k / G_FPS2
        available_g = SAFETY_FACTOR * _interp(_LATERAL_G, mph)
        if required_g <= available_g:
            lo = mph
        else:
            hi = mph
    return lo


def speed_profile_mph(points_xy_feet) -> np.ndarray:
    """Return a closed-lap 1995 CART speed profile for path sample points."""
    points = np.asarray(points_xy_feet, dtype=float)
    if len(points) < 3 or points.ndim != 2 or points.shape[1] != 2:
        raise ValueError("Speed profile needs at least three XY path points.")
    if not np.all(np.isfinite(points)):
        raise ValueError("Speed profile path contains nonfinite coordinates.")

    segment = np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1)
    if np.any(segment < 1e-6):
        raise ValueError("Speed profile path contains duplicate adjacent points.")

    limits = np.array([_corner_speed_mph(k) for k in _curvature(points)])
    speed = limits.copy()

    # Closed laps have no natural start. Repeated sweeps propagate constraints
    # through the seam and converge rapidly for ordinary LP sample counts.
    for _ in range(max(8, len(points) * 2)):
        changed = False

        # Forward: speed reachable under full-throttle acceleration.
        for i in range(len(points)):
            j = (i + 1) % len(points)
            v = speed[i] * MPH_TO_FPS
            a = SAFETY_FACTOR * _interp(_ACCEL_G, speed[i]) * G_FPS2
            reachable = math.sqrt(max(0.0, v * v + 2.0 * a * segment[i])) / MPH_TO_FPS
            new = min(speed[j], limits[j], reachable)
            if new < speed[j] - 1e-7:
                speed[j] = new
                changed = True

        # Backward: speed from which the next point remains reachable under
        # braking. Braking capability is evaluated at the faster/upstream end.
        for j in range(len(points) - 1, -1, -1):
            i = (j - 1) % len(points)
            downstream = speed[j] * MPH_TO_FPS
            guess = speed[i]
            brake_g = SAFETY_FACTOR * _interp(_BRAKE_G, guess)
            allowed = math.sqrt(max(
                0.0, downstream * downstream
                + 2.0 * brake_g * G_FPS2 * segment[i]
            )) / MPH_TO_FPS
            new = min(speed[i], limits[i], allowed)
            if new < speed[i] - 1e-7:
                speed[i] = new
                changed = True

        if not changed:
            break

    return np.clip(speed, 0.0, MAX_SPEED_MPH)
