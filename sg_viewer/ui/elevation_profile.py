from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

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

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(180)
        self._data: ElevationProfileData | None = None
        self._selected_range: tuple[float, float] | None = None

    def set_profile_data(self, data: ElevationProfileData | None) -> None:
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

        max_dlong = max(max(self._data.dlongs), self._data.track_length)
        if max_dlong <= 0:
            painter.end()
            return

        painter.save()
        painter.setPen(QtGui.QPen(QtGui.QColor("#bbb")))
        painter.drawRect(plot_rect)

        self._draw_section_highlight(painter, plot_rect, max_dlong)
        self._draw_series(painter, plot_rect, max_dlong, min_alt, max_alt)
        self._draw_axes_labels(painter, plot_rect, min_alt, max_alt)
        self._draw_legend(painter, plot_rect)
        painter.restore()
        painter.end()

    def _draw_section_highlight(
        self, painter: QtGui.QPainter, rect: QtCore.QRect, max_dlong: float
    ) -> None:
        if self._selected_range is None:
            return

        start, end = self._selected_range
        span = max(end - start, 0.0)
        if span <= 0:
            return

        start_x = self._map_x(start, rect, max_dlong)
        end_x = self._map_x(end, rect, max_dlong)
        highlight_rect = QtCore.QRectF(start_x, rect.top(), end_x - start_x, rect.height())

        color = QtGui.QColor("#3f51b5")
        color.setAlpha(32)
        painter.fillRect(highlight_rect, QtGui.QBrush(color))

    def _draw_series(
        self,
        painter: QtGui.QPainter,
        rect: QtCore.QRect,
        max_dlong: float,
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
            x = self._map_x(dlong, rect, max_dlong)
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

    def _map_x(self, dlong: float, rect: QtCore.QRect, max_dlong: float) -> float:
        return rect.left() + (dlong / max_dlong) * rect.width()

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
