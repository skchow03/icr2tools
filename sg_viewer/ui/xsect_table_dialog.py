from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PyQt5 import QtCore, QtWidgets


@dataclass(frozen=True)
class XsectEntry:
    key: int | None
    dlat: float


def _parse_float(value: str) -> float | None:
    value = value.strip()
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


class XsectTableWindow(QtWidgets.QDialog):
    """Displays an editable table of X-section DLAT values."""

    xsectsEdited = QtCore.pyqtSignal(list)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("X-Section Table")
        self.resize(420, 360)

        self._entries: list[XsectEntry] = []
        self._is_updating = False
        self._pending_edit = False
        self._next_new_key = -1

        self._apply_timer = QtCore.QTimer(self)
        self._apply_timer.setInterval(250)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.timeout.connect(self._apply_pending_edits)

        layout = QtWidgets.QVBoxLayout()
        self._table = QtWidgets.QTableWidget()
        self._table.setColumnCount(2)
        self._table.setRowCount(10)
        self._table.setHorizontalHeaderLabels(["Xsect", "DLAT"])
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

    def set_xsects(self, metadata: list[tuple[int, float]]) -> None:
        self._entries = [
            XsectEntry(key=idx, dlat=float(dlat)) for idx, dlat in metadata
        ]
        self._entries.sort(key=lambda entry: entry.dlat)
        self._next_new_key = -1
        self._is_updating = True
        self._pending_edit = False
        self._apply_timer.stop()
        try:
            self._populate_rows()
        finally:
            self._is_updating = False

    def on_xsects_edited(self, callback: Callable[[list[XsectEntry]], None]) -> None:
        self.xsectsEdited.connect(callback)

    def _handle_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._is_updating:
            return
        if item.column() != 1:
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
            key = item.data(QtCore.Qt.UserRole)
            if key is None:
                key = self._next_new_key
                self._next_new_key -= 1
            entries.append(XsectEntry(key=key, dlat=dlat))
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
            else:
                xsect_item = QtWidgets.QTableWidgetItem("–")
                xsect_item.setFlags(
                    QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled
                )
                dlat_item = QtWidgets.QTableWidgetItem("")
            self._table.setItem(row, 0, xsect_item)
            self._table.setItem(row, 1, dlat_item)
        self._table.blockSignals(False)

    @staticmethod
    def _format_dlat(value: float) -> str:
        if float(value).is_integer():
            return f"{int(value)}"
        return f"{value:.1f}"
