from __future__ import annotations

import math
from typing import Optional, Tuple

from sg_viewer.models.sg_model import Point

Heading = Tuple[float, float]


def clamp_unit(value: float) -> float:
    return max(-1.0, min(1.0, value))


def dot(a: Heading, b: Heading) -> float:
    return a[0] * b[0] + a[1] * b[1]


def cross(a: Heading, b: Heading) -> float:
    return a[0] * b[1] - a[1] * b[0]


def normalize_heading(vec: Heading | None) -> Heading | None:
    if vec is None:
        return None
    length = math.hypot(vec[0], vec[1])
    if length == 0:
        return None
    return (vec[0] / length, vec[1] / length)


def angle_between(a: Heading, b: Heading) -> float:
    return math.acos(clamp_unit(dot(a, b)))


def angle_between_deg(a: Heading, b: Heading) -> float:
    return math.degrees(angle_between(a, b))


def signed_angle_deg(a: Heading, b: Heading) -> float:
    return math.degrees(math.atan2(cross(a, b), clamp_unit(dot(a, b))))


def heading_angle_error(
    original: Heading | None, candidate: Heading | None
) -> float:
    if original is None or candidate is None:
        return 0.0
    return math.acos(clamp_unit(dot(original, candidate)))


def curve_tangent_heading(
    center: Point, point: Point, orientation: float
) -> Heading | None:
    vx = point[0] - center[0]
    vy = point[1] - center[1]
    radius = math.hypot(vx, vy)
    if radius <= 0:
        return None
    tx = orientation * (-vy / radius)
    ty = orientation * (vx / radius)
    return (tx, ty)


def curve_arc_length(center: Point, start: Point, end: Point, radius: float) -> float | None:
    sx = start[0] - center[0]
    sy = start[1] - center[1]
    ex = end[0] - center[0]
    ey = end[1] - center[1]

    dot_value = (sx * ex + sy * ey) / max(radius * radius, 1e-9)
    angle = abs(math.atan2(cross((sx, sy), (ex, ey)), clamp_unit(dot_value)))
    if angle <= 0:
        return None
    return radius * angle


def project_point_along_heading(
    origin: Point, heading: Heading | None, target: Point
) -> Point | None:
    heading_norm = normalize_heading(heading)
    if heading_norm is None:
        return None

    hx, hy = heading_norm
    dx = target[0] - origin[0]
    dy = target[1] - origin[1]
    projection = dx * hx + dy * hy

    return origin[0] + projection * hx, origin[1] + projection * hy


def curve_center_from_fixed_heading(
    fixed_point: Point,
    moving_point: Point,
    fixed_heading: Heading,
    orientation: float,
) -> tuple[Point, float] | None:
    heading_norm = normalize_heading(fixed_heading)
    if heading_norm is None:
        return None

    hx, hy = heading_norm
    normal = (-orientation * hy, orientation * hx)

    dx = moving_point[0] - fixed_point[0]
    dy = moving_point[1] - fixed_point[1]
    dot_value = dx * normal[0] + dy * normal[1]
    if abs(dot_value) <= 1e-9:
        return None

    radius = (dx * dx + dy * dy) / (2.0 * dot_value)
    if radius <= 0:
        return None

    center = (fixed_point[0] + normal[0] * radius, fixed_point[1] + normal[1] * radius)
    return center, radius


def circle_center_from_tangent_headings(
    start: Point,
    start_heading: Heading,
    end: Point,
    end_heading: Heading,
    orientation: float,
) -> tuple[Point, float, float] | None:
    start_norm = normalize_heading(start_heading)
    end_norm = normalize_heading(end_heading)
    if start_norm is None or end_norm is None:
        return None

    ns = (-orientation * start_norm[1], orientation * start_norm[0])
    ne = (-orientation * end_norm[1], orientation * end_norm[0])

    dx = end[0] - start[0]
    dy = end[1] - start[1]

    det = ns[0] * (-ne[1]) - ns[1] * (-ne[0])
    if abs(det) <= 1e-9:
        return None

    ts = (dx * (-ne[1]) - dy * (-ne[0])) / det
    te = (ns[0] * dy - ns[1] * dx) / det

    if ts <= 0 or te <= 0:
        return None

    center = (start[0] + ns[0] * ts, start[1] + ns[1] * ts)
    return center, ts, te


def signed_radius_from_heading(
    heading: Heading | None,
    start: Point,
    center: Point | None,
    radius: float | None,
) -> float | None:
    if heading is None or center is None or radius is None:
        return radius

    hx, hy = heading
    sx, sy = start
    cx, cy = center

    cross_value = hx * (cy - sy) - hy * (cx - sx)
    if abs(cross_value) <= 1e-9:
        return radius

    magnitude = abs(radius)
    if magnitude == 0:
        return radius

    return magnitude if cross_value > 0 else -magnitude
