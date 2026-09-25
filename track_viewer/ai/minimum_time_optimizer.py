"""Direct minimum-lap-time optimizer for an existing legal LP path."""

from __future__ import annotations
import numpy as np
DLAT_PER_FOOT = 6000.0

def optimize_minimum_time(seed_dlats, evaluate, legalize, *, progress_callback=None, coarse_controls=40):
    current = np.asarray(seed_dlats, dtype=float)
    best_time, best_speeds = evaluate(current)
    n = len(current)
    if n < 16:
        return current.tolist(), best_speeds, best_time, 0, 0
    controls = max(16, min(int(coarse_controls), n // 4))
    centers = np.linspace(0, n, controls, endpoint=False, dtype=int)
    half_window = max(4, int(round(n / controls)))
    trials = accepted = 0
    sensitive = []

    def perturb(base, center, shift_ft):
        candidate = np.asarray(base, dtype=float).copy()
        for offset in range(-half_window, half_window + 1):
            idx = (center + offset) % n
            phase = abs(offset) / float(half_window + 1)
            weight = 0.5 * (1.0 + np.cos(np.pi * phase))
            candidate[idx] += shift_ft * DLAT_PER_FOOT * weight
        return candidate

    for ordinal, center in enumerate(centers, 1):
        control_best = (best_time, current, best_speeds)
        improvement = 0.0
        for shift_ft in (-3.0, 3.0):
            candidate = legalize(perturb(current, center, shift_ft))
            lap_time, speeds = evaluate(candidate)
            trials += 1
            if lap_time < control_best[0] - 0.001:
                control_best = (lap_time, np.asarray(candidate, dtype=float), speeds)
        if control_best[0] < best_time - 0.001:
            improvement = best_time - control_best[0]
            best_time, current, best_speeds = control_best
            accepted += 1
        if improvement >= 0.002:
            sensitive.append((improvement, int(center)))
        if progress_callback:
            progress_callback(ordinal, controls + 12, f"Minimum-time search: control {ordinal}/{controls}")

    sensitive.sort(reverse=True)
    refine = [center for _, center in sensitive[:12]]
    for ordinal, center in enumerate(refine, 1):
        control_best = (best_time, current, best_speeds)
        for shift_ft in (-1.0, 1.0):
            candidate = legalize(perturb(current, center, shift_ft))
            lap_time, speeds = evaluate(candidate)
            trials += 1
            if lap_time < control_best[0] - 0.0005:
                control_best = (lap_time, np.asarray(candidate, dtype=float), speeds)
        if control_best[0] < best_time - 0.0005:
            best_time, current, best_speeds = control_best
            accepted += 1
        if progress_callback:
            progress_callback(controls + ordinal, controls + len(refine), f"Refining sensitive control {ordinal}/{len(refine)}")
    return current.tolist(), best_speeds, best_time, trials, accepted
