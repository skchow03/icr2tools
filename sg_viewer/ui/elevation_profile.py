from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math

from PyQt5 import QtCore, QtGui, QtWidgets


class ElevationSource(Enum):
    SG = "sg"
    TRK = "trk"


@dataclass
class ElevationProfileData:
    """Represents the elevation samples for a single x-section."""

    dlongs: list[float]
    sg_altitudes: list[float]
    trk_altitudes: list[float] | None
    section_ranges: list[tuple[float, float]]
    track_length: float
    xsect_label: str
    sources: tuple[ElevationSource, ...] = (ElevationSource.SG,)


class ElevationProfileWidget(QtWidgets.QWidget):
    """Lightweight plot for showing SG elevation behaviour."""

    sectionClicked = QtCore.pyqtSignal(int)
    altitudeDragged = QtCore.pyqtSignal(int, float)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(180)
        self._data: ElevationProfileData | None = None
        self._selected_range: tuple[float, float] | None = None
        self._x_view_range: tuple[float, float] | None = None
        self._is_panning = False
        self._is_dragging_marker = False
        self._dragged_section: int | None = None
        self._pan_start_pos: QtCore.QPoint | None = None
        self._pan_start_range: tuple[float, float] | None = None
        self._pending_click = False

    def set_profile_data(self, data: ElevationProfileData | None) -> None:
        if data is None:
            self._data = None
            self._x_view_range = None
            self.update()
            return

        if self._data is None:
            self._x_view_range = None

        self._data = data
        self.update()

    def set_selected_range(self, dlong_range: tuple[float, float] | None) -> None:
        self._selected_range = dlong_range
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: D401
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), self.palette().color(QtGui.QPalette.Base))

        if self._data is None or not self._data.dlongs:
            painter.setPen(QtGui.QPen(QtGui.QColor("#888")))
            painter.drawText(
                self.rect(),
                QtCore.Qt.AlignCenter,
                "Load an SG file and select an x-section to view elevation.",
            )
            painter.end()
            return

        margins = QtCore.QMargins(48, 20, 16, 32)
        plot_rect = self.rect().marginsRemoved(margins)
        if plot_rect.width() <= 0 or plot_rect.height() <= 0:
            painter.end()
            return

        min_alt, max_alt = self._alt_bounds()
        if min_alt == max_alt:
            min_alt -= 1
            max_alt += 1

        max_dlong = self._max_dlong()
        if max_dlong <= 0:
            painter.end()
            return

        x_start, x_end = self._x_bounds(max_dlong)
        if x_end <= x_start:
            painter.end()
            return

        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor("#bbb")))
        painter.drawRect(plot_rect)

        self._draw_section_highlight(painter, plot_rect, x_start, x_end)
        self._draw_series(painter, plot_rect, x_start, x_end, min_alt, max_alt)
        self._draw_section_markers(painter, plot_rect, x_start, x_end, min_alt, max_alt)
        self._draw_axes_labels(painter, plot_rect, min_alt, max_alt)
        self._draw_legend(painter, plot_rect)
        painter.restore()
        painter.end()

    def _draw_section_highlight(
        self, painter: QtGui.QPainter, rect: QtCore.QRect, x_start: float, x_end: float
    ) -> None:
        if self._selected_range is None:
            return

        start, end = self._selected_range
        span = max(end - start, 0.0)
        if span <= 0:
            return

        start_x = self._map_x(start, rect, x_start, x_end)
        end_x = self._map_x(end, rect, x_start, x_end)
        highlight_rect = QtCore.QRectF(start_x, rect.top(), end_x - start_x, rect.height())

        color = QtGui.QColor("#3f51b5")
        color.setAlpha(32)
        painter.fillRect(highlight_rect, QtGui.QBrush(color))

    def _draw_series(
        self,
        painter: QtGui.QPainter,
        rect: QtCore.QRect,
        x_start: float,
        x_end: float,
        min_alt: float,
        max_alt: float,
    ) -> None:
        sg_path = QtGui.QPainterPath()
        trk_path = QtGui.QPainterPath()
        draw_trk = (
            self._data.trk_altitudes is not None
            and ElevationSource.TRK in self._data.sources
        )
        for idx, dlong in enumerate(self._data.dlongs):
            x = self._map_x(dlong, rect, x_start, x_end)
            y_sg = self._map_y(self._data.sg_altitudes[idx], rect, min_alt, max_alt)
            if draw_trk:
                y_trk = self._map_y(self._data.trk_altitudes[idx], rect, min_alt, max_alt)

            if idx == 0:
                sg_path.moveTo(x, y_sg)
                if draw_trk:
                    trk_path.moveTo(x, y_trk)
            else:
                sg_path.lineTo(x, y_sg)
                if draw_trk:
                    trk_path.lineTo(x, y_trk)

        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        painter.setPen(QtGui.QPen(QtGui.QColor("#03a9f4"), 2.0))
        painter.drawPath(sg_path)

        if draw_trk:
            trk_pen = QtGui.QPen(QtGui.QColor("#ff9800"), 2.0)
            trk_pen.setStyle(QtCore.Qt.DashLine)
            painter.setPen(trk_pen)
            painter.drawPath(trk_path)
        painter.restore()

    def _draw_section_markers(
        self,
        painter: QtGui.QPainter,
        rect: QtCore.QRect,
        x_start: float,
        x_end: float,
        min_alt: float,
        max_alt: float,
    ) -> None:
        if not self._data.section_ranges:
            return

        selected_end: float | None = None
        if self._selected_range is not None:
            selected_end = self._selected_range[1]

        radius = 4.0
        pen = QtGui.QPen(QtGui.QColor("#03a9f4"), 1.5)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setPen(pen)

        for _, end in self._data.section_ranges:
            altitude = self._altitude_at_dlong(end)
            if altitude is None:
                continue
            x = self._map_x(end, rect, x_start, x_end)
            y = self._map_y(altitude, rect, min_alt, max_alt)
            rect_f = QtCore.QRectF(x - radius, y - radius, radius * 2, radius * 2)
            is_selected_end = (
                selected_end is not None
                and math.isclose(end, selected_end, rel_tol=1e-6, abs_tol=1e-3)
            )
            if is_selected_end:
                painter.setBrush(QtCore.Qt.NoBrush)
            else:
                painter.setBrush(QtGui.QBrush(QtGui.QColor("#03a9f4")))
            painter.drawEllipse(rect_f)

        painter.restore()

    def _selected_marker_position(
        self,
        rect: QtCore.QRect,
        x_start: float,
        x_end: float,
        min_alt: float,
        max_alt: float,
    ) -> tuple[QtCore.QPointF, int] | None:
        if self._selected_range is None:
            return None

        selected_end = self._selected_range[1]
        altitude = self._altitude_at_dlong(selected_end)
        if altitude is None:
            return None

        section_index = self._section_index_for_dlong(selected_end)
        if section_index is None:
            return None

        x = self._map_x(selected_end, rect, x_start, x_end)
        y = self._map_y(altitude, rect, min_alt, max_alt)
        return QtCore.QPointF(x, y), section_index

    def _draw_axes_labels(
        self, painter: QtGui.QPainter, rect: QtCore.QRect, min_alt: float, max_alt: float
    ) -> None:
        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor("#888")))
        font = painter.font()
        font.setPointSize(max(font.pointSize() - 1, 7))
        painter.setFont(font)

        painter.drawText(rect.adjusted(-36, 0, 0, 0), QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop, self._data.xsect_label)
        painter.drawText(
            rect.adjusted(0, 0, 0, 18),
            QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom,
            "DLONG",
        )
        painter.drawText(
            rect.adjusted(0, -18, 0, 0),
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop,
            f"Alt: {min_alt:.0f}–{max_alt:.0f}",
        )
        painter.restore()

    def _draw_legend(self, painter: QtGui.QPainter, rect: QtCore.QRect) -> None:
        legend_items = [("SG-derived cubic", QtGui.QColor("#03a9f4"))]
        if self._data.trk_altitudes is not None and ElevationSource.TRK in self._data.sources:
            legend_items.append(("TRK stored", QtGui.QColor("#ff9800")))
        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor("#ccc")))
        font = painter.font()
        font.setPointSize(max(font.pointSize() - 1, 7))
        painter.setFont(font)

        x = rect.left() + 8
        y = rect.top() + 10
        for label, color in legend_items:
            painter.setBrush(QtGui.QBrush(color))
            painter.drawRect(x, y - 6, 12, 6)
            painter.drawText(x + 18, y, label)
            y += 16

        painter.restore()

    def _map_x(
        self, dlong: float, rect: QtCore.QRect, x_start: float, x_end: float
    ) -> float:
        span = max(x_end - x_start, 1e-6)
        relative = (dlong - x_start) / span
        return rect.left() + relative * rect.width()

    def _map_y(self, altitude: float, rect: QtCore.QRect, min_alt: float, max_alt: float) -> float:
        span = max_alt - min_alt
        relative = (altitude - min_alt) / span
        return rect.bottom() - relative * rect.height()

    def _alt_bounds(self) -> tuple[float, float]:
        alts = list(self._data.sg_altitudes)
        if self._data.trk_altitudes is not None and ElevationSource.TRK in self._data.sources:
            alts.extend(self._data.trk_altitudes)
        min_alt = min(alts)
        max_alt = max(alts)
        padding = max(1.0, (max_alt - min_alt) * 0.05)
        return min_alt - padding, max_alt + padding

    def _max_dlong(self) -> float:
        return max(max(self._data.dlongs), self._data.track_length)

    def _altitude_at_dlong(self, dlong: float) -> float | None:
        if not self._data.dlongs:
            return None

        dlongs = self._data.dlongs
        altitudes = self._data.sg_altitudes
        if dlong <= dlongs[0]:
            return altitudes[0]
        if dlong >= dlongs[-1]:
            return altitudes[-1]

        for idx in range(1, len(dlongs)):
            if dlongs[idx] >= dlong:
                d0 = dlongs[idx - 1]
                d1 = dlongs[idx]
                if math.isclose(d1, d0):
                    return altitudes[idx]
                ratio = (dlong - d0) / (d1 - d0)
                return altitudes[idx - 1] + ratio * (altitudes[idx] - altitudes[idx - 1])
        return altitudes[-1]

    def _x_bounds(self, max_dlong: float) -> tuple[float, float]:
        if self._x_view_range is None:
            return 0.0, max_dlong
        start, end = self._x_view_range
        start = max(0.0, min(start, max_dlong))
        end = max(0.0, min(end, max_dlong))
        if end <= start:
            return 0.0, max_dlong
        return start, end

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:  # noqa: D401
        if self._data is None or not self._data.dlongs:
            return

        delta = event.angleDelta().y()
        if delta == 0:
            return

        margins = QtCore.QMargins(48, 20, 16, 32)
        plot_rect = self.rect().marginsRemoved(margins)
        if plot_rect.width() <= 0:
            return

        max_dlong = self._max_dlong()
        if max_dlong <= 0:
            return

        x_start, x_end = self._x_bounds(max_dlong)
        span = x_end - x_start
        if span <= 0:
            return

        zoom_in = delta > 0
        zoom_factor = 0.9 if zoom_in else 1.1
        new_span = max(span * zoom_factor, max_dlong * 0.02, 1.0)
        new_span = min(new_span, max_dlong)

        cursor_x = min(max(event.position().x(), plot_rect.left()), plot_rect.right())
        ratio = (cursor_x - plot_rect.left()) / plot_rect.width()
        focus = x_start + ratio * span

        new_start = focus - ratio * new_span
        new_end = new_start + new_span

        if new_start < 0:
            new_start = 0.0
            new_end = new_span
        if new_end > max_dlong:
            new_end = max_dlong
            new_start = max(0.0, max_dlong - new_span)

        self._x_view_range = (new_start, new_end)
        self.update()
        event.accept()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if event.button() != QtCore.Qt.LeftButton:
            return
        if self._data is None or not self._data.dlongs:
            return
        hit_marker = self._hit_selected_marker(event.pos())
        if hit_marker is not None:
            self._is_dragging_marker = True
            self._dragged_section = hit_marker
            self._pending_click = False
            self._pan_start_pos = None
            self._pan_start_range = None
            self.setCursor(QtCore.Qt.SizeVerCursor)
            event.accept()
            return
        self._is_panning = False
        self._pending_click = True
        self._pan_start_pos = event.pos()
        max_dlong = self._max_dlong()
        self._pan_start_range = self._x_bounds(max_dlong)
        event.accept()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if self._is_dragging_marker:
            self._update_dragged_altitude(event.pos())
            event.accept()
            return
        if self._pan_start_pos is None or not self._pending_click:
            return
        if self._data is None or not self._data.dlongs:
            return
        if not self._is_panning:
            threshold = QtWidgets.QApplication.startDragDistance()
            if (event.pos() - self._pan_start_pos).manhattanLength() < threshold:
                return
            self._is_panning = True
            self.setCursor(QtCore.Qt.ClosedHandCursor)

        margins = QtCore.QMargins(48, 20, 16, 32)
        plot_rect = self.rect().marginsRemoved(margins)
        if plot_rect.width() <= 0:
            return

        max_dlong = self._max_dlong()
        if max_dlong <= 0 or self._pan_start_range is None:
            return

        start, end = self._pan_start_range
        span = end - start
        if span <= 0:
            return

        delta_pixels = event.pos().x() - self._pan_start_pos.x()
        delta_ratio = delta_pixels / plot_rect.width()
        delta_dlong = -delta_ratio * span

        new_start = start + delta_dlong
        new_end = end + delta_dlong
        if new_start < 0:
            new_start = 0.0
            new_end = span
        if new_end > max_dlong:
            new_end = max_dlong
            new_start = max(0.0, max_dlong - span)

        self._x_view_range = (new_start, new_end)
        self.update()
        event.accept()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if event.button() != QtCore.Qt.LeftButton:
            return
        if self._is_dragging_marker:
            self._is_dragging_marker = False
            self._dragged_section = None
            self.unsetCursor()
            event.accept()
            return
        if self._pending_click and not self._is_panning:
            self._handle_click(event.pos())
        self._is_panning = False
        self._pending_click = False
        self._pan_start_pos = None
        self._pan_start_range = None
        self.unsetCursor()
        event.accept()

    def _hit_selected_marker(self, pos: QtCore.QPoint) -> int | None:
        if self._data is None or not self._data.dlongs:
            return None
        margins = QtCore.QMargins(48, 20, 16, 32)
        plot_rect = self.rect().marginsRemoved(margins)
        if plot_rect.width() <= 0 or plot_rect.height() <= 0:
            return None
        max_dlong = self._max_dlong()
        if max_dlong <= 0:
            return None
        x_start, x_end = self._x_bounds(max_dlong)
        if x_end <= x_start:
            return None
        min_alt, max_alt = self._alt_bounds()
        if min_alt == max_alt:
            min_alt -= 1
            max_alt += 1
        marker = self._selected_marker_position(
            plot_rect, x_start, x_end, min_alt, max_alt
        )
        if marker is None:
            return None
        marker_pos, section_index = marker
        radius = 6.0
        dx = marker_pos.x() - pos.x()
        dy = marker_pos.y() - pos.y()
        if dx * dx + dy * dy <= radius * radius:
            return section_index
        return None

    def _update_dragged_altitude(self, pos: QtCore.QPoint) -> None:
        if self._data is None or not self._data.dlongs or self._dragged_section is None:
            return
        margins = QtCore.QMargins(48, 20, 16, 32)
        plot_rect = self.rect().marginsRemoved(margins)
        if plot_rect.width() <= 0 or plot_rect.height() <= 0:
            return
        max_dlong = self._max_dlong()
        if max_dlong <= 0:
            return
        x_start, x_end = self._x_bounds(max_dlong)
        if x_end <= x_start:
            return
        min_alt, max_alt = self._alt_bounds()
        if min_alt == max_alt:
            min_alt -= 1
            max_alt += 1
        clamped_y = min(max(pos.y(), plot_rect.top()), plot_rect.bottom())
        ratio = (plot_rect.bottom() - clamped_y) / plot_rect.height()
        altitude = min_alt + ratio * (max_alt - min_alt)
        self.altitudeDragged.emit(self._dragged_section, altitude)

    def _handle_click(self, pos: QtCore.QPoint) -> None:
        if self._data is None or not self._data.dlongs:
            return
        margins = QtCore.QMargins(48, 20, 16, 32)
        plot_rect = self.rect().marginsRemoved(margins)
        if plot_rect.width() <= 0 or not plot_rect.contains(pos):
            return

        max_dlong = self._max_dlong()
        if max_dlong <= 0:
            return

        x_start, x_end = self._x_bounds(max_dlong)
        span = x_end - x_start
        if span <= 0:
            return

        ratio = (pos.x() - plot_rect.left()) / plot_rect.width()
        ratio = min(max(ratio, 0.0), 1.0)
        dlong = x_start + ratio * span

        section_index = self._section_index_for_dlong(dlong)
        if section_index is not None:
            self.sectionClicked.emit(section_index)

    def _section_index_for_dlong(self, dlong: float) -> int | None:
        if not self._data.section_ranges:
            return None

        track_length = self._data.track_length
        for idx, (start, end) in enumerate(self._data.section_ranges):
            if start <= dlong <= end:
                return idx
            if track_length > 0 and end > track_length and (
                dlong >= start or dlong <= end - track_length
            ):
                return idx
        return None
