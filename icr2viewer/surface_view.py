"""2D surface view for rendering TRK ground polygons."""

from __future__ import annotations

from collections import OrderedDict
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

        self._margin = 24
        self._show_centerline = True

        self._center: Tuple[float, float] = (0.0, 0.0)
        self._fit_scale = 1.0
        self._zoom = 1.0
        self._rotation = 0.0
        self._pan = QtCore.QPointF(0.0, 0.0)
        self._last_pos: Optional[QtCore.QPoint] = None
        self._drag_mode: Optional[str] = None

        self._fill_layers: List[Tuple[QtGui.QBrush, QtGui.QPainterPath]] = []
        self._centerline_path = QtGui.QPainterPath()

        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.ClickFocus)

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
            if self._bounds:
                min_x, max_x, min_y, max_y = self._bounds
                self._center = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
        self._rebuild_geometry()
        self._reset_view()

    def set_show_centerline(self, enabled: bool) -> None:
        self._show_centerline = bool(enabled)
        self.update()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _rebuild_geometry(self) -> None:
        self._fill_layers = []
        self._centerline_path = QtGui.QPainterPath()

        if not self._surface_mesh:
            self.update()
            return

        color_paths: "OrderedDict[int, QtGui.QPainterPath]" = OrderedDict()
        for strip in self._surface_mesh:
            if strip.ground_type not in color_paths:
                path = QtGui.QPainterPath()
                path.setFillRule(QtCore.Qt.WindingFill)
                color_paths[strip.ground_type] = path
            path = color_paths[strip.ground_type]
            polygon = QtGui.QPolygonF(
                [QtCore.QPointF(float(x), float(y)) for x, y in strip.points]
            )
            path.addPolygon(polygon)

        for ground_type, path in color_paths.items():
            fill_color = QtGui.QColor(color_from_ground_type(ground_type))
            fill_color.setAlpha(200)
            self._fill_layers.append((QtGui.QBrush(fill_color), path))

        if self._cline:
            points = [QtCore.QPointF(float(x), float(y)) for x, y in self._cline]
            if points:
                self._centerline_path = QtGui.QPainterPath(points[0])
                for pt in points[1:]:
                    self._centerline_path.lineTo(pt)
        self.update()

    def _reset_view(self) -> None:
        self._zoom = 1.0
        self._rotation = 0.0
        self._pan = QtCore.QPointF(0.0, 0.0)
        self._update_fit_scale()
        self.update()

    def _update_fit_scale(self) -> None:
        if not self._bounds:
            self._fit_scale = 1.0
            return

        min_x, max_x, min_y, max_y = self._bounds
        track_w = max_x - min_x
        track_h = max_y - min_y
        if track_w <= 0 or track_h <= 0:
            self._fit_scale = 1.0
            return

        available_w = max(1, self.width() - self._margin * 2)
        available_h = max(1, self.height() - self._margin * 2)
        scale_x = available_w / track_w
        scale_y = available_h / track_h
        self._fit_scale = max(1e-6, min(scale_x, scale_y))

    def _current_scale(self) -> float:
        return self._fit_scale * self._zoom

    def _build_transform(self) -> QtGui.QTransform | None:
        if not self._bounds:
            return None

        transform = QtGui.QTransform()
        transform.translate(self.width() / 2 + self._pan.x(), self.height() / 2 + self._pan.y())
        transform.scale(self._current_scale(), -self._current_scale())
        transform.rotateRadians(self._rotation)
        transform.translate(-self._center[0], -self._center[1])
        return transform

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------
    def wheelEvent(self, event: QtGui.QWheelEvent):  # noqa: N802
        delta = event.angleDelta().y() / 120.0
        factor = 1.15 ** delta
        self._zoom = max(0.05, min(25.0, self._zoom * factor))
        self.update()

    def mousePressEvent(self, event: QtGui.QMouseEvent):  # noqa: N802
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_mode = "rotate"
        elif event.button() == QtCore.Qt.RightButton:
            self._drag_mode = "pan"
        else:
            self._drag_mode = None

        if self._drag_mode:
            self._last_pos = event.pos()
            event.accept()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):  # noqa: N802
        if not self._drag_mode or self._last_pos is None:
            return

        dx = event.x() - self._last_pos.x()
        dy = event.y() - self._last_pos.y()

        if self._drag_mode == "rotate":
            self._rotation += dx * 0.01
        elif self._drag_mode == "pan":
            self._pan += QtCore.QPointF(dx, dy)

        self._last_pos = event.pos()
        self.update()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):  # noqa: N802
        self._drag_mode = None
        self._last_pos = None
        event.accept()

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent):  # noqa: N802
        self._reset_view()
        event.accept()

    def resizeEvent(self, event: QtGui.QResizeEvent):  # noqa: N802
        super().resizeEvent(event)
        self._update_fit_scale()
        self.update()

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

        transform = self._build_transform()
        if not transform:
            return

        painter.save()
        painter.setTransform(transform)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        painter.setPen(QtCore.Qt.NoPen)

        for brush, path in self._fill_layers:
            painter.fillPath(path, brush)

        if self._show_centerline and not self._centerline_path.isEmpty():
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            pen = QtGui.QPen(QtGui.QColor("#FF7043"), 2)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawPath(self._centerline_path)

        painter.restore()

