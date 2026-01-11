"""View-state container for the track preview UI.

This module sits in the model layer as a transient state holder that drives
rendering and interaction. It does not load data, perform rendering, or
persist anything; it simply stores mutable UI state for the coordinator.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Tuple

from PyQt5 import QtCore

from track_viewer.common.weather_compass import (
    heading_adjust_to_turns,
    wind_direction_to_turns,
)
from track_viewer.model.pit_models import PIT_DLONG_LINE_INDICES, PitParameters


@dataclass
class TrackPreviewViewState:
    """Mutable UI view state for the preview.

    The state is owned by the preview coordinator and mutated in response to
    user input. It is transient (not persisted) and contains no rendering or
    IO logic—only the fields and small helpers needed to interpret them.
    """
    status_message: str = "Select a track to preview."
    show_center_line: bool = True
    show_boundaries: bool = True
    show_cameras: bool = True
    show_zoom_points: bool = False
    show_section_dividers: bool = False
    ai_color_mode: str = "none"
    ai_acceleration_window: int = 3
    ai_line_width: int = 2
    lp_colors: dict[str, str] = field(default_factory=dict)
    camera_selection_enabled: bool = False
    flag_radius: float = 0.0
    flag_drawing_enabled: bool = False
    show_radius_raw: bool = False
    active_lp_line: str = "center-line"
    selected_lp_line: str | None = None
    selected_lp_index: int | None = None
    lp_shortcut_active: bool = False
    lp_dlat_step: int = 0
    pit_params: PitParameters | None = None
    visible_pit_indices: set[int] = field(
        default_factory=lambda: set(PIT_DLONG_LINE_INDICES)
    )
    show_pit_stall_center_dlat: bool = True
    show_pit_wall_dlat: bool = True
    show_pit_stall_cars: bool = True
    view_center: Tuple[float, float] | None = None
    fit_scale: float | None = None
    current_scale: float | None = 1.0
    user_transform_active: bool = False
    is_panning: bool = False
    last_mouse_pos: QtCore.QPoint | None = None
    left_press_pos: QtCore.QPoint | None = None
    dragged_during_press: bool = False
    dragging_camera_index: int | None = None
    camera_dragged: bool = False
    camera_drag_offset: Tuple[float, float] | None = None
    dragging_flag_index: int | None = None
    flags: List[Tuple[float, float]] = field(default_factory=list)
    selected_flag: int | None = None
    selected_camera: int | None = None
    nearest_projection_point: Tuple[float, float] | None = None
    nearest_projection_dlong: float | None = None
    nearest_projection_dlat: float | None = None
    nearest_projection_speed: float | None = None
    nearest_projection_elevation: float | None = None
    nearest_projection_acceleration: float | None = None
    nearest_projection_line: str | None = None
    projection_cached_point: QtCore.QPointF | None = None
    projection_cached_result: tuple[
        Tuple[float, float] | None,
        float | None,
        float | None,
        float | None,
        float | None,
        float | None,
        str | None,
    ] | None = None
    cursor_position: Tuple[float, float] | None = None
    show_weather_compass: bool = False
    weather_compass_source: str = "wind"
    wind_heading_adjust: int | None = None
    wind2_heading_adjust: int | None = None
    wind_dir: int | None = None
    wind_var: int | None = None
    wind2_dir: int | None = None
    wind2_var: int | None = None
    dragging_weather_compass: str | None = None

    def reset(self, message: str) -> None:
        """Restore the view state to initial defaults."""
        self.status_message = message
        self.show_center_line = True
        self.show_boundaries = True
        self.show_cameras = True
        self.show_zoom_points = False
        self.show_section_dividers = False
        self.ai_color_mode = "none"
        self.ai_acceleration_window = 3
        self.ai_line_width = 2
        self.lp_colors = {}
        self.camera_selection_enabled = False
        self.flag_radius = 0.0
        self.flag_drawing_enabled = False
        self.show_radius_raw = False
        self.active_lp_line = "center-line"
        self.selected_lp_line = None
        self.selected_lp_index = None
        self.lp_shortcut_active = False
        self.lp_dlat_step = 0
        self.pit_params = None
        self.visible_pit_indices = set(PIT_DLONG_LINE_INDICES)
        self.show_pit_stall_center_dlat = True
        self.show_pit_wall_dlat = True
        self.show_pit_stall_cars = True
        self.view_center = None
        self.fit_scale = None
        self.current_scale = 1.0
        self.user_transform_active = False
        self.is_panning = False
        self.last_mouse_pos = None
        self.left_press_pos = None
        self.dragged_during_press = False
        self.dragging_camera_index = None
        self.camera_dragged = False
        self.camera_drag_offset = None
        self.dragging_flag_index = None
        self.flags = []
        self.selected_flag = None
        self.selected_camera = None
        self.nearest_projection_point = None
        self.nearest_projection_dlong = None
        self.nearest_projection_dlat = None
        self.nearest_projection_speed = None
        self.nearest_projection_elevation = None
        self.nearest_projection_acceleration = None
        self.nearest_projection_line = None
        self.projection_cached_point = None
        self.projection_cached_result = None
        self.cursor_position = None
        self.show_weather_compass = False
        self.weather_compass_source = "wind"
        self.wind_heading_adjust = None
        self.wind2_heading_adjust = None
        self.wind_dir = None
        self.wind_var = None
        self.wind2_dir = None
        self.wind2_var = None
        self.dragging_weather_compass = None

    def default_center(
        self, bounds: tuple[float, float, float, float] | None
    ) -> Tuple[float, float] | None:
        """Return the world-space center of the given bounds."""
        if bounds:
            min_x, max_x, min_y, max_y = bounds
            return ((min_x + max_x) / 2, (min_y + max_y) / 2)
        return 0.0, 0.0

    def calculate_fit_scale(
        self, bounds: tuple[float, float, float, float] | None, size: QtCore.QSize
    ) -> float | None:
        """Compute a screen-space scale that fits the bounds in the viewport."""
        if not bounds:
            return None
        min_x, max_x, min_y, max_y = bounds
        track_w = max_x - min_x
        track_h = max_y - min_y
        if track_w <= 0 or track_h <= 0:
            return None
        margin = 24
        available_w = max(size.width() - margin * 2, 1)
        available_h = max(size.height() - margin * 2, 1)
        scale_x = available_w / track_w
        scale_y = available_h / track_h
        return min(scale_x, scale_y)

    def update_fit_scale(
        self, bounds: tuple[float, float, float, float] | None, size: QtCore.QSize
    ) -> None:
        """Update fit scale and recenters if the user has not transformed."""
        fit = self.calculate_fit_scale(bounds, size)
        self.fit_scale = fit
        if fit is not None and not self.user_transform_active:
            self.current_scale = fit
            if self.view_center is None:
                self.view_center = self.default_center(bounds)

    def current_transform(
        self, bounds: tuple[float, float, float, float] | None, size: QtCore.QSize
    ) -> Tuple[float, Tuple[float, float]] | None:
        """Return the current world-to-screen transform for rendering."""
        if self.current_scale is None:
            self.update_fit_scale(bounds, size)
        if self.current_scale is None:
            self.current_scale = 1.0
        center = self.view_center or self.default_center(bounds)
        if center is None:
            return None
        offsets = (
            size.width() / 2 - center[0] * self.current_scale,
            size.height() / 2 - center[1] * self.current_scale,
        )
        return self.current_scale, offsets

    def map_to_track(
        self,
        point: QtCore.QPointF,
        bounds: tuple[float, float, float, float] | None,
        size: QtCore.QSize,
    ) -> Tuple[float, float] | None:
        """Convert a screen point to world coordinates using current transform."""
        transform = self.current_transform(bounds, size)
        if not transform:
            return None
        scale, offsets = transform
        x = (point.x() - offsets[0]) / scale
        py = size.height() - point.y()
        y = (py - offsets[1]) / scale
        return x, y

    def clamp_scale(self, scale: float) -> float:
        """Clamp zoom scale relative to the current fit scale."""
        base = self.fit_scale or self.current_scale or 1.0
        min_scale = base * 0.1
        max_scale = base * 25.0
        return max(min_scale, min(max_scale, scale))

    def set_projection_data(
        self,
        point: Tuple[float, float] | None,
        dlong: float | None,
        dlat: float | None,
        speed: float | None,
        elevation: float | None,
        acceleration: float | None,
        line_name: str | None,
    ) -> bool:
        """Update nearest projection info, returning True if it changed."""
        if (
            point == self.nearest_projection_point
            and dlong == self.nearest_projection_dlong
            and dlat == self.nearest_projection_dlat
            and speed == self.nearest_projection_speed
            and elevation == self.nearest_projection_elevation
            and acceleration == self.nearest_projection_acceleration
            and line_name == self.nearest_projection_line
        ):
            return False
        self.nearest_projection_point = point
        self.nearest_projection_dlong = dlong
        self.nearest_projection_dlat = dlat
        self.nearest_projection_speed = speed
        self.nearest_projection_elevation = elevation
        self.nearest_projection_acceleration = acceleration
        self.nearest_projection_line = line_name
        return True

    def set_cursor_position(self, coords: Tuple[float, float] | None) -> bool:
        """Update cursor world coordinates, returning True on change."""
        if coords == self.cursor_position:
            return False
        self.cursor_position = coords
        return True

    def set_status_message(self, message: str) -> bool:
        """Update status message, returning True on change."""
        if self.status_message == message:
            return False
        self.status_message = message
        return True

    def weather_compass_center(self, size: QtCore.QSize) -> QtCore.QPointF:
        radius = self.weather_compass_radius(size)
        margin = 16 + radius * 0.35
        return QtCore.QPointF(margin + radius, size.height() - margin - radius)

    def weather_compass_radius(self, size: QtCore.QSize) -> float:
        return min(40.0, max(24.0, min(size.width(), size.height()) * 0.08))

    def weather_compass_handle_radius(self, size: QtCore.QSize) -> float:
        return max(4.0, self.weather_compass_radius(size) * 0.12)

    def weather_compass_direction(self) -> int | None:
        if self.weather_compass_source == "wind2":
            return self.wind2_dir
        return self.wind_dir

    def weather_compass_variation(self) -> int | None:
        if self.weather_compass_source == "wind2":
            return self.wind2_var
        return self.wind_var

    def weather_compass_turns(self) -> float:
        """Return wind direction in turns (0..1), factoring heading adjust."""
        direction = self.weather_compass_direction()
        if self.weather_compass_source == "wind2":
            adjust = self.wind2_heading_adjust
        else:
            adjust = self.wind_heading_adjust
        heading_turns = heading_adjust_to_turns(adjust) if adjust is not None else 0.0
        if direction is not None:
            return (heading_turns + wind_direction_to_turns(direction)) % 1.0
        if adjust is None:
            return 0.0
        return heading_turns

    def set_weather_heading_adjust(
        self, source: str, value: int | None
    ) -> bool:
        if source == "wind2":
            if self.wind2_heading_adjust == value:
                return False
            self.wind2_heading_adjust = value
            return True
        if self.wind_heading_adjust == value:
            return False
        self.wind_heading_adjust = value
        return True

    def set_weather_wind_direction(self, source: str, value: int | None) -> bool:
        if source == "wind2":
            if self.wind2_dir == value:
                return False
            self.wind2_dir = value
            return True
        if self.wind_dir == value:
            return False
        self.wind_dir = value
        return True

    def set_weather_wind_variation(self, source: str, value: int | None) -> bool:
        if source == "wind2":
            if self.wind2_var == value:
                return False
            self.wind2_var = value
            return True
        if self.wind_var == value:
            return False
        self.wind_var = value
        return True
