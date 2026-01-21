from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Tuple

from sg_viewer.sg_preview.model import Point, SgPreviewModel
from sg_viewer.sg_preview.transform import ViewTransform


@dataclass(frozen=True)
class HitResult:
    kind: str
    fsect_id: Optional[int]
    object_id: Optional[int]
    world_pos: Tuple[float, float]


def hit_test(
    model: SgPreviewModel,
    transform: ViewTransform,
    screen_pos: Tuple[float, float],
    tolerance_px: float = 6.0,
) -> HitResult:
    world_pos = transform.screen_to_world(screen_pos)
    if model is None:
        return HitResult("none", None, None, world_pos)

    tolerance_world = _tolerance_world(transform, tolerance_px)

    closest = None
    closest_dist = None
    for fsect in model.fsects:
        for boundary in fsect.boundaries:
            dist = _distance_to_polyline(world_pos, boundary.points)
            if dist is None:
                continue
            if closest_dist is None or dist < closest_dist:
                closest_dist = dist
                closest = HitResult("boundary", fsect.id, boundary.id, world_pos)

    if closest is not None and closest_dist is not None and closest_dist <= tolerance_world:
        return closest

    for fsect in model.fsects:
        for surface in fsect.surfaces:
            if _point_in_polygon(world_pos, surface.outline):
                if surface.holes and any(
                    _point_in_polygon(world_pos, hole) for hole in surface.holes
                ):
                    continue
                return HitResult("surface", fsect.id, surface.id, world_pos)

    return HitResult("none", None, None, world_pos)


def _tolerance_world(transform: ViewTransform, tolerance_px: float) -> float:
    if transform.scale == 0:
        return tolerance_px
    return tolerance_px / transform.scale


def _distance_to_polyline(point: Point, points: list[Point]) -> Optional[float]:
    if len(points) < 2:
        return None
    min_dist = None
    for idx in range(len(points) - 1):
        dist = _distance_to_segment(point, points[idx], points[idx + 1])
        if min_dist is None or dist < min_dist:
            min_dist = dist
    return min_dist


def _distance_to_segment(point: Point, a: Point, b: Point) -> float:
    px, py = point
    ax, ay = a
    bx, by = b
    dx = bx - ax
    dy = by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)

    t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    closest_x = ax + t * dx
    closest_y = ay + t * dy
    return math.hypot(px - closest_x, py - closest_y)


def _point_in_polygon(point: Point, polygon: list[Point]) -> bool:
    if len(polygon) < 3:
        return False
    x, y = point
    inside = False
    j = len(polygon) - 1
    for i, (xi, yi) in enumerate(polygon):
        xj, yj = polygon[j]
        intersects = (yi > y) != (yj > y) and (
            x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi
        )
        if intersects:
            inside = not inside
        j = i
    return inside
