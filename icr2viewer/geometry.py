"""Utilities for sampling TRK data into drawable geometry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

import numpy as np

from icr2_core.trk.trk_utils import get_cline_pos, getxyz
from icr2_core.trk.trk_classes import TRKFile


Point3D = Tuple[float, float, float]
Segment = Tuple[Point3D, Point3D]


@dataclass
class TrackWireframe:
    """Wireframe representation of a sampled track surface."""

    segments: List[Segment]
    bounds: Tuple[float, float, float, float, float, float] | None
    centerline: List[Point3D]


_DEFAULT_LONGITUDINAL = 180
_DEFAULT_LATERAL = 24


def build_track_wireframe(
    trk: TRKFile,
    *,
    num_longitudinal: int = _DEFAULT_LONGITUDINAL,
    num_lateral: int = _DEFAULT_LATERAL,
) -> TrackWireframe:
    """Sample the TRK surface and build a wireframe for rendering.

    Parameters
    ----------
    trk:
        Parsed TRK file to sample.
    num_longitudinal:
        Number of samples to take along the track (DLONG direction).
    num_lateral:
        Number of samples to take across the track width (DLAT direction).
    """

    if trk is None:
        return TrackWireframe([], None, [])

    if trk.trklength <= 0:
        return TrackWireframe([], None, [])

    cline = get_cline_pos(trk)
    if not cline:
        return TrackWireframe([], None, [])

    # Determine lateral sampling range from the available cross-sections.
    dlat_min = float(np.min(trk.xsect_dlats)) if len(trk.xsect_dlats) else -2000.0
    dlat_max = float(np.max(trk.xsect_dlats)) if len(trk.xsect_dlats) else 2000.0

    if dlat_min == dlat_max:
        spread = max(abs(dlat_min), 2000.0)
        dlat_min = -spread
        dlat_max = spread

    num_lateral = max(num_lateral, 4)
    num_longitudinal = max(num_longitudinal, 16)

    dlat_values = np.linspace(dlat_min, dlat_max, num=num_lateral)
    dlong_values = np.linspace(0.0, float(trk.trklength), num=num_longitudinal, endpoint=False)

    rows: List[List[Point3D]] = []
    points: List[Point3D] = []

    for dlong in dlong_values:
        row: List[Point3D] = []
        for dlat in dlat_values:
            try:
                x, y, z = getxyz(trk, float(dlong), float(dlat), cline)
            except Exception:
                x = y = z = 0.0
            point = (float(x), float(y), float(z))
            row.append(point)
            points.append(point)
        rows.append(row)

    # Close the loop by appending a final row at the end of the track length.
    closing_row: List[Point3D] = []
    for dlat in dlat_values:
        try:
            x, y, z = getxyz(trk, float(trk.trklength), float(dlat), cline)
        except Exception:
            x = y = z = 0.0
        point = (float(x), float(y), float(z))
        closing_row.append(point)
        points.append(point)
    rows.append(closing_row)

    segments: List[Segment] = []
    num_rows = len(rows)
    num_cols = len(dlat_values)

    # Segments along the length of the track (connecting rows).
    for i in range(num_rows - 1):
        row = rows[i]
        next_row = rows[i + 1]
        for j in range(num_cols):
            segments.append((row[j], next_row[j]))

    # Wrap the final row back to the first to close the loop.
    first_row = rows[0]
    last_row = rows[-1]
    for j in range(num_cols):
        segments.append((last_row[j], first_row[j]))

    # Segments across the width of the track (within each row).
    for row in rows[:-1]:
        for j in range(num_cols - 1):
            segments.append((row[j], row[j + 1]))

    # Compute centerline for highlighting (use mid DLAT sample).
    center_index = num_cols // 2
    centerline: List[Point3D] = [row[center_index] for row in rows[:-1]]
    centerline.append(centerline[0])

    bounds = None
    if points:
        xs, ys, zs = zip(*points)
        bounds = (
            float(min(xs)),
            float(max(xs)),
            float(min(ys)),
            float(max(ys)),
            float(min(zs)),
            float(max(zs)),
        )

    return TrackWireframe(segments, bounds, centerline)
