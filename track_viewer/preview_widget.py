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
from icr2_core.trk.trk_utils import get_cline_pos, color_from_ground_type


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
        self._cached_surface_pixmap: QtGui.QPixmap | None = None
        self._pixmap_size: QtCore.QSize | None = None
        self._current_track: Path | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def clear(self, message: str = "Select a track to preview.") -> None:
        self.trk = None
        self._cline = []
        self._surface_mesh = []
        self._bounds = None
        self._cached_surface_pixmap = None
        self._pixmap_size = None
        self._current_track = None
        self._status_message = message
        self.update()

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
        self._bounds = bounds
        self._cached_surface_pixmap = None
        self._pixmap_size = None
        self._current_track = track_folder
        self._status_message = f"Loaded {track_folder.name}" if track_folder else ""
        self.update()

    # ------------------------------------------------------------------
    # Painting helpers
    # ------------------------------------------------------------------
    def _map_point(self, x: float, y: float, scale: float, offsets: Tuple[float, float]) -> QtCore.QPointF:
        px = x * scale + offsets[0]
        py = y * scale + offsets[1]
        return QtCore.QPointF(px, self.height() - py)

    def _compute_transform(self) -> Tuple[float, Tuple[float, float]] | None:
        if not self._bounds:
            return None
        min_x, max_x, min_y, max_y = self._bounds
        track_w = max_x - min_x
        track_h = max_y - min_y
        if track_w <= 0 or track_h <= 0:
            return None

        margin = 24
        w, h = self.width(), self.height()
        scale_x = (w - margin * 2) / track_w
        scale_y = (h - margin * 2) / track_h
        scale = min(scale_x, scale_y)
        x_offset = (w - track_w * scale) / 2 - min_x * scale
        y_offset = (h - track_h * scale) / 2 - min_y * scale
        return scale, (x_offset, y_offset)

    def _render_surface_to_pixmap(self) -> QtGui.QPixmap:
        pixmap = QtGui.QPixmap(self.size())
        pixmap.fill(QtCore.Qt.transparent)
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        transform = self._compute_transform()
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
        painter.setPen(QtGui.QPen(QtGui.QColor("white")))
        painter.drawText(12, 20, self._status_message)

    def resizeEvent(self, event) -> None:  # noqa: D401 - Qt signature
        self._pixmap_size = None
        self._cached_surface_pixmap = None
        super().resizeEvent(event)
