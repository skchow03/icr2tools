from __future__ import annotations

from sg_viewer.model.preview_fsection import PreviewFSection
from sg_viewer.rendering.fsection_style_map import FENCE_TYPE2


def build_generated_fsects(
    *,
    template: str,
    track_width: float,
    left_grass: float,
    right_grass: float,
    grass_surface_type: int,
    wall_surface_type: int,
    wall_width: float,
    fence_enabled: bool,
) -> list[PreviewFSection]:
    fence_type2 = min(FENCE_TYPE2) if fence_enabled and FENCE_TYPE2 else 0

    def wall(at_dlat: float) -> PreviewFSection:
        return PreviewFSection(
            start_dlat=at_dlat,
            end_dlat=at_dlat,
            surface_type=wall_surface_type,
            type2=fence_type2,
        )

    def surface(start: float, end: float, surface_type: int) -> PreviewFSection:
        return PreviewFSection(
            start_dlat=start,
            end_dlat=start,
            surface_type=surface_type,
            type2=0,
        )

    fsects: list[PreviewFSection] = []
    half_track = track_width * 0.5

    if template == "street":
        fsects.append(wall(-half_track))
        fsects.append(surface(-half_track, half_track, 5))
        fsects.append(wall(half_track))
        return fsects

    if template == "oval":
        fsects.append(wall(-half_track))
        fsects.append(surface(-half_track, half_track, 5))
        if left_grass > 0:
            fsects.append(surface(half_track, half_track + left_grass, grass_surface_type))
        fsects.append(wall(half_track + left_grass))
        return fsects

    fsects.append(wall(-half_track - right_grass))
    if right_grass > 0:
        fsects.append(surface(-half_track - right_grass, -half_track, grass_surface_type))
    fsects.append(surface(-half_track, half_track, 5))
    if left_grass > 0:
        fsects.append(surface(half_track, half_track + left_grass, grass_surface_type))
    fsects.append(wall(half_track + left_grass))
    return fsects
