"""Localized, wall-constrained lateral dragging for an LP racing line."""

from __future__ import annotations

import numpy as np


def nearest_lp_line_anchor(
    screen_xy,
    cursor_xy,
    *,
    tolerance_px: float = 16.0,
) -> int | None:
    """Pick a record from the nearest visible polyline *segment*.

    The LP overlay draws connected segments, not just individual records.
    Picking vertices alone fails when zooming into a long LP interval: the
    user can click on the drawn line while all its vertices are >14 px away.
    Choose the closer endpoint of the nearest segment as the editing anchor.
    """
    points = np.asarray(screen_xy, dtype=float)
    cursor = np.asarray(cursor_xy, dtype=float)
    if (
        points.ndim != 2 or points.shape[1] != 2 or len(points) < 2
        or cursor.shape != (2,)
        or not np.all(np.isfinite(points)) or not np.all(np.isfinite(cursor))
    ):
        return None
    end = np.roll(points, -1, axis=0)
    segment = end - points
    lengths_sq = np.sum(segment * segment, axis=1)
    valid = lengths_sq > 1e-12
    if not np.any(valid):
        return None
    t = np.clip(
        np.sum((cursor - points) * segment, axis=1)
        / np.maximum(lengths_sq, 1e-12),
        0.0, 1.0,
    )
    nearest = points + segment * t[:, None]
    distance_sq = np.sum((nearest - cursor) ** 2, axis=1)
    distance_sq[~valid] = np.inf
    segment_index = int(np.argmin(distance_sq))
    if distance_sq[segment_index] > tolerance_px ** 2:
        return None
    return (
        (segment_index + 1) % len(points)
        if t[segment_index] > 0.5
        else segment_index
    )


def smooth_lateral_drag(
    dlats,
    dlongs,
    selected_index: int,
    requested_delta: float,
    influence_feet: float,
    track_length: float,
    lower,
    upper,
) -> np.ndarray:
    """Move a chosen LP point with a smooth, periodic neighboring deformation.

    Both offset/boundary arrays are native Papyrus units. The user's influence
    distance is in feet. A wall on one side *shortens that side's falloff*
    rather than scaling the entire edit to zero, which previously happened
    when even one neighboring LP sample touched the edge of the pavement.
    """
    values = np.asarray(dlats, dtype=float)
    stations = np.asarray(dlongs, dtype=float)
    low = np.asarray(lower, dtype=float)
    high = np.asarray(upper, dtype=float)
    if (
        values.ndim != 1
        or not (len(values) == len(stations) == len(low) == len(high))
        or not np.all(np.isfinite(values))
        or not np.all(np.isfinite(stations))
        or not np.all(np.isfinite(low))
        or not np.all(np.isfinite(high))
    ):
        raise ValueError("LP stations, offsets, and legal corridor must be finite and match.")
    if not 0 <= selected_index < len(values):
        raise IndexError("Selected LP record is out of range.")
    radius = float(influence_feet) * 6000.0
    if not np.isfinite(radius) or radius <= 0 or track_length <= 0:
        raise ValueError("Influence distance and track length must be positive.")
    delta = float(requested_delta)
    if not np.isfinite(delta):
        raise ValueError("Requested lateral displacement must be finite.")
    if delta == 0:
        return values.copy()

    direction = 1 if delta > 0 else -1
    capacity = (
        high - values if direction > 0 else values - low
    )
    # A point already against the wall must not be dragged farther into it.
    amplitude = min(abs(delta), max(0.0, float(capacity[selected_index])))
    if amplitude <= 1e-9:
        return values.copy()

    # Split the periodic lap at the anchor. Each side is allowed its own
    # influence extent, so one wall-constrained side cannot freeze the other.
    forward = (stations - stations[selected_index]) % track_length
    backward = (stations[selected_index] - stations) % track_length
    on_forward = forward <= backward
    offset = np.zeros(len(values), dtype=float)

    for side, distance in ((on_forward, forward), (~on_forward, backward)):
        included = side & (distance > 0) & (distance < radius)
        support = radius
        if np.any(included):
            phase = np.clip(distance[included] / radius, 0.0, 1.0)
            full_weight = 1.0 - (6*phase**5 - 15*phase**4 + 10*phase**3)
            blocked = (
                amplitude * full_weight
                > np.maximum(0.0, capacity[included]) + 1e-7
            )
            if np.any(blocked):
                # The first obstructed station becomes the endpoint of the
                # quintic bump. The shortened C2 falloff remains legal at
                # every closer station without individually clipping them.
                support = min(support, float(np.min(distance[included][blocked])))
        local = side & (distance > 0) & (distance < support)
        phase = np.clip(distance[local] / support, 0.0, 1.0)
        weights = 1.0 - (6*phase**5 - 15*phase**4 + 10*phase**3)
        offset[local] = amplitude * weights

    offset[selected_index] = amplitude
    return values + direction * offset
