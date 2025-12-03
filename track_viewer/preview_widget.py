"""Embedded surface preview widget for the standalone track viewer."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.cam.helpers import CameraPosition, CameraSegmentRange
from icr2_core.trk.surface_mesh import GroundSurfaceStrip
from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import (
    get_cline_pos,
    getxyz,
    sect2xy,
)
from track_viewer import rendering
from track_viewer.camera_controller import CameraController
from track_viewer.camera_models import CameraViewEntry, CameraViewListing
from track_viewer.camera_service import CameraService
from track_viewer.geometry import (
    CenterlineIndex,
    build_centerline_index,
    load_ai_line,
    project_point_to_centerline,
    sample_centerline,
)
from track_viewer.io_service import TrackIOService


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

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(320, 240)
        self.setAutoFillBackground(True)
        self.setMouseTracking(True)

        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(24, 24, 24))
        self.setPalette(palette)

        self._status_message = "Select a track to preview."

        self.trk = None
        self._cline: List[Tuple[float, float]] = []
        self._surface_mesh: List[GroundSurfaceStrip] = []
        self._bounds: Tuple[float, float, float, float] | None = None
        self._sampled_centerline: List[Tuple[float, float]] = []
        self._sampled_dlongs: List[float] = []
        self._sampled_bounds: Tuple[float, float, float, float] | None = None
        self._centerline_index: CenterlineIndex | None = None
        self._ai_lines: dict[str, List[Tuple[float, float]]] | None = None
        self._cached_surface_pixmap: QtGui.QPixmap | None = None
        self._pixmap_size: QtCore.QSize | None = None
        self._current_track: Path | None = None
        self._show_center_line = True
        self._show_boundaries = True
        self._show_cameras = True
        self._show_zoom_points = False
        self._visible_lp_files: set[str] = set()
        self._available_lp_files: List[str] = []
        self._track_length: float | None = None
        self._boundary_edges: List[tuple[Tuple[float, float], Tuple[float, float]]] = []

        self._view_center: Tuple[float, float] | None = None
        self._fit_scale: float | None = None
        self._current_scale: float | None = None
        self._user_transform_active = False
        self._is_panning = False
        self._last_mouse_pos: QtCore.QPoint | None = None
        self._left_press_pos: QtCore.QPoint | None = None
        self._dragged_during_press = False

        self._dragging_camera_index: int | None = None
        self._camera_dragged = False

        self._flags: List[Tuple[float, float]] = []
        self._selected_flag: int | None = None
        self._selected_camera: int | None = None
        self._nearest_centerline_point: Tuple[float, float] | None = None
        self._nearest_centerline_dlong: float | None = None
        self._nearest_centerline_elevation: float | None = None
        self._centerline_cached_point: QtCore.QPointF | None = None
        self._centerline_cached_projection: tuple[
            Tuple[float, float] | None,
            float | None,
            float | None,
        ] | None = None
        self._cursor_position: Tuple[float, float] | None = None
        self._io_service = TrackIOService()
        self._camera_service = CameraService(self._io_service, CameraController())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def clear(self, message: str = "Select a track to preview.") -> None:
        self.trk = None
        self._cline = []
        self._surface_mesh = []
        self._bounds = None
        self._sampled_centerline = []
        self._sampled_dlongs = []
        self._sampled_bounds = None
        self._centerline_index = None
        self._ai_lines = None
        self._cached_surface_pixmap = None
        self._pixmap_size = None
        self._current_track = None
        self._view_center = None
        self._fit_scale = None
        self._current_scale = None
        self._user_transform_active = False
        self._is_panning = False
        self._last_mouse_pos = None
        self._left_press_pos = None
        self._dragged_during_press = False
        self._dragging_camera_index = None
        self._camera_dragged = False
        self._flags = []
        self._selected_flag = None
        self._selected_camera = None
        self._nearest_centerline_point = None
        self._nearest_centerline_dlong = None
        self._nearest_centerline_elevation = None
        self._centerline_cached_point = None
        self._centerline_cached_projection = None
        self._cursor_position = None
        self._track_length = None
        self._visible_lp_files = set()
        self._available_lp_files = []
        self._boundary_edges = []
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
            if not show:
                self._set_centerline_projection(None, None, None)
            self.update()

    def set_show_boundaries(self, show: bool) -> None:
        """Enable or disable rendering of the track boundary edges."""

        if self._show_boundaries != show:
            self._show_boundaries = show
            self.update()

    def center_line_visible(self) -> bool:
        return self._show_center_line

    def ai_line_available(self) -> bool:
        return bool(self._available_lp_files)

    def available_lp_files(self) -> list[str]:
        return list(self._available_lp_files)

    def visible_lp_files(self) -> list[str]:
        return sorted(self._visible_lp_files)

    def set_visible_lp_files(self, names: list[str] | set[str]) -> None:
        valid = {name for name in names if name in self._available_lp_files}
        if valid == self._visible_lp_files:
            return
        self._visible_lp_files = valid
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

    def track_length(self) -> Optional[int]:
        return int(self._track_length) if self._track_length is not None else None

    def set_show_cameras(self, show: bool) -> None:
        """Enable or disable rendering of track camera overlays."""

        if self._show_cameras != show:
            self._show_cameras = show
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
            self._selected_camera, self._track_length
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
            self._selected_camera, self._track_length
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

        if self._current_track == track_folder:
            return  # nothing to do

        self._status_message = f"Loading {track_folder.name}…"
        self.update()

        try:
            track_data = self._io_service.load_track(track_folder)
        except Exception as exc:  # pragma: no cover - interactive feedback
            self.clear(f"Failed to load track: {exc}")
            return

        self.trk = track_data.trk
        self._track_length = track_data.track_length
        self._cline = track_data.centerline
        self._surface_mesh = track_data.surface_mesh
        self._boundary_edges = self._build_boundary_edges(self.trk, self._cline)
        sampled, sampled_dlongs, sampled_bounds = sample_centerline(self.trk, self._cline)
        self._sampled_centerline = sampled
        self._sampled_dlongs = sampled_dlongs
        self._sampled_bounds = sampled_bounds
        self._centerline_index = build_centerline_index(sampled, sampled_bounds)
        self._centerline_cached_point = None
        self._centerline_cached_projection = None
        self._bounds = self._merge_bounds(track_data.surface_bounds, sampled_bounds)
        self._available_lp_files = track_data.available_lp_files
        self._ai_lines = None
        self._visible_lp_files = {
            name for name in self._visible_lp_files if name in self._available_lp_files
        }
        self._cached_surface_pixmap = None
        self._pixmap_size = None
        self._current_track = track_folder
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

        if self._current_track is None:
            return False, "No track is currently loaded."

        try:
            self._status_message = self._camera_service.save()
            self.update()
        except Exception as exc:  # pragma: no cover - interactive feedback
            return False, f"Failed to save cameras: {exc}"

        return True, "Camera files saved successfully."

    def run_trk_gaps(self) -> tuple[bool, str]:
        """Replicate the ``trk_gaps`` script for the currently loaded track."""

        if self.trk is None or self._current_track is None:
            return False, "No track is currently loaded."

        track_name = self._current_track.name
        trk_path = self._current_track / f"{track_name}.trk"
        header_label = str(trk_path if trk_path.exists() else trk_path.name)

        try:
            cline = get_cline_pos(self.trk)
            dist_list: list[float] = []
            lines = [header_label]

            for sect in range(-1, self.trk.num_sects - 1):
                xy2 = getxyz(
                    self.trk,
                    self.trk.sects[sect].start_dlong + self.trk.sects[sect].length - 1,
                    0,
                    cline,
                )
                xy1 = sect2xy(self.trk, sect + 1, cline)

                dist = math.dist((xy1[0], xy1[1]), (xy2[0], xy2[1]))

                dist_list.append(dist)
                lines.append(f"Sect {sect}/{sect + 1}, gap {dist:.1f}")

            if dist_list:
                lines.append(f"Max gap {max(dist_list):.1f}")
                lines.append(f"Min gap {min(dist_list):.1f}")
                lines.append(f"Sum gaps {sum(dist_list):.1f}")
            lines.append(f"Track length: {self.trk.trklength}")
        except Exception as exc:  # pragma: no cover - interactive feedback
            return False, f"Failed to compute TRK gaps: {exc}"

        return True, "\n".join(lines)

    def _default_center(self) -> Tuple[float, float] | None:
        if not self._bounds:
            return None
        min_x, max_x, min_y, max_y = self._bounds
        return ((min_x + max_x) / 2, (min_y + max_y) / 2)

    def _calculate_fit_scale(self) -> float | None:
        if not self._bounds:
            return None
        min_x, max_x, min_y, max_y = self._bounds
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
        if self._current_track is None:
            return []

        if self._ai_lines is None:
            self._ai_lines = {}

        if lp_name not in self._ai_lines:
            self._ai_lines[lp_name] = load_ai_line(
                self.trk,
                self._cline,
                self._current_track,
                lp_name,
                track_length=self._track_length,
            )

        return self._ai_lines.get(lp_name) or []

    def _merge_bounds(
        self, *bounds: Tuple[float, float, float, float] | None
    ) -> Tuple[float, float, float, float] | None:
        valid = [b for b in bounds if b]
        if not valid:
            return None
        min_x = min(b[0] for b in valid)
        max_x = max(b[1] for b in valid)
        min_y = min(b[2] for b in valid)
        max_y = max(b[3] for b in valid)
        return (min_x, max_x, min_y, max_y)

    @staticmethod
    def _build_boundary_edges(
        trk: TRKFile | None,
        cline: Optional[List[Tuple[float, float]]],
    ) -> List[tuple[Tuple[float, float], Tuple[float, float]]]:
        """Create boundary line segments directly from TRK section data."""

        if trk is None or cline is None:
            return []

        edges: List[tuple[Tuple[float, float], Tuple[float, float]]] = []

        for sect in trk.sects:
            start_dlong = sect.start_dlong
            end_dlong = sect.start_dlong + sect.length

            for bound_idx in range(sect.num_bounds):
                start_dlat = sect.bound_dlat_start[bound_idx]
                end_dlat = sect.bound_dlat_end[bound_idx]

                start_x, start_y, _ = getxyz(trk, start_dlong, start_dlat, cline)
                end_x, end_y, _ = getxyz(trk, end_dlong, end_dlat, cline)

                edges.append(((start_x, start_y), (end_x, end_y)))

        return edges

    def _update_fit_scale(self) -> None:
        fit = self._calculate_fit_scale()
        self._fit_scale = fit
        if fit is not None and not self._user_transform_active:
            self._current_scale = fit
            if self._view_center is None:
                self._view_center = self._default_center()
            self._invalidate_cache()

    def _current_transform(self) -> Tuple[float, Tuple[float, float]] | None:
        if not self._bounds:
            return None
        if self._current_scale is None:
            self._update_fit_scale()
        if self._current_scale is None:
            return None
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

        if not self._surface_mesh or not self._bounds:
            painter.setPen(QtGui.QPen(QtGui.QColor("lightgray")))
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, self._status_message)
            return

        transform = self._current_transform()
        if self._cached_surface_pixmap is None or self._pixmap_size != self.size():
            self._cached_surface_pixmap = rendering.render_surface_to_pixmap(
                self._surface_mesh, transform, self.size()
            )
            self._pixmap_size = self.size()

        painter.drawPixmap(0, 0, self._cached_surface_pixmap)

        if transform and self._show_boundaries:
            rendering.draw_track_boundaries(
                painter, self._boundary_edges, transform, self.height()
            )

        if self._show_center_line and self._sampled_centerline and transform:
            rendering.draw_centerline(
                painter,
                self._sampled_centerline,
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

        if transform and self._nearest_centerline_point:
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            highlight = rendering.map_point(
                self._nearest_centerline_point[0],
                self._nearest_centerline_point[1],
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
                self._visible_lp_files,
                self._get_ai_line_points,
                transform,
                self.height(),
                self.lp_color,
            )
            rendering.draw_flags(
                painter, self._flags, self._selected_flag, transform, self.height()
            )
            if self._show_zoom_points:
                rendering.draw_zoom_points(
                    painter,
                    self._zoom_points_for_camera(),
                    transform,
                    self.height(),
                    self._centerline_point,
                )

        painter.setPen(QtGui.QPen(QtGui.QColor("white")))
        y = 20
        if self._track_length is not None:
            track_length_text = (
                f"Track length: {int(round(self._track_length))} DLONG"
            )
            painter.drawText(12, y, track_length_text)
            y += 16
        painter.drawText(12, y, self._status_message)
        y += 16
        if self._nearest_centerline_dlong is not None:
            dlong_text = f"Centerline DLONG: {int(round(self._nearest_centerline_dlong))}"
            painter.drawText(12, y, dlong_text)
            y += 16
        if self._nearest_centerline_elevation is not None:
            elevation_text = (
                f"Elevation: {self._nearest_centerline_elevation:.2f} (DLAT = 0)"
            )
            painter.drawText(12, y, elevation_text)

        self._draw_cursor_position(painter)

    def resizeEvent(self, event) -> None:  # noqa: D401 - Qt signature
        self._pixmap_size = None
        self._cached_surface_pixmap = None
        self._update_fit_scale()
        super().resizeEvent(event)

    # ------------------------------------------------------------------
    # Interaction handlers
    # ------------------------------------------------------------------
    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:  # noqa: D401 - Qt signature
        if not self._surface_mesh or not self._bounds:
            return
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
        if event.button() == QtCore.Qt.RightButton and self._surface_mesh:
            if self._handle_flag_removal(event.pos()):
                event.accept()
                return

        if event.button() == QtCore.Qt.LeftButton and self._surface_mesh:
            if self._handle_camera_press(event.pos()):
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
        if event.button() == QtCore.Qt.LeftButton and self._surface_mesh:
            if self._dragging_camera_index is not None:
                self._dragging_camera_index = None
                self._camera_dragged = False
                event.accept()
                return
            click_without_drag = not self._dragged_during_press
            self._is_panning = False
            self._last_mouse_pos = None
            self._left_press_pos = None
            self._dragged_during_press = False
            if click_without_drag:
                self._handle_primary_click(event.pos())
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: D401 - Qt signature
        self.cursorPositionChanged.emit(None)
        if self._cursor_position is not None:
            self._cursor_position = None
            self.update()
        self._set_centerline_projection(None, None, None)
        super().leaveEvent(event)

    # ------------------------------------------------------------------
    # Cursor & flag helpers
    # ------------------------------------------------------------------
    def _update_cursor_position(self, point: QtCore.QPointF) -> None:
        if not self._surface_mesh or not self._bounds:
            self.cursorPositionChanged.emit(None)
            if self._cursor_position is not None:
                self._cursor_position = None
                self.update()
            self._set_centerline_projection(None, None, None)
            return
        coords = self._map_to_track(point)
        if coords != self._cursor_position:
            self._cursor_position = coords
            self.update()
        self.cursorPositionChanged.emit(coords)
        self._update_centerline_projection(point)

    def _set_centerline_projection(
        self,
        point: Tuple[float, float] | None,
        dlong: float | None,
        elevation: float | None,
    ) -> None:
        if (
            point == self._nearest_centerline_point
            and dlong == self._nearest_centerline_dlong
            and elevation == self._nearest_centerline_elevation
        ):
            return
        self._nearest_centerline_point = point
        self._nearest_centerline_dlong = dlong
        self._nearest_centerline_elevation = elevation
        self.update()

    def _update_centerline_projection(self, point: QtCore.QPointF | None) -> None:
        if (
            point is None
            or not self._sampled_centerline
            or not self._sampled_dlongs
            or not self._show_center_line
        ):
            self._set_centerline_projection(None, None, None)
            return

        if (
            self._centerline_cached_point is not None
            and self._centerline_cached_projection is not None
            and (point - self._centerline_cached_point).manhattanLength() <= 3
        ):
            cached_point, cached_dlong, cached_elevation = self._centerline_cached_projection
            self._set_centerline_projection(cached_point, cached_dlong, cached_elevation)
            return

        transform = self._current_transform()
        if not transform or not self.trk:
            self._set_centerline_projection(None, None, None)
            return

        screen_bounds = rendering.centerline_screen_bounds(
            self._sampled_bounds, transform, self.height()
        )
        if screen_bounds:
            dx = max(screen_bounds.left() - point.x(), 0.0, point.x() - screen_bounds.right())
            dy = max(screen_bounds.top() - point.y(), 0.0, point.y() - screen_bounds.bottom())
            if max(dx, dy) > 24:
                self._centerline_cached_point = point
                self._centerline_cached_projection = (None, None, None)
                self._set_centerline_projection(None, None, None)
                return

        cursor_track = self._map_to_track(point)
        if cursor_track is None:
            self._set_centerline_projection(None, None, None)
            return

        if self._centerline_index is None:
            self._set_centerline_projection(None, None, None)
            return

        cursor_x, cursor_y = cursor_track
        track_length = float(self.trk.trklength)
        best_point, best_dlong, best_distance_sq = project_point_to_centerline(
            (cursor_x, cursor_y),
            self._centerline_index,
            self._sampled_dlongs,
            track_length,
        )

        if best_point is None:
            self._set_centerline_projection(None, None, None)
            return
        mapped_point = rendering.map_point(
            best_point[0], best_point[1], transform, self.height()
        )
        pixel_distance = (mapped_point - point).manhattanLength()
        if pixel_distance > 16:
            self._centerline_cached_point = point
            self._centerline_cached_projection = (None, None, None)
            self._set_centerline_projection(None, None, None)
            return
        elevation = None
        if best_dlong is not None and self._cline:
            _, _, elevation = getxyz(self.trk, float(best_dlong), 0, self._cline)
        self._centerline_cached_point = point
        self._centerline_cached_projection = (best_point, best_dlong, elevation)
        self._set_centerline_projection(best_point, best_dlong, elevation)

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
        start_y = margin + metrics.ascent()

        painter.setPen(QtGui.QPen(QtGui.QColor("white")))
        for line in lines:
            painter.drawText(start_x, start_y, line)
            start_y += line_height

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

    def _centerline_point_and_normal(
        self, dlong: float
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        if not self.trk or not self._cline:
            return None
        track_length = float(self.trk.trklength)
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

        px, py, _ = getxyz(self.trk, prev_dlong, 0, self._cline)
        nx, ny, _ = getxyz(self.trk, next_dlong, 0, self._cline)
        cx, cy, _ = getxyz(self.trk, base, 0, self._cline)

        vx = nx - px
        vy = ny - py
        length = (vx * vx + vy * vy) ** 0.5
        if length == 0:
            return None
        normal = (-vy / length, vx / length)
        return (cx, cy), normal

    def _centerline_point(self, dlong: float) -> tuple[float, float] | None:
        if not self.trk or not self._cline:
            return None
        track_length = float(self.trk.trklength)
        if track_length <= 0:
            return None
        wrapped = dlong % track_length
        cx, cy, _ = getxyz(self.trk, wrapped, 0, self._cline)
        return cx, cy

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
        coords = self._map_to_track(point)
        if coords is None:
            return
        self._flags.append(coords)
        self._set_selected_flag(len(self._flags) - 1)
        self.update()

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
