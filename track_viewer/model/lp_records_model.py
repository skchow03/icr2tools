"""Table model for LP record editing."""
from __future__ import annotations

from PyQt5 import QtCore

from icr2_core.lp.loader import papy_speed_to_mph
from track_viewer.ai.ai_line_service import LpPoint


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
    _LATERAL_SPEED_FACTOR = 31680000 / 54000
    _SPEED_RAW_FACTOR = 5280 / 9

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._records: list[LpPoint] = []
        self._show_speed_raw = False

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
        record = self._records[row]
        if column == 2:
            record.dlat = parsed
        elif column == 3:
            if self._show_speed_raw:
                speed_raw = int(round(parsed))
                record.speed_raw = speed_raw
                record.speed_mph = papy_speed_to_mph(speed_raw)
            else:
                record.speed_mph = parsed
                record.speed_raw = int(round(parsed * self._SPEED_RAW_FACTOR))
        elif column == 4:
            record.lateral_speed = parsed
        else:
            return False
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

    def set_records(self, records: list[LpPoint]) -> None:
        self.beginResetModel()
        self._records = list(records)
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
        if row < 0 or row >= len(self._records):
            return False
        record = self._records[row]
        record.speed_mph = record.speed_mph + delta
        record.speed_raw = int(round(record.speed_mph * self._SPEED_RAW_FACTOR))
        index = self.index(row, 3)
        if index.isValid():
            self.dataChanged.emit(
                index, index, [QtCore.Qt.DisplayRole, QtCore.Qt.EditRole]
            )
        self.recordEdited.emit(row)
        return True

    def recalculate_lateral_speeds(self) -> bool:
        if len(self._records) < 3:
            return False
        total_records = len(self._records)
        recalculated = [0.0] * total_records
        for index in range(total_records):
            prev_record = self._records[(index - 1) % total_records]
            next_record = self._records[(index + 1) % total_records]
            record = self._records[index]
            dlong_delta = next_record.dlong - prev_record.dlong
            if dlong_delta == 0:
                lateral_speed = 0.0
            else:
                lateral_speed = (
                    (next_record.dlat - prev_record.dlat)
                    / dlong_delta
                    * (record.speed_mph * self._LATERAL_SPEED_FACTOR)
                )
            recalculated[(index - 2) % total_records] = lateral_speed
        for index, lateral_speed in enumerate(recalculated):
            self._records[index].lateral_speed = lateral_speed
        start = self.index(0, 4)
        end = self.index(total_records - 1, 4)
        self.dataChanged.emit(start, end, [QtCore.Qt.DisplayRole, QtCore.Qt.EditRole])
        return True
