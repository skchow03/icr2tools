"""Compare the Pathfinder seed and refined LP against the actual speed envelope."""
from __future__ import annotations

import numpy as np

from track_viewer.ai.indycar_speed_model import (
    CarPerformance, G_FPS2, MPH_TO_FPS, _corner_speed_mph, _curvature,
)


def audit_paths(dlongs, baseline_xy, baseline_speeds, refined_xy, refined_speeds,
                *, performance=None, baseline_banking=None, refined_banking=None,
                max_speed_mph=245.0):
    """Return JSON-safe per-station traces and top grip/acceleration locations.

    Input XY must be the actual final LP coordinates in feet. The same
    curvature routine and cornering-limit solver as the speed model are used.
    This is a lateral-grip audit, not a combined-grip simulation.
    """
    performance = performance or CarPerformance()
    n = len(dlongs)
    if n < 3:
        raise ValueError("Audit requires at least three unique LP stations.")
    dlong = np.asarray(dlongs, dtype=float)
    traces = {}
    for name, xy_values, speed_values, bank_values in (
        ("baseline", baseline_xy, baseline_speeds, baseline_banking),
        ("refined", refined_xy, refined_speeds, refined_banking),
    ):
        xy = np.asarray(xy_values, dtype=float)
        speed = np.asarray(speed_values, dtype=float)
        bank = np.zeros(n) if bank_values is None else np.asarray(bank_values, dtype=float)
        if (xy.shape != (n, 2) or speed.shape != (n,) or bank.shape != (n,)
                or not np.all(np.isfinite(xy)) or not np.all(np.isfinite(speed))
                or not np.all(np.isfinite(bank))):
            raise ValueError(f"Invalid {name} audit coordinates, speeds or banking.")
        curvature = _curvature(xy)
        limits = np.asarray([
            min(max_speed_mph, _corner_speed_mph(float(k), performance, float(b)))
            for k, b in zip(curvature, bank)
        ])
        lateral_g = (speed * MPH_TO_FPS) ** 2 * np.abs(curvature) / G_FPS2
        limit_g = (limits * MPH_TO_FPS) ** 2 * np.abs(curvature) / G_FPS2
        excess = speed - limits
        traces[name] = {
            "dlong": dlong.tolist(),
            "speed_mph": speed.tolist(),
            "curvature_per_ft": curvature.tolist(),
            "banking_degrees": bank.tolist(),
            "lateral_g": lateral_g.tolist(),
            "corner_speed_limit_mph": limits.tolist(),
            "lateral_g_at_speed_limit": limit_g.tolist(),
            "speed_limit_excess_mph": excess.tolist(),
        }
    ref = traces["refined"]
    base = traces["baseline"]
    # Rank by actual grip-limit excess first; retain high-g stations even if
    # they are fully within the speed model's permitted envelope.
    excess = np.asarray(ref["speed_limit_excess_mph"])
    g = np.asarray(ref["lateral_g"])
    peak = int(np.argmax(g))
    ranked = sorted(range(n), key=lambda i: (excess[i], g[i]), reverse=True)
    selected = [peak] + [i for i in ranked if i != peak][:9]
    rows = []
    for i in selected:
        rows.append({
            "index": i,
            "dlong": float(dlong[i]),
            "refined_speed_mph": ref["speed_mph"][i],
            "baseline_speed_mph": base["speed_mph"][i],
            "refined_curvature_per_ft": ref["curvature_per_ft"][i],
            "baseline_curvature_per_ft": base["curvature_per_ft"][i],
            "refined_lateral_g": ref["lateral_g"][i],
            "baseline_lateral_g": base["lateral_g"][i],
            "permitted_corner_speed_mph": ref["corner_speed_limit_mph"][i],
            "permitted_lateral_g_at_limit": ref["lateral_g_at_speed_limit"][i],
            "speed_limit_excess_mph": ref["speed_limit_excess_mph"][i],
        })
    # Numerical solver tolerance and LP quantization can produce tiny excess.
    violations = np.flatnonzero(excess > 0.1)
    return {
        "peak_refined_lateral_g": float(g[peak]),
        "peak_refined_index": peak,
        "peak_refined_dlong": float(dlong[peak]),
        "max_speed_limit_excess_mph": float(np.max(excess)),
        "violations_over_0_1_mph": int(len(violations)),
        "rows": rows,
        "traces": traces,
        "note": ("This audit checks instantaneous lateral corner-speed limits only. "
                 "The separate combined-grip comparison checks acceleration "
                 "and braking while cornering, when enabled."),
    }


def format_audit(audit):
    lines = [
        "LATERAL-GRIP COMPLIANCE AUDIT (Pathfinder vs Refinement)",
        f"Peak refined lateral acceleration: {audit['peak_refined_lateral_g']:.3f} g "
        f"at DLONG {audit['peak_refined_dlong']:.0f} "
        f"(LP index {audit['peak_refined_index']})",
        f"Largest corner-speed limit excess: {audit['max_speed_limit_excess_mph']:+.3f} mph",
        f"Stations >0.1 mph over corner limit: {audit['violations_over_0_1_mph']}",
        "Peak-g station first, then nine largest limit-excess stations:",
    ]
    for row in audit["rows"]:
        lines.append(
            f"DLONG {row['dlong']:.0f} [#{row['index']}]: "
            f"baseline {row['baseline_speed_mph']:.2f} mph / "
            f"{row['baseline_lateral_g']:.3f} g; refined "
            f"{row['refined_speed_mph']:.2f} mph / "
            f"{row['refined_lateral_g']:.3f} g; "
            f"limit {row['permitted_corner_speed_mph']:.2f} mph / "
            f"{row['permitted_lateral_g_at_limit']:.3f} g; "
            f"excess {row['speed_limit_excess_mph']:+.3f} mph; "
            f"curvature baseline/refined "
            f"{row['baseline_curvature_per_ft']:.6f}/"
            f"{row['refined_curvature_per_ft']:.6f} 1/ft"
        )
    lines.append(audit["note"])
    return "\n".join(lines)
