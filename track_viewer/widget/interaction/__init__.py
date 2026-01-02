"""Interaction helpers for the track preview widget."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from icr2_core.cam.helpers import CameraPosition


@dataclass
class InteractionCallbacks:
    update: Callable[[], None]
    cursor_position_changed: Callable[[tuple[float, float] | None], None]
    selected_flag_changed: Callable[[tuple[float, float] | None], None]
    selected_camera_changed: Callable[[int | None, CameraPosition | None], None]
    lp_record_selected: Callable[[str, int], None]
    diagram_clicked: Callable[[], None]
