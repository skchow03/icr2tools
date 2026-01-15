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
        self.setMinimumHeight(160)
        self.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )

    def set_records(self, records: Iterable[LpPoint]) -> None:
        self._records = sorted(records, key=lambda record: record.dlong)
        self._reset_ranges()
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

        x_min, x_max = self._zoomed_bounds(self._x_center, self._x_range, self._x_zoom)
        y_min, y_max = self._zoomed_bounds(self._y_center, self._y_range, self._y_zoom)
        if x_min is None or x_max is None or y_min is None or y_max is None:
            painter.end()
            return
        if x_max <= x_min or y_max <= y_min:
            painter.end()
            return

        path = QtGui.QPainterPath()
        for index, record in enumerate(self._records):
            x = self._map_value(record.dlong, x_min, x_max, plot_rect.left(), plot_rect.right())
            y = self._map_value(record.speed_mph, y_min, y_max, plot_rect.bottom(), plot_rect.top())
            if index == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)

        painter.setPen(QtGui.QPen(QtGui.QColor(52, 152, 219), 2))
        painter.drawPath(path)

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
            return
        x_values = [record.dlong for record in self._records]
        y_values = [record.speed_mph for record in self._records]
        x_min = min(x_values)
        x_max = max(x_values)
        y_min = min(y_values)
        y_max = max(y_values)
        self._x_center = (x_min + x_max) / 2
        self._y_center = (y_min + y_max) / 2
        self._x_range = max(1.0, x_max - x_min)
        self._y_range = max(1.0, y_max - y_min)

    @classmethod
    def _clamp_zoom(cls, value: float) -> float:
        return min(max(value, cls._ZOOM_MIN), cls._ZOOM_MAX)

    @staticmethod
    def _zoomed_bounds(
        center: float | None, base_range: float | None, zoom: float
    ) -> tuple[float | None, float | None]:
        if center is None or base_range is None:
            return None, None
        half_range = (base_range / zoom) / 2
        return center - half_range, center + half_range

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
