from __future__ import annotations

from dataclasses import dataclass

from PyQt5 import QtCore, QtWidgets


@dataclass(frozen=True)
class ManualWallHeightOverride:
    boundary: int
    start_dlong: int
    end_dlong: int
    height: int

    def normalized(self) -> "ManualWallHeightOverride":
        start = min(self.start_dlong, self.end_dlong)
        end = max(self.start_dlong, self.end_dlong)
        return ManualWallHeightOverride(self.boundary, start, end, self.height)


class ManualWallHeightOverridesDialog(QtWidgets.QDialog):
    """Editor for pitwall.txt manual wall-height overrides."""

    HEADERS = ("Boundary", "Start DLONG", "End DLONG", "Height")

    def __init__(
        self,
        overrides: list[ManualWallHeightOverride],
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manual Wall Height Overrides")
        self.resize(560, 360)

        self._table = QtWidgets.QTableWidget(0, len(self.HEADERS), self)
        self._table.setHorizontalHeaderLabels(self.HEADERS)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)

        add_button = QtWidgets.QPushButton("Add")
        delete_button = QtWidgets.QPushButton("Delete")
        add_button.clicked.connect(self._add_row)
        delete_button.clicked.connect(self._delete_selected_rows)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        controls = QtWidgets.QHBoxLayout()
        controls.addWidget(add_button)
        controls.addWidget(delete_button)
        controls.addStretch()

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(
            QtWidgets.QLabel(
                "Manual entries override generated pitwall.txt heights for matching boundary "
                "numbers and DLONG ranges."
            )
        )
        layout.addWidget(self._table)
        layout.addLayout(controls)
        layout.addWidget(buttons)
        self.setLayout(layout)

        for override in overrides:
            self._add_row(override)

    def overrides(self) -> list[ManualWallHeightOverride]:
        values: list[ManualWallHeightOverride] = []
        for row in range(self._table.rowCount()):
            try:
                boundary = int(self._table.item(row, 0).text())
                start = int(self._table.item(row, 1).text())
                end = int(self._table.item(row, 2).text())
                height = int(self._table.item(row, 3).text())
            except (AttributeError, TypeError, ValueError):
                continue
            if boundary < 0 or height < 0 or start == end:
                continue
            values.append(ManualWallHeightOverride(boundary, start, end, height).normalized())
        values.sort(key=lambda item: (item.boundary, item.start_dlong, item.end_dlong, item.height))
        return values

    def _add_row(self, override: ManualWallHeightOverride | None = None) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        values = override if isinstance(override, ManualWallHeightOverride) else ManualWallHeightOverride(0, 0, 1, 0)
        for column, value in enumerate(
            (values.boundary, values.start_dlong, values.end_dlong, values.height)
        ):
            item = QtWidgets.QTableWidgetItem(str(value))
            item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            self._table.setItem(row, column, item)

    def _delete_selected_rows(self) -> None:
        rows = sorted(
            {index.row() for index in self._table.selectionModel().selectedRows()},
            reverse=True,
        )
        for row in rows:
            self._table.removeRow(row)
