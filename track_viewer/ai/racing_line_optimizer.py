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
            # Ground can be paved on BOTH sides of a pit wall. A boundary is
            # impassable even if the surface type does not change there.
            for wall_lo, wall_hi in zip(bounds, bounds[1:]):
                if split_edge is not None and (
                    (pit_side == "left" and wall_lo >= split_edge) or
                    (pit_side == "right" and wall_hi <= split_edge)
                ):
                    continue
                lo = max(raw_lo, wall_lo) / DLAT_PER_FOOT + margin_feet
                hi = min(raw_hi, wall_hi) / DLAT_PER_FOOT - margin_feet
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

        ranked = sorted(candidates, key=score)
        if (pit_side == "auto" and previous is None and len(ranked) > 1
                and abs(score(ranked[0]) - score(ranked[1])) < 1e-8):
            raise ValueError(
                "Existing LP line cannot distinguish sides of a wall; "
                "choose the pit side explicitly."
            )
        chosen = ranked[0]
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
                  corner_width_pct=75, apex_position_pct=60,
                  return_exit_signs=False):
    """Plan linked turn entries, apexes and exits around the whole lap."""
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

    corners = []
    sharpnesses = []
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
        # Start the setup farther upstream so the heading can build gradually
        # instead of making most of the turn immediately before the apex.
        lead = min(max(6, 3 * look), max(6, length // 2), n // 6)
        corners.append((start, start + length - 1, start + apex_at,
                        int(sign), lead, float(np.sum(
                            np.abs(curvature[window]) * distance[window]))))
        sharpnesses.append(float(np.max(magnitudes)))

    if not corners:
        baseline = ((lower + upper) * 0.5, np.full(n, 0.0001))
        return (*baseline, np.zeros(n)) if return_exit_signs else baseline
    planned = _linked_corner_targets(corners, lower, upper, corner_width_pct,
                                     sharpnesses)
    if return_exit_signs:
        return (*planned, _exit_turn_signs(corners, n))
    return planned


def _exit_turn_signs(corners, n):
    """Guard exits and following straights until the next corner's entry."""
    signs = np.zeros(n)
    for i, (_, _, apex, sign, _, _) in enumerate(corners):
        next_start, _, _, _, next_lead, _ = corners[
            (i + 1) % len(corners)
        ]
        if i == len(corners) - 1:
            next_start += n
        finish = next_start - next_lead
        for position in range(apex, max(apex, finish) + 1):
            signs[position % n] = sign
    return signs


def _linked_corner_targets(corners, lower, upper, corner_width_pct,
                           sharpnesses=None):
    """Join each apex to its neighbours with one transition per straight.

    Corners are (start, end, apex, signed direction, lead, turn severity).
    Coordinates can cross the lap seam; anchors are interpolated periodically.
    """
    n = len(lower)
    use = corner_width_pct / 200.0
    anchors = []
    for i, (start, end, apex, sign, lead, severity) in enumerate(corners):
        # Tight turns borrow more width at the apex than at entry or exit,
        # while the width control remains effective even at low values.
        sharpness = sharpnesses[i] if sharpnesses is not None else 0.0
        tightness = np.clip((sharpness - 0.008) / 0.02, 0, 1)
        apex_use = use + (0.5 - use) * tightness * (corner_width_pct / 100)
        anchors.append((apex % n, 0.5 + sign * apex_use))
        next_start, _, _, next_sign, next_lead, next_severity = corners[
            (i + 1) % len(corners)
        ]
        if i == len(corners) - 1:
            next_start += n
        gap = next_start - end - 1
        outgoing = 0.5 - sign * use
        incoming = 0.5 - next_sign * use
        if gap <= lead + next_lead:
            # A short gap has room for one handoff, not two independent
            # outside targets. Bias it toward the entry of the next turn.
            position = end + (gap + 1) // 2
            fraction = ((severity * outgoing + 1.2 * next_severity * incoming)
                        / (severity + 1.2 * next_severity))
            anchors.append((position % n, fraction))
        else:
            anchors.append(((end + lead) % n, outgoing))
            anchors.append(((next_start - next_lead) % n, incoming))

    # Duplicate anchors can occur at the seam or in a zero-length gap.
    # Combine them once before interpolating to avoid division by zero.
    grouped = {}
    for position, fraction in anchors:
        grouped.setdefault(position, []).append(fraction)
    anchors = sorted((position, float(np.mean(values)))
                     for position, values in grouped.items())
    positions = np.array([anchor[0] for anchor in anchors], dtype=int)
    fractions = np.array([anchor[1] for anchor in anchors])
    next_positions = np.r_[positions[1:], positions[0] + n]
    next_fractions = np.r_[fractions[1:], fractions[0]]
    fraction = np.empty(n)
    for start, end, first, last in zip(positions, next_positions,
                                       fractions, next_fractions):
        indices = np.arange(start, end)
        t = (indices - start) / (end - start)
        # Zero lateral slope AND second derivative at each anchor. The old
        # cubic easing had nonzero lateral curvature at the apex, which could
        # cancel the road's curvature and make the path look straight there.
        smooth = t**3 * (10 + t * (-15 + 6 * t))
        fraction[indices % n] = first + smooth * (last - first)

    target_weight = np.ones(n)
    for _, _, apex, _, lead, _ in corners:
        for step in range(-lead, lead + 1):
            index = (apex + step) % n
            target_weight[index] = max(target_weight[index],
                                       1 + 9 * (1 - abs(step) / (lead + 1)))
    return lower + fraction * (upper - lower), target_weight


def _between_record_constraints(trk, centerline, dlongs, reference_dlats,
                                margin_feet, pit_side, centers, normals):
    """Constrain the drawn XY chord between each pair of LP records.

    Check quarter points and both sides of every TRK section transition.
    Bounds within a section vary linearly in DLAT, while chords in curved
    sections need extra checks because they cut inside the centerline arc.
    """
    lap = float(getattr(trk, "trklength", 0) or 0)
    if lap <= dlongs[-1]:
        return []
    originals = np.asarray(dlongs, dtype=float)
    extra = []
    for i, start in enumerate(originals):
        end = originals[i + 1] if i + 1 < len(originals) else originals[0] + lap
        for t in (0.25, 0.5, 0.75):
            extra.append((start + t * (end - start)) % lap)
    if hasattr(trk.sects[0], "start_dlong"):
        for section in trk.sects:
            boundary = float(section.start_dlong)
            if not 0 <= boundary < lap:
                continue
            before = float(originals[np.searchsorted(originals, boundary) - 1]) \
                if boundary > originals[0] else float(originals[-1] - lap)
            epsilon = min(0.001, (boundary - before) * 0.25)
            if epsilon > 0:
                extra.append(boundary - epsilon if boundary >= epsilon
                             else lap + boundary - epsilon)
            if boundary not in originals and boundary > 0:
                extra.append(boundary)
    extra = sorted(set(x for x in extra if x not in originals and x < lap))
    if not extra:
        return []
    base_reference = (np.asarray(reference_dlats, dtype=float) / DLAT_PER_FOOT
                      if reference_dlats is not None else np.zeros(len(originals)))
    extended_x = np.r_[originals[-1] - lap, originals, originals[0] + lap]
    extended_y = np.r_[base_reference[-1], base_reference, base_reference[0]]
    all_points = sorted(set(dlongs) | set(extra))
    all_refs = np.interp(all_points, extended_x, extended_y) * DLAT_PER_FOOT
    lo, hi = _paved_corridor(trk, all_points, all_refs.tolist(),
                             margin_feet, pit_side)
    at = {point: index for index, point in enumerate(all_points)}
    constraints = []
    for point in extra:
        position = point if point >= originals[0] else point + lap
        i = int(np.searchsorted(originals, position, side="right") - 1)
        j = (i + 1) % len(originals)
        end = originals[j] if j > i else originals[j] + lap
        t = (position - originals[i]) / (end - originals[i])
        x, y, _ = getxyz(trk, point, 0, centerline)
        nx, ny, _ = getxyz(trk, point, DLAT_PER_FOOT, centerline)
        center = np.array((x, y)) / DLAT_PER_FOOT
        normal = (np.array((nx, ny)) - (x, y)) / DLAT_PER_FOOT
        normal_size = float(np.dot(normal, normal))
        if normal_size < 1e-8:
            raise ValueError(f"Invalid track normal near DLONG {point:.0f}.")
        a = (1 - t) * float(np.dot(normals[i], normal)) / normal_size
        b = t * float(np.dot(normals[j], normal)) / normal_size
        chord_center = (1 - t) * centers[i] + t * centers[j]
        constant = float(np.dot(chord_center - center, normal)) / normal_size
        constraints.append((i, j, a, b, constant,
                            lo[at[point]], hi[at[point]], point))
    return constraints


def _enforce_between_record_constraints(offsets, lower, upper, constraints):
    """Project LP offsets until their XY chords clear the sampled walls."""
    if not constraints:
        return offsets
    offsets = offsets.copy()
    for _ in range(300):
        worst = 0.0
        for i, j, a, b, constant, lo, hi, _ in constraints:
            value = a * offsets[i] + b * offsets[j] + constant
            correction = min(max(value, lo), hi) - value
            worst = max(worst, abs(correction))
            if correction:
                scale = correction / (a * a + b * b)
                offsets[i] = np.clip(offsets[i] + a * scale, lower[i], upper[i])
                offsets[j] = np.clip(offsets[j] + b * scale, lower[j], upper[j])
        if worst < 1e-5:
            break
    for i, j, a, b, constant, lo, hi, point in constraints:
        value = a * offsets[i] + b * offsets[j] + constant
        if value < lo - 1e-4 or value > hi + 1e-4:
            raise ValueError(
                f"LP path cannot clear a wall near DLONG {point:.0f}; "
                "use a denser LP grid or inspect the split."
            )
    return offsets


def _energy_and_gradient(points: np.ndarray,
                         jerk_spacing: float | None = None) -> tuple[float, np.ndarray]:
    """Penalize bending and abrupt curvature changes over a closed lap."""
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
    # The third difference tracks changes in the curvature vector. This
    # discourages a sudden rotation followed by a nearly straight apex.
    third = (np.roll(points, -2, axis=0) - 3 * np.roll(points, -1, axis=0)
             + 3 * points - np.roll(points, 1, axis=0))
    nominal_spacing = max(float(jerk_spacing if jerk_spacing is not None
                                else np.median(length)), 1.0)
    jerk_scale = 25.0 / nominal_spacing**5
    energy += jerk_scale * float(np.sum(third * third))
    gradient += 2 * jerk_scale * (
        np.roll(third, 2, axis=0) - 3 * np.roll(third, 1, axis=0)
        + 3 * third - np.roll(third, -1, axis=0)
    )
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
    side_preference: str = "none",
    side_preference_pct: int = 0,
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
    if side_preference not in {"none", "left", "right"}:
        raise ValueError("Side preference must be None, Left, or Right.")
    if not 0 <= side_preference_pct <= 100:
        raise ValueError("Side preference must be between 0 and 100 percent.")

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
    jerk_spacing = float(np.median(np.linalg.norm(
        np.roll(centers, -1, axis=0) - centers, axis=1
    )))
    between_records = _between_record_constraints(
        trk, centerline, dlongs, reference_dlats, margin_feet, pit_side,
        centers, normals,
    )
    targets, target_weight, exit_signs = _apex_targets(
        centers, lower, upper, lookahead_feet, corner_width_pct,
        apex_position_pct, return_exit_signs=True,
    )
    side_target = None
    if side_preference != "none" and side_preference_pct > 0:
        # Treat the preference as the desired lane position, not merely a
        # low-weight optimization hint. 0% is the normal racing-line target;
        # 100% is the nearest legal edge after the user's clearance margin.
        preference = side_preference_pct / 100.0
        preferred_edge = upper if side_preference == "left" else lower
        side_target = targets + preference * (preferred_edge - targets)
        # Keep a little room for the spline/constraint projection. The hard
        # lower/upper corridor remains the final authority.
        side_target = np.clip(side_target, lower, upper)
        targets = side_target
        # A passing line should deliberately hold its lane even through
        # corners, rather than allowing apex weights to pull it back onto the
        # same RACE trajectory. Increase target authority with preference.
        target_weight = np.maximum(
            target_weight, 1.0 + 19.0 * preference
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
            centers + normals * offsets[:, None], jerk_spacing
        )
        offset_gradient = np.sum(point_gradient * normals, axis=1)
        if np.any(exit_signs):
            points = centers + normals * offsets[:, None]
            second = (np.roll(points, -1, axis=0) - 2 * points
                      + np.roll(points, 1, axis=0))
            # Signed curvature proxy: positive means the same steering
            # direction as the corner. Penalize a reversal on its exit.
            signed_bend = (exit_signs * np.sum(second * normals, axis=1)
                           / max(jerk_spacing, 1.0)**2)
            wrong_way = np.minimum(signed_bend + 0.0003, 0.0)
            wrong_way[exit_signs == 0] = 0
            penalty = 500.0 / (0.02**2 * count)
            energy += penalty * float(np.sum(wrong_way**2))
            bend_gradient = (2 * penalty * wrong_way * exit_signs)[:, None] \
                * normals / max(jerk_spacing, 1.0)**2
            point_penalty_gradient = (
                np.roll(bend_gradient, 1, axis=0) - 2 * bend_gradient
                + np.roll(bend_gradient, -1, axis=0)
            )
            offset_gradient += np.sum(point_penalty_gradient * normals, axis=1)
        # Apex targets prevent the smoothest path from simply following the
        # outside edge through a whole bend. Small baseline weight applies on
        # straights; turn targets have much higher weight.
        difference = (offsets - targets) / np.maximum(upper - lower, 1.0)
        energy += 5.0 * float(np.mean(target_weight * difference**2))
        offset_gradient += (
            10 * target_weight * difference / np.maximum(upper - lower, 1.0) / count
        )
        # Include chord/wall clearance in the optimizer, so the final hard
        # projection is a small safety correction rather than a new kink.
        if between_records:
            wall_energy = 0.0
            wall_gradient = np.zeros(count)
            for i, j, a, b, constant, lo, hi, _ in between_records:
                value = a * offsets[i] + b * offsets[j] + constant
                violation = value - min(max(value, lo), hi)
                wall_energy += violation**2
                wall_gradient[i] += 2 * violation * a
                wall_gradient[j] += 2 * violation * b
            scale = 20.0 / len(between_records)
            energy += scale * wall_energy
            offset_gradient += scale * wall_gradient
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
    offsets = _enforce_between_record_constraints(
        offsets, lower, upper, between_records
    )
    return (offsets * DLAT_PER_FOOT).tolist()
