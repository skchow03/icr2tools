from __future__ import annotations

import math
from dataclasses import replace
from typing import Iterable

from sg_viewer.models.sg_model import Point, SectionPreview


def _curve_orientation_hint(section: SectionPreview) -> float:
    if section.center is not None:
        sx, sy = section.start
        ex, ey = section.end
        cx, cy = section.center
        start_vec = (sx - cx, sy - cy)
        end_vec = (ex - cx, ey - cy)
        cross = start_vec[0] * end_vec[1] - start_vec[1] * end_vec[0]
        if abs(cross) > 1e-9:
            return 1.0 if cross > 0 else -1.0

    if section.start_heading is not None and section.end_heading is not None:
        sx, sy = section.start_heading
        ex, ey = section.end_heading
        cross = sx * ey - sy * ex
        if abs(cross) > 1e-9:
            return 1.0 if cross > 0 else -1.0

    return 1.0


def _curve_heading_penalty(
    original: tuple[float, float] | None, candidate: tuple[float, float] | None
) -> float:
    if original is None or candidate is None:
        return 0.0
    dot = _clamp_unit(original[0] * candidate[0] + original[1] * candidate[1])
    return math.acos(dot)


def _curve_tangent_heading(
    center: Point, point: Point, orientation: float
) -> tuple[float, float] | None:
    vx = point[0] - center[0]
    vy = point[1] - center[1]
    radius = math.hypot(vx, vy)
    if radius <= 0:
        return None
    tx = orientation * (-vy / radius)
    ty = orientation * (vx / radius)
    return (tx, ty)


def _curve_arc_length(center: Point, start: Point, end: Point, radius: float) -> float | None:
    sx = start[0] - center[0]
    sy = start[1] - center[1]
    ex = end[0] - center[0]
    ey = end[1] - center[1]

    dot = _clamp_unit((sx * ex + sy * ey) / max(radius * radius, 1e-9))
    cross = sx * ey - sy * ex
    angle = abs(math.atan2(cross, dot))
    if angle <= 0:
        return None
    return radius * angle


def _project_point_along_heading(
    origin: Point, heading: tuple[float, float] | None, target: Point
) -> Point | None:
    if heading is None:
        return None

    hx, hy = heading
    mag = math.hypot(hx, hy)
    if mag <= 0:
        return None

    hx /= mag
    hy /= mag

    dx = target[0] - origin[0]
    dy = target[1] - origin[1]
    projection = dx * hx + dy * hy

    return origin[0] + projection * hx, origin[1] + projection * hy


def _solve_curve_with_fixed_heading(
    sect: SectionPreview,
    start: Point,
    end: Point,
    fixed_point: Point,
    fixed_heading: tuple[float, float],
    fixed_point_is_start: bool,
    orientation_hint: float,
) -> list[SectionPreview]:
    hx, hy = fixed_heading
    heading_length = math.hypot(hx, hy)
    if heading_length <= 1e-9:
        return []

    hx /= heading_length
    hy /= heading_length

    moving_point = end if fixed_point_is_start else start
    fx, fy = fixed_point
    dx = moving_point[0] - fx
    dy = moving_point[1] - fy

    candidates: list[SectionPreview] = []

    for orientation in {orientation_hint, -orientation_hint}:
        normal = (-orientation * hy, orientation * hx)
        dot = dx * normal[0] + dy * normal[1]
        if abs(dot) <= 1e-9:
            continue

        radius = (dx * dx + dy * dy) / (2.0 * dot)
        if radius <= 0:
            continue

        center = (fx + normal[0] * radius, fy + normal[1] * radius)
        start_heading = _curve_tangent_heading(center, start, orientation)
        end_heading = _curve_tangent_heading(center, end, orientation)

        if start_heading is None or end_heading is None:
            continue

        arc_length = _curve_arc_length(center, start, end, radius)
        if arc_length is None:
            continue

        candidates.append(
            replace(
                sect,
                start=start,
                end=end,
                center=center,
                radius=radius,
                sang1=start_heading[0],
                sang2=start_heading[1],
                eang1=end_heading[0],
                eang2=end_heading[1],
                start_heading=start_heading,
                end_heading=end_heading,
                length=arc_length,
            )
        )

    return candidates


def _solve_curve_drag(
    sect: SectionPreview, start: Point, end: Point, tolerance: float
) -> SectionPreview | None:
    if start == end:
        return None

    cx_hint, cy_hint = sect.center if sect.center is not None else (start[0], start[1])
    orientation_hint = _curve_orientation_hint(sect)

    best_section: SectionPreview | None = None
    best_score = float("inf")

    heading_preserving_candidates: list[SectionPreview] = []

    moved_start = start != sect.start
    moved_end = end != sect.end
    if moved_start and not moved_end and sect.end_heading is not None:
        heading_preserving_candidates = _solve_curve_with_fixed_heading(
            sect,
            start,
            end,
            fixed_point=end,
            fixed_heading=sect.end_heading,
            fixed_point_is_start=False,
            orientation_hint=orientation_hint,
        )
    elif moved_end and not moved_start and sect.start_heading is not None:
        heading_preserving_candidates = _solve_curve_with_fixed_heading(
            sect,
            start,
            end,
            fixed_point=start,
            fixed_heading=sect.start_heading,
            fixed_point_is_start=True,
            orientation_hint=orientation_hint,
        )

    for candidate in heading_preserving_candidates:
        score = _compute_curve_solution_metric(
            candidate.center if candidate.center is not None else (cx_hint, cy_hint),
            candidate.radius if candidate.radius is not None else 0.0,
            candidate.start_heading,
            candidate.end_heading,
            sect,
            tolerance,
        )
        if score < best_score:
            best_score = score
            best_section = candidate

    if best_section is not None:
        return best_section

    vx = end[0] - start[0]
    vy = end[1] - start[1]
    chord_length = math.hypot(vx, vy)
    if chord_length <= 1e-6:
        return None

    half_chord = chord_length / 2.0
    mid = (start[0] + vx * 0.5, start[1] + vy * 0.5)
    normal = (-vy / chord_length, vx / chord_length)

    offset_from_center = (cx_hint - mid[0]) * normal[0] + (cy_hint - mid[1]) * normal[1]
    offset_sign = 1.0 if offset_from_center >= 0 else -1.0
    if offset_sign == 0.0:
        offset_sign = orientation_hint

    radius_target = sect.radius if sect.radius and sect.radius > 0 else None
    offset_for_radius = None
    if radius_target is not None and radius_target > half_chord:
        offset_for_radius = math.sqrt(max(radius_target * radius_target - half_chord * half_chord, 0.0))
        offset_for_radius *= offset_sign

    preferred_offset = offset_sign * max(abs(offset_from_center), tolerance)

    offset_candidates: Iterable[float] = []
    candidates_list = []
    if offset_for_radius is not None:
        candidates_list.append(offset_for_radius)
    candidates_list.append(preferred_offset)
    if offset_for_radius is not None:
        blended = (offset_for_radius + preferred_offset) / 2.0
        candidates_list.append(blended)
    offset_candidates = candidates_list

    for offset in offset_candidates:
        if offset == 0:
            continue

        center = (mid[0] + normal[0] * offset, mid[1] + normal[1] * offset)
        radius = math.hypot(start[0] - center[0], start[1] - center[1])
        if radius <= half_chord:
            continue

        orientation = 1.0 if offset > 0 else -1.0
        start_heading = _curve_tangent_heading(center, start, orientation)
        end_heading = _curve_tangent_heading(center, end, orientation)

        arc_length = _curve_arc_length(center, start, end, radius)
        if arc_length is None:
            continue

        score = _compute_curve_solution_metric(
            center,
            radius,
            start_heading,
            end_heading,
            sect,
            tolerance,
        )

        if score < best_score:
            best_score = score
            best_section = replace(
                sect,
                start=start,
                end=end,
                center=center,
                radius=radius,
                sang1=start_heading[0] if start_heading else None,
                sang2=start_heading[1] if start_heading else None,
                eang1=end_heading[0] if end_heading else None,
                eang2=end_heading[1] if end_heading else None,
                start_heading=start_heading,
                end_heading=end_heading,
                length=arc_length,
            )

    return best_section


def _compute_curve_solution_metric(
    center: Point,
    radius: float,
    start_heading: tuple[float, float] | None,
    end_heading: tuple[float, float] | None,
    sect: SectionPreview,
    tolerance: float,
) -> float:
    center_penalty = 0.0
    if sect.center is not None:
        cx, cy = sect.center
        center_penalty = math.hypot(center[0] - cx, center[1] - cy) * 0.01

    radius_penalty = 0.0
    if sect.radius is not None and sect.radius > 0:
        radius_delta = abs(radius - sect.radius)
        radius_penalty = max(0.0, radius_delta - tolerance) * 0.05

    heading_penalty = 0.0
    heading_penalty += _curve_heading_penalty(sect.start_heading, start_heading)
    heading_penalty += _curve_heading_penalty(sect.end_heading, end_heading)

    return heading_penalty * 2.0 + radius_penalty + center_penalty


def _clamp_unit(value: float) -> float:
    return max(-1.0, min(1.0, value))
