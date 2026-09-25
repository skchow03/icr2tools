"""Adaptive direct minimum-lap-time optimizer.

The search is independent of apex/width/lookahead heuristics. It uses compact
cubic spline-like basis functions so it can move turn-in, clipping point and
exit independently instead of dragging a broad cosine window across a corner.
"""

from __future__ import annotations
import numpy as np

DLAT_PER_FOOT = 6000.0


def _project(candidate, lower, upper):
    return np.clip(np.asarray(candidate, dtype=float), lower, upper)


def _cubic_basis(n, center, spacing):
    """Compact C2 cubic B-spline basis centred on one path control."""
    radius = max(4, int(spacing * 2))
    offsets = np.arange(-radius, radius + 1)
    x = np.abs(offsets) / max(float(spacing), 1.0)
    weight = np.zeros_like(x, dtype=float)
    inner = x < 1.0
    outer = (x >= 1.0) & (x < 2.0)
    weight[inner] = 2.0 / 3.0 - x[inner] ** 2 + 0.5 * x[inner] ** 3
    weight[outer] = (2.0 - x[outer]) ** 3 / 6.0
    # Normalize peak to one so "shift feet" has intuitive meaning.
    weight /= max(float(np.max(weight)), 1e-12)
    return (center + offsets) % n, weight


def optimize_minimum_time(
    seed_dlats, lower_dlats, upper_dlats, evaluate, *,
    progress_callback=None, coarse_controls=48,
):
    current = _project(seed_dlats, lower_dlats, upper_dlats)
    lower = np.asarray(lower_dlats, dtype=float)
    upper = np.asarray(upper_dlats, dtype=float)
    best_time, best_speeds = evaluate(current)
    n = len(current)
    if n < 16:
        return current.tolist(), best_speeds, best_time, 0, 0, 0

    controls = max(24, min(int(coarse_controls), n // 5))
    centers = np.linspace(0, n, controls, endpoint=False, dtype=int)
    spacing = max(3, int(round(n / controls)))
    trials = accepted = 0
    opportunities = []

    def move(base, center, shift_ft, local_spacing=spacing):
        candidate = np.asarray(base, dtype=float).copy()
        idx, weight = _cubic_basis(n, int(center), max(3, int(local_spacing)))
        candidate[idx] += shift_ft * DLAT_PER_FOOT * weight
        return _project(candidate, lower, upper)

    # Coarse direct spline-control search. These controls have substantially
    # shorter influence than the old raised-cosine windows.
    for ordinal, center in enumerate(centers, 1):
        before = best_time
        local_best = (best_time, current, best_speeds)
        for shift in (-3.0, 3.0):
            candidate = move(current, center, shift)
            lap_time, speeds = evaluate(candidate)
            trials += 1
            if lap_time < local_best[0] - 0.001:
                local_best = (lap_time, candidate, speeds)
        if local_best[0] < best_time - 0.001:
            best_time, current, best_speeds = local_best
            accepted += 1
            opportunities.append((before - best_time, int(center)))
        if progress_callback:
            progress_callback(
                ordinal, controls + 32,
                f"Spline minimum-time search {ordinal}/{controls}",
            )

    # Densify only around regions that demonstrated lap-time sensitivity.
    # Offset controls are critical: they let the optimizer move curvature
    # longitudinally, e.g. later turn-in/shorter apex dwell, rather than only
    # moving an existing broad arc sideways.
    opportunities.sort(reverse=True)
    fine_spacing = max(3, spacing // 2)
    focus = []
    for _, center in opportunities[:10]:
        focus.extend((
            (center - spacing) % n,
            (center - fine_spacing) % n,
            center,
            (center + fine_spacing) % n,
            (center + spacing) % n,
        ))
    focus = list(dict.fromkeys(int(x) for x in focus))[:40]

    for ordinal, center in enumerate(focus, 1):
        local_best = (best_time, current, best_speeds)
        for shift in (-1.5, 1.5):
            candidate = move(current, center, shift, fine_spacing)
            lap_time, speeds = evaluate(candidate)
            trials += 1
            if lap_time < local_best[0] - 0.0004:
                local_best = (lap_time, candidate, speeds)
        if local_best[0] < best_time - 0.0004:
            best_time, current, best_speeds = local_best
            accepted += 1
        if progress_callback:
            progress_callback(
                controls + ordinal, controls + max(1, len(focus)),
                f"Local spline refinement {ordinal}/{len(focus)}",
            )

    # Final small controls only in the strongest original regions. This gives
    # turn-in/apex/exit enough independence without adding global wiggle room.
    micro_spacing = max(3, fine_spacing // 2)
    for _, center in opportunities[:8]:
        for shifted_center in (
            (center - fine_spacing) % n, center, (center + fine_spacing) % n
        ):
            local_best = (best_time, current, best_speeds)
            for shift in (-0.6, 0.6):
                candidate = move(current, shifted_center, shift, micro_spacing)
                lap_time, speeds = evaluate(candidate)
                trials += 1
                if lap_time < local_best[0] - 0.00015:
                    local_best = (lap_time, candidate, speeds)
            if local_best[0] < best_time - 0.00015:
                best_time, current, best_speeds = local_best
                accepted += 1

    return (
        current.tolist(), best_speeds, best_time, trials, accepted,
        len(opportunities),
    )
