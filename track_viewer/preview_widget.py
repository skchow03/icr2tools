"""Embedded surface preview widget for the standalone track viewer."""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.trk.track_loader import load_trk_from_folder
from icr2_core.trk.surface_mesh import (
    GroundSurfaceStrip,
    build_ground_surface_mesh,
    compute_mesh_bounds,
)
from icr2_core.trk.trk_utils import get_cline_pos, color_from_ground_type, getxyz


class TrackPreviewWidget(QtWidgets.QFrame):
    """Renders the TRK ground surface similar to the timing overlay."""

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(320, 240)
        self.setAutoFillBackground(True)

        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(24, 24, 24))
        self.setPalette(palette)

        self._status_message = "Select a track to preview."

        self.trk = None
        self._cline: List[Tuple[float, float]] = []
        self._surface_mesh: List[GroundSurfaceStrip] = []
        self._bounds: Tuple[float, float, float, float] | None = None
        self._sampled_centerline: List[Tuple[float, float]] = []
        self._sampled_bounds: Tuple[float, float, float, float] | None = None
        self._cached_surface_pixmap: QtGui.QPixmap | None = None
        self._pixmap_size: QtCore.QSize | None = None
        self._current_track: Path | None = None
        self._show_center_line = True

        self._view_center: Tuple[float, float] | None = None
        self._fit_scale: float | None = None
        self._current_scale: float | None = None
        self._user_transform_active = False
        self._is_panning = False
        self._last_mouse_pos: QtCore.QPoint | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def clear(self, message: str = "Select a track to preview.") -> None:
        self.trk = None
        self._cline = []
        self._surface_mesh = []
        self._bounds = None
        self._sampled_centerline = []
        self._sampled_bounds = None
        self._cached_surface_pixmap = None
        self._pixmap_size = None
        self._current_track = None
        self._view_center = None
        self._fit_scale = None
        self._current_scale = None
        self._user_transform_active = False
        self._is_panning = False
        self._last_mouse_pos = None
        self._status_message = message
        self.update()

    # ------------------------------------------------------------------
    # Center line controls
    # ------------------------------------------------------------------
    def set_show_center_line(self, show: bool) -> None:
        """Enable or disable rendering of the track center line."""

        if self._show_center_line != show:
            self._show_center_line = show
            self.update()

    def center_line_visible(self) -> bool:
        return self._show_center_line

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
            trk = load_trk_from_folder(str(track_folder))
            cline = get_cline_pos(trk)
            surface_mesh = build_ground_surface_mesh(trk, cline)
            bounds = compute_mesh_bounds(surface_mesh)
        except Exception as exc:  # pragma: no cover - interactive feedback
            self.clear(f"Failed to load track: {exc}")
            return

        self.trk = trk
        self._cline = cline
        self._surface_mesh = surface_mesh
        sampled, sampled_bounds = self._sample_centerline(trk, cline)
        self._sampled_centerline = sampled
        self._sampled_bounds = sampled_bounds
        self._bounds = self._merge_bounds(bounds, sampled_bounds)
        self._cached_surface_pixmap = None
        self._pixmap_size = None
        self._current_track = track_folder
        self._status_message = f"Loaded {track_folder.name}" if track_folder else ""
        self._view_center = self._default_center()
        self._user_transform_active = False
        self._update_fit_scale()
        self.update()

    # ------------------------------------------------------------------
    # Painting helpers
    # ------------------------------------------------------------------
    def _map_point(
        self, x: float, y: float, scale: float, offsets: Tuple[float, float]
    ) -> QtCore.QPointF:
        px = x * scale + offsets[0]
        py = y * scale + offsets[1]
        return QtCore.QPointF(px, self.height() - py)

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

    def _sample_centerline(
        self,
        trk,
        cline: List[Tuple[float, float]],
        step: int = 10000,
    ) -> Tuple[List[Tuple[float, float]], Tuple[float, float, float, float] | None]:
        if not trk or not cline:
            return [], None

        pts: List[Tuple[float, float]] = []
        dlong = 0
        while dlong <= trk.trklength:
            x, y, _ = getxyz(trk, dlong, 0, cline)
            pts.append((x, y))
            dlong += step

        if pts and pts[0] != pts[-1]:
            pts.append(pts[0])

        bounds = None
        if pts:
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            bounds = (min(xs), max(xs), min(ys), max(ys))
        return pts, bounds

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

        painter.setPen(QtGui.QPen(QtGui.QColor("white")))
        painter.drawText(12, 20, self._status_message)

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
        if event.button() == QtCore.Qt.LeftButton and self._surface_mesh:
            self._is_panning = True
            self._last_mouse_pos = event.pos()
            self._user_transform_active = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401 - Qt signature
        if self._is_panning and self._last_mouse_pos is not None:
            transform = self._current_transform()
            if transform:
                if self._view_center is None:
                    self._view_center = self._default_center()
                if self._view_center is not None:
                    scale, _ = transform
                    delta = event.pos() - self._last_mouse_pos
                    self._last_mouse_pos = event.pos()
                    cx, cy = self._view_center
                    cx -= delta.x() / scale
                    cy += delta.y() / scale
                    self._view_center = (cx, cy)
                    self._invalidate_cache()
                    self.update()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401 - Qt signature
        if event.button() == QtCore.Qt.LeftButton and self._is_panning:
            self._is_panning = False
            self._last_mouse_pos = None
            event.accept()
            return
        super().mouseReleaseEvent(event)
