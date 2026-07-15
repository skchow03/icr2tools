from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PyQt5 import QtCore, QtWidgets


@dataclass(frozen=True)
class XsectEntry:
    key: int | None
    dlat: float
    altitude: int | None = None
    grade: int | None = None


def _parse_float(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


class XsectTableWindow(QtWidgets.QDialog):
    """Displays editable X-section DLAT, elevation, and grade values."""

    xsectsEdited = QtCore.pyqtSignal(list)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("X-Section Data")
        self.resize(640, 420)

        self._entries: list[XsectEntry] = []
        self._is_updating = False
        self._pending_edit = False
        self._next_new_key = -1
        self._unit_label = "500ths"
        self._decimals = 0
        self._altitude_unit_label = "500ths"
        self._altitude_decimals = 0
        self._to_display_units: Callable[[float], float] = lambda value: float(value)
        self._from_display_units: Callable[[float], float] = lambda value: float(value)
        self._altitude_to_display_units: Callable[[float], float] = lambda value: float(
            value
        )
        self._altitude_from_display_units: Callable[[float], float] = (
            lambda value: float(value)
        )

        self._apply_timer = QtCore.QTimer(self)
        self._apply_timer.setInterval(250)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.timeout.connect(self._apply_pending_edits)

        layout = QtWidgets.QVBoxLayout()
        self._section_label = QtWidgets.QLabel("Section: none selected")
        self._section_label.setObjectName("xsectTableSectionLabel")
        font = self._section_label.font()
        font.setBold(True)
        self._section_label.setFont(font)
        layout.addWidget(self._section_label)

        self._table = QtWidgets.QTableWidget()
        self._table.setColumnCount(4)
        self._table.setRowCount(10)
        self._table.setHorizontalHeaderLabels(
            ["Xsect", "DLAT (500ths)", "Elevation (500ths)", "Grade"]
        )
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.AllEditTriggers)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch
        )
        self._table.itemChanged.connect(self._handle_item_changed)
        self._table.itemDelegate().closeEditor.connect(self._apply_after_editor_close)

        layout.addWidget(self._table)
        self.setLayout(layout)

    def set_display_unit(
        self,
        *,
        unit_label: str,
        decimals: int,
        to_display_units: Callable[[float], float],
        from_display_units: Callable[[float], float],
        altitude_unit_label: str | None = None,
        altitude_decimals: int | None = None,
        altitude_to_display_units: Callable[[float], float] | None = None,
        altitude_from_display_units: Callable[[float], float] | None = None,
    ) -> None:
        self._unit_label = unit_label
        self._decimals = max(0, int(decimals))
        self._to_display_units = to_display_units
        self._from_display_units = from_display_units
        if altitude_unit_label is not None:
            self._altitude_unit_label = altitude_unit_label
        if altitude_decimals is not None:
            self._altitude_decimals = max(0, int(altitude_decimals))
        if altitude_to_display_units is not None:
            self._altitude_to_display_units = altitude_to_display_units
        if altitude_from_display_units is not None:
            self._altitude_from_display_units = altitude_from_display_units
        self._table.setHorizontalHeaderLabels(
            [
                "Xsect",
                f"DLAT ({self._unit_label})",
                f"Elevation ({self._altitude_unit_label})",
                "Grade",
            ]
        )

    def set_xsects(
        self,
        metadata: list[tuple[int, float]],
        altitudes: list[int | None] | None = None,
        grades: list[int | None] | None = None,
        section_index: int | None = None,
    ) -> None:
        self.set_section_header(section_index)
        altitudes = altitudes or []
        grades = grades or []
        self._entries = []
        for row, (idx, dlat) in enumerate(metadata):
            altitude = altitudes[row] if row < len(altitudes) else None
            grade = grades[row] if row < len(grades) else None
            self._entries.append(
                XsectEntry(
                    key=idx,
                    dlat=float(dlat),
                    altitude=altitude,
                    grade=grade,
                )
            )
        self._entries.sort(key=lambda entry: entry.dlat)
        self._next_new_key = -1
        self._is_updating = True
        self._pending_edit = False
        self._apply_timer.stop()
        try:
            self._populate_rows()
        finally:
            self._is_updating = False

    def set_section_header(self, section_index: int | None) -> None:
        if section_index is None:
            self._section_label.setText("Section: none selected")
        else:
            self._section_label.setText(f"Section: {section_index}")

    def on_xsects_edited(self, callback: Callable[[list[XsectEntry]], None]) -> None:
        self.xsectsEdited.connect(callback)

    def _handle_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._is_updating:
            return
        if item.column() not in (1, 2, 3):
            return
        self._pending_edit = True
        self._apply_timer.start()

    def _apply_after_editor_close(self, editor, hint):
        if self._is_updating:
            return
        if self._pending_edit:
            self._apply_pending_edits()

    def _apply_pending_edits(self) -> None:
        if self._is_updating:
            return
        if not self._pending_edit:
            return
        self._pending_edit = False
        updated = self._build_entries_from_table()
        if len(updated) < 2:
            QtWidgets.QMessageBox.warning(
                self,
                "X-Section Table",
                "At least two X-sections are required.",
            )
            self._is_updating = True
            try:
                self._populate_rows()
            finally:
                self._is_updating = False
            return

        self._entries = updated
        self._is_updating = True
        try:
            self._populate_rows()
        finally:
            self._is_updating = False
        self.xsectsEdited.emit(updated)

    def _build_entries_from_table(self) -> list[XsectEntry]:
        entries: list[XsectEntry] = []
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 1)
            if item is None:
                continue
            dlat = _parse_float(item.text())
            if dlat is None:
                continue
            dlat = self._from_display_units(dlat)
            key = item.data(QtCore.Qt.UserRole)
            if key is None:
                key = self._next_new_key
                self._next_new_key -= 1
            altitude = None
            altitude_item = self._table.item(row, 2)
            if altitude_item is not None:
                altitude_display = _parse_float(altitude_item.text())
                if altitude_display is not None:
                    altitude = int(
                        round(self._altitude_from_display_units(altitude_display))
                    )
            grade = None
            grade_item = self._table.item(row, 3)
            if grade_item is not None:
                grade_value = _parse_float(grade_item.text())
                if grade_value is not None:
                    grade = int(round(grade_value))
            entries.append(
                XsectEntry(key=key, dlat=dlat, altitude=altitude, grade=grade)
            )
        entries.sort(key=lambda entry: entry.dlat)
        return entries[:10]

    def _populate_rows(self) -> None:
        self._table.blockSignals(True)
        self._table.clearContents()
        for row in range(self._table.rowCount()):
            if row < len(self._entries):
                entry = self._entries[row]
                xsect_item = QtWidgets.QTableWidgetItem(str(row))
                xsect_item.setFlags(
                    QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled
                )
                dlat_item = QtWidgets.QTableWidgetItem(self._format_dlat(entry.dlat))
                dlat_item.setData(QtCore.Qt.UserRole, entry.key)
                dlat_item.setTextAlignment(
                    QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
                )
                altitude_text = (
                    self._format_altitude(entry.altitude)
                    if entry.altitude is not None
                    else ""
                )
                altitude_item = QtWidgets.QTableWidgetItem(altitude_text)
                altitude_item.setTextAlignment(
                    QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
                )
                grade_item = QtWidgets.QTableWidgetItem(
                    "" if entry.grade is None else str(entry.grade)
                )
                grade_item.setTextAlignment(
                    QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
                )
            else:
                xsect_item = QtWidgets.QTableWidgetItem("–")
                xsect_item.setFlags(
                    QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled
                )
                dlat_item = QtWidgets.QTableWidgetItem("")
                altitude_item = QtWidgets.QTableWidgetItem("")
                grade_item = QtWidgets.QTableWidgetItem("")
            self._table.setItem(row, 0, xsect_item)
            self._table.setItem(row, 1, dlat_item)
            self._table.setItem(row, 2, altitude_item)
            self._table.setItem(row, 3, grade_item)
        self._table.blockSignals(False)

    def _format_dlat(self, value: float) -> str:
        display_value = self._to_display_units(value)
        if self._decimals == 0:
            return f"{int(round(display_value))}"
        return f"{display_value:.{self._decimals}f}".rstrip("0").rstrip(".")

    def _format_altitude(self, value: int) -> str:
        display_value = self._altitude_to_display_units(value)
        if self._altitude_decimals == 0:
            return f"{int(round(display_value))}"
        return f"{display_value:.{self._altitude_decimals}f}".rstrip("0").rstrip(".")
