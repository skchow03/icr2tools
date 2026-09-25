"""Editor for the baseline vehicle-performance envelope used by LP generation."""

from __future__ import annotations

import json
from pathlib import Path

from PyQt5 import QtWidgets

from track_viewer.ai.indycar_speed_model import (
    DEFAULT_MODEL_PATH,
    load_performance_model,
    reload_performance_model,
)


class CarPerformanceDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, path: Path | None = None):
        super().__init__(parent)
        self.path = path or DEFAULT_MODEL_PATH
        self.setWindowTitle("Car Performance Model")
        self.resize(720, 620)

        layout = QtWidgets.QVBoxLayout(self)
        note = QtWidgets.QLabel(
            "These are the baseline values used by Pathfinder, Minimum Time, "
            "Corner & Apex, and manual LP speed generation. Speeds are mph and "
            "performance values are g. The percentage controls in the generation "
            "dialogs are applied on top of these values. The default model "
            "supports speeds up to 245 mph; high-speed values are estimates."
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        max_row = QtWidgets.QHBoxLayout()
        max_row.addWidget(QtWidgets.QLabel("Model maximum speed"))
        self.max_speed = QtWidgets.QDoubleSpinBox()
        self.max_speed.setRange(1.0, 400.0)
        self.max_speed.setDecimals(1)
        self.max_speed.setSuffix(" mph")
        max_row.addWidget(self.max_speed)
        max_row.addStretch(1)
        layout.addLayout(max_row)

        self.tabs = QtWidgets.QTabWidget()
        self.tables = {}
        for key, title in (
            ("lateral_g", "Cornering / lateral G"),
            ("acceleration_g", "Acceleration G"),
            ("braking_g", "Braking G"),
        ):
            page = QtWidgets.QWidget()
            page_layout = QtWidgets.QVBoxLayout(page)
            table = QtWidgets.QTableWidget(0, 2)
            table.setHorizontalHeaderLabels(["Speed (mph)", "G"])
            table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
            page_layout.addWidget(table)
            row = QtWidgets.QHBoxLayout()
            add = QtWidgets.QPushButton("Add Row")
            remove = QtWidgets.QPushButton("Remove Selected")
            add.clicked.connect(lambda _=False, t=table: self._add_row(t))
            remove.clicked.connect(lambda _=False, t=table: self._remove_rows(t))
            row.addWidget(add)
            row.addWidget(remove)
            row.addStretch(1)
            page_layout.addLayout(row)
            self.tables[key] = table
            self.tabs.addTab(page, title)
        layout.addWidget(self.tabs, 1)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel
        )
        reset = buttons.addButton("Reload from File", QtWidgets.QDialogButtonBox.ResetRole)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        reset.clicked.connect(self._load)
        layout.addWidget(buttons)
        self._load()

    def _add_row(self, table):
        row = table.rowCount()
        table.insertRow(row)
        table.setItem(row, 0, QtWidgets.QTableWidgetItem("0"))
        table.setItem(row, 1, QtWidgets.QTableWidgetItem("0"))

    def _remove_rows(self, table):
        for row in sorted({i.row() for i in table.selectedIndexes()}, reverse=True):
            table.removeRow(row)

    def _load(self):
        try:
            data = load_performance_model(self.path)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Car Performance Model", str(exc))
            return
        self.max_speed.setValue(data["max_speed_mph"])
        for key, table in self.tables.items():
            values = data[key]
            table.setRowCount(len(values))
            for row, (mph, g_value) in enumerate(values):
                table.setItem(row, 0, QtWidgets.QTableWidgetItem(f"{mph:g}"))
                table.setItem(row, 1, QtWidgets.QTableWidgetItem(f"{g_value:g}"))

    def _save(self):
        try:
            data = {
                "description": (
                    "Editable baseline used by Track Viewer candidate LP speed generation. "
                    "Speeds are mph; acceleration/braking/lateral values are g."
                ),
                "max_speed_mph": self.max_speed.value(),
            }
            for key, table in self.tables.items():
                rows = []
                for row in range(table.rowCount()):
                    mph_item = table.item(row, 0)
                    g_item = table.item(row, 1)
                    if mph_item is None or g_item is None:
                        raise ValueError(f"{key}: every row needs Speed and G.")
                    rows.append([float(mph_item.text()), float(g_item.text())])
                data[key] = rows
            # Validate using a temporary sibling file before replacing the live model.
            temp = self.path.with_suffix(".json.tmp")
            temp.parent.mkdir(parents=True, exist_ok=True)
            temp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            try:
                load_performance_model(temp)
                self.path.write_text(temp.read_text(encoding="utf-8"), encoding="utf-8")
            finally:
                if temp.exists():
                    temp.unlink()
            reload_performance_model(self.path)
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Car Performance Model", str(exc))
            return
        self.accept()
