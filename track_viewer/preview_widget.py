"""Embedded surface preview widget for the standalone track viewer."""
from __future__ import annotations

import math
from pathlib import Path
from typing import List, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.cam.helpers import CameraPosition
from icr2_core.lp.lpcalc import get_trk_sect_radius
from icr2_core.trk.trk_utils import (
    dlong2sect,
    get_cline_pos,
    getbounddlat,
    getxyz,
    sect2xy,
)
from track_viewer import rendering
from track_viewer.ai_line_service import LpPoint
from track_viewer.camera_controller import CameraController
from track_viewer.camera_models import CameraViewEntry, CameraViewListing
from track_viewer.camera_service import CameraService
from track_viewer.geometry import project_point_to_centerline
from track_viewer.io_service import TrackIOService
from track_viewer.pit_models import (
    PIT_DLONG_LINE_COLORS,
    PIT_DLONG_LINE_INDICES,
    PitParameters,
)
from track_viewer.track_preview_model import TrackPreviewModel


LP_FILE_NAMES = [
    "RACE",
    "PASS1",
    "PASS2",
    "PIT",
    "MINRACE",
    "MAXRACE",
    "MINPANIC",
    "MAXPANIC",
    "PACE",
]


LP_COLORS = [
    "#e53935",
    "#8e24aa",
    "#3949ab",
    "#1e88e5",
    "#00897b",
    "#43a047",
    "#fdd835",
    "#fb8c00",
    "#6d4c41",
]


class TrackPreviewWidget(QtWidgets.QFrame):
    """Renders the TRK ground surface similar to the timing overlay."""

    cursorPositionChanged = QtCore.pyqtSignal(object)
    selectedFlagChanged = QtCore.pyqtSignal(object)
    camerasChanged = QtCore.pyqtSignal(list, list)
    selectedCameraChanged = QtCore.pyqtSignal(object, object)
    activeLpLineChanged = QtCore.pyqtSignal(str)
    aiLineLoaded = QtCore.pyqtSignal(str)
    lpRecordSelected = QtCore.pyqtSignal(str, int)
    diagramClicked = QtCore.pyqtSignal()

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(320, 240)
        self.setAutoFillBackground(True)
        self.setMouseTracking(True)

        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(24, 24, 24))
        self.setPalette(palette)

        self._status_message = "Select a track to preview."

        self._io_service = TrackIOService()
        self._model = TrackPreviewModel(self._io_service)
        self._model.aiLineLoaded.connect(self._handle_model_ai_line_loaded)
        self._cached_surface_pixmap: QtGui.QPixmap | None = None
        self._pixmap_size: QtCore.QSize | None = None
        self._show_center_line = True
        self._show_boundaries = True
        self._show_cameras = True
        self._show_zoom_points = False
        self._show_section_dividers = False
        self._ai_color_mode = "none"
        self._ai_acceleration_window = 3
        self._ai_line_width = 2
        self._flag_radius = 0.0
        self._show_radius_raw = False
        self._active_lp_line = "center-line"
        self._selected_lp_line: str | None = None
        self._selected_lp_index: int | None = None
        self._lp_shortcut_active = False
        self._lp_dlat_step = 0
        self._pit_params: PitParameters | None = None
        self._visible_pit_indices: set[int] = set(PIT_DLONG_LINE_INDICES)

        self._view_center: Tuple[float, float] | None = None
        self._fit_scale: float | None = None
        self._current_scale: float | None = 1.0
        self._user_transform_active = False
        self._is_panning = False
        self._last_mouse_pos: QtCore.QPoint | None = None
        self._left_press_pos: QtCore.QPoint | None = None
        self._dragged_during_press = False

        self._dragging_camera_index: int | None = None
        self._camera_dragged = False
        self._dragging_flag_index: int | None = None

        self._flags: List[Tuple[float, float]] = []
        self._selected_flag: int | None = None
        self._selected_camera: int | None = None
        self._nearest_projection_point: Tuple[float, float] | None = None
        self._nearest_projection_dlong: float | None = None
        self._nearest_projection_dlat: float | None = None
        self._nearest_projection_speed: float | None = None
        self._nearest_projection_elevation: float | None = None
        self._nearest_projection_acceleration: float | None = None
        self._nearest_projection_line: str | None = None
        self._projection_cached_point: QtCore.QPointF | None = None
        self._projection_cached_result: tuple[
            Tuple[float, float] | None,
            float | None,
            float | None,
            float | None,
            float | None,
            float | None,
            str | None,
        ] | None = None
        self._cursor_position: Tuple[float, float] | None = None
        self._camera_service = CameraService(self._io_service, CameraController())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def clear(self, message: str = "Select a track to preview.") -> None:
        self._model.clear()
        self._cached_surface_pixmap = None
        self._pixmap_size = None
        self._view_center = None
        self._fit_scale = None
        self._current_scale = 1.0
        self._user_transform_active = False
        self._is_panning = False
        self._last_mouse_pos = None
        self._left_press_pos = None
        self._dragged_during_press = False
        self._dragging_camera_index = None
        self._camera_dragged = False
        self._dragging_flag_index = None
        self._flags = []
        self._selected_flag = None
        self._selected_camera = None
        self._nearest_projection_point = None
        self._nearest_projection_dlong = None
        self._nearest_projection_dlat = None
        self._nearest_projection_speed = None
        self._nearest_projection_elevation = None
        self._nearest_projection_acceleration = None
        self._nearest_projection_line = None
        self._projection_cached_point = None
        self._projection_cached_result = None
        self._cursor_position = None
        self._active_lp_line = "center-line"
        self._selected_lp_line = None
        self._selected_lp_index = None
        self._pit_params = None
        self._camera_service.reset()
        self._status_message = message
        self.cursorPositionChanged.emit(None)
        self.selectedFlagChanged.emit(None)
        self.camerasChanged.emit([], [])
        self.selectedCameraChanged.emit(None, None)
        self.update()

    def tv_mode_count(self) -> int:
        return self._camera_service.tv_mode_count

    def set_tv_mode_count(self, count: int) -> None:
        updated_count = self._camera_service.set_tv_mode_count(count)
        if not updated_count:
            return
        self.camerasChanged.emit(
            self._camera_service.cameras, self._camera_service.camera_views
        )
        self.update()

    # ------------------------------------------------------------------
    # Center line controls
    # ------------------------------------------------------------------
    def set_show_center_line(self, show: bool) -> None:
        """Enable or disable rendering of the track center line."""

        if self._show_center_line != show:
            self._show_center_line = show
            if not show and self._active_lp_line == "center-line":
                self._set_projection_data(None, None, None, None, None, None, None)
            self.update()

    def set_show_boundaries(self, show: bool) -> None:
        """Enable or disable rendering of the track boundary edges."""

        if self._show_boundaries != show:
            self._show_boundaries = show
            self.update()

    def set_show_section_dividers(self, show: bool) -> None:
        """Enable or disable rendering of TRK section divider lines."""

        if self._show_section_dividers != show:
            self._show_section_dividers = show
            self.update()

    def center_line_visible(self) -> bool:
        return self._show_center_line

    def ai_line_available(self) -> bool:
        return self._model.ai_line_available()

    def available_lp_files(self) -> list[str]:
        return list(self._model.available_lp_files)

    def ai_acceleration_window(self) -> int:
        return self._ai_acceleration_window

    def set_ai_acceleration_window(self, segments: int) -> None:
        clamped = max(1, segments)
        if self._ai_acceleration_window != clamped:
            self._ai_acceleration_window = clamped
            self.update()

    def ai_line_width(self) -> int:
        return self._ai_line_width

    def set_ai_line_width(self, width: int) -> None:
        clamped = max(1, width)
        if self._ai_line_width != clamped:
            self._ai_line_width = clamped
            self.update()

    def flag_radius(self) -> float:
        return self._flag_radius

    def set_flag_radius(self, radius: float) -> None:
        clamped = max(0.0, radius)
        if self._flag_radius != clamped:
            self._flag_radius = clamped
            self.update()

    def set_radius_raw_visible(self, enabled: bool) -> None:
        if self._show_radius_raw == enabled:
            return
        self._show_radius_raw = enabled
        self.update()

    def _handle_model_ai_line_loaded(self, lp_name: str) -> None:
        self.aiLineLoaded.emit(lp_name)
        self.update()

    def visible_lp_files(self) -> list[str]:
        return sorted(self._model.visible_lp_files)

    def set_visible_lp_files(self, names: list[str] | set[str]) -> None:
        if not self._model.set_visible_lp_files(names):
            return
        self.update()

    def active_lp_line(self) -> str:
        return self._active_lp_line

    def set_active_lp_line(self, name: str) -> None:
        target = "center-line"
        if name in self._model.available_lp_files:
            target = name
        elif name == "center-line":
            target = name
        if target == self._active_lp_line:
            return
        self._active_lp_line = target
        self._selected_lp_line = None
        self._selected_lp_index = None
        self._projection_cached_point = None
        self._projection_cached_result = None
        self._set_projection_data(None, None, None, None, None, None, None)
        self.activeLpLineChanged.emit(target)
        if target != "center-line":
            self._model.ai_line_records(target)
        self.update()

    def ai_line_records(self, name: str) -> list[LpPoint]:
        return self._model.ai_line_records(name)

    def update_lp_record(self, lp_name: str, index: int) -> None:
        if not self._model.update_lp_record(lp_name, index):
            return
        self._projection_cached_point = None
        self._projection_cached_result = None
        self.update()

    def save_active_lp_line(self) -> tuple[bool, str]:
        return self._model.save_lp_line(self._active_lp_line)

    def export_active_lp_csv(self, output_path: Path) -> tuple[bool, str]:
        return self._model.export_lp_csv(self._active_lp_line, output_path)

    def set_selected_lp_record(self, name: str | None, index: int | None) -> None:
        if name is None or index is None:
            if self._selected_lp_line is None and self._selected_lp_index is None:
                return
            self._selected_lp_line = None
            self._selected_lp_index = None
            self.update()
            return
        if name not in self._model.available_lp_files:
            return
        records = self._model.ai_line_records(name)
        if index < 0 or index >= len(records):
            return
        if self._selected_lp_line == name and self._selected_lp_index == index:
            return
        self._selected_lp_line = name
        self._selected_lp_index = index
        self.update()

    def set_lp_shortcut_active(self, active: bool) -> None:
        if self._lp_shortcut_active == active:
            return
        self._lp_shortcut_active = active
        self.update()

    def set_lp_dlat_step(self, step: int) -> None:
        clamped = max(0, int(step))
        if self._lp_dlat_step == clamped:
            return
        self._lp_dlat_step = clamped
        if self._lp_shortcut_active:
            self.update()

    def lp_color(self, name: str) -> str:
        try:
            index = LP_FILE_NAMES.index(name)
        except ValueError:
            return "#e53935"
        return LP_COLORS[index % len(LP_COLORS)]

    def set_show_zoom_points(self, show: bool) -> None:
        """Enable or disable rendering of zoom DLONG markers."""

        if self._show_zoom_points != show:
            self._show_zoom_points = show
            self.update()

    def set_ai_speed_gradient_enabled(self, enabled: bool) -> None:
        """Toggle AI line rendering between solid colors and speed gradient."""

        self.set_ai_color_mode("speed" if enabled else "none")

    def set_ai_acceleration_gradient_enabled(self, enabled: bool) -> None:
        """Toggle AI line rendering between solid colors and acceleration gradient."""

        self.set_ai_color_mode("acceleration" if enabled else "none")

    def set_ai_color_mode(self, mode: str) -> None:
        if mode not in {"none", "speed", "acceleration"}:
            mode = "none"
        if self._ai_color_mode != mode:
            self._ai_color_mode = mode
            self.update()

    def track_length(self) -> Optional[int]:
        return int(self._model.track_length) if self._model.track_length is not None else None

    def set_show_cameras(self, show: bool) -> None:
        """Enable or disable rendering of track camera overlays."""

        if self._show_cameras != show:
            self._show_cameras = show
            self.update()

    def set_pit_parameters(self, params: PitParameters | None) -> None:
        if params == self._pit_params:
            return
        self._pit_params = params
        self.update()

    def set_visible_pit_indices(self, indices: set[int]) -> None:
        if indices == self._visible_pit_indices:
            return
        self._visible_pit_indices = set(indices)
        self.update()

    def cameras(self) -> List[CameraPosition]:
        return list(self._camera_service.cameras)

    def update_camera_dlongs(
        self, camera_index: int, start_dlong: Optional[int], end_dlong: Optional[int]
    ) -> None:
        if camera_index < 0 or camera_index >= len(self._camera_service.cameras):
            return

        # Editing start/end values in the TV modes table updates the segment
        # ranges directly on the shared camera view entries. We only need to
        # trigger a repaint so the centerline markers reflect the new values.
        if self._selected_camera == camera_index:
            self._emit_selected_camera()
        self.update()

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
        if self._selected_camera == camera_index:
            self._emit_selected_camera()
        self.update()

    def set_selected_camera(self, index: int | None) -> None:
        if index == self._selected_camera:
            return
        if index is not None:
            if index < 0 or index >= len(self._camera_service.cameras):
                index = None
        self._selected_camera = index
        self._emit_selected_camera()
        self.update()

    def add_type6_camera(self) -> tuple[bool, str]:
        """Create a new type 6 camera relative to the current selection."""
        success, message, selected = self._camera_service.add_type6_camera(
            self._selected_camera, self._model.track_length
        )
        if success and selected is not None:
            self.set_selected_camera(selected)
        self.camerasChanged.emit(
            self._camera_service.cameras, self._camera_service.camera_views
        )
        self._status_message = message
        self.update()
        return success, message

    def add_type7_camera(self) -> tuple[bool, str]:
        """Create a new type 7 camera relative to the current selection."""
        success, message, selected = self._camera_service.add_type7_camera(
            self._selected_camera, self._model.track_length
        )
        if success and selected is not None:
            self.set_selected_camera(selected)
        self.camerasChanged.emit(
            self._camera_service.cameras, self._camera_service.camera_views
        )
        self._status_message = message
        self.update()
        return success, message

    def _emit_selected_camera(self) -> None:
        selected = None
        index = self._selected_camera
        if index is not None and 0 <= index < len(self._camera_service.cameras):
            selected = self._camera_service.cameras[index]
        self.selectedCameraChanged.emit(index, selected)

    def load_track(self, track_folder: Path) -> None:
        """Load and render the contents of a track folder."""
        if not track_folder:
            self.clear()
            return

        if self._model.track_path == track_folder:
            return  # nothing to do

        self._status_message = f"Loading {track_folder.name}…"
        self.update()

        try:
            self._model.load_track(track_folder)
        except Exception as exc:  # pragma: no cover - interactive feedback
            self.clear(f"Failed to load track: {exc}")
            return

        self._projection_cached_point = None
        self._projection_cached_result = None
        if self._active_lp_line not in {"center-line", *self._model.available_lp_files}:
            self._active_lp_line = "center-line"
        self._set_projection_data(None, None, None, None, None, None, None)
        self._cached_surface_pixmap = None
        self._pixmap_size = None
        self._status_message = f"Loaded {track_folder.name}" if track_folder else ""
        self._view_center = self._default_center()
        self._user_transform_active = False
        self._update_fit_scale()
        self._flags = []
        self._set_selected_flag(None)
        self._camera_service.load_for_track(track_folder)
        self.camerasChanged.emit(
            self._camera_service.cameras, self._camera_service.camera_views
        )
        self.set_selected_camera(None)
        self.update()

    def save_cameras(self) -> tuple[bool, str]:
        """Persist the current camera data back to disk."""

        if self._model.track_path is None:
            return False, "No track is currently loaded."

        try:
            self._status_message = self._camera_service.save()
            self.update()
        except Exception as exc:  # pragma: no cover - interactive feedback
            return False, f"Failed to save cameras: {exc}"

        return True, "Camera files saved successfully."

    def run_trk_gaps(self) -> tuple[bool, str]:
        """Replicate the ``trk_gaps`` script for the currently loaded track."""

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

    def _default_center(self) -> Tuple[float, float] | None:
        if self._model.bounds:
            min_x, max_x, min_y, max_y = self._model.bounds
            return ((min_x + max_x) / 2, (min_y + max_y) / 2)
        return 0.0, 0.0

    def _calculate_fit_scale(self) -> float | None:
        if not self._model.bounds:
            return None
        min_x, max_x, min_y, max_y = self._model.bounds
        track_w = max_x - min_x
        track_h = max_y - min_y
        if track_w <= 0 or track_h <= 0:
            return None
        margin = 24
        w, h = self.width(), self.height()
        available_w = max(w - margin * 2, 1)
        available_h = max(h - margin * 2, 1)
        scale_x = available_w / track_w
        scale_y = available_h / track_h
        return min(scale_x, scale_y)

    def _get_ai_line_points(self, lp_name: str) -> List[Tuple[float, float]]:
        return [(p.x, p.y) for p in self._model.ai_line_records(lp_name)]

    def _update_fit_scale(self) -> None:
        fit = self._calculate_fit_scale()
        self._fit_scale = fit
        if fit is not None and not self._user_transform_active:
            self._current_scale = fit
            if self._view_center is None:
                self._view_center = self._default_center()
            self._invalidate_cache()

    def _current_transform(self) -> Tuple[float, Tuple[float, float]] | None:
        if self._current_scale is None:
            self._update_fit_scale()
        if self._current_scale is None:
            self._current_scale = 1.0
        center = self._view_center or self._default_center()
        if center is None:
            return None
        w, h = self.width(), self.height()
        offsets = (w / 2 - center[0] * self._current_scale, h / 2 - center[1] * self._current_scale)
        return self._current_scale, offsets

    def _invalidate_cache(self) -> None:
        self._cached_surface_pixmap = None
        self._pixmap_size = None

    def _map_to_track(self, point: QtCore.QPointF) -> Tuple[float, float] | None:
        transform = self._current_transform()
        if not transform:
            return None
        scale, offsets = transform
        x = (point.x() - offsets[0]) / scale
        py = self.height() - point.y()
        y = (py - offsets[1]) / scale
        return x, y

    def _clamp_scale(self, scale: float) -> float:
        base = self._fit_scale or self._current_scale or 1.0
        min_scale = base * 0.1
        max_scale = base * 25.0
        return max(min_scale, min(max_scale, scale))

    # ------------------------------------------------------------------
    # Qt events
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: D401 - Qt signature
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), self.palette().color(QtGui.QPalette.Window))

        if not self._model.surface_mesh or not self._model.bounds:
            painter.setPen(QtGui.QPen(QtGui.QColor("lightgray")))
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, self._status_message)
            return

        transform = self._current_transform()
        if self._cached_surface_pixmap is None or self._pixmap_size != self.size():
            self._cached_surface_pixmap = rendering.render_surface_to_pixmap(
                self._model.surface_mesh, transform, self.size()
            )
            self._pixmap_size = self.size()

        painter.drawPixmap(0, 0, self._cached_surface_pixmap)

        if transform and self._show_boundaries:
            rendering.draw_track_boundaries(
                painter, self._model.boundary_edges, transform, self.height()
            )

        if self._show_center_line and self._model.sampled_centerline and transform:
            rendering.draw_centerline(
                painter,
                self._model.sampled_centerline,
                transform,
                self.height(),
            )

        if transform and self._show_center_line:
            rendering.draw_start_finish_line(
                painter,
                transform,
                self.height(),
                self._centerline_point_and_normal,
            )

        if transform and self._show_center_line:
            rendering.draw_camera_range_markers(
                painter,
                self._camera_view_ranges(self._selected_camera),
                transform,
                self.height(),
                self._centerline_point_and_normal,
            )

        if transform and self._nearest_projection_point:
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            highlight = rendering.map_point(
                self._nearest_projection_point[0],
                self._nearest_projection_point[1],
                transform,
                self.height(),
            )
            pen = QtGui.QPen(QtGui.QColor("#ff5252"))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(QtGui.QBrush(QtGui.QColor("#ff5252")))
            painter.drawEllipse(highlight, 5, 5)

        if transform:
            if self._show_cameras:
                rendering.draw_camera_positions(
                    painter,
                    self._camera_service.cameras,
                    self._selected_camera,
                    transform,
                    self.height(),
                )
            rendering.draw_ai_lines(
                painter,
                self._model.visible_lp_files,
                self._get_ai_line_points,
                transform,
                self.height(),
                self.lp_color,
                gradient=self._ai_color_mode,
                get_records=self._model.ai_line_records,
                line_width=self._ai_line_width,
                acceleration_window=self._ai_acceleration_window,
            )
            if (
                self._selected_lp_line
                and self._selected_lp_index is not None
                and self._selected_lp_line in self._model.visible_lp_files
            ):
                records = self._model.ai_line_records(self._selected_lp_line)
                if len(records) >= 2:
                    index = self._selected_lp_index
                    if 0 <= index < len(records):
                        record = records[index]
                        painter.setRenderHint(
                            QtGui.QPainter.Antialiasing, True
                        )
                        marker = rendering.map_point(
                            record.x, record.y, transform, self.height()
                        )
                        pen = QtGui.QPen(QtGui.QColor("#fdd835"))
                        pen.setWidth(1)
                        painter.setPen(pen)
                        painter.setBrush(QtGui.QBrush(QtGui.QColor("#fdd835")))
                        painter.drawEllipse(marker, 4, 4)
                    start_index = index
                    end_index = index + 1
                    if end_index >= len(records):
                        end_index = index
                        start_index = index - 1
                    if 0 <= start_index < len(records) and 0 <= end_index < len(records):
                        start_record = records[start_index]
                        end_record = records[end_index]
                        rendering.draw_lp_segment(
                            painter,
                            (start_record.x, start_record.y),
                            (end_record.x, end_record.y),
                            transform,
                            self.height(),
                        )
            rendering.draw_flags(
                painter,
                self._flags,
                self._selected_flag,
                transform,
                self.height(),
                self._flag_radius,
            )
            if self._show_section_dividers:
                rendering.draw_pit_dlong_lines(
                    painter,
                    self._section_divider_segments(),
                    transform,
                    self.height(),
                    width=1,
                )
            rendering.draw_pit_dlong_lines(
                painter,
                self._pit_dlong_segments(),
                transform,
                self.height(),
            )
            if self._show_zoom_points:
                rendering.draw_zoom_points(
                    painter,
                    self._zoom_points_for_camera(),
                    transform,
                    self.height(),
                    self._centerline_point,
                )

        self._draw_lp_shortcut_overlay(painter)
        painter.setPen(QtGui.QPen(QtGui.QColor("white")))
        y = 20
        if self._model.track_length is not None:
            track_length_text = (
                f"Track length: {int(round(self._model.track_length))} DLONG"
            )
            painter.drawText(12, y, track_length_text)
            y += 16
        painter.drawText(12, y, self._status_message)
        y += 16
        if self._nearest_projection_line:
            line_label = (
                "Center line"
                if self._nearest_projection_line == "center-line"
                else f"{self._nearest_projection_line} line"
            )
            painter.drawText(12, y, line_label)
            y += 16
        if self._nearest_projection_dlong is not None:
            dlong_text = f"DLONG: {int(round(self._nearest_projection_dlong))}"
            painter.drawText(12, y, dlong_text)
            y += 16
        if (
            self._nearest_projection_line == "center-line"
            and self._nearest_projection_dlong is not None
        ):
            for line in self._centerline_section_info(self._nearest_projection_dlong):
                painter.drawText(12, y, line)
                y += 16
        if self._nearest_projection_dlat is not None:
            dlat_text = f"DLAT: {int(round(self._nearest_projection_dlat))}"
            painter.drawText(12, y, dlat_text)
            y += 16
        if self._nearest_projection_speed is not None:
            speed_text = f"Speed: {self._nearest_projection_speed:.1f} mph"
            painter.drawText(12, y, speed_text)
            y += 16
        if self._nearest_projection_acceleration is not None:
            accel_text = f"Accel: {self._nearest_projection_acceleration:+.3f} ft/s²"
            painter.drawText(12, y, accel_text)
            y += 16
        if self._nearest_projection_elevation is not None:
            elevation_text = (
                f"Elevation: {self._nearest_projection_elevation:.2f} (DLAT = 0)"
            )
            painter.drawText(12, y, elevation_text)

        self._draw_cursor_position(painter)

    def _draw_lp_shortcut_overlay(self, painter: QtGui.QPainter) -> None:
        if not self._lp_shortcut_active:
            return
        metrics = painter.fontMetrics()
        line_height = metrics.height()
        margin = 12
        step_value = self._lp_dlat_step
        lp_index_text = (
            "LP index: —"
            if self._selected_lp_index is None
            else f"LP index: {self._selected_lp_index}"
        )
        lines = [
            "LP arrow-key editing active:",
            "UP - next LP record",
            "DOWN - previous LP record",
            f"LEFT - increase DLAT by {step_value}",
            f"RIGHT - decrease DLAT by {step_value}",
            lp_index_text,
        ]
        max_width = max(metrics.horizontalAdvance(line) for line in lines)
        start_x = self.width() - margin - max_width
        start_y = margin + metrics.ascent()
        painter.setPen(QtGui.QPen(QtGui.QColor("white")))
        for line in lines:
            painter.drawText(start_x, start_y, line)
            start_y += line_height

    def resizeEvent(self, event) -> None:  # noqa: D401 - Qt signature
        self._pixmap_size = None
        self._cached_surface_pixmap = None
        self._update_fit_scale()
        super().resizeEvent(event)

    # ------------------------------------------------------------------
    # Interaction handlers
    # ------------------------------------------------------------------
    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:  # noqa: D401 - Qt signature
        if self._current_scale is None:
            self._current_scale = self._fit_scale or 1.0
        delta = event.angleDelta().y()
        if delta == 0:
            return
        if self._view_center is None:
            self._view_center = self._default_center()
        if self._view_center is None or self._current_scale is None:
            return
        factor = 1.15 if delta > 0 else 1 / 1.15
        new_scale = self._clamp_scale(self._current_scale * factor)
        cursor_track = self._map_to_track(event.pos())
        if cursor_track is None:
            cursor_track = self._view_center
        w, h = self.width(), self.height()
        px, py = event.pos().x(), event.pos().y()
        cx = cursor_track[0] - (px - w / 2) / new_scale
        cy = cursor_track[1] + (py - h / 2) / new_scale
        self._view_center = (cx, cy)
        self._current_scale = new_scale
        self._user_transform_active = True
        self._invalidate_cache()
        self.update()
        event.accept()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401 - Qt signature
        if event.button() == QtCore.Qt.RightButton and self._model.surface_mesh:
            if self._handle_flag_removal(event.pos()):
                event.accept()
                return

        if event.button() == QtCore.Qt.LeftButton:
            self.diagramClicked.emit()
            if self._model.surface_mesh and self._handle_camera_press(event.pos()):
                event.accept()
                return
            if self._model.surface_mesh and self._handle_flag_press(event.pos()):
                event.accept()
                return
            self._is_panning = True
            self._last_mouse_pos = event.pos()
            self._left_press_pos = event.pos()
            self._dragged_during_press = False
            self._user_transform_active = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401 - Qt signature
        handled = False
        if self._dragging_camera_index is not None:
            self._update_camera_position(event.pos())
            event.accept()
            handled = True
        if self._dragging_flag_index is not None:
            self._update_flag_position(event.pos())
            event.accept()
            handled = True
        if self._is_panning and self._last_mouse_pos is not None:
            transform = self._current_transform()
            if transform:
                if self._view_center is None:
                    self._view_center = self._default_center()
                if self._view_center is not None:
                    scale, _ = transform
                    delta = event.pos() - self._last_mouse_pos
                    self._last_mouse_pos = event.pos()
                    if (
                        not self._dragged_during_press
                        and self._left_press_pos is not None
                        and (event.pos() - self._left_press_pos).manhattanLength() > 4
                    ):
                        self._dragged_during_press = True
                    cx, cy = self._view_center
                    cx -= delta.x() / scale
                    cy += delta.y() / scale
                    self._view_center = (cx, cy)
                    self._invalidate_cache()
                    self.update()
            event.accept()
            handled = True
        self._update_cursor_position(event.pos())
        if not handled:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401 - Qt signature
        if event.button() == QtCore.Qt.LeftButton:
            if self._dragging_camera_index is not None:
                self._dragging_camera_index = None
                self._camera_dragged = False
                event.accept()
                return
            if self._dragging_flag_index is not None:
                self._dragging_flag_index = None
                event.accept()
                return
            click_without_drag = not self._dragged_during_press
            self._is_panning = False
            self._last_mouse_pos = None
            self._left_press_pos = None
            self._dragged_during_press = False
            if click_without_drag and self._model.surface_mesh:
                self._handle_primary_click(event.pos())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: D401 - Qt signature
        self.cursorPositionChanged.emit(None)
        if self._cursor_position is not None:
            self._cursor_position = None
            self.update()
        self._set_projection_data(None, None, None, None, None, None, None)
        super().leaveEvent(event)

    # ------------------------------------------------------------------
    # Cursor & flag helpers
    # ------------------------------------------------------------------
    def _update_cursor_position(self, point: QtCore.QPointF) -> None:
        if not self._model.surface_mesh or not self._model.bounds:
            self.cursorPositionChanged.emit(None)
            if self._cursor_position is not None:
                self._cursor_position = None
                self.update()
            self._set_projection_data(None, None, None, None, None, None, None)
            return
        coords = self._map_to_track(point)
        if coords != self._cursor_position:
            self._cursor_position = coords
            self.update()
        self.cursorPositionChanged.emit(coords)
        self._update_active_line_projection(point)

    def _set_projection_data(
        self,
        point: Tuple[float, float] | None,
        dlong: float | None,
        dlat: float | None,
        speed: float | None,
        elevation: float | None,
        acceleration: float | None,
        line_name: str | None,
    ) -> None:
        if (
            point == self._nearest_projection_point
            and dlong == self._nearest_projection_dlong
            and dlat == self._nearest_projection_dlat
            and speed == self._nearest_projection_speed
            and elevation == self._nearest_projection_elevation
            and acceleration == self._nearest_projection_acceleration
            and line_name == self._nearest_projection_line
        ):
            return
        self._nearest_projection_point = point
        self._nearest_projection_dlong = dlong
        self._nearest_projection_dlat = dlat
        self._nearest_projection_speed = speed
        self._nearest_projection_elevation = elevation
        self._nearest_projection_acceleration = acceleration
        self._nearest_projection_line = line_name
        self.update()

    def _update_active_line_projection(self, point: QtCore.QPointF | None) -> None:
        active = self._active_lp_line if self._active_lp_line else "center-line"
        if active != "center-line" and active not in self._model.available_lp_files:
            active = "center-line"
        if active == "center-line":
            self._update_centerline_projection(point)
            return
        self._update_ai_line_projection(point, active)

    def _update_centerline_projection(self, point: QtCore.QPointF | None) -> None:
        if (
            point is None
            or not self._model.sampled_centerline
            or not self._model.sampled_dlongs
            or not self._show_center_line
        ):
            self._set_projection_data(None, None, None, None, None, None, None)
            return

        if (
            self._projection_cached_point is not None
            and self._projection_cached_result is not None
            and (point - self._projection_cached_point).manhattanLength() <= 3
            and self._projection_cached_result[-1] == "center-line"
        ):
            (
                cached_point,
                cached_dlong,
                cached_dlat,
                cached_speed,
                cached_elevation,
                cached_acceleration,
                cached_line,
            ) = self._projection_cached_result
            self._set_projection_data(
                cached_point,
                cached_dlong,
                cached_dlat,
                cached_speed,
                cached_elevation,
                cached_acceleration,
                cached_line,
            )
            return

        transform = self._current_transform()
        if not transform or not self._model.trk:
            self._set_projection_data(None, None, None, None, None, None, None)
            return

        screen_bounds = rendering.centerline_screen_bounds(
            self._model.sampled_bounds, transform, self.height()
        )
        if screen_bounds:
            dx = max(screen_bounds.left() - point.x(), 0.0, point.x() - screen_bounds.right())
            dy = max(screen_bounds.top() - point.y(), 0.0, point.y() - screen_bounds.bottom())
            if max(dx, dy) > 24:
                self._projection_cached_point = point
                self._projection_cached_result = (
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                    None,
                )
                self._set_projection_data(None, None, None, None, None, None, None)
                return

        cursor_track = self._map_to_track(point)
        if cursor_track is None:
            self._set_projection_data(None, None, None, None, None, None, None)
            return

        if self._model.centerline_index is None:
            self._set_projection_data(None, None, None, None, None, None, None)
            return

        cursor_x, cursor_y = cursor_track
        track_length = float(self._model.trk.trklength)
        best_point, best_dlong, best_distance_sq = project_point_to_centerline(
            (cursor_x, cursor_y),
            self._model.centerline_index,
            self._model.sampled_dlongs,
            track_length,
        )

        if best_point is None:
            self._set_projection_data(None, None, None, None, None, None, None)
            return
        mapped_point = rendering.map_point(
            best_point[0], best_point[1], transform, self.height()
        )
        pixel_distance = (mapped_point - point).manhattanLength()
        if pixel_distance > 16:
            self._projection_cached_point = point
            self._projection_cached_result = (
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )
            self._set_projection_data(None, None, None, None, None, None, None)
            return
        elevation = None
        if best_dlong is not None and self._model.centerline:
            _, _, elevation = getxyz(
                self._model.trk, float(best_dlong), 0, self._model.centerline
            )
        self._projection_cached_point = point
        self._projection_cached_result = (
            best_point,
            best_dlong,
            0.0,
            None,
            elevation,
            None,
            "center-line",
        )
        self._set_projection_data(
            best_point, best_dlong, 0.0, None, elevation, None, "center-line"
        )

    def _update_ai_line_projection(
        self, point: QtCore.QPointF | None, lp_name: str
    ) -> None:
        if point is None or lp_name not in self._model.visible_lp_files:
            self._set_projection_data(None, None, None, None, None, None, None)
            return

        records = self._model.ai_line_records(lp_name)
        if not records:
            self._set_projection_data(None, None, None, None, None, None, None)
            return

        if (
            self._projection_cached_point is not None
            and self._projection_cached_result is not None
            and (point - self._projection_cached_point).manhattanLength() <= 3
            and self._projection_cached_result[-1] == lp_name
        ):
            (
                cached_point,
                cached_dlong,
                cached_dlat,
                cached_speed,
                cached_elevation,
                cached_acceleration,
                cached_line,
            ) = self._projection_cached_result
            self._set_projection_data(
                cached_point,
                cached_dlong,
                cached_dlat,
                cached_speed,
                cached_elevation,
                cached_acceleration,
                cached_line,
            )
            return

        transform = self._current_transform()
        if not transform or not self._model.trk:
            self._set_projection_data(None, None, None, None, None, None, None)
            return

        cursor_track = self._map_to_track(point)
        if cursor_track is None:
            self._set_projection_data(None, None, None, None, None, None, None)
            return

        cursor_x, cursor_y = cursor_track
        best_point: Tuple[float, float] | None = None
        best_distance_sq = math.inf
        best_dlong = None
        best_dlat = None
        best_speed = None
        best_accel = None

        track_length = float(self._model.trk.trklength) if self._model.trk else None
        for idx in range(len(records)):
            p0 = records[idx]
            p1 = records[(idx + 1) % len(records)]
            seg_dx = p1.x - p0.x
            seg_dy = p1.y - p0.y
            seg_len_sq = seg_dx * seg_dx + seg_dy * seg_dy
            if seg_len_sq == 0:
                continue
            t = ((cursor_x - p0.x) * seg_dx + (cursor_y - p0.y) * seg_dy) / seg_len_sq
            t = max(0.0, min(1.0, t))
            proj_x = p0.x + seg_dx * t
            proj_y = p0.y + seg_dy * t
            dist_sq = (cursor_x - proj_x) ** 2 + (cursor_y - proj_y) ** 2
            if dist_sq < best_distance_sq:
                best_distance_sq = dist_sq
                best_point = (proj_x, proj_y)
                dlong_delta = p1.dlong - p0.dlong
                if track_length is not None and dlong_delta < 0:
                    dlong_delta += track_length
                interp_dlong = p0.dlong + dlong_delta * t
                if track_length is not None and interp_dlong >= track_length:
                    interp_dlong -= track_length
                best_dlong = interp_dlong
                best_dlat = p0.dlat + (p1.dlat - p0.dlat) * t
                best_speed = p0.speed_mph + (p1.speed_mph - p0.speed_mph) * t
                best_accel = rendering.compute_segment_acceleration(
                    p0, p1, track_length=track_length
                )

        if best_point is None:
            self._set_projection_data(None, None, None, None, None, None, None)
            return

        mapped_point = rendering.map_point(best_point[0], best_point[1], transform, self.height())
        pixel_distance = (mapped_point - point).manhattanLength()
        if pixel_distance > 16:
            self._projection_cached_point = point
            self._projection_cached_result = (
                None,
                None,
                None,
                None,
                None,
                None,
                None,
            )
            self._set_projection_data(None, None, None, None, None, None, None)
            return

        self._projection_cached_point = point
        self._projection_cached_result = (
            best_point,
            best_dlong,
            best_dlat,
            best_speed,
            None,
            best_accel,
            lp_name,
        )
        self._set_projection_data(
            best_point,
            best_dlong,
            best_dlat,
            best_speed,
            None,
            best_accel,
            lp_name,
        )

    def _draw_cursor_position(self, painter: QtGui.QPainter) -> None:
        if self._cursor_position is None:
            return

        x, y = self._cursor_position
        lines = [
            f"Cursor X: {self._format_cursor_value(x)}",
            f"Cursor Y: {self._format_cursor_value(y)}",
        ]

        metrics = painter.fontMetrics()
        line_height = metrics.height()
        margin = 12
        max_width = max(metrics.horizontalAdvance(line) for line in lines)
        start_x = self.width() - margin - max_width
        start_y = (
            self.height()
            - margin
            - metrics.descent()
            - (len(lines) - 1) * line_height
        )

        painter.setPen(QtGui.QPen(QtGui.QColor("white")))
        for line in lines:
            painter.drawText(start_x, start_y, line)
            start_y += line_height

    def _centerline_section_info(self, dlong: float) -> list[str]:
        if self._model.trk is None:
            return []
        sect_info = dlong2sect(self._model.trk, dlong)
        if not sect_info:
            return []
        sect_index, _ = sect_info
        if sect_index is None or not (0 <= sect_index < self._model.trk.num_sects):
            return []
        section = self._model.trk.sects[sect_index]
        section_lines = [
            f"Section: {sect_index}",
            "Type: Curve" if section.type == 2 else "Type: Straight",
        ]
        if section.type == 2:
            radius_value: float | None = None
            if hasattr(section, "radius"):
                radius_value = float(section.radius)
            elif sect_index < self._model.trk.num_sects - 1:
                try:
                    radius_value = get_trk_sect_radius(self._model.trk, sect_index)
                except ZeroDivisionError:
                    radius_value = None
            if radius_value is not None and math.isfinite(radius_value):
                radius = abs(radius_value)
                if self._show_radius_raw:
                    section_lines.append(f"Radius: {int(round(radius))} 500ths")
                else:
                    radius_feet = radius * rendering.DLONG_TO_FEET
                    section_lines.append(f"Radius: {radius_feet:.2f} ft")
        return section_lines

    @staticmethod
    def _format_cursor_value(value: float) -> str:
        return f"{value:.2f}"

    def _camera_at_point(self, point: QtCore.QPointF, radius: int = 10) -> int | None:
        transform = self._current_transform()
        if not transform:
            return None
        for index, cam in enumerate(self._camera_service.cameras):
            camera_point = rendering.map_point(
                cam.x, cam.y, transform, self.height()
            )
            if (camera_point - point).manhattanLength() <= radius:
                return index
        return None

    def _handle_camera_press(self, point: QtCore.QPointF) -> bool:
        camera_index = self._camera_at_point(point)
        if camera_index is None:
            return False
        self.set_selected_camera(camera_index)
        self._dragging_camera_index = camera_index
        self._camera_dragged = False
        self._is_panning = False
        self._dragged_during_press = False
        return True

    def _handle_flag_press(self, point: QtCore.QPointF) -> bool:
        flag_index = self._flag_at_point(point)
        if flag_index is None:
            return False
        self._set_selected_flag(flag_index)
        self._dragging_flag_index = flag_index
        self._is_panning = False
        self._dragged_during_press = False
        return True

    def _update_camera_position(self, point: QtCore.QPointF) -> None:
        if self._dragging_camera_index is None:
            return
        coords = self._map_to_track(point)
        if coords is None:
            return
        index = self._dragging_camera_index
        if index < 0 or index >= len(self._camera_service.cameras):
            return
        cam = self._camera_service.cameras[index]
        cam.x = int(round(coords[0]))
        cam.y = int(round(coords[1]))
        self._camera_dragged = True
        self._emit_selected_camera()
        self.update()

    def _update_flag_position(self, point: QtCore.QPointF) -> None:
        if self._dragging_flag_index is None:
            return
        coords = self._map_to_track(point)
        if coords is None:
            return
        index = self._dragging_flag_index
        if index < 0 or index >= len(self._flags):
            return
        self._flags[index] = coords
        self.selectedFlagChanged.emit(coords)
        self.update()

    def _centerline_point_and_normal(
        self, dlong: float
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        if not self._model.trk or not self._model.centerline:
            return None
        track_length = float(self._model.trk.trklength)
        if track_length <= 0:
            return None

        def _wrap(value: float) -> float:
            while value < 0:
                value += track_length
            while value >= track_length:
                value -= track_length
            return value

        base = _wrap(float(dlong))
        delta = max(50.0, track_length * 0.002)
        prev_dlong = _wrap(base - delta)
        next_dlong = _wrap(base + delta)

        px, py, _ = getxyz(self._model.trk, prev_dlong, 0, self._model.centerline)
        nx, ny, _ = getxyz(self._model.trk, next_dlong, 0, self._model.centerline)
        cx, cy, _ = getxyz(self._model.trk, base, 0, self._model.centerline)

        vx = nx - px
        vy = ny - py
        length = (vx * vx + vy * vy) ** 0.5
        if length == 0:
            return None
        normal = (-vy / length, vx / length)
        return (cx, cy), normal

    def _centerline_point(self, dlong: float) -> tuple[float, float] | None:
        if not self._model.trk or not self._model.centerline:
            return None
        track_length = float(self._model.trk.trklength)
        if track_length <= 0:
            return None
        wrapped = dlong % track_length
        cx, cy, _ = getxyz(self._model.trk, wrapped, 0, self._model.centerline)
        return cx, cy

    def _pit_dlong_segments(
        self,
    ) -> list[tuple[tuple[float, float], tuple[float, float], str]]:
        if (
            self._model.trk is None
            or not self._model.centerline
            or self._pit_params is None
            or not self._visible_pit_indices
        ):
            return []
        track_length = float(self._model.trk.trklength or 0.0)
        if track_length <= 0:
            return []
        values = self._pit_params.values()
        segments: list[tuple[tuple[float, float], tuple[float, float], str]] = []
        for index in sorted(self._visible_pit_indices):
            if index < 0 or index >= len(values):
                continue
            dlong = float(values[index])
            dlong = dlong % track_length
            sect_info = dlong2sect(self._model.trk, dlong)
            if not sect_info:
                continue
            sect_index, subsect = sect_info
            if sect_index is None or subsect is None:
                continue
            section = self._model.trk.sects[sect_index]
            dlats: list[float] = []
            for bound_index in range(section.num_bounds):
                dlats.append(
                    getbounddlat(self._model.trk, sect_index, subsect, bound_index)
                )
            if not dlats:
                continue
            min_dlat = min(dlats)
            max_dlat = max(dlats)
            start_x, start_y, _ = getxyz(
                self._model.trk, dlong, min_dlat, self._model.centerline
            )
            end_x, end_y, _ = getxyz(
                self._model.trk, dlong, max_dlat, self._model.centerline
            )
            color = PIT_DLONG_LINE_COLORS.get(index, "#ffffff")
            segments.append(((start_x, start_y), (end_x, end_y), color))
        return segments

    def _section_divider_segments(
        self,
    ) -> list[tuple[tuple[float, float], tuple[float, float], str]]:
        if self._model.trk is None or not self._model.centerline:
            return []
        track_length = float(self._model.trk.trklength or 0.0)
        if track_length <= 0:
            return []
        segments: list[tuple[tuple[float, float], tuple[float, float], str]] = []
        seen_dlongs: set[float] = set()
        for section in self._model.trk.sects:
            try:
                dlong = float(section.start_dlong)
            except (TypeError, ValueError):
                continue
            dlong = dlong % track_length
            if dlong in seen_dlongs:
                continue
            seen_dlongs.add(dlong)
            sect_info = dlong2sect(self._model.trk, dlong)
            if not sect_info:
                continue
            sect_index, subsect = sect_info
            if sect_index is None or subsect is None:
                continue
            sect = self._model.trk.sects[sect_index]
            dlats: list[float] = []
            for bound_index in range(sect.num_bounds):
                dlats.append(
                    getbounddlat(self._model.trk, sect_index, subsect, bound_index)
                )
            if not dlats:
                continue
            min_dlat = min(dlats)
            max_dlat = max(dlats)
            start_x, start_y, _ = getxyz(
                self._model.trk, dlong, min_dlat, self._model.centerline
            )
            end_x, end_y, _ = getxyz(
                self._model.trk, dlong, max_dlat, self._model.centerline
            )
            segments.append(((start_x, start_y), (end_x, end_y), "lightgray"))
        return segments

    def _camera_view_ranges(self, camera_index: int | None) -> list[tuple[float, float]]:
        if camera_index is None:
            return []
        if camera_index < 0 or camera_index >= len(self._camera_service.cameras):
            return []
        ranges: list[tuple[float, float]] = []
        for view in self._camera_service.camera_views:
            for entry in view.entries:
                if entry.camera_index != camera_index:
                    continue
                if entry.start_dlong is None or entry.end_dlong is None:
                    continue
                ranges.append((float(entry.start_dlong), float(entry.end_dlong)))
        return ranges

    def _zoom_points_for_camera(self) -> list[tuple[float, QtGui.QColor]]:
        if not self._show_zoom_points:
            return []
        if self._selected_camera is None:
            return []
        if self._selected_camera < 0 or self._selected_camera >= len(
            self._camera_service.cameras
        ):
            return []

        camera = self._camera_service.cameras[self._selected_camera]
        params = camera.type6
        if params is None:
            return []

        return [
            (params.start_point, QtGui.QColor("#ffeb3b")),
            (params.middle_point, QtGui.QColor("#00e676")),
            (params.end_point, QtGui.QColor("#42a5f5")),
        ]

    def _flag_at_point(self, point: QtCore.QPointF, radius: int = 8) -> int | None:
        transform = self._current_transform()
        if not transform:
            return None
        for index, (fx, fy) in enumerate(self._flags):
            flag_point = rendering.map_point(
                fx, fy, transform, self.height()
            )
            if (flag_point - point).manhattanLength() <= radius:
                return index
        return None

    def _handle_primary_click(self, point: QtCore.QPointF) -> None:
        transform = self._current_transform()
        if not transform:
            return
        camera_index = self._camera_at_point(point)
        if camera_index is not None:
            self.set_selected_camera(camera_index)
            return
        flag_index = self._flag_at_point(point)
        if flag_index is not None:
            self._set_selected_flag(flag_index)
            return
        active_line = self._active_lp_line or "center-line"
        if (
            active_line != "center-line"
            and active_line in self._model.visible_lp_files
            and self._model.surface_mesh
        ):
            lp_index = self._lp_record_at_point(point, active_line)
            if lp_index is not None:
                self.set_selected_lp_record(active_line, lp_index)
                self.lpRecordSelected.emit(active_line, lp_index)
                return
        coords = self._map_to_track(point)
        if coords is None:
            return
        self._flags.append(coords)
        self._set_selected_flag(len(self._flags) - 1)
        self.update()

    def _lp_record_at_point(
        self, point: QtCore.QPointF, lp_name: str
    ) -> int | None:
        records = self._model.ai_line_records(lp_name)
        if not records:
            return None
        transform = self._current_transform()
        if not transform:
            return None
        cursor_track = self._map_to_track(point)
        if cursor_track is None:
            return None

        cursor_x, cursor_y = cursor_track
        best_point = None
        best_distance_sq = math.inf
        best_start_index = None
        best_end_index = None

        for idx in range(len(records)):
            p0 = records[idx]
            p1 = records[(idx + 1) % len(records)]
            seg_dx = p1.x - p0.x
            seg_dy = p1.y - p0.y
            seg_len_sq = seg_dx * seg_dx + seg_dy * seg_dy
            if seg_len_sq == 0:
                continue
            t = ((cursor_x - p0.x) * seg_dx + (cursor_y - p0.y) * seg_dy) / seg_len_sq
            t = max(0.0, min(1.0, t))
            proj_x = p0.x + seg_dx * t
            proj_y = p0.y + seg_dy * t
            dist_sq = (cursor_x - proj_x) ** 2 + (cursor_y - proj_y) ** 2
            if dist_sq < best_distance_sq:
                best_distance_sq = dist_sq
                best_point = (proj_x, proj_y)
                best_start_index = idx
                best_end_index = (idx + 1) % len(records)

        if best_point is None or best_start_index is None or best_end_index is None:
            return None

        mapped_point = rendering.map_point(
            best_point[0], best_point[1], transform, self.height()
        )
        if (mapped_point - point).manhattanLength() > 16:
            return None

        start_record = records[best_start_index]
        end_record = records[best_end_index]
        dist_start = (cursor_x - start_record.x) ** 2 + (cursor_y - start_record.y) ** 2
        dist_end = (cursor_x - end_record.x) ** 2 + (cursor_y - end_record.y) ** 2
        return best_start_index if dist_start <= dist_end else best_end_index

    def _handle_flag_removal(self, point: QtCore.QPointF) -> bool:
        flag_index = self._flag_at_point(point)
        if flag_index is None:
            return False
        del self._flags[flag_index]
        if self._selected_flag is not None:
            if self._selected_flag == flag_index:
                self._set_selected_flag(None)
            elif self._selected_flag > flag_index:
                self._set_selected_flag(self._selected_flag - 1)
        self.update()
        return True

    def _set_selected_flag(self, index: int | None) -> None:
        self._selected_flag = index
        coords = None
        if index is not None and 0 <= index < len(self._flags):
            coords = self._flags[index]
        self.selectedFlagChanged.emit(coords)
        self.update()
