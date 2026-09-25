"""Physics-free geometric racing-line optimizer."""

from __future__ import annotations
import numpy as np

DLAT_PER_FOOT = 6000.0


def _project(values, lower, upper):
    return np.clip(np.asarray(values, dtype=float), lower, upper)


def _basis(n, center, spacing):
    radius = max(4, 2 * spacing)
    offsets = np.arange(-radius, radius + 1)
    x = np.abs(offsets) / max(float(spacing), 1.0)
    w = np.zeros_like(x, dtype=float)
    a = x < 1.0
    b = (x >= 1.0) & (x < 2.0)
    w[a] = 2 / 3 - x[a] ** 2 + 0.5 * x[a] ** 3
    w[b] = (2 - x[b]) ** 3 / 6
    w /= max(float(w.max()), 1e-12)
    return (center + offsets) % n, w


def _geometry_score(xy):
    """Dimensionless objective: coherent low curvature without wandering."""
    p = np.asarray(xy, dtype=float)
    prev = np.roll(p, 1, axis=0)
    nxt = np.roll(p, -1, axis=0)
    vin = p - prev
    vout = nxt - p
    lin = np.maximum(np.linalg.norm(vin, axis=1), 0.25)
    lout = np.maximum(np.linalg.norm(vout, axis=1), 0.25)
    cross = vin[:, 0] * vout[:, 1] - vin[:, 1] * vout[:, 0]
    dot = np.sum(vin * vout, axis=1)
    angle = np.arctan2(cross, dot)
    spacing = 0.5 * (lin + lout)
    kappa = angle / spacing
    dk = np.roll(kappa, -1) - kappa
    d2k = np.roll(dk, -1) - dk
    length = float(np.sum(lout))
    # Curvature-squared favors radius; curvature derivatives discourage long,
    # vague crossovers and abrupt steering reversals. A small path-length term
    # prevents needless lateral wandering when curvature is equivalent.
    return (
        float(np.mean(kappa * kappa))
        + 18.0 * float(np.mean(dk * dk))
        + 6.0 * float(np.mean(d2k * d2k))
        + 2.0e-8 * length
    )


def optimize_geometric(seed_dlats, lower_dlats, upper_dlats, build_xy, *, progress_callback=None):
    current = _project(seed_dlats, lower_dlats, upper_dlats)
    n = len(current)
    best_score = _geometry_score(build_xy(current))
    if n < 16:
        return current.tolist(), best_score, best_score, 0, 0
    baseline = best_score
    controls = max(32, min(64, n // 5))
    centers = np.linspace(0, n, controls, endpoint=False, dtype=int)
    spacing = max(3, int(round(n / controls)))
    trials = accepted = 0
    useful = []

    def move(base, center, feet, local_spacing):
        trial = np.asarray(base, dtype=float).copy()
        idx, weight = _basis(n, int(center), local_spacing)
        trial[idx] += feet * DLAT_PER_FOOT * weight
        return _project(trial, lower_dlats, upper_dlats)

    for ordinal, center in enumerate(centers, 1):
        before = best_score
        local = (best_score, current)
        for feet in (-4.0, -2.0, 2.0, 4.0):
            trial = move(current, center, feet, spacing)
            score = _geometry_score(build_xy(trial))
            trials += 1
            if score < local[0] - 1e-12:
                local = (score, trial)
        if local[0] < best_score - 1e-12:
            best_score, current = local
            accepted += 1
            useful.append((before - best_score, int(center)))
        if progress_callback:
            progress_callback(ordinal, controls + 40, f"Geometric search {ordinal}/{controls}")

    useful.sort(reverse=True)
    fine_spacing = max(3, spacing // 2)
    focus = []
    for _, center in useful[:12]:
        focus.extend(((center - fine_spacing) % n, center, (center + fine_spacing) % n))
    focus = list(dict.fromkeys(int(x) for x in focus))[:40]
    for ordinal, center in enumerate(focus, 1):
        local = (best_score, current)
        for feet in (-1.25, 1.25):
            trial = move(current, center, feet, fine_spacing)
            score = _geometry_score(build_xy(trial))
            trials += 1
            if score < local[0] - 1e-12:
                local = (score, trial)
        if local[0] < best_score - 1e-12:
            best_score, current = local
            accepted += 1
        if progress_callback:
            progress_callback(controls + ordinal, controls + max(1, len(focus)), f"Geometric refinement {ordinal}/{len(focus)}")
    return current.tolist(), baseline, best_score, trials, accepted
