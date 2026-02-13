from __future__ import annotations

import math
from dataclasses import replace
from typing import Tuple

from sg_viewer.geometry.curve_solver import _project_point_along_heading
from sg_viewer.geometry.curve_solver import _solve_curve_drag as _solve_curve_drag_util
from sg_viewer.geometry.picking import project_point_to_segment
from sg_viewer.model.sg_model import SectionPreview

Point = Tuple[float, float]


def solve_curve_drag(
    sect: SectionPreview,
    start: Point,
    end: Point,
    tolerance: float = 1.0,
) -> SectionPreview | None:
    """Solve a dragged curve section within ``tolerance`` inches."""

    return _solve_curve_drag_util(sect, start, end, tolerance)


def distance_to_polyline(point: Point, polyline: list[Point]) -> float:
    """Return the shortest distance from ``point`` to a polyline."""

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


def project_point_to_polyline(point: Point, polyline: list[Point]) -> Point | None:
    if len(polyline) < 2:
        return None

    best_point: Point | None = None
    best_distance_sq = float("inf")
    for start, end in zip(polyline, polyline[1:]):
        projection = project_point_to_segment(point, start, end)
        if projection is None:
            continue
        dx = projection[0] - point[0]
        dy = projection[1] - point[1]
        distance_sq = dx * dx + dy * dy
        if distance_sq < best_distance_sq:
            best_distance_sq = distance_sq
            best_point = projection

    return best_point


def project_point_along_heading(
    origin: Point, heading: tuple[float, float] | None, target: Point
) -> Point | None:
    return _project_point_along_heading(origin, heading, target)


def update_straight_endpoints(
    section: SectionPreview, start: Point, end: Point
) -> SectionPreview:
    length = math.hypot(end[0] - start[0], end[1] - start[1])
    return replace(section, start=start, end=end, length=length)


def translate_section(section: SectionPreview, dx: float, dy: float) -> SectionPreview:
    start = (section.start[0] + dx, section.start[1] + dy)
    end = (section.end[0] + dx, section.end[1] + dy)
    center = section.center
    if center is not None:
        center = (center[0] + dx, center[1] + dy)
    return replace(section, start=start, end=end, center=center)
