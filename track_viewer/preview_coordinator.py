"""Non-Qt coordinator for the track preview domain logic."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, List, Optional

from PyQt5 import QtCore, QtGui

from icr2_core.cam.helpers import CameraPosition
from icr2_core.trk.trk_utils import get_cline_pos, getxyz, sect2xy
from track_viewer.ai.ai_line_service import LpPoint
from track_viewer.common.preview_constants import LP_COLORS, LP_FILE_NAMES
from track_viewer.controllers.camera_controller import CameraController
from track_viewer.model.pit_models import PitParameters
from track_viewer.model.track_preview_model import TrackPreviewModel
from track_viewer.model.view_state import TrackPreviewViewState
from track_viewer.rendering.track_preview_renderer import TrackPreviewRenderer
from track_viewer.services.camera_service import CameraService
from track_viewer.services.io_service import TrackIOService
from track_viewer.widget.editing.camera_edit_controller import CameraEditController
from track_viewer.widget.editing.flag_edit_controller import FlagEditController
from track_viewer.widget.editing.lp_edit_controller import LpEditController
from track_viewer.widget.interaction import InteractionCallbacks, PreviewIntent
from track_viewer.widget.interaction.keyboard_controller import (
    TrackPreviewKeyboardController,
)
from track_viewer.widget.interaction.mouse_controller import TrackPreviewMouseController
from track_viewer.widget.selection.selection_controller import SelectionController


class PreviewCoordinator:
    """Coordinate track preview model, state, and interactions."""

    def __init__(
        self,
        request_repaint: Callable[[], None],
        cursor_position_changed: Callable[[tuple[float, float] | None], None],
        selected_flag_changed: Callable[[tuple[float, float] | None], None],
        cameras_changed: Callable[[list, list], None],
        selected_camera_changed: Callable[[int | None, CameraPosition | None], None],
        active_lp_line_changed: Callable[[str], None],
        ai_line_loaded: Callable[[str], None],
        lp_record_selected: Callable[[str, int], None],
        diagram_clicked: Callable[[], None],
        weather_heading_adjust_changed: Callable[[str, int], None],
        weather_wind_direction_changed: Callable[[str, int], None],
    ) -> None:
        self._request_repaint = request_repaint
        self._emit_cursor_position_changed = cursor_position_changed
        self._emit_selected_flag_changed = selected_flag_changed
        self._emit_cameras_changed = cameras_changed
        self._emit_selected_camera_changed = selected_camera_changed
        self._emit_active_lp_line_changed = active_lp_line_changed
        self._emit_ai_line_loaded = ai_line_loaded
        self._emit_lp_record_selected = lp_record_selected
        self._emit_diagram_clicked = diagram_clicked
        self._emit_weather_heading_adjust_changed = weather_heading_adjust_changed
        self._emit_weather_wind_direction_changed = weather_wind_direction_changed

        self._state = TrackPreviewViewState()
        self._last_size = QtCore.QSize()
        self._io_service = TrackIOService()
        self._model = TrackPreviewModel(self._io_service)
        self._model.aiLineLoaded.connect(self._handle_model_ai_line_loaded)
        self._camera_service = CameraService(self._io_service, CameraController())
        self._renderer = TrackPreviewRenderer(self._model, self._camera_service, self._state)
        self._interaction_callbacks = InteractionCallbacks(
            state_changed=self._handle_intent,
            cursor_position_changed=self._emit_cursor_position_changed,
            selected_flag_changed=self._emit_selected_flag_changed,
            selected_camera_changed=self._emit_selected_camera_changed,
            lp_record_selected=self._emit_lp_record_selected,
            diagram_clicked=self._emit_diagram_clicked,
            weather_heading_adjust_changed=self._emit_weather_heading_adjust_changed,
            weather_wind_direction_changed=self._emit_weather_wind_direction_changed,
        )
        self._selection_controller = SelectionController(
            self._model, self._camera_service, self._state, self._interaction_callbacks
        )
        self._camera_edit_controller = CameraEditController(
            self._model,
            self._camera_service,
            self._state,
            self._selection_controller,
            self._interaction_callbacks,
        )
        self._flag_edit_controller = FlagEditController(
            self._model,
            self._state,
            self._selection_controller,
            self._interaction_callbacks,
        )
        self._lp_edit_controller = LpEditController(self._selection_controller)
        self._mouse_controller = TrackPreviewMouseController(
            self._model,
            self._state,
            self._interaction_callbacks,
            self._selection_controller,
            self._camera_edit_controller,
            self._flag_edit_controller,
            self._lp_edit_controller,
        )
        self._keyboard_controller = TrackPreviewKeyboardController()

    @property
    def mouse_controller(self) -> TrackPreviewMouseController:
        return self._mouse_controller

    @property
    def keyboard_controller(self) -> TrackPreviewKeyboardController:
        return self._keyboard_controller

    def paint(self, painter: QtGui.QPainter, size: QtCore.QSize) -> None:
        self._renderer.paint(painter, size)

    def handle_resize(self, size: QtCore.QSize) -> None:
        self._last_size = size
        self._state.update_fit_scale(self._model.bounds, size)
        self._handle_intent(PreviewIntent.VIEW_TRANSFORM_CHANGED)

    def _handle_intent(self, intent: PreviewIntent) -> None:
        if intent == PreviewIntent.SURFACE_DATA_CHANGED:
            self._renderer.invalidate_surface_cache()
        self._request_repaint()

    def _handle_model_ai_line_loaded(self, lp_name: str) -> None:
        self._emit_ai_line_loaded(lp_name)
        self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    # ------------------------------------------------------------------
    # Public API - state orchestration
    # ------------------------------------------------------------------
    def clear(self, message: str = "Select a track to preview.") -> None:
        lp_colors = dict(self._state.lp_colors)
        self._model.clear()
        self._state.reset(message)
        self._state.lp_colors = lp_colors
        self._camera_service.reset()
        self._emit_cursor_position_changed(None)
        self._emit_selected_flag_changed(None)
        self._emit_cameras_changed([], [])
        self._emit_selected_camera_changed(None, None)
        self._handle_intent(PreviewIntent.SURFACE_DATA_CHANGED)

    def tv_mode_count(self) -> int:
        return self._camera_service.tv_mode_count

    def set_tv_mode_count(self, count: int) -> None:
        updated_count = self._camera_service.set_tv_mode_count(count)
        if not updated_count:
            return
        self._emit_cameras_changed(
            self._camera_service.cameras, self._camera_service.camera_views
        )
        self._handle_intent(PreviewIntent.CAMERA_CHANGED)

    def set_show_center_line(self, show: bool) -> None:
        if self._state.show_center_line != show:
            self._state.show_center_line = show
            if not show and self._state.active_lp_line == "center-line":
                if self._state.set_projection_data(
                    None, None, None, None, None, None, None
                ):
                    self._handle_intent(PreviewIntent.PROJECTION_CHANGED)
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def set_show_weather_compass(self, show: bool) -> None:
        if self._state.show_weather_compass != show:
            self._state.show_weather_compass = show
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def set_weather_compass_source(self, source: str) -> None:
        if source not in {"wind", "wind2"}:
            return
        if self._state.weather_compass_source != source:
            self._state.weather_compass_source = source
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def set_weather_heading_adjust(self, source: str, value: int | None) -> None:
        if self._state.set_weather_heading_adjust(source, value):
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def set_weather_wind_direction(self, source: str, value: int | None) -> None:
        if self._state.set_weather_wind_direction(source, value):
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def set_weather_wind_variation(self, source: str, value: int | None) -> None:
        if self._state.set_weather_wind_variation(source, value):
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def set_show_boundaries(self, show: bool) -> None:
        if self._state.show_boundaries != show:
            self._state.show_boundaries = show
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def set_show_section_dividers(self, show: bool) -> None:
        if self._state.show_section_dividers != show:
            self._state.show_section_dividers = show
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def center_line_visible(self) -> bool:
        return self._state.show_center_line

    def ai_line_available(self) -> bool:
        return self._model.ai_line_available()

    def available_lp_files(self) -> list[str]:
        return list(self._model.available_lp_files)

    def ai_acceleration_window(self) -> int:
        return self._state.ai_acceleration_window

    def set_ai_acceleration_window(self, segments: int) -> None:
        clamped = max(1, segments)
        if self._state.ai_acceleration_window != clamped:
            self._state.ai_acceleration_window = clamped
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def ai_line_width(self) -> int:
        return self._state.ai_line_width

    def set_ai_line_width(self, width: int) -> None:
        clamped = max(1, width)
        if self._state.ai_line_width != clamped:
            self._state.ai_line_width = clamped
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def flag_radius(self) -> float:
        return self._state.flag_radius

    def set_flag_radius(self, radius: float) -> None:
        clamped = max(0.0, radius)
        if self._state.flag_radius != clamped:
            self._state.flag_radius = clamped
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def set_radius_raw_visible(self, enabled: bool) -> None:
        if self._state.show_radius_raw == enabled:
            return
        self._state.show_radius_raw = enabled
        self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def visible_lp_files(self) -> list[str]:
        return sorted(self._model.visible_lp_files)

    def set_visible_lp_files(self, names: list[str] | set[str]) -> None:
        if not self._model.set_visible_lp_files(names):
            return
        self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def active_lp_line(self) -> str:
        return self._state.active_lp_line

    def set_active_lp_line(self, name: str) -> None:
        target = "center-line"
        if name in self._model.available_lp_files:
            target = name
        elif name == "center-line":
            target = name
        if target == self._state.active_lp_line:
            return
        self._state.active_lp_line = target
        self._state.selected_lp_line = None
        self._state.selected_lp_index = None
        self._state.projection_cached_point = None
        self._state.projection_cached_result = None
        self._state.set_projection_data(None, None, None, None, None, None, None)
        self._emit_active_lp_line_changed(target)
        if target != "center-line":
            self._model.ai_line_records(target)
        self._handle_intent(PreviewIntent.PROJECTION_CHANGED)

    def ai_line_records(self, name: str) -> list[LpPoint]:
        return self._model.ai_line_records(name)

    def update_lp_record(self, lp_name: str, index: int) -> None:
        if not self._model.update_lp_record(lp_name, index):
            return
        self._state.projection_cached_point = None
        self._state.projection_cached_result = None
        self._handle_intent(PreviewIntent.PROJECTION_CHANGED)

    def save_active_lp_line(self) -> tuple[bool, str]:
        return self._model.save_lp_line(self._state.active_lp_line)

    def export_active_lp_csv(self, output_path: Path) -> tuple[bool, str]:
        return self._model.export_lp_csv(self._state.active_lp_line, output_path)

    def set_selected_lp_record(self, name: str | None, index: int | None) -> None:
        if name is None or index is None:
            if self._state.selected_lp_line is None and self._state.selected_lp_index is None:
                return
            self._state.selected_lp_line = None
            self._state.selected_lp_index = None
            self._handle_intent(PreviewIntent.SELECTION_CHANGED)
            return
        if name not in self._model.available_lp_files:
            return
        records = self._model.ai_line_records(name)
        if index < 0 or index >= len(records):
            return
        if self._state.selected_lp_line == name and self._state.selected_lp_index == index:
            return
        self._state.selected_lp_line = name
        self._state.selected_lp_index = index
        self._handle_intent(PreviewIntent.SELECTION_CHANGED)

    def set_lp_shortcut_active(self, active: bool) -> None:
        if self._state.lp_shortcut_active == active:
            return
        self._state.lp_shortcut_active = active
        self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def set_lp_dlat_step(self, step: int) -> None:
        clamped = max(0, int(step))
        if self._state.lp_dlat_step == clamped:
            return
        self._state.lp_dlat_step = clamped
        if self._state.lp_shortcut_active:
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def lp_color(self, name: str) -> str:
        override = self._state.lp_colors.get(name)
        if override:
            return override
        try:
            index = LP_FILE_NAMES.index(name)
        except ValueError:
            return "#e53935"
        return LP_COLORS[index % len(LP_COLORS)]

    def set_lp_color(self, name: str, color: str | None) -> None:
        if name == "center-line":
            return
        if color:
            candidate = QtGui.QColor(color)
            if not candidate.isValid():
                return
            self._state.lp_colors[name] = candidate.name()
        else:
            self._state.lp_colors.pop(name, None)
        self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def lp_color_overrides(self) -> dict[str, str]:
        return dict(self._state.lp_colors)

    def set_show_zoom_points(self, show: bool) -> None:
        if self._state.show_zoom_points != show:
            self._state.show_zoom_points = show
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def set_ai_speed_gradient_enabled(self, enabled: bool) -> None:
        self.set_ai_color_mode("speed" if enabled else "none")

    def set_ai_acceleration_gradient_enabled(self, enabled: bool) -> None:
        self.set_ai_color_mode("acceleration" if enabled else "none")

    def set_ai_color_mode(self, mode: str) -> None:
        if mode not in {"none", "speed", "acceleration"}:
            mode = "none"
        if self._state.ai_color_mode != mode:
            self._state.ai_color_mode = mode
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def track_length(self) -> Optional[int]:
        return int(self._model.track_length) if self._model.track_length is not None else None

    @property
    def trk(self) -> object | None:
        return self._model.trk

    def set_show_cameras(self, show: bool) -> None:
        if self._state.show_cameras != show:
            self._state.show_cameras = show
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def set_pit_parameters(self, params: PitParameters | None) -> None:
        if params == self._state.pit_params:
            return
        self._state.pit_params = params
        self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def set_visible_pit_indices(self, indices: set[int]) -> None:
        if indices == self._state.visible_pit_indices:
            return
        self._state.visible_pit_indices = set(indices)
        self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def set_show_pit_stall_center_dlat(self, show: bool) -> None:
        if self._state.show_pit_stall_center_dlat != show:
            self._state.show_pit_stall_center_dlat = show
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def set_show_pit_wall_dlat(self, show: bool) -> None:
        if self._state.show_pit_wall_dlat != show:
            self._state.show_pit_wall_dlat = show
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def set_show_pit_stall_cars(self, show: bool) -> None:
        if self._state.show_pit_stall_cars != show:
            self._state.show_pit_stall_cars = show
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def cameras(self) -> List[CameraPosition]:
        return list(self._camera_service.cameras)

    def update_camera_dlongs(
        self, camera_index: int, start_dlong: Optional[int], end_dlong: Optional[int]
    ) -> None:
        if camera_index < 0 or camera_index >= len(self._camera_service.cameras):
            return

        if self._state.selected_camera == camera_index:
            self._selection_controller.emit_selected_camera()
        self._handle_intent(PreviewIntent.CAMERA_CHANGED)

    def update_camera_position(
        self, camera_index: int, x: Optional[int], y: Optional[int], z: Optional[int]
    ) -> None:
        if camera_index < 0 or camera_index >= len(self._camera_service.cameras):
            return
        camera = self._camera_service.cameras[camera_index]
        if x is not None:
            camera.x = int(x)
        if y is not None:
            camera.y = int(y)
        if z is not None:
            camera.z = int(z)
        if self._state.selected_camera == camera_index:
            self._selection_controller.emit_selected_camera()
        self._handle_intent(PreviewIntent.CAMERA_CHANGED)

    def set_selected_camera(self, index: int | None) -> None:
        self._selection_controller.set_selected_camera(index)

    def add_type6_camera(self) -> tuple[bool, str]:
        success, message, selected = self._camera_edit_controller.add_type6_camera()
        if success and selected is not None:
            self.set_selected_camera(selected)
        self._emit_cameras_changed(
            self._camera_service.cameras, self._camera_service.camera_views
        )
        self._state.status_message = message
        self._handle_intent(PreviewIntent.CAMERA_CHANGED)
        return success, message

    def add_type7_camera(self) -> tuple[bool, str]:
        success, message, selected = self._camera_edit_controller.add_type7_camera()
        if success and selected is not None:
            self.set_selected_camera(selected)
        self._emit_cameras_changed(
            self._camera_service.cameras, self._camera_service.camera_views
        )
        self._state.status_message = message
        self._handle_intent(PreviewIntent.CAMERA_CHANGED)
        return success, message

    def load_track(self, track_folder: Path) -> None:
        if not track_folder:
            self.clear()
            return

        if self._model.track_path == track_folder:
            return

        self._state.status_message = f"Loading {track_folder.name}…"
        self._handle_intent(PreviewIntent.SURFACE_DATA_CHANGED)

        try:
            self._model.load_track(track_folder)
        except Exception as exc:  # pragma: no cover - interactive feedback
            self.clear(f"Failed to load track: {exc}")
            return

        self._state.projection_cached_point = None
        self._state.projection_cached_result = None
        if self._state.active_lp_line not in {"center-line", *self._model.available_lp_files}:
            self._state.active_lp_line = "center-line"
        self._state.set_projection_data(None, None, None, None, None, None, None)
        self._state.status_message = f"Loaded {track_folder.name}" if track_folder else ""
        self._state.view_center = self._state.default_center(self._model.bounds)
        self._state.user_transform_active = False
        self._state.update_fit_scale(self._model.bounds, self._last_size)
        self._state.flags = []
        self._selection_controller.set_selected_flag(None)
        self._camera_service.load_for_track(track_folder)
        self._emit_cameras_changed(
            self._camera_service.cameras, self._camera_service.camera_views
        )
        self.set_selected_camera(None)
        self._handle_intent(PreviewIntent.SURFACE_DATA_CHANGED)

    def save_cameras(self) -> tuple[bool, str]:
        if self._model.track_path is None:
            return False, "No track is currently loaded."

        try:
            self._state.status_message = self._camera_service.save()
            self._handle_intent(PreviewIntent.CAMERA_CHANGED)
        except Exception as exc:  # pragma: no cover - interactive feedback
            return False, f"Failed to save cameras: {exc}"

        return True, "Camera files saved successfully."

    def run_trk_gaps(self) -> tuple[bool, str]:
        if self._model.trk is None or self._model.track_path is None:
            return False, "No track is currently loaded."

        track_name = self._model.track_path.name
        trk_path = self._model.track_path / f"{track_name}.trk"
        header_label = str(trk_path if trk_path.exists() else trk_path.name)

        try:
            cline = get_cline_pos(self._model.trk)
            dist_list: list[float] = []
            lines = [header_label]

            for sect in range(-1, self._model.trk.num_sects - 1):
                xy2 = getxyz(
                    self._model.trk,
                    self._model.trk.sects[sect].start_dlong
                    + self._model.trk.sects[sect].length
                    - 1,
                    0,
                    cline,
                )
                xy1 = sect2xy(self._model.trk, sect + 1, cline)

                dist = math.dist((xy1[0], xy1[1]), (xy2[0], xy2[1]))

                dist_list.append(dist)
                lines.append(f"Sect {sect}/{sect + 1}, gap {dist:.1f}")

            if dist_list:
                lines.append(f"Max gap {max(dist_list):.1f}")
                lines.append(f"Min gap {min(dist_list):.1f}")
                lines.append(f"Sum gaps {sum(dist_list):.1f}")
            lines.append(f"Track length: {self._model.trk.trklength}")
        except Exception as exc:  # pragma: no cover - interactive feedback
            return False, f"Failed to compute TRK gaps: {exc}"

        return True, "\n".join(lines)
