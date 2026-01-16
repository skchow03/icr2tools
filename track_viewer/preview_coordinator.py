"""Non-Qt coordinator for the track preview domain logic."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, List, Optional

from PyQt5 import QtCore, QtGui

from icr2_core.cam.helpers import CameraPosition
from icr2_core.lp.loader import papy_speed_to_mph
from icr2_core.lp.rpy import Rpy
from icr2_core.trk.trk2csv import convert_trk_to_csv
from icr2_core.trk.trk2sg import trk_to_sg
from icr2_core.trk.trk_utils import get_cline_pos, getxyz, sect2xy
from track_viewer.ai.ai_line_service import LpPoint
from track_viewer.common.preview_constants import LP_COLORS, LP_FILE_NAMES
from track_viewer.controllers.camera_controller import CameraController
from track_viewer.model.lp_editing_session import LPChange, LPEditingSession
from track_viewer.model.pit_models import PitParameters
from track_viewer.model.track_preview_model import TrackPreviewModel
from track_viewer.model.view_state import TrackPreviewViewState
from track_viewer.rendering.renderer import TrackPreviewRenderer
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
        camera_position_changed: Callable[[int], None],
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
        self._emit_camera_position_changed = camera_position_changed
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
        self._lp_session = LPEditingSession(self._model)
        self._camera_service = CameraService(self._io_service, CameraController())
        self._renderer = TrackPreviewRenderer(
            self._model, self._camera_service, self._state, self._lp_session
        )
        self._interaction_callbacks = InteractionCallbacks(
            state_changed=self._handle_intent,
            cursor_position_changed=self._emit_cursor_position_changed,
            selected_flag_changed=self._emit_selected_flag_changed,
            selected_camera_changed=self._emit_selected_camera_changed,
            camera_position_changed=self._emit_camera_position_changed,
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
        self._lp_edit_controller = LpEditController(
            self._model, self._state, self._lp_session, self._interaction_callbacks
        )
        self._mouse_controller = TrackPreviewMouseController(
            self._model,
            self._state,
            self._lp_session,
            self._interaction_callbacks,
            self._selection_controller,
            self._camera_edit_controller,
            self._flag_edit_controller,
            self._lp_edit_controller,
        )
        self._keyboard_controller = TrackPreviewKeyboardController()
        self._replay_tab_active = False

    @property
    def mouse_controller(self) -> TrackPreviewMouseController:
        return self._mouse_controller

    @property
    def keyboard_controller(self) -> TrackPreviewKeyboardController:
        return self._keyboard_controller

    @property
    def lp_session(self) -> LPEditingSession:
        return self._lp_session

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

    def _apply_lp_changes(self, changes: set[LPChange]) -> None:
        if LPChange.DATA in changes:
            self._state.projection_cached_point = None
            self._state.projection_cached_result = None
            self._handle_intent(PreviewIntent.PROJECTION_CHANGED)
        if LPChange.SELECTION in changes:
            self._handle_intent(PreviewIntent.SELECTION_CHANGED)
        if changes & {LPChange.DATA, LPChange.VISIBILITY}:
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def apply_lp_changes(self, changes: set[LPChange]) -> None:
        self._apply_lp_changes(changes)

    # ------------------------------------------------------------------
    # Public API - state orchestration
    # ------------------------------------------------------------------
    def clear(self, message: str = "Select a track to preview.") -> None:
        lp_colors = dict(self._state.lp_colors)
        self._model.clear()
        self._state.reset(message)
        self._state.lp_colors = lp_colors
        self._lp_session.reset()
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
            if not show and self._lp_session.active_lp_line == "center-line":
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

    def weather_compass_heading_turns(self) -> float:
        return self._state.weather_compass_heading_turns()

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

    def flag_drawing_enabled(self) -> bool:
        return self._state.flag_drawing_enabled

    def set_flag_drawing_enabled(self, enabled: bool) -> None:
        if self._state.flag_drawing_enabled != enabled:
            self._state.flag_drawing_enabled = enabled

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
        return self._lp_session.active_lp_line

    def set_active_lp_line(self, name: str) -> None:
        before = self._lp_session.active_lp_line
        changes = self._lp_session.set_active_lp_line(name)
        if not changes and before == self._lp_session.active_lp_line:
            return
        self._state.projection_cached_point = None
        self._state.projection_cached_result = None
        self._state.set_projection_data(None, None, None, None, None, None, None)
        if before != self._lp_session.active_lp_line:
            self._emit_active_lp_line_changed(self._lp_session.active_lp_line)
        self._handle_intent(PreviewIntent.PROJECTION_CHANGED)
        self._apply_lp_changes(changes)

    def ai_line_records(self, name: str) -> list[LpPoint]:
        return self._lp_session.records(name)

    def lp_line_dirty(self, name: str) -> bool:
        return self._lp_session.is_dirty(name)

    def mark_lp_line_dirty(self, name: str) -> None:
        self._apply_lp_changes(self._lp_session.mark_dirty(name))

    def save_active_lp_line(self) -> tuple[bool, str]:
        return self._model.save_lp_line(self._lp_session.active_lp_line)

    def save_all_lp_lines(self) -> tuple[bool, str]:
        return self._model.save_all_lp_lines()

    def export_active_lp_csv(self, output_path: Path) -> tuple[bool, str]:
        return self._model.export_lp_csv(self._lp_session.active_lp_line, output_path)

    def export_all_lp_csvs(self, output_dir: Path) -> tuple[bool, str]:
        return self._model.export_all_lp_csvs(output_dir)

    def import_active_lp_csv(self, csv_path: Path) -> tuple[bool, str]:
        success, message = self._model.import_lp_csv(
            self._lp_session.active_lp_line, csv_path
        )
        if success:
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)
        return success, message

    def generate_lp_line(
        self, lp_name: str, speed_mph: float, dlat: float
    ) -> tuple[bool, str]:
        success, message, changes = self._lp_session.generate_lp_line(
            lp_name, speed_mph, dlat
        )
        self._apply_lp_changes(changes)
        return success, message

    def generate_lp_line_from_replay(
        self,
        lp_name: str,
        rpy: Rpy,
        car_id: int,
        start_frame: int,
        end_frame: int,
    ) -> tuple[bool, str]:
        success, message, changes = self._lp_session.generate_lp_line_from_replay(
            lp_name, rpy, car_id, start_frame, end_frame
        )
        self._apply_lp_changes(changes)
        return success, message

    def copy_lp_speeds_from_replay(
        self,
        lp_name: str,
        rpy: Rpy,
        car_id: int,
        start_frame: int,
        end_frame: int,
    ) -> tuple[bool, str]:
        success, message, changes = self._lp_session.copy_lp_speeds_from_replay(
            lp_name, rpy, car_id, start_frame, end_frame
        )
        self._apply_lp_changes(changes)
        return success, message

    def set_selected_lp_record(self, name: str | None, index: int | None) -> None:
        changes = self._lp_session.set_selected_lp_record(name, index)
        self._apply_lp_changes(changes)

    def set_lp_shortcut_active(self, active: bool) -> None:
        changes = self._lp_session.set_lp_shortcut_active(active)
        self._apply_lp_changes(changes)

    def set_lp_editing_tab_active(self, active: bool) -> None:
        changes = self._lp_session.set_lp_editing_tab_active(active)
        self._apply_lp_changes(changes)

    def set_lp_dlat_step(self, step: int) -> None:
        changes = self._lp_session.set_lp_dlat_step(step)
        self._apply_lp_changes(changes)

    def selected_lp_record(self) -> tuple[str, int] | None:
        return self._lp_session.selected_lp_record()

    def lp_shortcut_active(self) -> bool:
        return self._lp_session.lp_shortcut_active

    def lp_dlat_step(self) -> int:
        return self._lp_session.lp_dlat_step

    def lp_editing_tab_active(self) -> bool:
        return self._lp_session.lp_editing_tab_active

    def step_lp_selection(self, delta: int) -> None:
        changes = self._lp_session.step_selection(delta)
        self._apply_lp_changes(changes)

    def adjust_selected_lp_dlat(self, delta: int) -> None:
        changes = self._lp_session.adjust_selected_dlat(delta)
        self._apply_lp_changes(changes)

    def adjust_selected_lp_speed(self, delta_mph: float) -> None:
        changes = self._lp_session.adjust_selected_speed(delta_mph)
        self._apply_lp_changes(changes)

    def copy_selected_lp_fields(self, delta: int) -> None:
        changes = self._lp_session.copy_selected_fields(delta)
        self._apply_lp_changes(changes)

    def update_lp_record_dlat(self, lp_name: str, index: int, value: float) -> None:
        changes = self._lp_session.update_record_dlat(lp_name, index, value)
        self._apply_lp_changes(changes)

    def update_lp_record_speed(
        self, lp_name: str, index: int, value: float, *, raw_mode: bool
    ) -> None:
        changes = self._lp_session.update_record_speed(
            lp_name, index, value, raw_mode=raw_mode
        )
        self._apply_lp_changes(changes)

    def update_lp_record_lateral_speed(
        self, lp_name: str, index: int, value: float
    ) -> None:
        changes = self._lp_session.update_record_lateral_speed(lp_name, index, value)
        self._apply_lp_changes(changes)

    def recalculate_lateral_speeds(self, lp_name: str) -> None:
        changes = self._lp_session.recalculate_lateral_speeds(lp_name)
        self._apply_lp_changes(changes)

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

    def sampled_centerline(self) -> list[tuple[float, float]]:
        return list(self._model.sampled_centerline)

    @property
    def trk(self) -> object | None:
        return self._model.trk

    def track_path(self) -> Path | None:
        return self._model.track_path

    def trk_file_path(self) -> Path | None:
        return self._model.trk_file_path

    def set_show_cameras(self, show: bool) -> None:
        if self._state.show_cameras != show:
            self._state.show_cameras = show
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def set_show_cameras_current_tv_only(self, show: bool) -> None:
        if self._state.show_cameras_current_tv_only != show:
            self._state.show_cameras_current_tv_only = show
            self._handle_intent(PreviewIntent.CAMERA_CHANGED)

    def set_show_camera_guidance(self, show: bool) -> None:
        if self._state.show_camera_guidance != show:
            self._state.show_camera_guidance = show
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def set_current_tv_mode_index(self, index: int) -> None:
        clamped = max(0, int(index))
        if self._state.current_tv_mode_index != clamped:
            self._state.current_tv_mode_index = clamped
            self._handle_intent(PreviewIntent.CAMERA_CHANGED)

    def camera_selection_enabled(self) -> bool:
        return self._state.camera_selection_enabled

    def set_camera_selection_enabled(self, enabled: bool) -> None:
        if self._state.camera_selection_enabled == enabled:
            return
        self._state.camera_selection_enabled = enabled

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

    def set_replay_lap_samples(
        self,
        samples: list[tuple[float, float]] | None,
        *,
        label: str | None = None,
        fps: float = 15.0,
    ) -> None:
        if (
            not samples
            or self._model.trk is None
            or not self._model.centerline
            or fps <= 0
        ):
            changed = self._model.clear_replay_lap()
            self._state.show_replay_line = False
            if self._state.nearest_projection_line == "replay-lap":
                if self._state.set_projection_data(
                    None, None, None, None, None, None, None
                ):
                    self._handle_intent(PreviewIntent.PROJECTION_CHANGED)
            if changed:
                self._handle_intent(PreviewIntent.OVERLAY_CHANGED)
            return
        raw_points: list[tuple[float, float, float, float]] = []
        for dlong, dlat in samples:
            try:
                x, y, _ = getxyz(
                    self._model.trk, float(dlong), dlat, self._model.centerline
                )
            except Exception:
                continue
            raw_points.append((x, y, float(dlong), float(dlat)))
        if len(raw_points) < 2:
            changed = self._model.clear_replay_lap()
            self._state.show_replay_line = False
            if changed:
                self._handle_intent(PreviewIntent.OVERLAY_CHANGED)
            return
        segment_speeds: list[float] = []
        fps_factor = fps / 15 if fps > 0 else 0.0
        for idx in range(len(raw_points) - 1):
            _, _, dlong0, dlat0 = raw_points[idx]
            _, _, dlong1, dlat1 = raw_points[idx + 1]
            distance_raw = math.hypot(dlong1 - dlong0, dlat1 - dlat0)
            segment_speeds.append(papy_speed_to_mph(distance_raw) * fps_factor)
        points: list[LpPoint] = []
        for idx, (x, y, dlong, dlat) in enumerate(raw_points):
            if segment_speeds:
                prev_speed = segment_speeds[idx - 1] if idx > 0 else segment_speeds[0]
                next_speed = (
                    segment_speeds[idx]
                    if idx < len(segment_speeds)
                    else segment_speeds[-1]
                )
                speed_mph = (prev_speed + next_speed) / 2
            else:
                speed_mph = 0.0
            speed_raw = int(round(speed_mph * 5280 / 9))
            points.append(
                LpPoint(
                    x=x,
                    y=y,
                    dlong=dlong,
                    dlat=dlat,
                    speed_raw=speed_raw,
                    speed_mph=speed_mph,
                    lateral_speed=0.0,
                )
            )
        changed = self._model.set_replay_lap(points, label)
        show_replay_line = self._replay_tab_active
        show_changed = self._state.show_replay_line != show_replay_line
        self._state.show_replay_line = show_replay_line
        if changed or show_changed:
            self._handle_intent(PreviewIntent.OVERLAY_CHANGED)

    def set_replay_tab_active(self, active: bool) -> None:
        active = bool(active)
        if self._replay_tab_active == active:
            return
        self._replay_tab_active = active
        show_replay_line = active and bool(self._model.replay_lap_points)
        show_changed = self._state.show_replay_line != show_replay_line
        self._state.show_replay_line = show_replay_line
        if not show_replay_line and self._state.nearest_projection_line == "replay-lap":
            if self._state.set_projection_data(None, None, None, None, None, None, None):
                self._handle_intent(PreviewIntent.PROJECTION_CHANGED)
        if show_changed:
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

    def add_type2_camera(self) -> tuple[bool, str]:
        success, message, selected = self._camera_edit_controller.add_type2_camera()
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
        before_line = self._lp_session.active_lp_line
        changes = self._lp_session.sync_available_lines()
        if before_line != self._lp_session.active_lp_line:
            self._emit_active_lp_line_changed(self._lp_session.active_lp_line)
        self._apply_lp_changes(changes)
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

    def load_trk_file(self, trk_path: Path) -> None:
        if not trk_path:
            self.clear()
            return

        if self._model.trk_file_path == trk_path:
            return

        self._state.status_message = f"Loading {trk_path.name}…"
        self._handle_intent(PreviewIntent.SURFACE_DATA_CHANGED)

        try:
            self._model.load_trk_file(trk_path)
        except Exception as exc:  # pragma: no cover - interactive feedback
            self.clear(f"Failed to load TRK file: {exc}")
            return

        self._state.projection_cached_point = None
        self._state.projection_cached_result = None
        before_line = self._lp_session.active_lp_line
        changes = self._lp_session.sync_available_lines()
        if before_line != self._lp_session.active_lp_line:
            self._emit_active_lp_line_changed(self._lp_session.active_lp_line)
        self._apply_lp_changes(changes)
        self._state.set_projection_data(None, None, None, None, None, None, None)
        self._state.status_message = f"Loaded {trk_path.stem}"
        self._state.view_center = self._state.default_center(self._model.bounds)
        self._state.user_transform_active = False
        self._state.update_fit_scale(self._model.bounds, self._last_size)
        self._state.flags = []
        self._selection_controller.set_selected_flag(None)
        self._camera_service.reset()
        self._emit_cameras_changed([], [])
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
        if self._model.trk is None:
            return False, "No track is currently loaded."

        trk_path = None
        if self._model.track_path is not None:
            track_name = self._model.track_path.name
            trk_path = self._model.track_path / f"{track_name}.trk"
        elif self._model.trk_file_path is not None:
            trk_path = self._model.trk_file_path
        if trk_path is None:
            header_label = "TRK"
        else:
            header_label = (
                str(trk_path) if trk_path.exists() else trk_path.name
            )

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

    def convert_trk_to_sg(self, output_path: Path) -> tuple[bool, str]:
        if self._model.trk is None:
            return False, "No track is currently loaded."

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            sg = trk_to_sg(self._model.trk)
            sg.rebuild_dlongs(start_index=0, start_dlong=0)
            sg.output_sg(str(output_path))
        except Exception as exc:  # pragma: no cover - interactive feedback
            return False, f"Failed to convert TRK to SG: {exc}"

        return True, f"Saved SG file to {output_path}."

    def convert_trk_to_csv(self, output_path: Path) -> tuple[bool, str]:
        if self._model.trk is None:
            return False, "No track is currently loaded."

        trk_path = None
        if self._model.track_path is not None:
            track_name = self._model.track_path.name
            trk_path = self._model.track_path / f"{track_name}.trk"
        elif self._model.trk_file_path is not None:
            trk_path = self._model.trk_file_path
        if trk_path is None:
            return False, "TRK file path is not available."
        if not trk_path.exists():
            return False, f"TRK file not found at {trk_path}."

        try:
            convert_trk_to_csv(trk_path, output_path)
        except Exception as exc:  # pragma: no cover - interactive feedback
            return False, f"Failed to convert TRK to CSV: {exc}"

        return True, f"Saved CSV files to {output_path}."
