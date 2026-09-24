"""1995 CART/IndyCar speed-envelope model for generated RACE lines.

This is deliberately a compact engineering approximation, not a full vehicle
simulation.  It turns the generated XY path into a continuous speed profile
using a speed-dependent lateral-grip envelope plus forward acceleration and
backward braking passes around the closed lap.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MPH_TO_FPS = 5280.0 / 3600.0
G_FPS2 = 32.174
DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / "config" / "car_performance.json"


def load_performance_model(path: Path | None = None) -> dict:
    path = path or DEFAULT_MODEL_PATH
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    required = ("max_speed_mph", "lateral_g", "acceleration_g", "braking_g")
    missing = [key for key in required if key not in data]
    if missing:
        raise ValueError("Car performance model is missing: " + ", ".join(missing))
    result = dict(data)
    for key in ("lateral_g", "acceleration_g", "braking_g"):
        table = np.asarray(result[key], dtype=float)
        if table.ndim != 2 or table.shape[1] != 2 or len(table) < 2:
            raise ValueError(f"{key} must contain at least two [mph, g] rows.")
        if np.any(~np.isfinite(table)) or np.any(np.diff(table[:, 0]) <= 0):
            raise ValueError(f"{key} speeds must be finite and strictly increasing.")
        if np.any(table[:, 1] < 0):
            raise ValueError(f"{key} g values cannot be negative.")
        result[key] = table
    result["max_speed_mph"] = float(result["max_speed_mph"])
    if result["max_speed_mph"] <= 0:
        raise ValueError("max_speed_mph must be greater than zero.")
    return result


_MODEL = load_performance_model()
MAX_SPEED_MPH = _MODEL["max_speed_mph"]
_LATERAL_G = _MODEL["lateral_g"]
_ACCEL_G = _MODEL["acceleration_g"]
_BRAKE_G = _MODEL["braking_g"]


def reload_performance_model(path: Path | None = None) -> dict:
    """Reload the editable baseline without restarting Track Viewer."""
    global _MODEL, MAX_SPEED_MPH, _LATERAL_G, _ACCEL_G, _BRAKE_G
    _MODEL = load_performance_model(path)
    MAX_SPEED_MPH = _MODEL["max_speed_mph"]
    _LATERAL_G = _MODEL["lateral_g"]
    _ACCEL_G = _MODEL["acceleration_g"]
    _BRAKE_G = _MODEL["braking_g"]
    return _MODEL


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


def _corner_speed_mph(curvature: float, performance: CarPerformance | None = None) -> float:
    """Solve v^2*|k|/g <= available lateral g at v."""
    performance = performance or CarPerformance()
    k = abs(float(curvature))
    if k < 1e-7:
        return MAX_SPEED_MPH
    lo, hi = 0.0, MAX_SPEED_MPH
    for _ in range(32):
        mph = (lo + hi) * 0.5
        fps = mph * MPH_TO_FPS
        required_g = fps * fps * k / G_FPS2
        base_g = _interp(_LATERAL_G, mph)
        # Separate mechanical grip from the speed-dependent aero contribution.
        mechanical_g = _LATERAL_G[0, 1]
        aero_g = max(0.0, base_g - mechanical_g)
        available_g = performance.safety_factor * performance.cornering_factor * (
            mechanical_g + aero_g * performance.aero_factor
        )
        if required_g <= available_g:
            lo = mph
        else:
            hi = mph
    return lo


def speed_profile_mph(points_xy_feet, performance: CarPerformance | None = None) -> np.ndarray:
    """Return a closed-lap 1995 CART speed profile for path sample points."""
    performance = performance or CarPerformance()
    points = np.asarray(points_xy_feet, dtype=float)
    if len(points) < 3 or points.ndim != 2 or points.shape[1] != 2:
        raise ValueError("Speed profile needs at least three XY path points.")
    if not np.all(np.isfinite(points)):
        raise ValueError("Speed profile path contains nonfinite coordinates.")

    segment = np.linalg.norm(np.roll(points, -1, axis=0) - points, axis=1)
    if np.any(segment < 1e-6):
        raise ValueError("Speed profile path contains duplicate adjacent points.")

    limits = np.array([_corner_speed_mph(k, performance) for k in _curvature(points)])
    speed = limits.copy()

    # Closed laps have no natural start. Repeated sweeps propagate constraints
    # through the seam and converge rapidly for ordinary LP sample counts.
    for _ in range(max(8, len(points) * 2)):
        changed = False

        # Forward: speed reachable under full-throttle acceleration.
        for i in range(len(points)):
            j = (i + 1) % len(points)
            v = speed[i] * MPH_TO_FPS
            a = performance.safety_factor * performance.acceleration_factor * _interp(_ACCEL_G, speed[i]) * G_FPS2
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
            brake_g = performance.safety_factor * performance.braking_factor * _interp(_BRAKE_G, guess)
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
