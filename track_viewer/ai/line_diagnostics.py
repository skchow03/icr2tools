"""Comparable, distance-normalized diagnostics for every generated LP."""
from __future__ import annotations

import numpy as np

MPH_TO_FPS = 5280.0 / 3600.0


def analyze_line(records, *, track_length=None, lower=None, upper=None):
    """Analyze a closed LP without counting its duplicated terminal record.

    lower/upper, when supplied, are the legal DLAT bounds in native units.
    Acceleration/braking durations are *inferred from speed changes*, not
    simulated throttle or brake inputs. Steering reversals are raw,
    thresholded curvature sign changes; they are not necessarily errors.
    """
    points = list(records)
    if track_length is not None and len(points) > 3 and abs(
        float(points[-1].dlong) - float(track_length)
    ) < 1.0:
        points = points[:-1]
    if len(points) < 3:
        raise ValueError("At least three unique LP records are required.")
    xy = np.array([(p.x / 6000.0, p.y / 6000.0) for p in points], dtype=float)
    speeds = np.array([float(p.speed_mph) for p in points], dtype=float)
    if not np.all(np.isfinite(xy)) or not np.all(np.isfinite(speeds)):
        raise ValueError("LP has nonfinite coordinates or speeds.")
    ds = np.linalg.norm(np.roll(xy, -1, axis=0) - xy, axis=1)
    mean_speed = (speeds + np.roll(speeds, -1)) * 0.5
    if np.any(ds < 1e-6) or np.any(mean_speed <= 0.01):
        raise ValueError("LP has duplicate points or nonpositive segment speed.")
    dt = ds / (mean_speed * MPH_TO_FPS)
    lap = float(np.sum(dt))
    # Three-point signed curvature at each sample, using its actual XY
    # distances; variation is normalized by distance rather than record count.
    prev = np.roll(xy, 1, axis=0)
    nxt = np.roll(xy, -1, axis=0)
    a = np.linalg.norm(xy - prev, axis=1)
    b = np.linalg.norm(nxt - xy, axis=1)
    c = np.linalg.norm(nxt - prev, axis=1)
    cross = ((xy[:, 0] - prev[:, 0]) * (nxt[:, 1] - xy[:, 1])
             - (xy[:, 1] - prev[:, 1]) * (nxt[:, 0] - xy[:, 0]))
    k = 2.0 * cross / np.maximum(a * b * c, 1e-9)
    # Match the shared speed model's noise suppression.
    k = (np.roll(k, 1) + 2.0 * k + np.roll(k, -1)) * 0.25
    dk = np.roll(k, -1) - k
    dk_per_ft = np.abs(dk) / ds
    # Ignore near-straight curvature noise; report observed sign changes,
    # not a claim that each reversal is an inappropriate steering action.
    threshold = 1.0 / 5000.0
    signs = np.where(np.abs(k) >= threshold, np.sign(k), 0)
    nonzero = signs[signs != 0]
    reversals = int(np.count_nonzero(nonzero != np.roll(nonzero, 1))) if len(nonzero) > 1 else 0
    dv = np.roll(speeds, -1) - speeds
    accel_seconds = float(np.sum(dt[dv > 0.25]))
    brake_seconds = float(np.sum(dt[dv < -0.25]))
    steady_seconds = float(np.sum(dt[np.abs(dv) <= 0.25]))
    # Lateral acceleration in g, using the recorded speed profile.
    lat_g = (speeds * MPH_TO_FPS) ** 2 * np.abs(k) / 32.174
    result = {
        "sample_count": len(points),
        "lap_seconds": lap,
        "distance_miles": float(np.sum(ds) / 5280.0),
        "average_mph": float(np.sum(ds) / 5280.0 * 3600.0 / lap),
        "minimum_speed_mph": float(np.min(speeds)),
        "maximum_speed_mph": float(np.max(speeds)),
        "accelerating_seconds_estimate": accel_seconds,
        "decelerating_seconds_estimate": brake_seconds,
        "near_constant_speed_seconds_estimate": steady_seconds,
        "peak_abs_curvature_per_ft": float(np.max(np.abs(k))),
        "peak_abs_curvature_change_per_ft2": float(np.max(dk_per_ft)),
        "curvature_total_variation_per_ft": float(np.sum(np.abs(dk)) / np.sum(ds)),
        "thresholded_curvature_sign_changes": reversals,
        "peak_lateral_g_estimate": float(np.max(lat_g)),
        "minimum_legal_clearance_ft": None,
    }
    if lower is not None and upper is not None:
        dlat = np.asarray([p.dlat for p in points], dtype=float)
        low, high = np.asarray(lower, dtype=float), np.asarray(upper, dtype=float)
        if low.shape != dlat.shape or high.shape != dlat.shape:
            raise ValueError("Legal envelope must match unique LP sample count.")
        result["minimum_legal_clearance_ft"] = float(
            np.min(np.minimum(dlat - low, high - dlat)) / 6000.0
        )
    return result


def format_diagnostics(stats):
    lines = [
        "COMMON LP DIAGNOSTICS",
        f"Estimated lap: {stats['lap_seconds']:.3f} s",
        f"LP distance: {stats['distance_miles']:.3f} mi",
        f"Average speed: {stats['average_mph']:.2f} mph",
        f"Speed range: {stats['minimum_speed_mph']:.2f}–{stats['maximum_speed_mph']:.2f} mph",
        f"Accelerating / decelerating / steady (speed-derived): "
        f"{stats['accelerating_seconds_estimate']:.2f} / "
        f"{stats['decelerating_seconds_estimate']:.2f} / "
        f"{stats['near_constant_speed_seconds_estimate']:.2f} s",
        f"Peak curvature: {stats['peak_abs_curvature_per_ft']:.6f} 1/ft",
        f"Peak curvature change: {stats['peak_abs_curvature_change_per_ft2']:.8f} 1/ft²",
        f"Curvature variation per foot: {stats['curvature_total_variation_per_ft']:.8f} 1/ft²",
        f"Curvature sign changes (thresholded): {stats['thresholded_curvature_sign_changes']}",
        f"Peak lateral acceleration (speed-derived): {stats['peak_lateral_g_estimate']:.2f} g",
    ]
    clearance = stats["minimum_legal_clearance_ft"]
    if clearance is not None:
        lines.append(f"Minimum legal-corridor clearance: {clearance:.2f} ft")
    lines.append(
        "Speed-derived acceleration/deceleration is not a throttle/brake trace. "
        "Curvature sign changes may include legitimate corner transitions."
    )
    return "\n".join(lines)
