"""Public API surface for track preview operations."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from icr2_core.cam.helpers import CameraPosition
from track_viewer.ai.ai_line_service import LpPoint
from track_viewer.model.pit_models import PitParameters
from track_viewer.preview_coordinator import PreviewCoordinator


class TrackPreviewApi:
    """Thin API wrapper over the preview coordinator."""

    def __init__(self, coordinator: PreviewCoordinator) -> None:
        self._coordinator = coordinator

    def clear(self, message: str = "Select a track to preview.") -> None:
        self._coordinator.clear(message)

    def tv_mode_count(self) -> int:
        return self._coordinator.tv_mode_count()

    def set_tv_mode_count(self, count: int) -> None:
        self._coordinator.set_tv_mode_count(count)

    def set_show_center_line(self, show: bool) -> None:
        self._coordinator.set_show_center_line(show)

    def set_show_boundaries(self, show: bool) -> None:
        self._coordinator.set_show_boundaries(show)

    def set_show_section_dividers(self, show: bool) -> None:
        self._coordinator.set_show_section_dividers(show)

    def set_show_weather_compass(self, show: bool) -> None:
        self._coordinator.set_show_weather_compass(show)

    def set_weather_compass_source(self, source: str) -> None:
        self._coordinator.set_weather_compass_source(source)

    def set_weather_heading_adjust(self, source: str, value: int | None) -> None:
        self._coordinator.set_weather_heading_adjust(source, value)

    def set_weather_wind_direction(self, source: str, value: int | None) -> None:
        self._coordinator.set_weather_wind_direction(source, value)

    def set_weather_wind_variation(self, source: str, value: int | None) -> None:
        self._coordinator.set_weather_wind_variation(source, value)

    def center_line_visible(self) -> bool:
        return self._coordinator.center_line_visible()

    def ai_line_available(self) -> bool:
        return self._coordinator.ai_line_available()

    def available_lp_files(self) -> list[str]:
        return self._coordinator.available_lp_files()

    def ai_acceleration_window(self) -> int:
        return self._coordinator.ai_acceleration_window()

    def set_ai_acceleration_window(self, segments: int) -> None:
        self._coordinator.set_ai_acceleration_window(segments)

    def ai_line_width(self) -> int:
        return self._coordinator.ai_line_width()

    def set_ai_line_width(self, width: int) -> None:
        self._coordinator.set_ai_line_width(width)

    def flag_radius(self) -> float:
        return self._coordinator.flag_radius()

    def set_flag_radius(self, radius: float) -> None:
        self._coordinator.set_flag_radius(radius)

    def flag_drawing_enabled(self) -> bool:
        return self._coordinator.flag_drawing_enabled()

    def set_flag_drawing_enabled(self, enabled: bool) -> None:
        self._coordinator.set_flag_drawing_enabled(enabled)

    def set_radius_raw_visible(self, enabled: bool) -> None:
        self._coordinator.set_radius_raw_visible(enabled)

    def visible_lp_files(self) -> list[str]:
        return self._coordinator.visible_lp_files()

    def set_visible_lp_files(self, names: list[str] | set[str]) -> None:
        self._coordinator.set_visible_lp_files(names)

    def active_lp_line(self) -> str:
        return self._coordinator.active_lp_line()

    def set_active_lp_line(self, name: str) -> None:
        self._coordinator.set_active_lp_line(name)

    def ai_line_records(self, name: str) -> list[LpPoint]:
        return self._coordinator.ai_line_records(name)

    def update_lp_record(self, lp_name: str, index: int) -> None:
        self._coordinator.update_lp_record(lp_name, index)

    def save_active_lp_line(self) -> tuple[bool, str]:
        return self._coordinator.save_active_lp_line()

    def save_all_lp_lines(self) -> tuple[bool, str]:
        return self._coordinator.save_all_lp_lines()

    def export_active_lp_csv(self, output_path: Path) -> tuple[bool, str]:
        return self._coordinator.export_active_lp_csv(output_path)

    def generate_lp_line(
        self, lp_name: str, speed_mph: float, dlat: float
    ) -> tuple[bool, str]:
        return self._coordinator.generate_lp_line(lp_name, speed_mph, dlat)

    def set_selected_lp_record(self, name: str | None, index: int | None) -> None:
        self._coordinator.set_selected_lp_record(name, index)

    def set_lp_shortcut_active(self, active: bool) -> None:
        self._coordinator.set_lp_shortcut_active(active)

    def set_lp_editing_tab_active(self, active: bool) -> None:
        self._coordinator.set_lp_editing_tab_active(active)

    def set_lp_dlat_step(self, step: int) -> None:
        self._coordinator.set_lp_dlat_step(step)

    def lp_color(self, name: str) -> str:
        return self._coordinator.lp_color(name)

    def set_lp_color(self, name: str, color: str | None) -> None:
        self._coordinator.set_lp_color(name, color)

    def lp_color_overrides(self) -> dict[str, str]:
        return self._coordinator.lp_color_overrides()

    def set_show_zoom_points(self, show: bool) -> None:
        self._coordinator.set_show_zoom_points(show)

    def set_ai_speed_gradient_enabled(self, enabled: bool) -> None:
        self._coordinator.set_ai_speed_gradient_enabled(enabled)

    def set_ai_acceleration_gradient_enabled(self, enabled: bool) -> None:
        self._coordinator.set_ai_acceleration_gradient_enabled(enabled)

    def set_ai_color_mode(self, mode: str) -> None:
        self._coordinator.set_ai_color_mode(mode)

    def track_length(self) -> Optional[int]:
        return self._coordinator.track_length()

    def sampled_centerline(self) -> list[tuple[float, float]]:
        return self._coordinator.sampled_centerline()

    @property
    def trk(self) -> object | None:
        return self._coordinator.trk

    def track_path(self) -> Optional[Path]:
        return self._coordinator.track_path()

    def set_show_cameras(self, show: bool) -> None:
        self._coordinator.set_show_cameras(show)

    def set_show_cameras_current_tv_only(self, show: bool) -> None:
        self._coordinator.set_show_cameras_current_tv_only(show)

    def set_current_tv_mode_index(self, index: int) -> None:
        self._coordinator.set_current_tv_mode_index(index)

    def camera_selection_enabled(self) -> bool:
        return self._coordinator.camera_selection_enabled()

    def set_camera_selection_enabled(self, enabled: bool) -> None:
        self._coordinator.set_camera_selection_enabled(enabled)

    def set_pit_parameters(self, params: PitParameters | None) -> None:
        self._coordinator.set_pit_parameters(params)

    def set_visible_pit_indices(self, indices: set[int]) -> None:
        self._coordinator.set_visible_pit_indices(indices)

    def set_show_pit_stall_center_dlat(self, show: bool) -> None:
        self._coordinator.set_show_pit_stall_center_dlat(show)

    def set_show_pit_wall_dlat(self, show: bool) -> None:
        self._coordinator.set_show_pit_wall_dlat(show)

    def set_show_pit_stall_cars(self, show: bool) -> None:
        self._coordinator.set_show_pit_stall_cars(show)

    def cameras(self) -> List[CameraPosition]:
        return self._coordinator.cameras()

    def update_camera_dlongs(
        self, camera_index: int, start_dlong: Optional[int], end_dlong: Optional[int]
    ) -> None:
        self._coordinator.update_camera_dlongs(camera_index, start_dlong, end_dlong)

    def update_camera_position(
        self, camera_index: int, x: Optional[int], y: Optional[int], z: Optional[int]
    ) -> None:
        self._coordinator.update_camera_position(camera_index, x, y, z)

    def set_selected_camera(self, index: int | None) -> None:
        self._coordinator.set_selected_camera(index)

    def add_type6_camera(self) -> tuple[bool, str]:
        return self._coordinator.add_type6_camera()

    def add_type2_camera(self) -> tuple[bool, str]:
        return self._coordinator.add_type2_camera()

    def add_type7_camera(self) -> tuple[bool, str]:
        return self._coordinator.add_type7_camera()

    def load_track(self, track_folder: Path) -> None:
        self._coordinator.load_track(track_folder)

    def save_cameras(self) -> tuple[bool, str]:
        return self._coordinator.save_cameras()

    def run_trk_gaps(self) -> tuple[bool, str]:
        return self._coordinator.run_trk_gaps()

    def convert_trk_to_sg(self, output_path: Path) -> tuple[bool, str]:
        return self._coordinator.convert_trk_to_sg(output_path)
