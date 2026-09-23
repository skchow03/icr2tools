"""Pavement-aware candidate racing line on an existing ICR2 LP grid.

The path follows an apex plan and minimizes bending within the chosen paved
corridor. This is a geometric candidate, not a minimum-lap-time solution.
"""

from __future__ import annotations

import numpy as np

from icr2_core.trk.trk_utils import dlong2sect, getbounddlat, getgrounddlat, getxyz


DLAT_PER_FOOT = 6000.0
PAVED_GROUND_TYPES = frozenset(range(32, 55, 2))  # concrete, asphalt, paint


def _paved_intervals(trk, section_id: int, fraction: float) -> list[tuple[float, float]]:
    """Return connected paved DLAT intervals, ordered from right to left."""
    section = trk.sects[section_id]
    if section.num_bounds < 2 or section.ground_fsects < 1:
        return []
    left = max(getbounddlat(trk, section_id, fraction, i)
               for i in range(section.num_bounds))
    strips = []
    # The ground f-sections run from the left boundary toward the right.
    # This is the same strip construction used by build_ground_surface_mesh.
    for i in range(section.ground_fsects - 1, -1, -1):
        right = getgrounddlat(trk, section_id, fraction, i)
        if section.ground_type[i] in PAVED_GROUND_TYPES:
            strips.append((min(left, right), max(left, right)))
        left = right
    strips.sort()
    merged = []
    for lo, hi in strips:
        if merged and lo <= merged[-1][1] + 1.0:
            merged[-1] = (merged[-1][0], max(hi, merged[-1][1]))
        else:
            merged.append((lo, hi))
    return merged


def _paved_corridor(trk, dlongs, reference_dlats, margin_feet, pit_side="auto"):
    if pit_side not in {"auto", "left", "right"}:
        raise ValueError("Pit side must be Auto, Left, or Right.")
    lower, upper = [], []
    previous = None
    for i, dlong in enumerate(dlongs):
        section_id, fraction = dlong2sect(trk, dlong)
        section = trk.sects[section_id]
        bounds = sorted(getbounddlat(trk, section_id, fraction, j)
                        for j in range(section.num_bounds))
        # Extra boundaries can mark a split, but do not encode which branch
        # is the pit. When specified, keep the racing side of the innermost
        # pit-side boundary. Ground types still determine usable pavement.
        split = len(bounds) > 2
        split_edge = (bounds[-2] if pit_side == "left" else bounds[1]) \
            if split and pit_side != "auto" else None
        candidates = []
        for raw_lo, raw_hi in _paved_intervals(trk, section_id, fraction):
            if split_edge is not None:
                if pit_side == "left":
                    raw_hi = min(raw_hi, split_edge)
                else:
                    raw_lo = max(raw_lo, split_edge)
            lo = raw_lo / DLAT_PER_FOOT + margin_feet
            hi = raw_hi / DLAT_PER_FOOT - margin_feet
            if hi > lo:
                candidates.append((lo, hi))
        if not candidates:
            if split_edge is not None:
                raise ValueError(
                    f"Pit-side choice leaves no paved racing corridor at DLONG "
                    f"{dlong:.0f}; try Auto, the other side, or less clearance."
                )
            raise ValueError(
                f"No paved corridor wide enough at DLONG {dlong:.0f}; "
                "reduce the clearance or inspect the TRK ground types."
            )
        reference = reference_dlats[i] / DLAT_PER_FOOT if reference_dlats else 0.0

        def score(interval):
            lo, hi = interval
            distance = max(lo - reference, 0, reference - hi)
            if previous is None:
                return distance
            overlap = min(hi, previous[1]) - max(lo, previous[0])
            continuity = 0 if overlap >= 0 else 1000 + 10 * -overlap
            previous_center = (previous[0] + previous[1]) * 0.5
            return 3 * distance + continuity + max(
                lo - previous_center, 0, previous_center - hi
            )

        chosen = min(candidates, key=score)
        if previous is not None and min(chosen[1], previous[1]) < max(chosen[0], previous[0]):
            raise ValueError(
                f"Paved corridor is discontinuous at DLONG {dlong:.0f}; "
                "inspect pavement or existing RACE line."
            )
        lower.append(chosen[0])
        upper.append(chosen[1])
        previous = chosen
    if min(upper[0], upper[-1]) < max(lower[0], lower[-1]):
        raise ValueError("Paved corridor is discontinuous at the start/finish seam.")
    return np.asarray(lower), np.asarray(upper)


def _apex_targets(centers, lower, upper, lookahead_feet=60.0,
                  corner_width_pct=75, apex_position_pct=60):
    """Plan outside/inside/outside targets around sustained signed turns."""
    n = len(centers)
    spacing = float(np.median(np.linalg.norm(
        np.roll(centers, -1, axis=0) - centers, axis=1
    )))
    look = max(2, min(n // 12, round(lookahead_feet / max(spacing, 1.0))))
    incoming = centers - np.roll(centers, look, axis=0)
    outgoing = np.roll(centers, -look, axis=0) - centers
    cross = incoming[:, 0] * outgoing[:, 1] - incoming[:, 1] * outgoing[:, 0]
    dot = np.sum(incoming * outgoing, axis=1)
    distance = np.maximum(np.linalg.norm(incoming, axis=1), 1.0)
    curvature = np.arctan2(cross, dot) / distance
    for _ in range(2):
        curvature = (np.roll(curvature, 1) + 2 * curvature
                     + np.roll(curvature, -1)) * 0.25
    threshold = max(0.00025, 0.12 * float(np.max(np.abs(curvature))))
    signs = np.where(curvature > threshold, 1,
                     np.where(curvature < -threshold, -1, 0))
    # Tiny near-zero gaps inside a bend should not become separate corners.
    for _ in range(3):
        gaps = (signs == 0) & (np.roll(signs, 1) == np.roll(signs, -1))
        signs[gaps] = np.roll(signs, 1)[gaps]

    baseline = (lower + upper) * 0.5
    weighted_target = 0.0001 * baseline
    target_weight = np.full(n, 0.0001)
    starts = [i for i in range(n) if signs[i] and signs[i] != signs[(i - 1) % n]]
    for start in starts:
        sign = signs[start]
        length = 0
        while length < n and signs[(start + length) % n] == sign:
            length += 1
        if length < 8 or length > 0.7 * n:
            continue
        window = np.array([(start + j) % n for j in range(length)])
        if np.sum(np.abs(curvature[window]) * distance[window]) < 0.08:
            continue
        magnitudes = np.abs(curvature[window])
        plateau = np.flatnonzero(magnitudes >= 0.9 * np.max(magnitudes))
        desired_apex = apex_position_pct / 100 * length
        peak_at = plateau[np.argmin(np.abs(plateau - desired_apex))]
        apex_at = int(round(0.4 * peak_at + 0.6 * desired_apex))
        apex_at = max(0, min(length - 1, apex_at))
        lead = min(max(6, 2 * look), max(6, length // 2), n // 6)
        entry, apex, exit_at = -lead, apex_at, length - 1 + lead
        for position in range(entry, exit_at + 1):
            i = (start + position) % n
            if position <= apex:
                t = (position - entry) / max(1, apex - entry)
                blend = t * t * (3 - 2 * t)
            else:
                t = (position - apex) / max(1, exit_at - apex)
                blend = 1 - t * t * (3 - 2 * t)
            width = upper[i] - lower[i]
            half_use = corner_width_pct / 200 * width
            midpoint = (lower[i] + upper[i]) * 0.5
            inside = midpoint + sign * half_use
            outside = midpoint - sign * half_use
            desired = outside * (1 - blend) + inside * blend
            weight = 1.0 + 2.0 * blend
            weighted_target[i] += weight * desired
            target_weight[i] += weight
    return weighted_target / target_weight, target_weight


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
    reference_dlats: list[float] | None = None,
    pit_side: str = "auto",
    lookahead_feet: float = 60.0,
    corner_width_pct: int = 75,
    apex_position_pct: int = 60,
    iterations: int = 160,
) -> list[float]:
    """Return DLATs at unique LP DLONGs within the continuous paved corridor.

    The margin measures clearance from the car center to the pavement edge;
    it should include half the car width and any desired safety clearance.
    """
    if len(dlongs) < 8 or margin_feet < 0:
        raise ValueError("Need at least eight LP samples and a nonnegative margin.")
    if any(b <= a for a, b in zip(dlongs, dlongs[1:])):
        raise ValueError("LP DLONG samples must be strictly increasing.")
    if not 10 <= lookahead_feet <= 500:
        raise ValueError("Lookahead must be between 10 and 500 feet.")
    if not 0 <= corner_width_pct <= 100:
        raise ValueError("Corner width must be between 0 and 100 percent.")
    if not 40 <= apex_position_pct <= 80:
        raise ValueError("Apex position must be between 40 and 80 percent.")

    if reference_dlats is not None and len(reference_dlats) != len(dlongs):
        raise ValueError("Reference RACE DLAT count does not match the LP grid.")
    lower, upper = _paved_corridor(
        trk, dlongs, reference_dlats, margin_feet, pit_side
    )
    centers = []
    normals = []
    for dlong in dlongs:
        x, y, _ = getxyz(trk, dlong, 0, centerline)
        nx, ny, _ = getxyz(trk, dlong, DLAT_PER_FOOT, centerline)
        centers.append((x / DLAT_PER_FOOT, y / DLAT_PER_FOOT))
        normals.append(((nx - x) / DLAT_PER_FOOT, (ny - y) / DLAT_PER_FOOT))

    centers = np.asarray(centers, dtype=float)
    normals = np.asarray(normals, dtype=float)
    targets, target_weight = _apex_targets(
        centers, lower, upper, lookahead_feet, corner_width_pct,
        apex_position_pct,
    )
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
    controls[:] = targets[np.round(np.arange(len(controls)) * count /
                                    len(controls)).astype(int) % count]

    def evaluate(values):
        unconstrained = np.sum(values[indices] * weights, axis=1)
        offsets = np.clip(unconstrained, lower, upper)
        energy, point_gradient = _energy_and_gradient(
            centers + normals * offsets[:, None]
        )
        offset_gradient = np.sum(point_gradient * normals, axis=1)
        # Apex targets prevent the smoothest path from simply following the
        # outside edge through a whole bend. Small baseline weight applies on
        # straights; turn targets have much higher weight.
        difference = (offsets - targets) / np.maximum(upper - lower, 1.0)
        energy += 5.0 * float(np.mean(target_weight * difference**2))
        offset_gradient += (
            10 * target_weight * difference / np.maximum(upper - lower, 1.0) / count
        )
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
