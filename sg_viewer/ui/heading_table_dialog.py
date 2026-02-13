from __future__ import annotations

from PyQt5 import QtWidgets

from sg_viewer.model.selection import SectionHeadingData


class HeadingTableWindow(QtWidgets.QDialog):
    """Displays start/end headings and deltas between sections."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Heading Table")
        self.resize(780, 520)

        layout = QtWidgets.QVBoxLayout()
        self._table = QtWidgets.QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(
            [
                "Section",
                "Start X",
                "Start Y",
                "End X",
                "End Y",
                "Δ to Next (deg)",
            ]
        )
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch
        )

        layout.addWidget(self._table)
        self.setLayout(layout)

    def set_headings(self, headings: list[SectionHeadingData]) -> None:
        self._table.setRowCount(len(headings))

        def _fmt(value: float | None) -> str:
            return "–" if value is None else f"{value:.5f}"

        for row, entry in enumerate(headings):
            values = [
                str(entry.index),
                _fmt(entry.start_heading[0] if entry.start_heading else None),
                _fmt(entry.start_heading[1] if entry.start_heading else None),
                _fmt(entry.end_heading[0] if entry.end_heading else None),
                _fmt(entry.end_heading[1] if entry.end_heading else None),
                _fmt(entry.delta_to_next),
            ]
            for col, value in enumerate(values):
                self._table.setItem(row, col, QtWidgets.QTableWidgetItem(value))
