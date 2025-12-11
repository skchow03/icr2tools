from __future__ import annotations

import math
from dataclasses import replace
from typing import List, Tuple

from track_viewer.geometry import CenterlineIndex, build_centerline_index

from sg_viewer.sg_model import SectionPreview, Point


def normalize_heading(vec: tuple[float, float] | None) -> tuple[float, float] | None:
    if vec is None:
        return None
    length = math.hypot(vec[0], vec[1])
    if length == 0:
        return None
    return (vec[0] / length, vec[1] / length)


def round_heading(vec: tuple[float, float] | None) -> tuple[float, float] | None:
    norm = normalize_heading(vec)
    if norm is None:
        return None
    return (round(norm[0], 5), round(norm[1], 5))


def _radius_vector(
    center: Point | None, provided: tuple[float, float] | None, fallback: Point | None
) -> tuple[float, float] | None:
    if center is None:
        return None

    if provided is not None and provided[0] is not None and provided[1] is not None:
        return provided

    if fallback is None:
        return None

    cx, cy = center
    fx, fy = fallback
    return fx - cx, fy - cy


def _orientation_from_radii(
    start_radius: tuple[float, float] | None, end_radius: tuple[float, float] | None
) -> float | None:
    if start_radius is None or end_radius is None:
        return None

    cross = start_radius[0] * end_radius[1] - start_radius[1] * end_radius[0]
    if abs(cross) < 1e-9:
        return None
    return 1.0 if cross > 0 else -1.0


def _heading_from_radius(
    radius_vec: tuple[float, float] | None, orientation: float | None
) -> tuple[float, float] | None:
    if radius_vec is None:
        return None

    rx, ry = radius_vec
    if orientation is None:
        orientation = 1.0

    if orientation > 0:
        tangent = (-ry, rx)
    else:
        tangent = (ry, -rx)

    return round_heading(tangent)


def derive_radius_vectors(
    center: Point | None,
    start: Point,
    end: Point,
    sang1: float | None,
    sang2: float | None,
    eang1: float | None,
    eang2: float | None,
) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    start_radius = _radius_vector(center, (sang1, sang2), start)
    end_radius = _radius_vector(center, (eang1, eang2), end)
    return start_radius, end_radius


def build_section_polyline(
    type_name: str,
    start: Point,
    end: Point,
    center: Point | None,
    radius: float | None,
    start_heading: tuple[float, float] | None,
    end_heading: tuple[float, float] | None,
) -> List[Point]:
    if type_name != "curve" or center is None:
        return [start, end]

    def _choose_ccw_direction(start_vec: tuple[float, float], end_vec: tuple[float, float]) -> bool:
        start_norm = normalize_heading(start_vec)
        end_norm = normalize_heading(end_vec)
        if start_norm and end_norm:
            cross = start_norm[0] * end_norm[1] - start_norm[1] * end_norm[0]
            if abs(cross) > 1e-9:
                return cross > 0
        return True

    def _heading_prefers_ccw(vec: tuple[float, float], heading: tuple[float, float]) -> bool | None:
        heading_norm = normalize_heading(heading)
        vec_norm = normalize_heading(vec)
        if heading_norm is None or vec_norm is None:
            return None
        ccw_tangent = (-vec_norm[1], vec_norm[0])
        cw_tangent = (vec_norm[1], -vec_norm[0])
        ccw_dot = ccw_tangent[0] * heading_norm[0] + ccw_tangent[1] * heading_norm[1]
        cw_dot = cw_tangent[0] * heading_norm[0] + cw_tangent[1] * heading_norm[1]
        if abs(ccw_dot - cw_dot) < 1e-9:
            return None
        return ccw_dot > cw_dot

    def _heading_radius_angle(
        heading: tuple[float, float] | None, reference_vec: tuple[float, float] | None
    ) -> float | None:
        heading_norm = normalize_heading(heading)
        if heading_norm is None:
            return None

        heading_angle = math.atan2(heading_norm[1], heading_norm[0])
        candidates = [heading_angle - math.pi / 2, heading_angle + math.pi / 2]

        ref_norm = normalize_heading(reference_vec)
        if ref_norm is None:
            return candidates[0]

        def _dot(angle: float) -> float:
            return math.cos(angle) * ref_norm[0] + math.sin(angle) * ref_norm[1]

        best_angle = max(candidates, key=_dot)
        return best_angle

    cx, cy = center
    start_vec = (start[0] - cx, start[1] - cy)
    end_vec = (end[0] - cx, end[1] - cy)
    radius_length = radius if radius is not None and radius > 0 else (start_vec[0] ** 2 + start_vec[1] ** 2) ** 0.5

    if radius_length <= 0:
        return [start, end]

    start_angle = _heading_radius_angle(start_heading, start_vec)
    if start_angle is None:
        start_angle = math.atan2(start_vec[1], start_vec[0])

    end_angle = _heading_radius_angle(end_heading, end_vec)
    if end_angle is None:
        end_angle = math.atan2(end_vec[1], end_vec[0])

    prefer_ccw = _heading_prefers_ccw(start_vec, start_heading) if start_heading else None
    if prefer_ccw is None and end_heading:
        prefer_ccw = _heading_prefers_ccw(end_vec, end_heading)
    if prefer_ccw is None:
        prefer_ccw = _choose_ccw_direction(start_vec, end_vec)

    angle_span = end_angle - start_angle
    if prefer_ccw:
        if angle_span <= 0:
            angle_span += 2 * math.pi
    else:
        if angle_span >= 0:
            angle_span -= 2 * math.pi

    total_angle = abs(angle_span)
    if total_angle < 1e-6:
        return [start, end]

    steps = max(8, int(total_angle / (math.pi / 36)))
    points: list[Point] = []
    for step in range(steps + 1):
        fraction = step / steps
        angle = start_angle + angle_span * fraction
        x = cx + math.cos(angle) * radius_length
        y = cy + math.sin(angle) * radius_length
        points.append((x, y))

    return points


def derive_heading_vectors(
    polyline: List[Point],
    start_radius: tuple[float, float] | None,
    end_radius: tuple[float, float] | None,
) -> tuple[tuple[float, float] | None, tuple[float, float] | None]:
    orientation = _orientation_from_radii(start_radius, end_radius)
    start_heading = _heading_from_radius(start_radius, orientation)
    end_heading = _heading_from_radius(end_radius, orientation)

    if start_heading is not None and end_heading is not None:
        return start_heading, end_heading

    if len(polyline) < 2:
        return None, None

    start = polyline[0]
    end = polyline[-1]
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = (dx * dx + dy * dy) ** 0.5
    if length <= 0:
        return None, None

    heading = (dx / length, dy / length)
    rounded = round_heading(heading)
    return rounded, rounded


def update_section_geometry(section: SectionPreview) -> SectionPreview:
    start_radius, end_radius = derive_radius_vectors(
        section.center,
        section.start,
        section.end,
        section.sang1,
        section.sang2,
        section.eang1,
        section.eang2,
    )

    orientation = _orientation_from_radii(start_radius, end_radius)
    start_heading = _heading_from_radius(start_radius, orientation) or section.start_heading
    end_heading = _heading_from_radius(end_radius, orientation) or section.end_heading

    polyline = build_section_polyline(
        section.type_name,
        section.start,
        section.end,
        section.center,
        section.radius,
        start_heading,
        end_heading,
    )
    start_heading, end_heading = derive_heading_vectors(polyline, start_radius, end_radius)

    return replace(
        section,
        polyline=polyline,
        start_heading=start_heading,
        end_heading=end_heading,
        sang1=start_radius[0] if start_radius else None,
        sang2=start_radius[1] if start_radius else None,
        eang1=end_radius[0] if end_radius else None,
        eang2=end_radius[1] if end_radius else None,
    )


def rebuild_centerline_from_sections(
    sections: list[SectionPreview],
) -> tuple[list[Point], list[float], tuple[float, float, float, float] | None, CenterlineIndex | None]:
    """Flatten section polylines into the active centreline representation."""

    polylines = [sect.polyline for sect in sections if sect.polyline]
    if not polylines:
        return [], [], None, None

    points: list[Point] = []
    for polyline in polylines:
        if not polyline:
            continue
        if points and points[-1] == polyline[0]:
            points.extend(polyline[1:])
        else:
            points.extend(polyline)

    if len(points) < 2:
        return [], [], None, None

    bounds = (
        min(p[0] for p in points),
        max(p[0] for p in points),
        min(p[1] for p in points),
        max(p[1] for p in points),
    )

    dlongs: list[float] = [0.0]
    distance = 0.0
    for prev, cur in zip(points, points[1:]):
        distance += math.hypot(cur[0] - prev[0], cur[1] - prev[1])
        dlongs.append(distance)

    centerline_index = build_centerline_index(points, bounds)

    return points, dlongs, bounds, centerline_index
