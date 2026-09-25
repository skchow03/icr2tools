"""Adaptive direct minimum-lap-time optimizer.

This module deliberately knows nothing about corner/apex/width parameters.
It manipulates the LP's lateral path directly inside a precomputed legal
DLAT envelope and scores complete modeled lap time.
"""

from __future__ import annotations
import numpy as np

DLAT_PER_FOOT = 6000.0


def _window(n, center, half_width):
    idx = (np.arange(-half_width, half_width + 1) + center) % n
    phase = np.abs(np.arange(-half_width, half_width + 1)) / float(half_width + 1)
    weight = 0.5 * (1.0 + np.cos(np.pi * phase))
    return idx, weight


def _project(candidate, lower, upper):
    """Cheap hard projection into the already-selected legal corridor."""
    return np.clip(np.asarray(candidate, dtype=float), lower, upper)


def optimize_minimum_time(
    seed_dlats, lower_dlats, upper_dlats, evaluate, *,
    progress_callback=None, coarse_controls=32,
):
    current = _project(seed_dlats, lower_dlats, upper_dlats)
    lower = np.asarray(lower_dlats, dtype=float)
    upper = np.asarray(upper_dlats, dtype=float)
    best_time, best_speeds = evaluate(current)
    baseline_time = best_time
    n = len(current)
    if n < 16:
        return current.tolist(), best_speeds, best_time, 0, 0, 0

    controls = max(16, min(int(coarse_controls), n // 6))
    centers = np.linspace(0, n, controls, endpoint=False, dtype=int)
    half = max(5, int(round(n / controls)))
    trials = accepted = 0
    opportunities = []

    def try_mode(base, center, shift_ft, mode="single"):
        candidate = np.asarray(base, dtype=float).copy()
        idx, weight = _window(n, center, half)
        candidate[idx] += shift_ft * DLAT_PER_FOOT * weight
        if mode == "paired":
            # Coordinated entry/exit shape: opposite displacement downstream.
            other = (center + half) % n
            idx2, weight2 = _window(n, other, max(4, half // 2))
            candidate[idx2] -= 0.65 * shift_ft * DLAT_PER_FOOT * weight2
        return _project(candidate, lower, upper)

    # Broad discovery. Test larger direct changes without invoking the old
    # geometric optimizer. Keep useful changes immediately (pattern search).
    for ordinal, center in enumerate(centers, 1):
        before = best_time
        local_best = (best_time, current, best_speeds)
        for shift in (-4.0, 4.0):
            for mode in ("single", "paired"):
                candidate = try_mode(current, int(center), shift, mode)
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
                ordinal, controls + 24,
                f"Direct minimum-time search {ordinal}/{controls}",
            )

    # Rank the regions where the line actually affected lap time, then add
    # finer controls around those regions instead of densifying long straights.
    opportunities.sort(reverse=True)
    focus = []
    quarter = max(2, half // 2)
    for _, center in opportunities[:8]:
        focus.extend(((center - quarter) % n, center, (center + quarter) % n))
    # Preserve order while removing duplicate nearby integer controls.
    focus = list(dict.fromkeys(int(x) for x in focus))[:24]

    for ordinal, center in enumerate(focus, 1):
        local_best = (best_time, current, best_speeds)
        for shift in (-2.0, 2.0):
            candidate = try_mode(current, center, shift, "single")
            lap_time, speeds = evaluate(candidate)
            trials += 1
            if lap_time < local_best[0] - 0.0005:
                local_best = (lap_time, candidate, speeds)
        if local_best[0] < best_time - 0.0005:
            best_time, current, best_speeds = local_best
            accepted += 1
        if progress_callback:
            progress_callback(
                controls + ordinal, controls + max(1, len(focus)),
                f"Adaptive refinement {ordinal}/{len(focus)}",
            )

    # One cheap settling pass at the controls that originally mattered.
    for _, center in opportunities[:8]:
        local_best = (best_time, current, best_speeds)
        for shift in (-0.75, 0.75):
            candidate = try_mode(current, center, shift, "single")
            lap_time, speeds = evaluate(candidate)
            trials += 1
            if lap_time < local_best[0] - 0.0002:
                local_best = (lap_time, candidate, speeds)
        if local_best[0] < best_time - 0.0002:
            best_time, current, best_speeds = local_best
            accepted += 1

    return (
        current.tolist(), best_speeds, best_time, trials, accepted,
        len(opportunities),
    )
