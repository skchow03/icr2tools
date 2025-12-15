"""Geometry helpers for SG preview logic.

These functions operate on track/world coordinates only and avoid Qt types.
"""
from __future__ import annotations

import math
from typing import Tuple

from sg_viewer.models.sg_model import SectionPreview

Point = Tuple[float, float]


def curve_angles(
    start: Point,
    end: Point,
    center: Point,
    radius: float,
) -> tuple[float, float, float, float]:
    """Compute SG curve angles based on geometry.

    The returned tuple matches SG format expectations using world coordinates.
    Each component is multiplied by the sign of ``radius`` (positive for left
    turns, negative for right turns).
    """

    cx, cy = center
    sx, sy = start
    ex, ey = end
    sign = 1 if radius >= 0 else -1

    sang1 = (cy - sy) * sign
    sang2 = (sx - cx) * sign
    eang1 = (cy - ey) * sign
    eang2 = (ex - cx) * sign

    return sang1, sang2, eang1, eang2


def heading_for_endpoint(
    section: SectionPreview, endtype: str
) -> tuple[float, float] | None:
    """Return a unit heading vector for a section endpoint.

    The heading is expressed in track/world coordinates, pointing outwards from
    the specified endpoint. ``endtype`` must be ``"start"`` or ``"end"``.
    """

    heading = section.start_heading if endtype == "start" else section.end_heading
    if heading is not None:
        hx, hy = heading
    else:
        dx = section.end[0] - section.start[0]
        dy = section.end[1] - section.start[1]
        length = math.hypot(dx, dy)
        if length <= 0:
            return None
        hx, hy = dx / length, dy / length

    if endtype == "start":
        return (-hx, -hy)
    return (hx, hy)


def distance_to_polyline(point: Point, polyline: list[Point]) -> float:
    """Return the shortest distance from ``point`` to a polyline.

    The polyline is a list of points in world coordinates. If fewer than two
    points are provided, ``inf`` is returned.
    """

    if len(polyline) < 2:
        return float("inf")

    px, py = point
    min_dist_sq = float("inf")

    for (x1, y1), (x2, y2) in zip(polyline, polyline[1:]):
        dx = x2 - x1
        dy = y2 - y1
        if dx == dy == 0:
            continue
        t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        proj_x = x1 + t * dx
        proj_y = y1 + t * dy
        dist_sq = (px - proj_x) ** 2 + (py - proj_y) ** 2
        if dist_sq < min_dist_sq:
            min_dist_sq = dist_sq

    return math.sqrt(min_dist_sq)
