from __future__ import annotations

from dataclasses import dataclass

from PyQt5 import QtCore

from sg_viewer.services.tsd_io import TrackSurfaceDetailLine, normalize_tsd_command


@dataclass(frozen=True)
class TsdLineRow:
    command: str
    color_index: int
    width_500ths: int
    start_dlong: int
    start_dlat: int
    end_dlong: int
    end_dlat: int

    def to_track_surface_detail_line(self) -> TrackSurfaceDetailLine:
        return TrackSurfaceDetailLine(
            color_index=self.color_index,
            width_500ths=self.width_500ths,
            start_dlong=self.start_dlong,
            start_dlat=self.start_dlat,
            end_dlong=self.end_dlong,
            end_dlat=self.end_dlat,
            command=self.command,
        )


class TsdLinesTableModel(QtCore.QAbstractTableModel):
    COLUMN_LABELS = (
        "Command",
        "Color Index",
        "Width (500ths)",
        "Start DLONG",
        "Start DLAT",
        "End DLONG",
        "End DLAT",
    )

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._rows: list[TsdLineRow] = []

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self.COLUMN_LABELS)

    def headerData(
        self,
        section: int,
        orientation: QtCore.Qt.Orientation,
        role: int = QtCore.Qt.DisplayRole,
    ) -> str | None:
        if role != QtCore.Qt.DisplayRole:
            return None
        if orientation == QtCore.Qt.Horizontal and 0 <= section < len(self.COLUMN_LABELS):
            return self.COLUMN_LABELS[section]
        return str(section + 1)

    def data(self, index: QtCore.QModelIndex, role: int = QtCore.Qt.DisplayRole) -> str | int | None:
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None

        row = self._rows[index.row()]
        column_values: tuple[str | int, ...] = (
            row.command,
            row.color_index,
            row.width_500ths,
            row.start_dlong,
            row.start_dlat,
            row.end_dlong,
            row.end_dlat,
        )

        if role in (QtCore.Qt.DisplayRole, QtCore.Qt.EditRole):
            return str(column_values[index.column()])
        if role == QtCore.Qt.TextAlignmentRole:
            return int(QtCore.Qt.AlignCenter)
        return None

    def flags(self, index: QtCore.QModelIndex) -> QtCore.Qt.ItemFlags:
        if not index.isValid():
            return QtCore.Qt.ItemIsEnabled
        return (
            QtCore.Qt.ItemIsEnabled
            | QtCore.Qt.ItemIsSelectable
            | QtCore.Qt.ItemIsEditable
        )

    def setData(
        self,
        index: QtCore.QModelIndex,
        value: object,
        role: int = QtCore.Qt.EditRole,
    ) -> bool:
        if role != QtCore.Qt.EditRole or not index.isValid():
            return False
        if not (0 <= index.row() < len(self._rows)):
            return False

        parsed_value = self._parse_value(index.column(), value)
        if parsed_value is None:
            return False

        existing = self._rows[index.row()]
        updated = TsdLineRow(
            command=existing.command,
            color_index=existing.color_index,
            width_500ths=existing.width_500ths,
            start_dlong=existing.start_dlong,
            start_dlat=existing.start_dlat,
            end_dlong=existing.end_dlong,
            end_dlat=existing.end_dlat,
        )
        values = [
            updated.command,
            updated.color_index,
            updated.width_500ths,
            updated.start_dlong,
            updated.start_dlat,
            updated.end_dlong,
            updated.end_dlat,
        ]
        values[index.column()] = parsed_value
        try:
            candidate = TsdLineRow(
                command=str(values[0]),
                color_index=int(values[1]),
                width_500ths=int(values[2]),
                start_dlong=int(values[3]),
                start_dlat=int(values[4]),
                end_dlong=int(values[5]),
                end_dlat=int(values[6]),
            )
        except (TypeError, ValueError):
            return False

        if candidate.width_500ths <= 0:
            return False

        self._rows[index.row()] = candidate
        self.dataChanged.emit(index, index, [QtCore.Qt.DisplayRole, QtCore.Qt.EditRole])
        return True

    def _parse_value(self, column: int, value: object) -> str | int | None:
        text = "" if value is None else str(value).strip()
        if column == 0:
            try:
                return normalize_tsd_command(text or "Detail")
            except ValueError:
                return None
        try:
            return int(text)
        except ValueError:
            return None

    def add_default_row(self) -> int:
        return self.add_row(
            TsdLineRow(
                command="Detail",
                color_index=36,
                width_500ths=4000,
                start_dlong=0,
                start_dlat=0,
                end_dlong=0,
                end_dlat=0,
            )
        )

    def add_row(self, row: TsdLineRow) -> int:
        row_index = len(self._rows)
        self.beginInsertRows(QtCore.QModelIndex(), row_index, row_index)
        self._rows.append(row)
        self.endInsertRows()
        return row_index

    def remove_row(self, row_index: int) -> bool:
        if not (0 <= row_index < len(self._rows)):
            return False
        self.beginRemoveRows(QtCore.QModelIndex(), row_index, row_index)
        self._rows.pop(row_index)
        self.endRemoveRows()
        return True

    def replace_lines(self, lines: tuple[TrackSurfaceDetailLine, ...]) -> None:
        self.beginResetModel()
        self._rows = [
            TsdLineRow(
                command=line.command,
                color_index=line.color_index,
                width_500ths=line.width_500ths,
                start_dlong=line.start_dlong,
                start_dlat=line.start_dlat,
                end_dlong=line.end_dlong,
                end_dlat=line.end_dlat,
            )
            for line in lines
        ]
        self.endResetModel()

    def line_at(self, row: int) -> TrackSurfaceDetailLine | None:
        if not (0 <= row < len(self._rows)):
            return None
        return self._rows[row].to_track_surface_detail_line()

    def lines_for_rows(self, rows: list[int] | range | None = None) -> list[TrackSurfaceDetailLine]:
        if rows is None:
            selected_rows = range(len(self._rows))
        else:
            selected_rows = rows
        lines: list[TrackSurfaceDetailLine] = []
        for row in selected_rows:
            line = self.line_at(int(row))
            if line is not None:
                lines.append(line)
        return lines

    def all_lines(self) -> tuple[TrackSurfaceDetailLine, ...]:
        return tuple(row.to_track_surface_detail_line() for row in self._rows)
