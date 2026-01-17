from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import color_from_ground_type
from sg_viewer.models.selection import SectionSelection
from sg_viewer.services import sg_rendering


class SectionSurfaceWidget(QtWidgets.QWidget):
    """Render surface feature lines for the selected section."""

    _DEFAULT_HALF_WIDTH = 25_000.0  # ~50 ft in both directions (500ths)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(160)
        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor("black"))
        self.setPalette(palette)

        self._trk: TRKFile | None = None
        self._selection: SectionSelection | None = None
        self._status_message = "Select a section to view surface features."

    def set_section_data(
        self, trk: TRKFile | None, selection: SectionSelection | None
    ) -> None:
        self._trk = trk
        self._selection = selection

        if trk is None:
            self._status_message = "Load an SG file to view section features."
        elif selection is None:
            self._status_message = "Select a section to view surface features."
        else:
            self._status_message = ""

        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        rect = event.rect()
        painter.fillRect(rect, self.palette().window())

        if self._trk is None or self._selection is None:
            sg_rendering.draw_placeholder(painter, rect, self._status_message)
            return

        section_index = self._selection.index
        if section_index < 0 or section_index >= len(self._trk.sects):
            sg_rendering.draw_placeholder(painter, rect, "Section data unavailable.")
            return

        sect = self._trk.sects[section_index]
        if sect.ground_fsects <= 0:
            sg_rendering.draw_placeholder(painter, rect, "No surface features in this section.")
            return

        start_dlong = float(self._selection.start_dlong)
        end_dlong = float(self._selection.end_dlong)
        if end_dlong <= start_dlong:
            sg_rendering.draw_placeholder(painter, rect, "Invalid section length.")
            return

        content = rect.adjusted(18, 18, -18, -18)
        if content.width() <= 0 or content.height() <= 0:
            return

        dlat_min = -self._DEFAULT_HALF_WIDTH
        dlat_max = self._DEFAULT_HALF_WIDTH
        dlat_span = dlat_max - dlat_min
        dlong_span = end_dlong - start_dlong

        def _map(dlat: float, dlong: float) -> QtCore.QPointF:
            x = content.left() + (dlat - dlat_min) / dlat_span * content.width()
            y = content.bottom() - (dlong - start_dlong) / dlong_span * content.height()
            return QtCore.QPointF(x, y)

        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        center_x = _map(0.0, start_dlong).x()
        painter.setPen(QtGui.QPen(QtGui.QColor(90, 90, 90), 1, QtCore.Qt.DotLine))
        painter.drawLine(
            QtCore.QPointF(center_x, content.top()),
            QtCore.QPointF(center_x, content.bottom()),
        )

        painter.setPen(QtGui.QPen(QtGui.QColor(140, 140, 140), 1))
        painter.drawRect(content)

        for ground_idx in range(sect.ground_fsects):
            dlat_start = float(sect.ground_dlat_start[ground_idx])
            dlat_end = float(sect.ground_dlat_end[ground_idx])
            color = QtGui.QColor(color_from_ground_type(sect.ground_type[ground_idx]))

            painter.setPen(QtGui.QPen(color, 2))
            painter.drawLine(
                _map(dlat_start, start_dlong),
                _map(dlat_end, end_dlong),
            )

        painter.restore()
