"""Optional combined lateral/longitudinal grip re-score of existing LP geometry.

The friction ellipse uses the existing speed-dependent lateral, acceleration
and braking tables. It does not regenerate or alter either LP path.
"""
from __future__ import annotations

import math
import numpy as np

from track_viewer.ai.indycar_speed_model import (
    CarPerformance, G_FPS2, MPH_TO_FPS, _ACCEL_G, _BRAKE_G,
    _corner_speed_mph, _curvature, _interp,
)


def combined_grip_profile(points_xy_feet, performance=None, *, banking_degrees=None,
                          max_speed_mph=245.0):
    """Closed-lap speed profile with an elliptical shared tire-grip budget.

    Lateral utilization is (speed / lateral-limit-speed)^2, using the exact
    existing bank-aware cornering solver. Remaining longitudinal acceleration
    is scaled by sqrt(1 - utilization**2). This is a deliberately conservative
    engineering approximation, not a full tire or load-transfer simulation.
    """
    performance = performance or CarPerformance()
    xy = np.asarray(points_xy_feet, dtype=float)
    if xy.ndim != 2 or xy.shape[1] != 2 or len(xy) < 3 or not np.all(np.isfinite(xy)):
        raise ValueError("At least three finite XY samples are required.")
    n = len(xy)
    bank = np.zeros(n) if banking_degrees is None else np.asarray(banking_degrees, dtype=float)
    if bank.shape != (n,) or not np.all(np.isfinite(bank)):
        raise ValueError("Banking must match the LP sample count.")
    ds = np.linalg.norm(np.roll(xy, -1, axis=0) - xy, axis=1)
    if np.any(ds < 1e-6):
        raise ValueError("Duplicate adjacent LP points.")
    limits = np.minimum(max_speed_mph, [
        _corner_speed_mph(float(k), performance, float(b))
        for k, b in zip(_curvature(xy), bank)
    ])
    speed = np.asarray(limits, dtype=float).copy()

    def longitudinal_factor(index, mph):
        limit = max(float(limits[index]), 1e-6)
        utilization = min(1.0, (max(0.0, mph) / limit) ** 2)
        return math.sqrt(max(0.0, 1.0 - utilization ** 2))

    # Integrate each segment with midpoint grip, and iterate until the closed
    # loop converges. A bisection avoids optimistic full-throttle assumptions
    # when speed and lateral load change materially across one LP segment.
    for _ in range(max(16, n * 3)):
        changed = False
        for i in range(n):
            j = (i + 1) % n
            initial = float(speed[i])
            lo, hi = initial, max(initial, float(limits[j]))
            for _ in range(20):
                candidate = (lo + hi) * 0.5
                mid = (initial + candidate) * 0.5
                grip = min(longitudinal_factor(i, mid), longitudinal_factor(j, mid))
                accel = (performance.safety_factor * performance.acceleration_factor
                         * _interp(_ACCEL_G, mid) * G_FPS2 * grip)
                reachable_sq = (initial * MPH_TO_FPS) ** 2 + 2 * accel * ds[i]
                if (candidate * MPH_TO_FPS) ** 2 <= reachable_sq:
                    lo = candidate
                else:
                    hi = candidate
            new = min(float(speed[j]), float(limits[j]), lo)
            if new < speed[j] - 1e-6:
                speed[j] = new
                changed = True
        for j in range(n - 1, -1, -1):
            i = (j - 1) % n
            downstream = float(speed[j])
            lo, hi = downstream, max(downstream, float(limits[i]))
            for _ in range(20):
                candidate = (lo + hi) * 0.5
                mid = (candidate + downstream) * 0.5
                grip = min(longitudinal_factor(i, mid), longitudinal_factor(j, mid))
                brake = (performance.safety_factor * performance.braking_factor
                         * _interp(_BRAKE_G, mid) * G_FPS2 * grip)
                reachable_sq = (downstream * MPH_TO_FPS) ** 2 + 2 * brake * ds[i]
                if (candidate * MPH_TO_FPS) ** 2 <= reachable_sq:
                    lo = candidate
                else:
                    hi = candidate
            new = min(float(speed[i]), float(limits[i]), lo)
            if new < speed[i] - 1e-6:
                speed[i] = new
                changed = True
        if not changed:
            break
    return speed


def modeled_lap_seconds(xy, speeds):
    xy = np.asarray(xy, dtype=float)
    speeds = np.asarray(speeds, dtype=float)
    ds = np.linalg.norm(np.roll(xy, -1, axis=0) - xy, axis=1)
    segment_mph = (speeds + np.roll(speeds, -1)) * 0.5
    return float(np.sum(ds / 5280.0 / np.maximum(segment_mph, 1e-9)) * 3600.0)


def compare_combined_grip(baseline_xy, refined_xy, *, performance=None,
                          baseline_banking=None, refined_banking=None,
                          max_speed_mph=245.0):
    results = {}
    for name, xy, bank in (
        ("baseline", baseline_xy, baseline_banking),
        ("refined", refined_xy, refined_banking),
    ):
        speeds = combined_grip_profile(
            xy, performance, banking_degrees=bank, max_speed_mph=max_speed_mph
        )
        results[name] = {
            "lap_seconds": modeled_lap_seconds(xy, speeds),
            "minimum_speed_mph": float(np.min(speeds)),
            "maximum_speed_mph": float(np.max(speeds)),
            "speeds_mph": speeds.tolist(),
        }
    results["refined_minus_baseline_seconds"] = (
        results["refined"]["lap_seconds"] - results["baseline"]["lap_seconds"]
    )
    return results


def format_combined_grip_comparison(result, *, speeds_saved=False):
    baseline, refined = result["baseline"], result["refined"]
    return (
        "OPTIONAL COMBINED-GRIP RE-SCORE (unchanged LP geometry)\n"
        f"Pathfinder baseline: {baseline['lap_seconds']:.3f} s; "
        f"speed range {baseline['minimum_speed_mph']:.2f}–"
        f"{baseline['maximum_speed_mph']:.2f} mph\n"
        f"Pathfinder Refinement: {refined['lap_seconds']:.3f} s; "
        f"speed range {refined['minimum_speed_mph']:.2f}–"
        f"{refined['maximum_speed_mph']:.2f} mph\n"
        f"Refined minus baseline: {result['refined_minus_baseline_seconds']:+.3f} s\n"
        "Friction ellipse shares lateral and longitudinal grip. "
        + ("The optimized LP saves combined-grip speeds." if speeds_saved
           else "These are comparative estimates; saved LP speeds are unchanged.")
    )
