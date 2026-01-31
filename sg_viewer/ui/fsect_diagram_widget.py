from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Iterable

from PyQt5 import QtCore, QtGui, QtWidgets

from sg_viewer.models.preview_fsection import PreviewFSection
from sg_viewer.rendering.fsection_style_map import resolve_fsection_style
from sg_viewer.services import sg_rendering


@dataclass
class _FsectNode:
    fsect_index: int
    endpoint: str
    center: QtCore.QPointF
    dlat: float


class FsectDiagramWidget(QtWidgets.QWidget):
    dlatChanged = QtCore.pyqtSignal(int, int, str, float)
    _SNAP_DISTANCE_PX = 8.0
    _RULER_TICK_LENGTH = 6.0
    _RULER_LABEL_MARGIN = 2.0
    _RULER_FONT_SIZE = 8

    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
        *,
        on_dlat_changed: Callable[[int, int, str, float], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setMinimumHeight(140)
        self.setMouseTracking(True)
        self._section_index: int | None = None
        self._fsects: list[PreviewFSection] = []
        self._prev_fsects: list[PreviewFSection] = []
        self._next_fsects: list[PreviewFSection] = []
        self._nodes: list[_FsectNode] = []
        self._dragged_node: _FsectNode | None = None
        self._panning = False
        self._pan_last_pos: QtCore.QPoint | None = None
        self._range: tuple[float, float] = (-300000.0, 300000.0)
        if on_dlat_changed is not None:
            self.dlatChanged.connect(on_dlat_changed)

    def set_fsects(
        self,
        section_index: int | None,
        fsects: Iterable[PreviewFSection],
        *,
        prev_fsects: Iterable[PreviewFSection] | None = None,
        next_fsects: Iterable[PreviewFSection] | None = None,
    ) -> None:
        self._section_index = section_index
        self._fsects = list(fsects)
        self._prev_fsects = list(prev_fsects or [])
        self._next_fsects = list(next_fsects or [])
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: D401
        _ = event
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        rect = self.rect()
        painter.fillRect(rect, QtGui.QColor("black"))
        if not self._fsects:
            self._draw_placeholder(painter, rect)
            return

        plot_rect = rect.adjusted(10, 10, -10, -10)
        min_dlat, max_dlat = self._range
        left = plot_rect.left()
        right = plot_rect.right()
        top = plot_rect.top()
        bottom = plot_rect.bottom()
        width = max(1.0, float(right - left))
        height = max(1.0, float(bottom - top))

        self._draw_stub_lines(
            painter,
            left,
            width,
            top,
            bottom,
            min_dlat,
            max_dlat,
        )
        self._draw_ruler(
            painter,
            left,
            right,
            top,
            bottom,
            min_dlat,
            max_dlat,
        )

        self._nodes = []
        for index, fsect in enumerate(self._fsects):
            start_x = self._dlat_to_x(fsect.start_dlat, left, width, min_dlat, max_dlat)
            end_x = self._dlat_to_x(fsect.end_dlat, left, width, min_dlat, max_dlat)
            start_point = QtCore.QPointF(start_x, bottom)
            end_point = QtCore.QPointF(end_x, top)
            pen = self._pen_for_fsect(fsect)
            painter.setPen(pen)
            painter.drawLine(start_point, end_point)
            self._nodes.append(
                _FsectNode(index, "start", start_point, fsect.start_dlat)
            )
            self._nodes.append(_FsectNode(index, "end", end_point, fsect.end_dlat))

        for node in self._nodes:
            self._draw_node(painter, node)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if event.button() != QtCore.Qt.LeftButton:
            return
        node = self._find_node_at(event.pos())
        if node is not None:
            self._dragged_node = node
            self.setCursor(QtCore.Qt.ClosedHandCursor)
            return
        self._panning = True
        self._pan_last_pos = event.pos()
        self.setCursor(QtCore.Qt.ClosedHandCursor)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if self._panning and self._pan_last_pos is not None:
            rect = self.rect().adjusted(10, 10, -10, -10)
            min_dlat, max_dlat = self._range
            left = rect.left()
            right = rect.right()
            width = max(1.0, float(right - left))
            start_dlat = self._x_to_dlat(
                self._pan_last_pos.x(), left, width, min_dlat, max_dlat
            )
            current_dlat = self._x_to_dlat(
                event.pos().x(), left, width, min_dlat, max_dlat
            )
            delta = start_dlat - current_dlat
            self._range = (min_dlat + delta, max_dlat + delta)
            self._pan_last_pos = event.pos()
            self.update()
            return
        if self._dragged_node is None:
            hovered = self._find_node_at(event.pos())
            self.setCursor(
                QtCore.Qt.OpenHandCursor if hovered is not None else QtCore.Qt.ArrowCursor
            )
            return
        if self._section_index is None:
            return
        rect = self.rect().adjusted(10, 10, -10, -10)
        min_dlat, max_dlat = self._range
        left = rect.left()
        right = rect.right()
        width = max(1.0, float(right - left))
        new_dlat = self._x_to_dlat(
            event.pos().x(), left, width, min_dlat, max_dlat
        )
        snapped_dlat = self._snap_dlat(
            self._dragged_node, float(event.pos().x()), left, width, min_dlat, max_dlat
        )
        if snapped_dlat is not None:
            new_dlat = snapped_dlat
        self._update_local_dlat(self._dragged_node, new_dlat)
        self.dlatChanged.emit(
            self._section_index,
            self._dragged_node.fsect_index,
            self._dragged_node.endpoint,
            new_dlat,
        )
        self.update()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if event.button() != QtCore.Qt.LeftButton:
            return
        self._dragged_node = None
        self._panning = False
        self._pan_last_pos = None
        self.setCursor(QtCore.Qt.ArrowCursor)

    def leaveEvent(self, event: QtCore.QEvent) -> None:  # noqa: D401
        _ = event
        if self._dragged_node is None and not self._panning:
            self.setCursor(QtCore.Qt.ArrowCursor)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:  # noqa: D401
        rect = self.rect().adjusted(10, 10, -10, -10)
        min_dlat, max_dlat = self._range
        left = rect.left()
        right = rect.right()
        width = max(1.0, float(right - left))
        cursor_x = event.pos().x()
        cursor_ratio = (cursor_x - left) / width
        cursor_dlat = self._x_to_dlat(cursor_x, left, width, min_dlat, max_dlat)
        span = max(max_dlat - min_dlat, 1.0)
        delta = event.angleDelta().y()
        if delta == 0:
            return
        zoom_factor = 0.9 if delta > 0 else 1.1
        new_span = max(span * zoom_factor, 1.0)
        new_max = cursor_dlat + cursor_ratio * new_span
        new_min = new_max - new_span
        self._range = (new_min, new_max)
        self.update()

    @staticmethod
    def _calculate_dlat_range(fsects: Iterable[PreviewFSection]) -> tuple[float, float]:
        values = [fs.start_dlat for fs in fsects] + [fs.end_dlat for fs in fsects]
        if not values:
            return (-1.0, 1.0)
        min_dlat = min(values)
        max_dlat = max(values)
        if min_dlat == max_dlat:
            pad = max(100.0, abs(min_dlat) * 0.1)
            return (min_dlat - pad, max_dlat + pad)
        pad = max((max_dlat - min_dlat) * 0.1, 100.0)
        return (min_dlat - pad, max_dlat + pad)

    @staticmethod
    def _dlat_to_x(
        dlat: float, left: float, width: float, min_dlat: float, max_dlat: float
    ) -> float:
        span = max(max_dlat - min_dlat, 1.0)
        ratio = (max_dlat - dlat) / span
        return left + ratio * width

    @staticmethod
    def _x_to_dlat(
        x: float, left: float, width: float, min_dlat: float, max_dlat: float
    ) -> float:
        span = max(max_dlat - min_dlat, 1.0)
        ratio = (x - left) / width
        return max_dlat - ratio * span

    def _draw_node(self, painter: QtGui.QPainter, node: _FsectNode) -> None:
        arrow_length = 5.0
        arrow_half_width = 3.0
        tip = node.center
        if node.endpoint == "start":
            base_y = tip.y() - arrow_length
        else:
            base_y = tip.y() + arrow_length

        polygon = QtGui.QPolygonF(
            [
                QtCore.QPointF(tip.x(), tip.y()),
                QtCore.QPointF(tip.x() - arrow_half_width, base_y),
                QtCore.QPointF(tip.x() + arrow_half_width, base_y),
            ]
        )
        color = self._pen_for_fsect(self._fsects[node.fsect_index]).color()
        painter.setBrush(color)
        pen = QtGui.QPen(color)
        pen.setWidthF(1.0)
        painter.setPen(pen)
        painter.drawPolygon(polygon)

    def _find_node_at(self, pos: QtCore.QPoint) -> _FsectNode | None:
        radius = 7
        for node in self._nodes:
            if QtCore.QLineF(pos, node.center).length() <= radius:
                return node
        return None

    def _snap_dlat(
        self,
        node: _FsectNode,
        cursor_x: float,
        left: float,
        width: float,
        min_dlat: float,
        max_dlat: float,
    ) -> float | None:
        if node.endpoint == "start":
            candidates = [fsect.end_dlat for fsect in self._prev_fsects]
        else:
            candidates = [fsect.start_dlat for fsect in self._next_fsects]
        if not candidates:
            return None
        snapped_dlat = None
        closest = self._SNAP_DISTANCE_PX
        for dlat in candidates:
            candidate_x = self._dlat_to_x(dlat, left, width, min_dlat, max_dlat)
            distance = abs(cursor_x - candidate_x)
            if distance <= closest:
                closest = distance
                snapped_dlat = dlat
        return snapped_dlat

    @staticmethod
    def _pen_for_fsect(fsect: PreviewFSection) -> QtGui.QPen:
        style = resolve_fsection_style(fsect.surface_type, fsect.type2)
        if (
            style is not None
            and style.role == "boundary"
            and style.boundary_color is not None
        ):
            return sg_rendering.make_boundary_pen(
                style.boundary_color,
                is_fence=style.is_fence,
                width=2.0,
            )
        if style is not None and style.surface_color is not None:
            color = style.surface_color
        else:
            color = sg_rendering.DEFAULT_SURFACE_COLOR
        pen = QtGui.QPen(color)
        pen.setWidthF(2.0)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        return pen

    def _draw_stub_lines(
        self,
        painter: QtGui.QPainter,
        left: float,
        width: float,
        top: float,
        bottom: float,
        min_dlat: float,
        max_dlat: float,
    ) -> None:
        stub_length = 6.0
        stub_offset = 0.0
        top_start = QtCore.QPointF
        bottom_start = QtCore.QPointF
        for fsect in self._next_fsects:
            x = self._dlat_to_x(fsect.start_dlat, left, width, min_dlat, max_dlat)
            pen = self._pen_for_fsect(fsect)
            painter.setPen(pen)
            painter.drawLine(
                top_start(x, top - stub_offset - stub_length),
                top_start(x, top - stub_offset),
            )
        for fsect in self._prev_fsects:
            x = self._dlat_to_x(fsect.end_dlat, left, width, min_dlat, max_dlat)
            pen = self._pen_for_fsect(fsect)
            painter.setPen(pen)
            painter.drawLine(
                bottom_start(x, bottom + stub_offset),
                bottom_start(x, bottom + stub_offset + stub_length),
            )

    def _draw_ruler(
        self,
        painter: QtGui.QPainter,
        left: float,
        right: float,
        top: float,
        bottom: float,
        min_dlat: float,
        max_dlat: float,
    ) -> None:
        span = max(max_dlat - min_dlat, 1.0)
        width = max(1.0, float(right - left))
        pixels_per_foot = width / span
        step = self._select_ruler_step(pixels_per_foot)
        start_tick = math.ceil(min_dlat / step) * step

        painter.save()
        font = painter.font()
        font.setPointSize(self._RULER_FONT_SIZE)
        painter.setFont(font)
        pen = QtGui.QPen(QtGui.QColor(180, 180, 180))
        painter.setPen(pen)

        tick_length = self._RULER_TICK_LENGTH
        for dlat in self._frange(start_tick, max_dlat, step):
            x = self._dlat_to_x(dlat, left, width, min_dlat, max_dlat)
            painter.drawLine(
                QtCore.QPointF(x, top),
                QtCore.QPointF(x, top + tick_length),
            )
            painter.drawLine(
                QtCore.QPointF(x, bottom),
                QtCore.QPointF(x, bottom - tick_length),
            )
            label = f"{dlat:.0f}"
            metrics = QtGui.QFontMetrics(font)
            label_width = metrics.horizontalAdvance(label)
            label_height = metrics.height()
            painter.drawText(
                QtCore.QRectF(
                    x - label_width / 2,
                    top - label_height - self._RULER_LABEL_MARGIN,
                    label_width,
                    label_height,
                ),
                QtCore.Qt.AlignCenter,
                label,
            )
            painter.drawText(
                QtCore.QRectF(
                    x - label_width / 2,
                    bottom + self._RULER_LABEL_MARGIN,
                    label_width,
                    label_height,
                ),
                QtCore.Qt.AlignCenter,
                label,
            )

        painter.restore()

    @staticmethod
    def _select_ruler_step(pixels_per_foot: float) -> float:
        if pixels_per_foot >= 25.0:
            return 1.0
        if pixels_per_foot >= 12.0:
            return 5.0
        return 10.0

    @staticmethod
    def _frange(start: float, stop: float, step: float) -> Iterable[float]:
        if step <= 0:
            return []
        value = start
        while value <= stop:
            yield value
            value += step

    def _draw_placeholder(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        painter.save()
        pen = QtGui.QPen(QtGui.QColor(200, 200, 200))
        painter.setPen(pen)
        painter.drawText(rect, QtCore.Qt.AlignCenter, "No fsects to display")
        painter.restore()

    def _update_local_dlat(self, node: _FsectNode, new_dlat: float) -> None:
        if node.fsect_index < 0 or node.fsect_index >= len(self._fsects):
            return
        current = self._fsects[node.fsect_index]
        if node.endpoint == "start":
            self._fsects[node.fsect_index] = PreviewFSection(
                start_dlat=new_dlat,
                end_dlat=current.end_dlat,
                surface_type=current.surface_type,
                type2=current.type2,
            )
        else:
            self._fsects[node.fsect_index] = PreviewFSection(
                start_dlat=current.start_dlat,
                end_dlat=new_dlat,
                surface_type=current.surface_type,
                type2=current.type2,
            )
