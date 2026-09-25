"""Localized periodic lateral dragging for existing LP records."""

from __future__ import annotations

import numpy as np


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
    """Displace an LP point and its neighbors with a C2 periodic falloff.

    All coordinates and legal bounds use native Papyrus units except the user-
    facing influence distance in feet. The drag is globally scaled to the
    first reached legal boundary so the curve keeps its shape, rather than
    creating sharp flat clipped sections next to walls.
    """
    values = np.asarray(dlats, dtype=float)
    stations = np.asarray(dlongs, dtype=float)
    low = np.asarray(lower, dtype=float)
    high = np.asarray(upper, dtype=float)
    if values.ndim != 1 or not (len(values) == len(stations) == len(low) == len(high)):
        raise ValueError("LP stations, offsets, and legal corridor must match.")
    if not 0 <= selected_index < len(values):
        raise IndexError("Selected LP record is out of range.")
    radius = float(influence_feet) * 6000.0
    if radius <= 0:
        raise ValueError("Influence distance must be positive.")

    distance = np.abs(stations - stations[selected_index])
    if track_length > 0:
        distance = np.minimum(distance, np.maximum(0.0, track_length - distance))
    t = np.clip(distance / radius, 0.0, 1.0)
    # Quintic smootherstep is C2 at both ends: anchor moves fully, while
    # records at the radius boundary retain position and first two derivatives.
    weight = 1 - (6*t**5 - 15*t**4 + 10*t**3)
    shift = float(requested_delta) * weight
    valid = np.abs(shift) > 1e-9
    alpha = 1.0
    for idx in np.flatnonzero(valid):
        if shift[idx] > 0:
            available = max(0.0, high[idx] - values[idx])
        else:
            available = max(0.0, values[idx] - low[idx])
        alpha = min(alpha, available / abs(shift[idx]))
    # Existing points may have already been outside a newly configured margin;
    # don't teleport those points during a local manual edit.
    return values + alpha * shift
