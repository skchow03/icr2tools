"""Geometry-only candidate racing line for an existing ICR2 LP sampling grid.

This minimizes integrated squared curvature. It deliberately makes no claim
about lap time: the car model and a speed profile are separate work.
"""

from __future__ import annotations

import numpy as np

from icr2_core.trk.trk_utils import dlong2sect, getbounddlat, getxyz


DLAT_PER_FOOT = 6000.0


def _energy_and_gradient(points: np.ndarray) -> tuple[float, np.ndarray]:
    """Approximate integral of curvature squared, with a periodic gradient."""
    prev = np.roll(points, 1, axis=0)
    following = np.roll(points, -1, axis=0)
    a = following - 2 * points + prev
    edge = following - points
    length = np.maximum(np.linalg.norm(edge, axis=1), 0.01)
    spacing = np.maximum((length + np.roll(length, 1)) * 0.5, 0.01)
    bend_sq = np.sum(a * a, axis=1)
    energy = float(np.sum(bend_sq / spacing**3))

    bend_gradient = 2 * a / spacing[:, None] ** 3
    gradient = (
        np.roll(bend_gradient, 1, axis=0)
        - 2 * bend_gradient
        + np.roll(bend_gradient, -1, axis=0)
    )
    edge_gradient = (
        -1.5 * (bend_sq / spacing**4 + np.roll(bend_sq / spacing**4, -1))
    )[:, None] * edge / length[:, None]
    gradient += np.roll(edge_gradient, 1, axis=0) - edge_gradient
    return energy, gradient


def optimize_race_line(
    trk,
    centerline,
    dlongs: list[float],
    *,
    margin_feet: float = 5.0,
    iterations: int = 160,
) -> list[float]:
    """Return DLATs at the supplied unique LP DLONGs, inside TRK walls.

    The margin measures clearance from the line's *center* to each outer wall;
    it should include half the car width and any desired safety clearance.
    """
    if len(dlongs) < 8 or margin_feet < 0:
        raise ValueError("Need at least eight LP samples and a nonnegative margin.")
    if any(b <= a for a, b in zip(dlongs, dlongs[1:])):
        raise ValueError("LP DLONG samples must be strictly increasing.")

    centers = []
    normals = []
    lower = []
    upper = []
    for dlong in dlongs:
        section_id, fraction = dlong2sect(trk, dlong)
        section = trk.sects[section_id]
        if section.num_bounds < 2:
            raise ValueError(f"Section {section_id} lacks two outer boundaries.")
        bounds = [getbounddlat(trk, section_id, fraction, i)
                  for i in range(section.num_bounds)]
        lo = min(bounds) / DLAT_PER_FOOT + margin_feet
        hi = max(bounds) / DLAT_PER_FOOT - margin_feet
        if hi <= lo:
            raise ValueError(f"No usable width at DLONG {dlong:.0f}; reduce the margin.")
        x, y, _ = getxyz(trk, dlong, 0, centerline)
        nx, ny, _ = getxyz(trk, dlong, DLAT_PER_FOOT, centerline)
        centers.append((x / DLAT_PER_FOOT, y / DLAT_PER_FOOT))
        normals.append(((nx - x) / DLAT_PER_FOOT, (ny - y) / DLAT_PER_FOOT))
        lower.append(lo)
        upper.append(hi)

    centers = np.asarray(centers, dtype=float)
    normals = np.asarray(normals, dtype=float)
    lower = np.asarray(lower, dtype=float)
    upper = np.asarray(upper, dtype=float)
    # A few smooth control values govern many LP records. Directly optimizing
    # every record is ill-conditioned: microscopic alternating DLAT changes
    # dominate the discrete curvature gradient.
    count = len(dlongs)
    controls = np.zeros(max(8, (count + 7) // 8), dtype=float)
    phase = np.arange(count, dtype=float) * len(controls) / count
    cell = np.floor(phase).astype(int)
    t = phase - cell
    indices = np.stack([(cell - 1) % len(controls), cell,
                        (cell + 1) % len(controls), (cell + 2) % len(controls)], axis=1)
    weights = np.stack([
        (1 - t)**3 / 6,
        (3*t**3 - 6*t**2 + 4) / 6,
        (-3*t**3 + 3*t**2 + 3*t + 1) / 6,
        t**3 / 6,
    ], axis=1)

    def evaluate(values):
        unconstrained = np.sum(values[indices] * weights, axis=1)
        offsets = np.clip(unconstrained, lower, upper)
        energy, point_gradient = _energy_and_gradient(
            centers + normals * offsets[:, None]
        )
        offset_gradient = np.sum(point_gradient * normals, axis=1)
        offset_gradient[unconstrained != offsets] = 0
        control_gradient = np.zeros(len(controls), dtype=float)
        for j in range(4):
            np.add.at(control_gradient, indices[:, j], offset_gradient * weights[:, j])
        return energy, control_gradient, offsets

    energy, gradient, offsets = evaluate(controls)
    for _ in range(iterations):
        direction = -gradient
        for _ in range(3):
            direction = (np.roll(direction, 1) + 2 * direction
                         + np.roll(direction, -1)) * 0.25
        # A fixed maximum displacement keeps optimization predictable across
        # tracks with very different section lengths and corner radii.
        scale = float(np.max(np.abs(direction)))
        if scale < 1e-12:
            break
        direction /= scale
        step = min(2.0, float(np.max(upper - lower)) * 0.25)
        improved = False
        for _ in range(12):
            candidate = controls + step * direction
            candidate = (np.roll(candidate, 1) + 2 * candidate
                         + np.roll(candidate, -1)) * 0.25
            if np.max(np.abs(candidate - controls)) < 1e-5:
                break
            candidate_energy, candidate_gradient, candidate_offsets = evaluate(candidate)
            if candidate_energy < energy - 1e-10:
                controls, energy, gradient, offsets = (
                    candidate, candidate_energy, candidate_gradient, candidate_offsets
                )
                improved = True
                break
            step *= 0.5
        if not improved:
            break

    if not np.all(np.isfinite(offsets)):
        raise ValueError("Optimizer produced nonfinite DLAT values.")
    return (offsets * DLAT_PER_FOOT).tolist()
