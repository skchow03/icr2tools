from __future__ import annotations

from dataclasses import dataclass
import math

from PyQt5 import QtCore, QtGui, QtWidgets

from sg_viewer.ui.altitude_units import units_from_500ths

@dataclass
class XsectElevationData:
    section_index: int
    altitudes: list[float | None]
    xsect_dlats: list[float] | None = None
    selected_xsect_index: int | None = None
    y_range: tuple[float, float] | None = None
    unit: str = "500ths"
    unit_label: str = "500ths"
    decimals: int = 0


class XsectElevationWidget(QtWidgets.QWidget):
    """Renders elevation values across x-sections for the selected section."""

    xsectClicked = QtCore.pyqtSignal(int)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(140)
        self._data: XsectElevationData | None = None
        self._y_view_range: tuple[float, float] | None = None
        self._data_signature: tuple[int, int, float, float] | None = None

    def set_xsect_data(self, data: XsectElevationData | None) -> None:
        signature = self._signature_for(data)
        if signature is None:
            self._y_view_range = None
        elif self._data_signature != signature:
            self._y_view_range = None
        self._data = data
        self._data_signature = signature
        self.update()

    @staticmethod
    def _signature_for(data: XsectElevationData | None) -> tuple[int, int, float, float] | None:
        if data is None:
            return None
        dlats = data.xsect_dlats if data.xsect_dlats else []
        min_dlat = float(min(dlats)) if dlats else 0.0
        max_dlat = float(max(dlats)) if dlats else 0.0
        return (len(data.altitudes), data.section_index, min_dlat, max_dlat)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:  # noqa: D401
        if self._data is None:
            return
        if not (event.modifiers() & QtCore.Qt.ControlModifier):
            return

        plot_context = self._plot_context()
        if plot_context is None:
            return
        plot_rect, min_alt, max_alt = plot_context
        if not plot_rect.contains(event.position().toPoint()):
            return

        delta = event.angleDelta().y()
        if delta == 0:
            return
        span = max_alt - min_alt
        if span <= 0:
            return

        zoom_factor = 0.9 if delta > 0 else 1.1
        new_span = max(span * zoom_factor, 1.0)
        cursor_y = min(max(event.position().y(), plot_rect.top()), plot_rect.bottom())
        ratio = (plot_rect.bottom() - cursor_y) / plot_rect.height()
        focus = min_alt + ratio * span
        new_min = focus - ratio * new_span
        new_max = new_min + new_span

        self._y_view_range = (new_min, new_max)
        self.update()
        event.accept()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: D401
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), self.palette().color(QtGui.QPalette.Base))

        if self._data is None:
            painter.setPen(QtGui.QPen(QtGui.QColor("#888")))
            painter.drawText(
                self.rect(),
                QtCore.Qt.AlignCenter,
                "Select a section to view x-section elevation.",
            )
            painter.end()
            return

        altitudes = self._data.altitudes
        valid = [alt for alt in altitudes if alt is not None]
        if not altitudes or not valid:
            painter.setPen(QtGui.QPen(QtGui.QColor("#888")))
            painter.drawText(
                self.rect(),
                QtCore.Qt.AlignCenter,
                "No elevation data for the selected section.",
            )
            painter.end()
            return

        plot_context = self._plot_context()
        if plot_context is None:
            painter.end()
            return
        plot_rect, min_alt, max_alt = plot_context

        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor("#bbb")))
        painter.drawRect(plot_rect)

        self._draw_profile(painter, plot_rect, altitudes, min_alt, max_alt)
        self._draw_axes_labels(painter, plot_rect, min_alt, max_alt)
        painter.restore()
        painter.end()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if event.button() != QtCore.Qt.LeftButton or self._data is None:
            return

        plot_context = self._plot_context()
        if plot_context is None:
            return
        plot_rect, min_alt, max_alt = plot_context
        if not plot_rect.contains(event.pos()):
            return

        altitudes = self._data.altitudes
        count = len(altitudes)
        if count == 0:
            return

        dlats = self._data.xsect_dlats
        click_pos = event.pos()
        radius = 6.0
        for idx, altitude in enumerate(altitudes):
            if altitude is None:
                continue
            x = self._map_x(idx, plot_rect, count, dlats)
            y = self._map_y(altitude, plot_rect, min_alt, max_alt)
            if QtCore.QLineF(click_pos, QtCore.QPointF(x, y)).length() <= radius:
                self.xsectClicked.emit(idx)
                return

    def _draw_profile(
        self,
        painter: QtGui.QPainter,
        rect: QtCore.QRect,
        altitudes: list[float | None],
        min_alt: float,
        max_alt: float,
    ) -> None:
        count = len(altitudes)
        if count == 0:
            return

        dlats = self._data.xsect_dlats if self._data else None
        selected_index = self._data.selected_xsect_index if self._data else None

        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setPen(QtGui.QPen(QtGui.QColor("#4caf50"), 2.0))
        painter.setClipRect(rect)

        path = QtGui.QPainterPath()
        started = False
        for idx, altitude in enumerate(altitudes):
            if altitude is None:
                started = False
                continue
            x = self._map_x(idx, rect, count, dlats)
            y = self._map_y(altitude, rect, min_alt, max_alt)
            if not started:
                path.moveTo(x, y)
                started = True
            else:
                path.lineTo(x, y)

        painter.drawPath(path)

        radius = 3.0
        for idx, altitude in enumerate(altitudes):
            if altitude is None:
                continue
            if idx == selected_index:
                continue
            x = self._map_x(idx, rect, count, dlats)
            y = self._map_y(altitude, rect, min_alt, max_alt)
            painter.setBrush(QtGui.QBrush(QtGui.QColor("#4caf50")))
            painter.drawEllipse(QtCore.QRectF(x - radius, y - radius, radius * 2, radius * 2))

        if (
            selected_index is not None
            and 0 <= selected_index < count
            and altitudes[selected_index] is not None
        ):
            selected_alt = altitudes[selected_index]
            selected_x = self._map_x(selected_index, rect, count, dlats)
            selected_y = self._map_y(selected_alt, rect, min_alt, max_alt)
            highlight_radius = 4.5
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.setPen(QtGui.QPen(QtGui.QColor("#4caf50"), 2.0))
            painter.drawEllipse(
                QtCore.QRectF(
                    selected_x - highlight_radius,
                    selected_y - highlight_radius,
                    highlight_radius * 2,
                    highlight_radius * 2,
                )
            )
        painter.restore()

    def _draw_axes_labels(
        self,
        painter: QtGui.QPainter,
        rect: QtCore.QRect,
        min_alt: float,
        max_alt: float,
    ) -> None:
        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor("#888")))
        font = painter.font()
        font.setPointSize(max(font.pointSize() - 1, 7))
        painter.setFont(font)

        min_display = units_from_500ths(min_alt, self._data.unit)
        max_display = units_from_500ths(max_alt, self._data.unit)
        decimals = max(self._data.decimals, 0)
        if decimals == 0:
            min_text = f"{int(round(min_display))}"
            max_text = f"{int(round(max_display))}"
        else:
            min_text = f"{min_display:.{decimals}f}"
            max_text = f"{max_display:.{decimals}f}"
        unit_label = self._data.unit_label
        unit_suffix = f" {unit_label}" if unit_label else ""
        painter.drawText(
            rect.adjusted(0, -18, 0, 0),
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop,
            f"Alt: {min_text}–{max_text}{unit_suffix}",
        )
        bank_angles = self._banking_angles_degrees()
        if bank_angles is not None:
            prev_bank, next_bank = bank_angles
            painter.drawText(
                rect.adjusted(0, -18, 0, 0),
                QtCore.Qt.AlignRight | QtCore.Qt.AlignTop,
                f"Bank Prev: {prev_bank:+.2f}°  Next: {next_bank:+.2f}°",
            )
        painter.restore()

    def _banking_angles_degrees(self) -> tuple[float, float] | None:
        if self._data is None:
            return None

        altitudes = self._data.altitudes
        selected_index = self._data.selected_xsect_index
        if selected_index is None:
            return None
        prev_idx = selected_index - 1
        next_idx = selected_index + 1

        prev_angle = self._banking_angle_between(selected_index, prev_idx)
        next_angle = self._banking_angle_between(selected_index, next_idx)
        if prev_angle is None or next_angle is None:
            return None
        return prev_angle, next_angle

    def _banking_angle_between(self, base_idx: int, other_idx: int) -> float | None:
        altitudes = self._data.altitudes if self._data else None
        if altitudes is None:
            return None
        if other_idx < 0 or other_idx >= len(altitudes):
            return 0.0

        base_alt = altitudes[base_idx]
        other_alt = altitudes[other_idx]
        if base_alt is None or other_alt is None:
            return None

        dlats = self._data.xsect_dlats if self._data else None
        if dlats and len(dlats) == len(altitudes):
            delta_dlat = dlats[other_idx] - dlats[base_idx]
        else:
            delta_dlat = float(other_idx - base_idx)

        if math.isclose(delta_dlat, 0.0):
            return None

        slope = (other_alt - base_alt) / delta_dlat
        return math.degrees(math.atan(slope))

    def _plot_context(self) -> tuple[QtCore.QRect, float, float] | None:
        if self._data is None:
            return None
        altitudes = self._data.altitudes
        valid = [alt for alt in altitudes if alt is not None]
        if not altitudes or not valid:
            return None

        margins = QtCore.QMargins(48, 18, 16, 28)
        plot_rect = self.rect().marginsRemoved(margins)
        if plot_rect.width() <= 0 or plot_rect.height() <= 0:
            return None

        if self._y_view_range is not None:
            min_alt, max_alt = self._y_view_range
        elif self._data.y_range is not None:
            min_alt, max_alt = self._data.y_range
        else:
            min_alt = min(valid)
            max_alt = max(valid)
            if min_alt == max_alt:
                min_alt -= 1
                max_alt += 1
            padding = max(1.0, (max_alt - min_alt) * 0.05)
            min_alt -= padding
            max_alt += padding

        min_alt, max_alt = self._adjust_y_range_for_aspect(
            min_alt, max_alt, plot_rect, altitudes, self._data.xsect_dlats
        )
        return plot_rect, min_alt, max_alt

    @staticmethod
    def _adjust_y_range_for_aspect(
        min_alt: float,
        max_alt: float,
        rect: QtCore.QRect,
        altitudes: list[float | None],
        dlats: list[float] | None,
    ) -> tuple[float, float]:
        count = len(altitudes)
        if count <= 1 or rect.width() <= 0 or rect.height() <= 0:
            return min_alt, max_alt

        if dlats and len(dlats) == count:
            x_span = abs(max(dlats) - min(dlats))
        else:
            x_span = float(count - 1)

        if x_span <= 0:
            return min_alt, max_alt

        target_y_span = x_span * rect.height() / rect.width()
        current_span = max(max_alt - min_alt, 1e-6)
        y_span = max(current_span, target_y_span)
        center = (max_alt + min_alt) / 2.0
        return center - y_span / 2.0, center + y_span / 2.0

    @staticmethod
    def _map_x(
        index: int,
        rect: QtCore.QRect,
        count: int,
        dlats: list[float] | None = None,
    ) -> float:
        if count <= 1:
            return rect.right()
        if dlats and len(dlats) == count:
            min_dlat = min(dlats)
            max_dlat = max(dlats)
            if max_dlat == min_dlat:
                return rect.center().x()
            ratio = (dlats[index] - min_dlat) / (max_dlat - min_dlat)
            return rect.right() - ratio * rect.width()
        ratio = index / (count - 1)
        return rect.right() - ratio * rect.width()

    @staticmethod
    def _map_y(altitude: float, rect: QtCore.QRect, min_alt: float, max_alt: float) -> float:
        span = max(max_alt - min_alt, 1e-6)
        relative = (altitude - min_alt) / span
        return rect.bottom() - relative * rect.height()
