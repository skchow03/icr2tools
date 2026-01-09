"""Rendering helpers for the track preview widget."""
from __future__ import annotations

from track_viewer.rendering.overlays.ai_line_overlay import (
    DLONG_TO_FEET,
    MPH_TO_FEET_PER_SECOND,
    compute_segment_acceleration,
    draw_ai_lines,
    draw_lp_segment,
)
from track_viewer.rendering.overlays.camera_overlay import draw_camera_positions
from track_viewer.rendering.overlays.flag_overlay import draw_flags
from track_viewer.rendering.overlays.pit_overlay import (
    draw_pit_dlong_lines,
    draw_pit_stall_cars,
    draw_pit_stall_range,
)
from track_viewer.rendering.overlays.surface_overlay import (
    draw_centerline,
    draw_track_boundaries,
    render_surface_to_image,
)
from track_viewer.rendering.overlays.zoom_overlay import draw_zoom_points
from track_viewer.rendering.primitives.bars import (
    draw_camera_range_markers,
    draw_start_finish_line,
)
from track_viewer.rendering.primitives.mapping import (
    Point2D,
    Transform,
    centerline_screen_bounds,
    map_point,
)

__all__ = [
    "DLONG_TO_FEET",
    "MPH_TO_FEET_PER_SECOND",
    "Point2D",
    "Transform",
    "centerline_screen_bounds",
    "compute_segment_acceleration",
    "draw_ai_lines",
    "draw_camera_positions",
    "draw_camera_range_markers",
    "draw_centerline",
    "draw_flags",
    "draw_lp_segment",
    "draw_pit_dlong_lines",
    "draw_pit_stall_cars",
    "draw_pit_stall_range",
    "draw_start_finish_line",
    "draw_track_boundaries",
    "draw_zoom_points",
    "map_point",
    "render_surface_to_image",
]
