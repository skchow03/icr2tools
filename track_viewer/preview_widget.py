"""Embedded surface preview widget for the standalone track viewer."""
from __future__ import annotations

import math
from pathlib import Path
from typing import List, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.cam.helpers import CameraPosition
from icr2_core.trk.surface_mesh import GroundSurfaceStrip
from icr2_core.trk.trk_utils import (
    color_from_ground_type,
    get_cline_pos,
    getxyz,
    sect2xy,
)
from track_viewer.camera_manager import CameraManager
from track_viewer.camera_models import CameraViewListing
from track_viewer.track_data_loader import (
    AiLineData,
    CameraData,
    TrackDataLoader,
    TrackSurfaceData,
)


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

    def __init__(
        self,
        loader: TrackDataLoader | None = None,
        camera_manager: CameraManager | None = None,
    ) -> None:
        super().__init__()
        self.setMinimumSize(320, 240)
        self.setAutoFillBackground(True)
        self.setMouseTracking(True)

        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(24, 24, 24))
        self.setPalette(palette)

        self._status_message = "Select a track to preview."

        self._loader = loader or TrackDataLoader()
        self._camera_manager = camera_manager or CameraManager()
        self._camera_manager.camerasChanged.connect(self._handle_cameras_changed)
        self._camera_manager.selectedCameraChanged.connect(
            self._handle_selected_camera_changed
        )

        self.trk = None
        self._cline: List[Tuple[float, float]] = []
        self._surface_mesh: List[GroundSurfaceStrip] = []
        self._bounds: Tuple[float, float, float, float] | None = None
        self._sampled_centerline: List[Tuple[float, float]] = []
        self._sampled_dlongs: List[float] = []
        self._sampled_bounds: Tuple[float, float, float, float] | None = None
        self._ai_lines: dict[str, List[Tuple[float, float]]] = {}
        self._cached_surface_pixmap: QtGui.QPixmap | None = None
        self._pixmap_size: QtCore.QSize | None = None
        self._current_track: Path | None = None
        self._camera_source: str | None = None
        self._dat_path: Path | None = None
        self._show_center_line = True
        self._show_cameras = True
        self._show_zoom_points = False
        self._visible_lp_files: set[str] = set()
        self._available_lp_files: List[str] = []
        self._track_length: float | None = None
        self._tv_mode_count: int = 0

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
        self._nearest_centerline_point: Tuple[float, float] | None = None
        self._nearest_centerline_dlong: float | None = None
        self._nearest_centerline_elevation: float | None = None

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
        self._ai_lines = {}
        self._cached_surface_pixmap = None
        self._pixmap_size = None
        self._current_track = None
        self._camera_source = None
        self._dat_path = None
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
        self._camera_manager.reset()
        self._nearest_centerline_point = None
        self._nearest_centerline_dlong = None
        self._nearest_centerline_elevation = None
        self._track_length = None
        self._visible_lp_files = set()
        self._available_lp_files = []
        self._tv_mode_count = 0
        self._status_message = message
        self.cursorPositionChanged.emit(None)
        self.selectedFlagChanged.emit(None)
        self.update()

    def tv_mode_count(self) -> int:
        return self._camera_manager.tv_mode_count

    def set_tv_mode_count(self, count: int) -> None:
        self._camera_manager.set_tv_mode_count(count)
        self._tv_mode_count = self._camera_manager.tv_mode_count
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

    def center_line_visible(self) -> bool:
        return self._show_center_line

    def ai_line_available(self) -> bool:
        return any(points for points in self._ai_lines.values())

    def available_lp_files(self) -> list[str]:
        return list(self._available_lp_files)

    def visible_lp_files(self) -> list[str]:
        return sorted(self._visible_lp_files)

    def set_visible_lp_files(self, names: list[str] | set[str]) -> None:
        if not self._ai_lines:
            names = set()
        valid = {name for name in names if self._ai_lines.get(name)}
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
        return list(self._camera_manager.cameras)

    def update_camera_dlongs(
        self, camera_index: int, start_dlong: Optional[int], end_dlong: Optional[int]
    ) -> None:
        self._camera_manager.update_camera_dlongs(camera_index, start_dlong, end_dlong)
        self.update()

    def update_camera_position(
        self, camera_index: int, x: Optional[int], y: Optional[int], z: Optional[int]
    ) -> None:
        self._camera_manager.update_camera_position(camera_index, x, y, z)
        self.update()

    def set_selected_camera(self, index: int | None) -> None:
        self._camera_manager.set_selected_camera(index)
        self.update()

    def add_type6_camera(self) -> tuple[bool, str]:
        """Create a new type 6 camera relative to the current selection."""
        success, message = self._camera_manager.add_type6_camera()
        if success:
            self._status_message = message
        self.update()
        return success, message

    def add_type7_camera(self) -> tuple[bool, str]:
        """Create a new type 7 camera relative to the current selection."""
        success, message = self._camera_manager.add_type7_camera()
        if success:
            self._status_message = message
        self.update()
        return success, message

    def _handle_cameras_changed(
        self, cameras: list[CameraPosition], views: list[CameraViewListing]
    ) -> None:
        self._tv_mode_count = self._camera_manager.tv_mode_count
        self.camerasChanged.emit(cameras, views)
        self.update()

    def _handle_selected_camera_changed(
        self, index: object, camera: object
    ) -> None:
        self.selectedCameraChanged.emit(index, camera)

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
            track_data, ai_data, camera_data = self._loader.load_track(track_folder)
        except Exception as exc:  # pragma: no cover - interactive feedback
            self.clear(f"Failed to load track: {exc}")
            return

        self._apply_track_data(track_data)
        self._apply_ai_data(ai_data)
        self._apply_camera_data(camera_data)
        self._cached_surface_pixmap = None
        self._pixmap_size = None
        self._current_track = track_folder
        self._status_message = f"Loaded {track_folder.name}" if track_folder else ""
        self._view_center = self._default_center()
        self._user_transform_active = False
        self._update_fit_scale()
        self._flags = []
        self._set_selected_flag(None)
        self.set_selected_camera(None)
        self.update()

    def save_cameras(self) -> tuple[bool, str]:
        """Persist the current camera data back to disk."""

        if self._current_track is None:
            return False, "No track is currently loaded."
        camera_data = CameraData(
            cameras=self._camera_manager.cameras,
            camera_views=self._camera_manager.camera_views,
            camera_source=self._camera_manager.camera_source,
            camera_files_from_dat=self._camera_manager.camera_files_from_dat,
            dat_path=self._camera_manager.dat_path,
        )
        success, message = self._loader.save_cameras(self._current_track, camera_data)
        if success:
            self._status_message = f"Saved cameras for {self._current_track.name}"
            self.update()
        return success, message

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

    def _apply_track_data(self, track_data: TrackSurfaceData) -> None:
        self.trk = track_data.trk
        self._track_length = track_data.track_length
        self._camera_manager.set_track_length(self._track_length)
        self._cline = track_data.cline
        self._surface_mesh = track_data.surface_mesh
        self._sampled_centerline = track_data.sampled_centerline
        self._sampled_dlongs = track_data.sampled_dlongs
        self._sampled_bounds = track_data.sampled_bounds
        self._bounds = self._merge_bounds(track_data.bounds, track_data.sampled_bounds)

    def _apply_ai_data(self, ai_data: AiLineData) -> None:
        self._available_lp_files = list(ai_data.available_files)
        self._ai_lines = ai_data.ai_lines
        self._visible_lp_files = {
            name for name in self._visible_lp_files if self._ai_lines.get(name)
        }

    def _apply_camera_data(self, camera_data: CameraData) -> None:
        self._camera_manager.set_track_length(self._track_length)
        self._camera_manager.set_camera_data(camera_data)
        self._tv_mode_count = self._camera_manager.tv_mode_count
        self._camera_source = camera_data.camera_source
        self._dat_path = camera_data.dat_path

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

    def _calculate_fit_scale(self) -> float | None:
        """Compute a scale that fits the entire track within the widget."""

        if not self._bounds:
            return None

        widget_width, widget_height = self.width(), self.height()
        if widget_width <= 0 or widget_height <= 0:
            return None

        min_x, max_x, min_y, max_y = self._bounds
        track_width = max_x - min_x
        track_height = max_y - min_y
        if track_width <= 0 or track_height <= 0:
            return None

        padding_ratio = 0.9
        scale_x = widget_width * padding_ratio / track_width
        scale_y = widget_height * padding_ratio / track_height

        return min(scale_x, scale_y)

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

    def _map_point(
        self, x: float, y: float, scale: float, offsets: Tuple[float, float]
    ) -> QtCore.QPointF:
        px = x * scale + offsets[0]
        py = self.height() - (y * scale + offsets[1])
        return QtCore.QPointF(px, py)

    def _default_center(self) -> Tuple[float, float] | None:
        if not self._bounds:
            return None
        min_x, max_x, min_y, max_y = self._bounds
        return (min_x + max_x) / 2, (min_y + max_y) / 2

    def _render_surface_to_pixmap(self) -> QtGui.QPixmap:
        pixmap = QtGui.QPixmap(self.size())
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        transform = self._current_transform()
        if not transform:
            painter.end()
            return pixmap
        scale, offsets = transform
        for strip in self._surface_mesh:
            base_color = QtGui.QColor(color_from_ground_type(strip.ground_type))
            fill = QtGui.QColor(base_color)
            fill.setAlpha(200)
            outline = base_color.darker(125)
            points = [self._map_point(x, y, scale, offsets) for x, y in strip.points]
            poly = QtGui.QPolygonF(points)
            painter.setBrush(QtGui.QBrush(fill))
            painter.setPen(QtGui.QPen(outline, 1))
            painter.drawPolygon(poly)
        painter.end()
        return pixmap

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

        if self._cached_surface_pixmap is None or self._pixmap_size != self.size():
            self._cached_surface_pixmap = self._render_surface_to_pixmap()
            self._pixmap_size = self.size()

        painter.drawPixmap(0, 0, self._cached_surface_pixmap)

        transform = self._current_transform()
        if self._show_center_line and self._sampled_centerline and transform:
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            scale, offsets = transform
            points = [
                self._map_point(x, y, scale, offsets)
                for x, y in self._sampled_centerline
            ]
            painter.setPen(QtGui.QPen(QtGui.QColor("white"), 2))
            painter.drawPolyline(QtGui.QPolygonF(points))

        if transform and self._show_center_line:
            self._draw_start_finish_line(painter, transform)

        if transform and self._show_center_line:
            self._draw_camera_range_markers(painter, transform)

        if transform and self._nearest_centerline_point:
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            scale, offsets = transform
            highlight = self._map_point(
                self._nearest_centerline_point[0],
                self._nearest_centerline_point[1],
                scale,
                offsets,
            )
            pen = QtGui.QPen(QtGui.QColor("#ff5252"))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(QtGui.QBrush(QtGui.QColor("#ff5252")))
            painter.drawEllipse(highlight, 5, 5)

        if transform:
            if self._show_cameras:
                self._draw_camera_positions(painter, transform)
            self._draw_ai_lines(painter, transform)
            self._draw_flags(painter, transform)
            if self._show_zoom_points:
                self._draw_zoom_points(painter, transform)

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
        self._set_centerline_projection(None, None, None)
        super().leaveEvent(event)

    # ------------------------------------------------------------------
    # Cursor & flag helpers
    # ------------------------------------------------------------------
    def _update_cursor_position(self, point: QtCore.QPointF) -> None:
        if not self._surface_mesh or not self._bounds:
            self.cursorPositionChanged.emit(None)
            self._set_centerline_projection(None, None, None)
            return
        coords = self._map_to_track(point)
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

        transform = self._current_transform()
        if not transform or not self.trk:
            self._set_centerline_projection(None, None, None)
            return

        cursor_track = self._map_to_track(point)
        if cursor_track is None:
            self._set_centerline_projection(None, None, None)
            return

        cursor_x, cursor_y = cursor_track
        best_point: Tuple[float, float] | None = None
        best_dlong: float | None = None
        best_distance_sq = float("inf")

        track_length = float(self.trk.trklength)
        for index, start in enumerate(self._sampled_centerline):
            end = self._sampled_centerline[(index + 1) % len(self._sampled_centerline)]
            start_dlong = self._sampled_dlongs[index]
            end_dlong = self._sampled_dlongs[(index + 1) % len(self._sampled_dlongs)]
            dlong_delta = end_dlong - start_dlong
            if dlong_delta <= 0:
                dlong_delta += track_length

            sx, sy = start
            ex, ey = end
            vx = ex - sx
            vy = ey - sy
            if vx == 0 and vy == 0:
                continue
            t = ((cursor_x - sx) * vx + (cursor_y - sy) * vy) / (vx * vx + vy * vy)
            t = max(0.0, min(1.0, t))
            proj_x = sx + vx * t
            proj_y = sy + vy * t

            distance_sq = (cursor_x - proj_x) ** 2 + (cursor_y - proj_y) ** 2
            if distance_sq < best_distance_sq:
                best_distance_sq = distance_sq
                projected_dlong = start_dlong + dlong_delta * t
                if projected_dlong >= track_length:
                    projected_dlong -= track_length
                best_point = (proj_x, proj_y)
                best_dlong = projected_dlong

        scale, offsets = transform
        if best_point is None:
            self._set_centerline_projection(None, None, None)
            return

        mapped_point = self._map_point(best_point[0], best_point[1], scale, offsets)
        pixel_distance = (mapped_point - point).manhattanLength()
        if pixel_distance > 16:
            self._set_centerline_projection(None, None, None)
            return
        elevation = None
        if best_dlong is not None and self._cline:
            _, _, elevation = getxyz(self.trk, float(best_dlong), 0, self._cline)
        self._set_centerline_projection(best_point, best_dlong, elevation)

    def _draw_ai_lines(
        self, painter: QtGui.QPainter, transform: tuple[float, tuple[float, float]]
    ) -> None:
        if not self._visible_lp_files:
            return
        scale, offsets = transform
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        for name in sorted(self._visible_lp_files):
            points = self._ai_lines.get(name)
            if not points:
                continue
            mapped = [
                self._map_point(point[0], point[1], scale, offsets)
                for point in points
            ]
            color = QtGui.QColor(self.lp_color(name))
            painter.setPen(QtGui.QPen(color, 2))
            painter.drawPolyline(QtGui.QPolygonF(mapped))

    def _draw_flags(
        self,
        painter: QtGui.QPainter,
        transform: Tuple[float, Tuple[float, float]],
    ) -> None:
        if not self._flags:
            return
        scale, offsets = transform
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        radius = 6
        for index, (fx, fy) in enumerate(self._flags):
            point = self._map_point(fx, fy, scale, offsets)
            color = QtGui.QColor("#ffcc33")
            if index == self._selected_flag:
                color = QtGui.QColor("#ff7f0e")
            pen = QtGui.QPen(QtGui.QColor("black"))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(QtGui.QBrush(color))
            painter.drawEllipse(point, radius, radius)
            painter.setPen(QtGui.QPen(QtGui.QColor("black")))
            flag_pole = QtCore.QLineF(
                point.x(),
                point.y() - radius - 4,
                point.x(),
                point.y() - radius,
            )
            painter.drawLine(flag_pole)

    def _camera_at_point(self, point: QtCore.QPointF, radius: int = 10) -> int | None:
        transform = self._current_transform()
        if not transform:
            return None
        scale, offsets = transform
        for index, cam in enumerate(self._camera_manager.cameras):
            camera_point = self._map_point(cam.x, cam.y, scale, offsets)
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
        if index < 0 or index >= len(self._camera_manager.cameras):
            return
        self._camera_manager.update_camera_position(
            index,
            int(round(coords[0])),
            int(round(coords[1])),
            None,
        )
        self._camera_dragged = True
        self.update()

    def _draw_camera_positions(
        self,
        painter: QtGui.QPainter,
        transform: Tuple[float, Tuple[float, float]],
    ) -> None:
        if not self._camera_manager.cameras:
            return
        scale, offsets = transform
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        type_colors = {
            2: QtGui.QColor("#ffeb3b"),
            6: QtGui.QColor("#ff9800"),
            7: QtGui.QColor("#4dd0e1"),
        }
        selected_index = self._camera_manager.selected_camera
        for index, cam in enumerate(self._camera_manager.cameras):
            point = self._map_point(cam.x, cam.y, scale, offsets)
            color = type_colors.get(cam.camera_type, QtGui.QColor("#ffffff"))
            if cam.camera_type == 7 and cam.type7 is not None:
                self._draw_camera_orientation(
                    painter, cam, point, scale, offsets, color
                )
            self._draw_camera_symbol(painter, point, color, index == selected_index)

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

    def _draw_perpendicular_bar(
        self,
        painter: QtGui.QPainter,
        transform: Tuple[float, Tuple[float, float]],
        dlong: float,
        *,
        color: QtGui.QColor | str = "#ff4081",
        width: float = 3.0,
        half_length_px: float = 10.0,
    ) -> None:
        mapping = self._centerline_point_and_normal(dlong)
        if mapping is None:
            return
        (cx, cy), (nx, ny) = mapping
        scale, offsets = transform
        if scale == 0:
            return

        half_length_track = half_length_px / scale
        start = self._map_point(
            cx - nx * half_length_track,
            cy - ny * half_length_track,
            scale,
            offsets,
        )
        end = self._map_point(
            cx + nx * half_length_track,
            cy + ny * half_length_track,
            scale,
            offsets,
        )
        pen = QtGui.QPen(QtGui.QColor(color), width)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        painter.save()
        painter.setPen(pen)
        painter.drawLine(QtCore.QLineF(start, end))
        painter.restore()

    def _draw_start_finish_line(
        self,
        painter: QtGui.QPainter,
        transform: Tuple[float, Tuple[float, float]],
    ) -> None:
        self._draw_perpendicular_bar(
            painter,
            transform,
            0.0,
            color="white",
            width=3.0,
            half_length_px=12.0,
        )

    def _camera_view_ranges(self, camera_index: int) -> list[tuple[float, float]]:
        ranges: list[tuple[float, float]] = []
        for view in self._camera_manager.camera_views:
            for entry in view.entries:
                if entry.camera_index != camera_index:
                    continue
                if entry.start_dlong is None or entry.end_dlong is None:
                    continue
                ranges.append((float(entry.start_dlong), float(entry.end_dlong)))
        return ranges

    def _draw_camera_range_markers(
        self,
        painter: QtGui.QPainter,
        transform: Tuple[float, Tuple[float, float]],
    ) -> None:
        selected = self._camera_manager.selected_camera
        if selected is None:
            return
        if selected < 0 or selected >= len(self._camera_manager.cameras):
            return

        ranges = self._camera_view_ranges(selected)
        if not ranges:
            return

        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        for start_dlong, end_dlong in ranges:
            self._draw_perpendicular_bar(painter, transform, float(start_dlong))
            self._draw_perpendicular_bar(painter, transform, float(end_dlong))

    def _draw_zoom_points(
        self,
        painter: QtGui.QPainter,
        transform: Tuple[float, Tuple[float, float]],
    ) -> None:
        if not self._show_zoom_points:
            return
        selected = self._camera_manager.selected_camera
        if selected is None:
            return
        if selected < 0 or selected >= len(self._camera_manager.cameras):
            return

        camera = self._camera_manager.cameras[selected]
        params = camera.type6
        if params is None:
            return

        scale, offsets = transform
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        pen = QtGui.QPen(QtGui.QColor("black"))
        pen.setWidth(3)
        painter.setPen(pen)

        points = [
            (params.start_point, QtGui.QColor("#ffeb3b")),
            (params.middle_point, QtGui.QColor("#00e676")),
            (params.end_point, QtGui.QColor("#42a5f5")),
        ]

        for dlong, color in points:
            if dlong is None:
                continue
            point = self._centerline_point(float(dlong))
            if point is None:
                continue
            mapped = self._map_point(point[0], point[1], scale, offsets)
            painter.setBrush(QtGui.QBrush(color))
            painter.drawEllipse(mapped, 7, 7)

        painter.restore()

    def _draw_camera_orientation(
        self,
        painter: QtGui.QPainter,
        camera: CameraPosition,
        center: QtCore.QPointF,
        scale: float,
        offsets: Tuple[float, float],
        base_color: QtGui.QColor,
    ) -> None:
        if scale == 0 or camera.type7 is None:
            return

        angle_scale = math.pi / 2147483648
        angle = camera.type7.z_axis_rotation * angle_scale
        direction = QtCore.QPointF(math.cos(angle), math.sin(angle))

        line_length_px = 18.0
        line_length_track = line_length_px / scale

        end = self._map_point(
            camera.x + direction.x() * line_length_track,
            camera.y + direction.y() * line_length_track,
            scale,
            offsets,
        )

        pen = QtGui.QPen(QtGui.QColor(base_color))
        pen.setWidth(2)
        pen.setCapStyle(QtCore.Qt.RoundCap)

        painter.save()
        painter.setPen(pen)
        painter.drawLine(QtCore.QLineF(center, end))
        painter.restore()

    def _draw_camera_symbol(
        self,
        painter: QtGui.QPainter,
        center: QtCore.QPointF,
        base_color: QtGui.QColor,
        selected: bool,
    ) -> None:
        painter.save()
        painter.translate(center)
        pen = QtGui.QPen(QtGui.QColor("#111111"))
        pen.setWidth(1 if not selected else 2)
        pen.setColor(base_color if not selected else QtGui.QColor("#ff4081"))
        painter.setPen(pen)
        painter.setBrush(QtGui.QBrush(base_color))

        body_width = 14
        body_height = 9
        lens_radius = 3
        viewfinder_width = 5
        viewfinder_height = 4

        body_rect = QtCore.QRectF(
            -body_width / 2, -body_height / 2, body_width, body_height
        )
        painter.drawRoundedRect(body_rect, 2, 2)

        lens_center = QtCore.QPointF(body_width / 2 - lens_radius - 1, 0)
        painter.drawEllipse(lens_center, lens_radius, lens_radius)

        viewfinder_rect = QtCore.QRectF(
            -body_width / 2,
            -body_height / 2 - viewfinder_height + 1,
            viewfinder_width,
            viewfinder_height,
        )
        painter.drawRoundedRect(viewfinder_rect, 1.5, 1.5)

        painter.restore()

    def _flag_at_point(self, point: QtCore.QPointF, radius: int = 8) -> int | None:
        transform = self._current_transform()
        if not transform:
            return None
        scale, offsets = transform
        for index, (fx, fy) in enumerate(self._flags):
            flag_point = self._map_point(fx, fy, scale, offsets)
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
