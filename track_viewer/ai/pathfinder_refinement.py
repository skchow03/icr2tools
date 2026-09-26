"""Refine a geometric Pathfinder lap without ever accepting a slower result.

The search uses the existing compact periodic spline controls, but only
evaluates candidates that do not introduce significant new curvature spikes.
"""
from __future__ import annotations

import numpy as np

from track_viewer.ai.indycar_speed_model import _curvature
from track_viewer.ai.minimum_time_optimizer import optimize_minimum_time


def refine_pathfinder(
    seed_dlats, lower_dlats, upper_dlats, xy_from_dlats, lap_evaluator,
    *, progress_callback=None,
):
    """Return (dlats, speeds, baseline_time, final_time, trials, accepted, regions).

    xy_from_dlats accepts DLAT in native ICR2 units and returns XY in feet.
    lap_evaluator returns (seconds, speed_profile_mph). No slower or newly
    kinked candidate is ever accepted, including when optimization finishes.
    """
    seed = np.asarray(seed_dlats, dtype=float)
    lower = np.asarray(lower_dlats, dtype=float)
    upper = np.asarray(upper_dlats, dtype=float)
    baseline_xy = np.asarray(xy_from_dlats(seed), dtype=float)
    baseline_k = _curvature(baseline_xy)
    baseline_jerk = np.abs(np.roll(baseline_k, -1) - baseline_k)
    baseline_time, baseline_speeds = lap_evaluator(seed)

    def guarded_evaluate(candidate):
        xy = np.asarray(xy_from_dlats(candidate), dtype=float)
        k = _curvature(xy)
        jerk = np.abs(np.roll(k, -1) - k)
        # Reject *new* sharp curvature changes, without requiring the
        # original Pathfinder to be perfectly smooth at every LP station.
        # 0.0006 1/ft permits ordinary shallow steering changes.
        if np.any(jerk > np.maximum(1.35 * baseline_jerk, 0.0006)):
            return float("inf"), baseline_speeds
        return lap_evaluator(candidate)

    result, speeds, final_time, trials, accepted, regions = optimize_minimum_time(
        seed, lower, upper, guarded_evaluate,
        progress_callback=progress_callback, coarse_controls=48,
    )
    # A strict baseline guarantee, even if the guarded search encounters
    # a nonfinite or unexpectedly inconsistent objective.
    if not np.isfinite(final_time) or final_time >= baseline_time - 0.0001:
        return seed.tolist(), baseline_speeds, baseline_time, baseline_time, trials, 0, regions
    verified_time, verified_speeds = lap_evaluator(result)
    if not np.isfinite(verified_time) or verified_time >= baseline_time - 0.0001:
        return seed.tolist(), baseline_speeds, baseline_time, baseline_time, trials, 0, regions
    return result, verified_speeds, baseline_time, verified_time, trials, accepted, regions
