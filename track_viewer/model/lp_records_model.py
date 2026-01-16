"""Table model for LP record editing."""
from __future__ import annotations

from typing import Callable

from PyQt5 import QtCore

from track_viewer.ai.ai_line_service import LpPoint
from track_viewer.model.lp_editing_session import LPChange, LPEditingSession


class LpRecordsModel(QtCore.QAbstractTableModel):
    """Table model that lazily renders LP records for the view."""

    _HEADERS = [
        "Index",
        "DLONG",
        "DLAT",
        "Speed (mph)",
        "Lateral Speed",
    ]
    recordEdited = QtCore.pyqtSignal(int)

    def __init__(
        self,
        session: LPEditingSession,
        on_changes: Callable[[set[LPChange]], None] | None = None,
        parent: QtCore.QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._on_changes = on_changes or (lambda _changes: None)
        self._records: list[LpPoint] = []
        self._show_speed_raw = False
        self._lp_name: str | None = None

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._records)

    def columnCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._HEADERS)

    def data(
        self, index: QtCore.QModelIndex, role: int = QtCore.Qt.DisplayRole
    ) -> object | None:
        if not index.isValid():
            return None
        if role == QtCore.Qt.TextAlignmentRole:
            return QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
        if role not in {QtCore.Qt.DisplayRole, QtCore.Qt.EditRole}:
            return None
        row = index.row()
        if row < 0 or row >= len(self._records):
            return None
        record = self._records[row]
        column = index.column()
        if column == 0:
            return str(row)
        if column == 1:
            return (
                f"{record.dlong:.0f}" if role == QtCore.Qt.DisplayRole else record.dlong
            )
        if column == 2:
            return (
                f"{record.dlat:.0f}" if role == QtCore.Qt.DisplayRole else record.dlat
            )
        if column == 3:
            if self._show_speed_raw:
                return (
                    str(record.speed_raw)
                    if role == QtCore.Qt.DisplayRole
                    else record.speed_raw
                )
            return (
                f"{record.speed_mph:.2f}"
                if role == QtCore.Qt.DisplayRole
                else record.speed_mph
            )
        if column == 4:
            return (
                f"{record.lateral_speed:.2f}"
                if role == QtCore.Qt.DisplayRole
                else record.lateral_speed
            )
        return None

    def flags(self, index: QtCore.QModelIndex) -> QtCore.Qt.ItemFlags:
        if not index.isValid():
            return QtCore.Qt.NoItemFlags
        base_flags = QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
        if index.column() in {2, 3, 4}:
            return base_flags | QtCore.Qt.ItemIsEditable
        return base_flags

    def setData(
        self, index: QtCore.QModelIndex, value: object, role: int = QtCore.Qt.EditRole
    ) -> bool:
        if role != QtCore.Qt.EditRole or not index.isValid():
            return False
        row = index.row()
        if row < 0 or row >= len(self._records):
            return False
        column = index.column()
        if column not in {2, 3, 4}:
            return False
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return False
        if column == 2:
            if self._lp_name is None:
                return False
            changed = self._session.update_record_dlat(
                self._lp_name, row, parsed
            )
        elif column == 3:
            if self._lp_name is None:
                return False
            changed = self._session.update_record_speed(
                self._lp_name, row, parsed, raw_mode=self._show_speed_raw
            )
        elif column == 4:
            if self._lp_name is None:
                return False
            changed = self._session.update_record_lateral_speed(
                self._lp_name, row, parsed
            )
        else:
            return False
        if not changed:
            return False
        self._on_changes(changed)
        self.refresh_row(row)
        self.dataChanged.emit(index, index, [QtCore.Qt.DisplayRole, QtCore.Qt.EditRole])
        self.recordEdited.emit(row)
        return True

    def headerData(
        self,
        section: int,
        orientation: QtCore.Qt.Orientation,
        role: int = QtCore.Qt.DisplayRole,
    ) -> object | None:
        if role != QtCore.Qt.DisplayRole:
            return None
        if orientation == QtCore.Qt.Horizontal:
            if 0 <= section < len(self._HEADERS):
                if section == 3:
                    return (
                        "Speed (500ths/frame)"
                        if self._show_speed_raw
                        else "Speed (mph)"
                    )
                return self._HEADERS[section]
            return None
        return str(section)

    def set_records(self, records: list[LpPoint], lp_name: str | None = None) -> None:
        self.beginResetModel()
        self._records = list(records)
        self._lp_name = lp_name
        self.endResetModel()

    def set_speed_raw_visible(self, enabled: bool) -> None:
        if self._show_speed_raw == enabled:
            return
        self._show_speed_raw = enabled
        self.headerDataChanged.emit(QtCore.Qt.Horizontal, 3, 3)
        if self._records:
            start = self.index(0, 3)
            end = self.index(len(self._records) - 1, 3)
            self.dataChanged.emit(start, end, [QtCore.Qt.DisplayRole, QtCore.Qt.EditRole])

    def adjust_speed_mph(self, row: int, delta: float) -> bool:
        if self._lp_name is None:
            return False
        if row < 0 or row >= len(self._records):
            return False
        record = self._records[row]
        target_speed = record.speed_mph + delta
        changes = self._session.update_record_speed(
            self._lp_name, row, target_speed, raw_mode=False
        )
        if not changes:
            return False
        self._on_changes(changes)
        self.refresh_row(row)
        index = self.index(row, 3)
        if index.isValid():
            self.dataChanged.emit(
                index, index, [QtCore.Qt.DisplayRole, QtCore.Qt.EditRole]
            )
        self.recordEdited.emit(row)
        return True

    def recalculate_lateral_speeds(self) -> bool:
        if self._lp_name is None:
            return False
        changes = self._session.recalculate_lateral_speeds(self._lp_name)
        if not changes:
            return False
        self._on_changes(changes)
        self._records = self._session.records(self._lp_name)
        total_records = len(self._records)
        start = self.index(0, 4)
        end = self.index(total_records - 1, 4)
        self.dataChanged.emit(start, end, [QtCore.Qt.DisplayRole, QtCore.Qt.EditRole])
        return True

    def refresh_row(self, row: int) -> None:
        if self._lp_name is None:
            return
        snapshot = self._session.record_snapshot(self._lp_name, row)
        if snapshot is None:
            return
        self._records[row] = snapshot
