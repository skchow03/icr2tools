"""Review UI for geometry-derived pit-lane suggestions (no implicit saves)."""
from __future__ import annotations

import math

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.trk.trk_utils import get_cline_pos, getxyz
from track_viewer.model.pit_models import PIT_PARAMETER_DEFINITIONS, PitParameters
from track_viewer.pit.pit_lane_detector import (
    PitCandidate, PitDetection, PitSuggestion, recommend_pit_parameters,
)


class PitDetectionMap(QtWidgets.QWidget):
    """Show the whole track and highlight the currently selected corridor."""

    def __init__(self, trk, centerline, parent=None):
        super().__init__(parent)
        self._trk = trk
        self._cline = centerline
        self._candidate: PitCandidate | None = None
        self._track_points: list[tuple[float, float]] = []
        self.setMinimumHeight(230)
        for sec in trk.sects:
            n = max(2, min(16, math.ceil(sec.length / (80 * 6000))))
            for k in range(n):
                dlong = (sec.start_dlong + sec.length * k / n) % trk.trklength
                x, y, _ = getxyz(trk, dlong, 0.0, centerline)
                self._track_points.append((x, y))

    def show_candidate(self, candidate: PitCandidate | None) -> None:
        self._candidate = candidate
        self.update()

    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.fillRect(self.rect(), QtGui.QColor("#273e31"))
        candidate = self._candidate
        if not candidate or not self._track_points:
            painter.setPen(QtGui.QColor("white"))
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, "No candidate selected")
            painter.end()
            return

        points = []
        for item in candidate.samples:
            x, y, _ = getxyz(
                self._trk, item.dlong, item.pit.center, self._cline
            )
            points.append((x, y))
        all_points = self._track_points + points
        xmin = min(x for x, _ in all_points)
        xmax = max(x for x, _ in all_points)
        ymin = min(y for _, y in all_points)
        ymax = max(y for _, y in all_points)
        width = max(xmax - xmin, 1)
        height = max(ymax - ymin, 1)
        scale = min((self.width() - 24) / width, (self.height() - 24) / height)
        ox = (self.width() - width * scale) / 2
        oy = (self.height() - height * scale) / 2

        def mapped(p):
            return QtCore.QPointF(
                ox + (p[0] - xmin) * scale,
                self.height() - oy - (p[1] - ymin) * scale,
            )

        track = QtGui.QPainterPath(mapped(self._track_points[0]))
        for p in self._track_points[1:]:
            track.lineTo(mapped(p))
        track.closeSubpath()
        painter.setPen(QtGui.QPen(QtGui.QColor("#92979d"), 5))
        painter.drawPath(track)
        if points:
            highlight = QtGui.QPainterPath(mapped(points[0]))
            for p in points[1:]:
                highlight.lineTo(mapped(p))
            painter.setPen(QtGui.QPen(QtGui.QColor("#42e0fa"), 3))
            painter.drawPath(highlight)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor("#32da79"))
            painter.drawEllipse(mapped(points[0]), 5, 5)
            painter.setBrush(QtGui.QColor("#ff9d48"))
            painter.drawEllipse(mapped(points[-1]), 5, 5)
        painter.end()


class PitDetectionDialog(QtWidgets.QDialog):
    """Require explicit candidate review before updating the PIT editor."""

    def __init__(
        self,
        trk,
        detection: PitDetection,
        existing: PitParameters | None,
        lp_lines: dict[str, list[tuple[float, float]]],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Auto Detect Pit Lane — Review")
        self.setMinimumSize(580, 620)
        self._trk = trk
        self._detection = detection
        self._existing = existing
        self._lp_lines = lp_lines
        self.suggestion: PitSuggestion | None = None
        self.candidate: PitCandidate | None = None

        layout = QtWidgets.QVBoxLayout(self)
        self._map = PitDetectionMap(trk, get_cline_pos(trk), self)
        layout.addWidget(self._map)
        legend = QtWidgets.QLabel(
            "Cyan: detected corridor    Green: entrance    Orange: exit"
        )
        layout.addWidget(legend)

        summary = QtWidgets.QLabel(
            f"{len(detection.candidates)} candidate(s), "
            f"{detection.dead_ends} disconnected/dead-end branch(es) rejected, "
            f"{detection.too_short} short/distant branch(es) rejected."
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)

        form = QtWidgets.QFormLayout()
        self._side = QtWidgets.QComboBox()
        self._side.addItem("Automatic — show all candidates", None)
        self._side.addItem("Pit on right", "right")
        self._side.addItem("Pit on left", "left")
        self._side.currentIndexChanged.connect(self._populate_candidates)
        form.addRow("Pit side:", self._side)
        self._choices = QtWidgets.QComboBox()
        self._choices.currentIndexChanged.connect(self._refresh)
        form.addRow("Detected corridor:", self._choices)
        layout.addLayout(form)

        self._table = QtWidgets.QTableWidget(len(PIT_PARAMETER_DEFINITIONS), 3)
        self._table.setHorizontalHeaderLabels(("Parameter", "Existing", "Proposed"))
        self._table.verticalHeader().hide()
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.Stretch
        )
        for i in (1, 2):
            self._table.horizontalHeader().setSectionResizeMode(
                i, QtWidgets.QHeaderView.ResizeToContents
            )
        layout.addWidget(self._table, stretch=1)

        self._notes = QtWidgets.QLabel()
        self._notes.setWordWrap(True)
        self._notes.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        layout.addWidget(self._notes)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Apply to PIT editor")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self._apply = buttons.button(QtWidgets.QDialogButtonBox.Ok)
        layout.addWidget(buttons)
        self._populate_candidates()

    def _populate_candidates(self, _index: int = 0) -> None:
        side = self._side.currentData()
        with QtCore.QSignalBlocker(self._choices):
            self._choices.clear()
            for candidate in self._detection.candidates:
                if side is not None and candidate.side != side:
                    continue
                feet = candidate.length / 6000
                label = (
                    f"{candidate.side.title()} — {feet:.0f} ft "
                    f"({candidate.confidence} geometric evidence)"
                )
                self._choices.addItem(label, candidate)
        self._refresh()

    def _refresh(self, _index: int = 0) -> None:
        self.candidate = self._choices.currentData()
        self.suggestion = None
        self._map.show_candidate(self.candidate)
        self._apply.setEnabled(self.candidate is not None)
        self._table.clearContents()
        if self.candidate is None:
            self._notes.setText("No candidate on this side. Select another side.")
            return
        self.suggestion = recommend_pit_parameters(
            self.candidate, float(self._trk.trklength),
            self._existing, lp_lines=self._lp_lines,
        )
        original = self._existing or PitParameters.empty()
        for i, (field, label, _help, _int) in enumerate(PIT_PARAMETER_DEFINITIONS):
            new_value = getattr(self.suggestion.parameters, field)
            old_value = getattr(original, field)
            changed = field in self.suggestion.updated_fields
            values = (label, str(old_value), str(new_value) if changed else "Unchanged")
            for col, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                if changed and col == 2:
                    item.setForeground(QtGui.QBrush(QtGui.QColor("#23783e")))
                self._table.setItem(i, col, item)
        self._notes.setText(
            "Review the highlighted corridor before applying. "
            "Rejoining service roads can resemble pit lanes.\n\n"
            + "\n".join("• " + note for note in self.suggestion.notes)
        )
        self._table.resizeRowsToContents()

    def accept(self) -> None:
        if self.suggestion is None:
            return
        super().accept()


class PitLaneSelectionDialog(QtWidgets.QDialog):
    """Require the user to confirm a detected side/corridor for PIT.LP."""

    def __init__(self, trk, detection: PitDetection, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Confirm PIT.LP Pit Lane")
        self.setMinimumSize(560, 430)
        self.candidate: PitCandidate | None = None
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel(
            "Select and visually confirm which side contains the pit lane. "
            "Dead-end branches have been ignored.", self
        ))
        self._map = PitDetectionMap(trk, get_cline_pos(trk), self)
        layout.addWidget(self._map)
        form = QtWidgets.QFormLayout()
        self._choices = QtWidgets.QComboBox(self)
        self._choices.addItem("Select pit side…", None)
        for candidate in detection.candidates:
            self._choices.addItem(
                f"Pit on {candidate.side} — {candidate.length / 6000:.0f} ft",
                candidate,
            )
        self._choices.currentIndexChanged.connect(self._refresh)
        form.addRow("Confirmed pit lane:", self._choices)
        layout.addLayout(form)
        summary = QtWidgets.QLabel(
            f"{detection.dead_ends} disconnected/dead-end branch(es) ignored; "
            f"{detection.too_short} short/distant branch(es) ignored.", self
        )
        summary.setWordWrap(True)
        layout.addWidget(summary)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText("Use this pit lane")
        self._confirm = buttons.button(QtWidgets.QDialogButtonBox.Ok)
        self._confirm.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _refresh(self, _index=0):
        self.candidate = self._choices.currentData()
        self._map.show_candidate(self.candidate)
        self._confirm.setEnabled(self.candidate is not None)

    def accept(self):
        if self.candidate is not None:
            super().accept()
