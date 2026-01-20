from __future__ import annotations

from typing import Tuple

from sg_viewer.geometry.picking import project_point_to_segment

Point = Tuple[float, float]


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
