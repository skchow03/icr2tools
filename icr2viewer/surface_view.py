"""2D surface view for rendering TRK ground polygons."""

from __future__ import annotations

from typing import List, Optional, Tuple

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.trk.surface_mesh import (
    GroundSurfaceStrip,
    build_ground_surface_mesh,
    compute_mesh_bounds,
)
from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import color_from_ground_type, get_cline_pos


class TrackSurfaceView(QtWidgets.QWidget):
    """Widget that renders a cached 2D view of track ground surfaces."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)

        self._trk: Optional[TRKFile] = None
        self._cline: List[Tuple[float, float]] = []
        self._surface_mesh: List[GroundSurfaceStrip] = []
        self._bounds: Tuple[float, float, float, float] | None = None

        self._cached_surface_pixmap: QtGui.QPixmap | None = None
        self._pixmap_size: QtCore.QSize | None = None

        self._margin = 24
        self._show_centerline = True

    # ------------------------------------------------------------------
    # Qt overrides
    # ------------------------------------------------------------------
    def sizeHint(self) -> QtCore.QSize:  # pragma: no cover - UI hint only
        return QtCore.QSize(900, 600)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def set_track(self, trk: Optional[TRKFile]) -> None:
        """Load a track and rebuild the cached surface mesh."""

        self._trk = trk
        if trk is None:
            self._cline = []
            self._surface_mesh = []
            self._bounds = None
        else:
            self._cline = get_cline_pos(trk)
            self._surface_mesh = build_ground_surface_mesh(trk, self._cline)
            self._bounds = compute_mesh_bounds(self._surface_mesh)

        self._invalidate_cache()

    def set_show_centerline(self, enabled: bool) -> None:
        self._show_centerline = bool(enabled)
        self.update()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _invalidate_cache(self) -> None:
        self._cached_surface_pixmap = None
        self._pixmap_size = None
        self.update()

    def _compute_transform(self) -> Tuple[float, Tuple[float, float]] | None:
        if not self._bounds:
            return None

        min_x, max_x, min_y, max_y = self._bounds
        track_w = max_x - min_x
        track_h = max_y - min_y
        if track_w <= 0 or track_h <= 0:
            return None

        w, h = self.width(), self.height()
        scale_x = (w - self._margin * 2) / track_w
        scale_y = (h - self._margin * 2) / track_h
        scale = min(scale_x, scale_y)
        x_offset = (w - track_w * scale) / 2 - min_x * scale
        y_offset = (h - track_h * scale) / 2 - min_y * scale
        return scale, (x_offset, y_offset)

    def _render_surface_pixmap(self) -> QtGui.QPixmap:
        pixmap = QtGui.QPixmap(self.size())
        pixmap.fill(QtCore.Qt.transparent)

        transform = self._compute_transform()
        if not transform:
            return pixmap

        scale, offsets = transform
        height = self.height()

        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)

        for strip in self._surface_mesh:
            base_color = QtGui.QColor(color_from_ground_type(strip.ground_type))
            fill = QtGui.QColor(base_color)
            fill.setAlpha(200)
            outline = base_color.darker(130)
            polygon = QtGui.QPolygonF(
                [self._map_point(x, y, scale, offsets, height) for x, y in strip.points]
            )
            painter.setBrush(QtGui.QBrush(fill))
            painter.setPen(QtGui.QPen(outline, 1))
            painter.drawPolygon(polygon)

        painter.end()
        return pixmap

    @staticmethod
    def _map_point(
        x: float,
        y: float,
        scale: float,
        offsets: Tuple[float, float],
        height: int,
    ) -> QtCore.QPointF:
        px = x * scale + offsets[0]
        py = y * scale + offsets[1]
        return QtCore.QPointF(px, height - py)

    def _draw_centerline(
        self,
        painter: QtGui.QPainter,
        scale: float,
        offsets: Tuple[float, float],
    ) -> None:
        if not self._cline:
            return

        height = self.height()
        points = [self._map_point(x, y, scale, offsets, height) for x, y in self._cline]
        if not points:
            return

        path = QtGui.QPainterPath(points[0])
        for pt in points[1:]:
            path.lineTo(pt)

        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setPen(QtGui.QPen(QtGui.QColor("#FF7043"), 2))
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawPath(path)

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    def paintEvent(self, event: QtGui.QPaintEvent):  # noqa: N802
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(18, 18, 18))

        if not self._surface_mesh or not self._bounds:
            painter.setPen(QtGui.QPen(QtGui.QColor("#bbbbbb")))
            painter.drawText(
                self.rect(),
                QtCore.Qt.AlignCenter,
                "Track surface not available",
            )
            return

        if self._cached_surface_pixmap is None or self._pixmap_size != self.size():
            self._cached_surface_pixmap = self._render_surface_pixmap()
            self._pixmap_size = self.size()

        painter.drawPixmap(0, 0, self._cached_surface_pixmap)

        if self._show_centerline:
            transform = self._compute_transform()
            if transform:
                scale, offsets = transform
                self._draw_centerline(painter, scale, offsets)

