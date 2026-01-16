"""Widget for plotting LP speed over DLONG."""
from __future__ import annotations

from typing import Iterable

from PyQt5 import QtCore, QtGui, QtWidgets

from track_viewer.ai.ai_line_service import LpPoint


class LpSpeedGraphWidget(QtWidgets.QWidget):
    """Small graph plotting LP speed along DLONG."""

    _ZOOM_MIN = 0.5
    _ZOOM_MAX = 8.0

    def __init__(self) -> None:
        super().__init__()
        self._records: list[LpPoint] = []
        self._x_zoom = 1.0
        self._y_zoom = 1.0
        self._x_center: float | None = None
        self._y_center: float | None = None
        self._x_range: float | None = None
        self._y_range: float | None = None
        self._x_min: float | None = None
        self._x_max: float | None = None
        self._y_min: float | None = None
        self._y_max: float | None = None
        self._selected_index: int | None = None
        self._follow_selection = True
        self.setMinimumHeight(160)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )

    def set_records(self, records: Iterable[LpPoint]) -> None:
        self._records = sorted(records, key=lambda record: record.dlong)
        self._reset_ranges()
        if self._follow_selection:
            self._center_on_selected_record()
        self.update()

    def zoom_x(self, factor: float) -> None:
        self._x_zoom = self._clamp_zoom(self._x_zoom * factor)
        self.update()

    def zoom_y(self, factor: float) -> None:
        self._y_zoom = self._clamp_zoom(self._y_zoom * factor)
        self.update()

    def reset_zoom(self) -> None:
        self._x_zoom = 1.0
        self._y_zoom = 1.0
        self.update()

    def set_selected_index(self, index: int | None) -> None:
        self._selected_index = index
        if self._follow_selection:
            self._center_on_selected_record()
        self.update()

    def set_follow_selection(self, follow: bool) -> None:
        self._follow_selection = follow
        if follow:
            self._center_on_selected_record()
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: D401
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), self.palette().color(QtGui.QPalette.Base))

        if not self._records:
            painter.setPen(QtGui.QColor(120, 120, 120))
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, "No LP speeds loaded.")
            painter.end()
            return

        margin_left = 48
        margin_right = 12
        margin_top = 12
        margin_bottom = 28
        plot_rect = QtCore.QRectF(
            margin_left,
            margin_top,
            max(10, self.width() - margin_left - margin_right),
            max(10, self.height() - margin_top - margin_bottom),
        )

        painter.setPen(QtGui.QColor(70, 70, 70))
        painter.drawRect(plot_rect)

        x_min, x_max = self._zoomed_bounds(
            self._x_center, self._x_range, self._x_zoom, self._x_min, self._x_max
        )
        y_min, y_max = self._zoomed_bounds(
            self._y_center, self._y_range, self._y_zoom, self._y_min, self._y_max
        )
        if x_min is None or x_max is None or y_min is None or y_max is None:
            painter.end()
            return
        if x_max <= x_min or y_max <= y_min:
            painter.end()
            return

        clip_rect = plot_rect.adjusted(1, 1, -1, -1)
        painter.save()
        painter.setClipRect(clip_rect)

        path = QtGui.QPainterPath()
        for index, record in enumerate(self._records):
            x = self._map_value(
                record.dlong, x_min, x_max, plot_rect.left(), plot_rect.right()
            )
            y = self._map_value(
                record.speed_mph, y_min, y_max, plot_rect.bottom(), plot_rect.top()
            )
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)

        painter.setPen(QtGui.QPen(QtGui.QColor(52, 152, 219), 2))
        painter.drawPath(path)

        if (
            self._selected_index is not None
            and 0 <= self._selected_index < len(self._records)
        ):
            highlight_index = self._selected_index
            start_index = highlight_index
            end_index = highlight_index + 1
            if end_index >= len(self._records):
                end_index = highlight_index
                start_index = highlight_index - 1
            if (
                0 <= start_index < len(self._records)
                and 0 <= end_index < len(self._records)
            ):
                start_record = self._records[start_index]
                end_record = self._records[end_index]
                start_x = self._map_value(
                    start_record.dlong, x_min, x_max, plot_rect.left(), plot_rect.right()
                )
                start_y = self._map_value(
                    start_record.speed_mph, y_min, y_max, plot_rect.bottom(), plot_rect.top()
                )
                end_x = self._map_value(
                    end_record.dlong, x_min, x_max, plot_rect.left(), plot_rect.right()
                )
                end_y = self._map_value(
                    end_record.speed_mph, y_min, y_max, plot_rect.bottom(), plot_rect.top()
                )
                highlight_pen = QtGui.QPen(QtGui.QColor("#e53935"), 3)
                painter.setPen(highlight_pen)
                painter.drawLine(QtCore.QLineF(start_x, start_y, end_x, end_y))
                selected_record = self._records[highlight_index]
                selected_x = self._map_value(
                    selected_record.dlong,
                    x_min,
                    x_max,
                    plot_rect.left(),
                    plot_rect.right(),
                )
                selected_y = self._map_value(
                    selected_record.speed_mph,
                    y_min,
                    y_max,
                    plot_rect.bottom(),
                    plot_rect.top(),
                )
                painter.setBrush(QtGui.QBrush(QtGui.QColor("#e53935")))
                painter.drawEllipse(QtCore.QPointF(selected_x, selected_y), 4, 4)
                mph_label = f"{round(selected_record.speed_mph):.0f} mph"
                metrics = painter.fontMetrics()
                text_width = metrics.horizontalAdvance(mph_label)
                text_height = metrics.height()
                text_x = selected_x - (text_width / 2)
                text_y = selected_y - 6 - text_height
                text_x = max(
                    plot_rect.left() + 2,
                    min(text_x, plot_rect.right() - text_width - 2),
                )
                text_y = max(plot_rect.top() + 2, text_y)
                painter.setPen(QtGui.QColor("#e53935"))
                painter.drawText(
                    QtCore.QRectF(text_x, text_y, text_width, text_height),
                    QtCore.Qt.AlignCenter,
                    mph_label,
                )

        painter.restore()

        painter.setPen(QtGui.QColor(90, 90, 90))
        painter.drawText(
            QtCore.QRectF(0, plot_rect.bottom() + 4, self.width(), 20),
            QtCore.Qt.AlignCenter,
            "DLONG",
        )
        painter.save()
        painter.translate(12, plot_rect.center().y())
        painter.rotate(-90)
        painter.drawText(
            QtCore.QRectF(-plot_rect.height() / 2, -20, plot_rect.height(), 20),
            QtCore.Qt.AlignCenter,
            "Speed (mph)",
        )
        painter.restore()

        painter.setPen(QtGui.QColor(120, 120, 120))
        painter.drawText(
            QtCore.QRectF(plot_rect.left(), 0, plot_rect.width(), margin_top),
            QtCore.Qt.AlignCenter,
            f"{x_min:.0f} → {x_max:.0f}",
        )
        painter.drawText(
            QtCore.QRectF(0, plot_rect.top(), margin_left - 6, plot_rect.height()),
            QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
            f"{y_max:.0f}\n⋮\n{y_min:.0f}",
        )
        painter.end()

    def _reset_ranges(self) -> None:
        if not self._records:
            self._x_center = None
            self._y_center = None
            self._x_range = None
            self._y_range = None
            self._x_min = None
            self._x_max = None
            self._y_min = None
            self._y_max = None
            return
        x_values = [record.dlong for record in self._records]
        y_values = [record.speed_mph for record in self._records]
        self._x_min = min(x_values)
        self._x_max = max(x_values)
        self._y_min = min(y_values)
        self._y_max = max(y_values)
        self._x_center = (self._x_min + self._x_max) / 2
        self._y_center = (self._y_min + self._y_max) / 2
        self._x_range = max(1.0, self._x_max - self._x_min)
        self._y_range = max(1.0, self._y_max - self._y_min)

    @classmethod
    def _clamp_zoom(cls, value: float) -> float:
        return min(max(value, cls._ZOOM_MIN), cls._ZOOM_MAX)

    @staticmethod
    def _zoomed_bounds(
        center: float | None,
        base_range: float | None,
        zoom: float,
        min_value: float | None,
        max_value: float | None,
    ) -> tuple[float | None, float | None]:
        if center is None or base_range is None:
            return None, None
        if min_value is None or max_value is None:
            half_range = (base_range / zoom) / 2
            return center - half_range, center + half_range
        data_range = max_value - min_value
        if data_range <= 0:
            return min_value, max_value
        half_range = (base_range / zoom) / 2
        if half_range * 2 >= data_range:
            return min_value, max_value
        desired_min = center - half_range
        desired_max = center + half_range
        if desired_min < min_value:
            shift = min_value - desired_min
            desired_min += shift
            desired_max += shift
        if desired_max > max_value:
            shift = desired_max - max_value
            desired_min -= shift
            desired_max -= shift
        return desired_min, desired_max

    @staticmethod
    def _map_value(
        value: float,
        src_min: float,
        src_max: float,
        dst_min: float,
        dst_max: float,
    ) -> float:
        if src_max == src_min:
            return (dst_min + dst_max) / 2
        ratio = (value - src_min) / (src_max - src_min)
        return dst_min + ratio * (dst_max - dst_min)

    def _center_on_selected_record(self) -> None:
        if (
            self._selected_index is None
            or self._selected_index < 0
            or self._selected_index >= len(self._records)
        ):
            return
        record = self._records[self._selected_index]
        self._x_center = record.dlong
        self._y_center = record.speed_mph
