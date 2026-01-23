from __future__ import annotations

from dataclasses import dataclass

from PyQt5 import QtCore, QtGui, QtWidgets


@dataclass
class XsectElevationData:
    section_index: int
    altitudes: list[float | None]
    xsect_dlats: list[float] | None = None
    selected_xsect_index: int | None = None
    y_range: tuple[float, float] | None = None


class XsectElevationWidget(QtWidgets.QWidget):
    """Renders elevation values across x-sections for the selected section."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(140)
        self._data: XsectElevationData | None = None

    def set_xsect_data(self, data: XsectElevationData | None) -> None:
        self._data = data
        self.update()

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

        margins = QtCore.QMargins(48, 18, 16, 28)
        plot_rect = self.rect().marginsRemoved(margins)
        if plot_rect.width() <= 0 or plot_rect.height() <= 0:
            painter.end()
            return

        if self._data.y_range is not None:
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

        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor("#bbb")))
        painter.drawRect(plot_rect)

        self._draw_profile(painter, plot_rect, altitudes, min_alt, max_alt)
        self._draw_axes_labels(painter, plot_rect, min_alt, max_alt)
        painter.restore()
        painter.end()

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

        painter.drawText(
            rect.adjusted(-36, 0, 0, 0),
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop,
            f"Section {self._data.section_index}",
        )
        painter.drawText(
            rect.adjusted(0, 0, 0, 18),
            QtCore.Qt.AlignHCenter | QtCore.Qt.AlignBottom,
            "DLAT (min → right)",
        )
        painter.drawText(
            rect.adjusted(0, -18, 0, 0),
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop,
            f"Alt: {min_alt:.0f}–{max_alt:.0f}",
        )
        painter.restore()

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
