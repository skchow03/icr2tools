from __future__ import annotations

import logging
import math
from typing import Iterable, List, Optional, Tuple

from sg_viewer.sg_preview.model import (
    Point,
    SgBoundaryGeom,
    SgFsectGeom,
    SgPreviewModel,
    SgSurfaceGeom,
)
from sg_viewer.models.sg_model import SectionPreview

logger = logging.getLogger(__name__)


def build_sg_preview_model(
    sg_document,
    sections: Iterable[SectionPreview] | None = None,
) -> SgPreviewModel:
    sg_data = getattr(sg_document, "sg_data", None)
    if sg_data is None or not getattr(sg_data, "sects", None):
        return SgPreviewModel(fsects=[], bounds=None)

    fsects: list[SgFsectGeom] = []
    bounds = None
    section_polylines = _build_section_polylines(sections)

    for sect_idx, sect in enumerate(sg_data.sects):
        surface_geoms: list[SgSurfaceGeom] = []
        boundary_geoms: list[SgBoundaryGeom] = []
        forward = _forward_from_polyline(section_polylines.get(sect_idx), sect_idx)

        ground_lines: list[tuple[float, float, List[Point], dict]] = []
        boundary_lines: list[tuple[float, float, List[Point], dict]] = []

        ftype1_list = list(getattr(sect, "ftype1", []))
        ftype2_list = list(getattr(sect, "ftype2", []))
        fstart_list = list(getattr(sect, "fstart", []))
        fend_list = list(getattr(sect, "fend", []))

        for f_idx, ftype1 in enumerate(ftype1_list):
            ftype2 = ftype2_list[f_idx] if f_idx < len(ftype2_list) else 0
            fstart = fstart_list[f_idx] if f_idx < len(fstart_list) else 0
            fend = fend_list[f_idx] if f_idx < len(fend_list) else 0

            line_points = _sample_section_offset(
                sect,
                float(fstart),
                float(fend),
                forward=forward,
            )
            line_attrs = {
                "type1": int(ftype1),
                "type2": int(ftype2),
                "dlat_start": float(fstart),
                "dlat_end": float(fend),
            }

            if _is_ground_type(ftype1):
                ground_lines.append((float(fstart), float(fend), line_points, line_attrs))
            else:
                boundary_lines.append((float(fstart), float(fend), line_points, line_attrs))
                boundary_geoms.append(
                    SgBoundaryGeom(
                        id=f_idx,
                        points=line_points,
                        is_closed=False,
                        attrs=line_attrs,
                    )
                )

        left_boundary = _pick_left_boundary(boundary_lines)
        ground_lines_sorted = sorted(
            ground_lines,
            key=lambda entry: _mean_dlat(entry[0], entry[1]),
            reverse=True,
        )

        start_index = 0
        if left_boundary is None and ground_lines_sorted:
            left_boundary = ground_lines_sorted[0]
            start_index = 1

        if left_boundary is not None:
            current_left = left_boundary
            for line_idx in range(start_index, len(ground_lines_sorted)):
                right_line = ground_lines_sorted[line_idx]
                outline = _build_strip_outline(current_left[2], right_line[2])
                outline = _normalize_polygon(outline)
                if len(outline) < 3:
                    current_left = right_line
                    continue

                attrs = dict(right_line[3])
                attrs["section_id"] = sect_idx

                surface_geoms.append(
                    SgSurfaceGeom(
                        id=line_idx,
                        outline=outline,
                        holes=[],
                        attrs=attrs,
                    )
                )
                current_left = right_line

        fsect_geom = SgFsectGeom(
            id=sect_idx,
            surfaces=surface_geoms,
            boundaries=boundary_geoms,
            attrs={"section_id": sect_idx},
        )
        fsects.append(fsect_geom)

        bounds = _merge_bounds(bounds, _bounds_from_fsect(fsect_geom))

    return SgPreviewModel(fsects=fsects, bounds=bounds)


def _is_ground_type(ftype1: int) -> bool:
    return int(ftype1) in {0, 1, 2, 3, 4, 5, 6}


def _mean_dlat(start: float, end: float) -> float:
    return (start + end) * 0.5


def _pick_left_boundary(
    boundaries: Iterable[tuple[float, float, List[Point], dict]]
) -> Optional[tuple[float, float, List[Point], dict]]:
    best = None
    best_value = None
    for start, end, points, attrs in boundaries:
        value = _mean_dlat(start, end)
        if best is None or value > (best_value or -math.inf):
            best = (start, end, points, attrs)
            best_value = value
    return best


def _sample_section_offset(
    sect,
    start_dlat: float,
    end_dlat: float,
    steps: Optional[int] = None,
    forward: Optional[Point] = None,
) -> List[Point]:
    start = (float(getattr(sect, "start_x", 0.0)), float(getattr(sect, "start_y", 0.0)))
    end = (
        float(getattr(sect, "end_x", start[0])),
        float(getattr(sect, "end_y", start[1])),
    )

    if int(getattr(sect, "type", 1)) != 2:
        return _sample_straight(start, end, start_dlat, end_dlat, steps)

    center = (
        float(getattr(sect, "center_x", start[0])),
        float(getattr(sect, "center_y", start[1])),
    )
    return _sample_curve(
        sect,
        start,
        end,
        center,
        start_dlat,
        end_dlat,
        steps,
        forward=forward,
    )


def _sample_straight(
    start: Point,
    end: Point,
    start_dlat: float,
    end_dlat: float,
    steps: Optional[int],
) -> List[Point]:
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length <= 0:
        return [start]

    ux = dx / length
    uy = dy / length
    nx = -uy
    ny = ux

    count = max(2, steps or 2)
    points: list[Point] = []
    for idx in range(count):
        t = idx / (count - 1)
        dlat = start_dlat + (end_dlat - start_dlat) * t
        cx = start[0] + dx * t
        cy = start[1] + dy * t
        points.append((cx + nx * dlat, cy + ny * dlat))

    return points


def _sample_curve(
    sect,
    start: Point,
    end: Point,
    center: Point,
    start_dlat: float,
    end_dlat: float,
    steps: Optional[int],
    forward: Optional[Point],
) -> List[Point]:
    sx, sy = start
    ex, ey = end
    cx, cy = center

    start_vec = (sx - cx, sy - cy)
    end_vec = (ex - cx, ey - cy)
    base_radius = math.hypot(start_vec[0], start_vec[1])
    if base_radius <= 0:
        return [start, end]

    start_angle = math.atan2(start_vec[1], start_vec[0])
    end_angle = math.atan2(end_vec[1], end_vec[0])

    heading = _heading_from_section(sect, start, end)
    ccw = _is_ccw_turn(start_vec, end_vec, heading)
    delta = _angle_delta(start_angle, end_angle, ccw)

    sign = _normal_sign_from_forward(start_vec, forward, ccw)

    count = _curve_steps(delta, steps)
    points: list[Point] = []
    for idx in range(count):
        t = idx / (count - 1)
        dlat = start_dlat + (end_dlat - start_dlat) * t
        radius = max(0.0, base_radius + sign * dlat)
        angle = start_angle + delta * t
        points.append((cx + math.cos(angle) * radius, cy + math.sin(angle) * radius))

    return points


def _heading_from_section(sect, start: Point, end: Point) -> Optional[Point]:
    sang1 = getattr(sect, "sang1", None)
    sang2 = getattr(sect, "sang2", None)
    if sang1 is not None and sang2 is not None:
        hx = _fixed_to_float(float(sang1))
        hy = _fixed_to_float(float(sang2))
        return _normalize((hx, hy))

    dx = end[0] - start[0]
    dy = end[1] - start[1]
    return _normalize((dx, dy))


def _fixed_to_float(value: float) -> float:
    if abs(value) > 1.5:
        return value / 32768.0
    return value


def _normalize(vec: Point) -> Optional[Point]:
    length = math.hypot(vec[0], vec[1])
    if length <= 0:
        return None
    return (vec[0] / length, vec[1] / length)


def _build_section_polylines(
    sections: Iterable[SectionPreview] | None,
) -> dict[int, list[Point]]:
    if not sections:
        return {}
    polylines: dict[int, list[Point]] = {}
    for section in sections:
        if section.polyline:
            polylines[section.section_id] = list(section.polyline)
    return polylines


def _forward_from_polyline(
    polyline: list[Point] | None,
    section_id: int,
) -> Optional[Point]:
    if not polyline:
        return None
    assert len(polyline) >= 2
    logger.debug(
        "Fsect using polyline-derived forward",
        extra={"section_id": section_id},
    )
    start = polyline[0]
    end = polyline[1]
    return _normalize((end[0] - start[0], end[1] - start[1]))


def _normal_sign_from_forward(
    start_vec: Point,
    forward: Optional[Point],
    ccw: bool,
) -> float:
    forward_norm = _normalize(forward) if forward is not None else None
    if forward_norm is None:
        return -1.0 if ccw else 1.0
    normal = (-forward_norm[1], forward_norm[0])
    radial = _normalize(start_vec)
    if radial is None:
        return 1.0
    dot = normal[0] * radial[0] + normal[1] * radial[1]
    return 1.0 if dot >= 0 else -1.0


def _is_ccw_turn(start_vec: Point, end_vec: Point, heading: Optional[Point]) -> bool:
    if heading is not None:
        left_normal = (-heading[1], heading[0])
        to_center = (-start_vec[0], -start_vec[1])
        dot = left_normal[0] * to_center[0] + left_normal[1] * to_center[1]
        return dot > 0

    cross = start_vec[0] * end_vec[1] - start_vec[1] * end_vec[0]
    return cross >= 0


def _angle_delta(start_angle: float, end_angle: float, ccw: bool) -> float:
    delta = end_angle - start_angle
    if ccw:
        if delta <= 0:
            delta += math.tau
    else:
        if delta >= 0:
            delta -= math.tau
    return delta


def _curve_steps(delta: float, steps: Optional[int]) -> int:
    if steps is not None:
        return max(2, steps)
    total = abs(delta)
    return max(8, int(total / (math.pi / 18)) + 1)


def _build_strip_outline(left: List[Point], right: List[Point]) -> List[Point]:
    if not left or not right:
        return []
    return list(left) + list(reversed(right))


def _normalize_polygon(points: List[Point]) -> List[Point]:
    if len(points) < 3:
        return points

    if _points_close(points[0], points[-1]):
        points = points[:-1]

    if _polygon_area(points) < 0:
        points = list(reversed(points))

    return points


def _polygon_area(points: List[Point]) -> float:
    area = 0.0
    total = len(points)
    for idx, (x1, y1) in enumerate(points):
        x2, y2 = points[(idx + 1) % total]
        area += x1 * y2 - x2 * y1
    return area * 0.5


def _points_close(a: Point, b: Point, eps: float = 1e-6) -> bool:
    return abs(a[0] - b[0]) <= eps and abs(a[1] - b[1]) <= eps


def _bounds_from_points(points: Iterable[Point]) -> Optional[Tuple[float, float, float, float]]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    if not xs or not ys:
        return None
    return min(xs), max(xs), min(ys), max(ys)


def _bounds_from_fsect(fsect: SgFsectGeom) -> Optional[Tuple[float, float, float, float]]:
    bounds = None
    for surface in fsect.surfaces:
        bounds = _merge_bounds(bounds, _bounds_from_points(surface.outline))
        for hole in surface.holes:
            bounds = _merge_bounds(bounds, _bounds_from_points(hole))
    for boundary in fsect.boundaries:
        bounds = _merge_bounds(bounds, _bounds_from_points(boundary.points))
    return bounds


def _merge_bounds(
    a: Optional[Tuple[float, float, float, float]],
    b: Optional[Tuple[float, float, float, float]],
) -> Optional[Tuple[float, float, float, float]]:
    if a is None:
        return b
    if b is None:
        return a
    return (
        min(a[0], b[0]),
        max(a[1], b[1]),
        min(a[2], b[2]),
        max(a[3], b[3]),
    )
