from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from sg_viewer.model.dlong_mapping import dlong_to_section_position
from sg_viewer.model.sg_model import Point, SectionPreview
from sg_viewer.services.trackside_objects import TracksideObject
from sg_viewer.ui.presentation.fsect_table_presenter import boundary_numbers_for_fsects
from track_viewer.geometry import project_point_to_centerline


@dataclass(frozen=True)
class TsoBoundaryElevationContext:
    centerline_index: object
    sampled_dlongs: object
    sections: object
    track_length: float
    get_section_fsects: Callable[[int], object]
    sample_elevation_at_dlat: Callable[[int, float, float], float | None]


def point_on_section(section: SectionPreview, fraction: float, dlat: float) -> Point:
    sx, sy = section.start
    ex, ey = section.end
    center = section.center
    if center is None:
        dx = ex - sx
        dy = ey - sy
        cx = sx + dx * fraction
        cy = sy + dy * fraction
        length = math.hypot(dx, dy)
        if length <= 0:
            return (cx, cy)
        nx = -dy / length
        ny = dx / length
        return (cx + nx * dlat, cy + ny * dlat)

    center_x, center_y = center
    start_vec = (sx - center_x, sy - center_y)
    end_vec = (ex - center_x, ey - center_y)
    base_radius = math.hypot(start_vec[0], start_vec[1])
    if base_radius <= 0:
        return (sx, sy)
    start_angle = math.atan2(start_vec[1], start_vec[0])
    end_angle = math.atan2(end_vec[1], end_vec[0])
    heading = section.start_heading
    if heading is not None:
        cross = start_vec[0] * heading[1] - start_vec[1] * heading[0]
        ccw = cross > 0
    else:
        cross_vectors = start_vec[0] * end_vec[1] - start_vec[1] * end_vec[0]
        ccw = cross_vectors > 0
    if ccw:
        angle_delta = end_angle - start_angle
        if angle_delta < 0:
            angle_delta += math.tau
    else:
        angle_delta = end_angle - start_angle
        if angle_delta > 0:
            angle_delta -= math.tau
    angle = start_angle + angle_delta * fraction
    sign = -1.0 if ccw else 1.0
    radius = max(0.0, base_radius + sign * dlat)
    return (
        center_x + math.cos(angle) * radius,
        center_y + math.sin(angle) * radius,
    )


def closest_boundary_elevation_for_tso_with_context(
    obj: TracksideObject,
    *,
    context: TsoBoundaryElevationContext | None,
    memo: dict[tuple[int, int, int, int, int], int | None] | None = None,
) -> int | None:
    if context is None:
        return None
    revision_token = (
        id(context.centerline_index),
        id(context.sampled_dlongs),
        id(context.sections),
    )
    cache_key = (int(obj.x), int(obj.y), *revision_token)
    if memo is not None and cache_key in memo:
        return memo[cache_key]
    projected_point, projected_dlong, _distance_sq = project_point_to_centerline(
        (float(obj.x), float(obj.y)),
        context.centerline_index,
        context.sampled_dlongs,
        context.track_length,
    )
    if projected_point is None or projected_dlong is None:
        return None
    mapped = dlong_to_section_position(context.sections, projected_dlong, context.track_length)
    if mapped is None:
        return None
    section_index = int(mapped.section_index)
    if section_index < 0 or section_index >= len(context.sections):
        return None
    progress = max(0.0, min(1.0, float(mapped.fraction)))
    section = context.sections[section_index]
    fsects = context.get_section_fsects(section_index)
    boundary_number_by_row = boundary_numbers_for_fsects(fsects)
    if not boundary_number_by_row:
        return None
    best_distance_sq: float | None = None
    best_elevation: int | None = None
    for row_index in boundary_number_by_row:
        if row_index < 0 or row_index >= len(fsects):
            continue
        fsect = fsects[row_index]
        dlat = float(fsect.start_dlat) + (float(fsect.end_dlat) - float(fsect.start_dlat)) * progress
        boundary_point = point_on_section(section, progress, dlat)
        distance_sq = (boundary_point[0] - float(obj.x)) ** 2 + (boundary_point[1] - float(obj.y)) ** 2
        elevation = context.sample_elevation_at_dlat(section_index, progress, dlat)
        if elevation is None:
            continue
        if best_distance_sq is None or distance_sq < best_distance_sq:
            best_distance_sq = distance_sq
            best_elevation = int(round(elevation))
    if memo is not None:
        memo[cache_key] = best_elevation
    return best_elevation
