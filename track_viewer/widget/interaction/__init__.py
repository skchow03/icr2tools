"""Interaction helpers for the track preview widget."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from icr2_core.cam.helpers import CameraPosition


class PreviewIntent(Enum):
    """Intent hints for view updates."""

    VIEW_TRANSFORM_CHANGED = "view_transform_changed"
    SURFACE_DATA_CHANGED = "surface_data_changed"
    SELECTION_CHANGED = "selection_changed"
    CAMERA_CHANGED = "camera_changed"
    FLAG_CHANGED = "flag_changed"
    PROJECTION_CHANGED = "projection_changed"
    OVERLAY_CHANGED = "overlay_changed"


@dataclass
class InteractionCallbacks:
    state_changed: Callable[[PreviewIntent], None]
    cursor_position_changed: Callable[[tuple[float, float] | None], None]
    selected_flag_changed: Callable[[tuple[float, float] | None], None]
    selected_camera_changed: Callable[[int | None, CameraPosition | None], None]
    lp_record_selected: Callable[[str, int], None]
    diagram_clicked: Callable[[], None]
    weather_heading_adjust_changed: Callable[[str, int], None]
