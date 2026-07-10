from __future__ import annotations

from dataclasses import dataclass

from PyQt5 import QtCore, QtGui

from sg_viewer.services.tsd_io import TrackSurfaceDetailLine, normalize_tsd_command
from sg_viewer.ui.altitude_units import units_from_500ths, units_to_500ths
from sg_viewer.ui.presentation.units_presenter import (
    measurement_unit_decimals,
    measurement_unit_label,
)

TSD_COMMAND_CHOICES = ("Detail", "Detail_Dash")


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
        self._palette_colors: tuple[QtGui.QColor, ...] = ()
        self._display_unit = "500ths"

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
        if orientation == QtCore.Qt.Horizontal and 0 <= section < len(
            self.COLUMN_LABELS
        ):
            if section == 2:
                return f"Width ({measurement_unit_label(self._display_unit)})"
            if 3 <= section <= 6:
                base = self.COLUMN_LABELS[section].split(" (")[0]
                return f"{base} ({measurement_unit_label(self._display_unit)})"
            return self.COLUMN_LABELS[section]
        return str(section + 1)

    def data(
        self, index: QtCore.QModelIndex, role: int = QtCore.Qt.DisplayRole
    ) -> str | int | QtGui.QBrush | None:
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None

        row = self._rows[index.row()]
        if role in (QtCore.Qt.DisplayRole, QtCore.Qt.EditRole):
            value = self._display_value(row, index.column())
            return str(value)
        if role == QtCore.Qt.TextAlignmentRole:
            return int(QtCore.Qt.AlignCenter)
        if index.column() == 1:
            if role == QtCore.Qt.BackgroundRole:
                color = self._color_for_index(row.color_index)
                return QtGui.QBrush(color) if color is not None else None
            if role == QtCore.Qt.ForegroundRole:
                color = self._color_for_index(row.color_index)
                if color is None:
                    return None
                luminance = (
                    (0.299 * color.red())
                    + (0.587 * color.green())
                    + (0.114 * color.blue())
                )
                return QtGui.QBrush(
                    QtGui.QColor("black") if luminance >= 140 else QtGui.QColor("white")
                )
            if role == QtCore.Qt.ToolTipRole:
                color = self._color_for_index(row.color_index)
                if color is not None:
                    return (
                        f"SUNNY.PCX palette index {row.color_index}: "
                        f"rgb({color.red()}, {color.green()}, {color.blue()})"
                    )
                return "Load SUNNY.PCX to preview this palette index color."
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
        self.dataChanged.emit(
            index,
            index,
            [
                QtCore.Qt.DisplayRole,
                QtCore.Qt.EditRole,
                QtCore.Qt.BackgroundRole,
                QtCore.Qt.ForegroundRole,
                QtCore.Qt.ToolTipRole,
            ],
        )
        return True

    def _parse_value(self, column: int, value: object) -> str | int | None:
        text = "" if value is None else str(value).strip()
        if column == 0:
            try:
                return normalize_tsd_command(text or TSD_COMMAND_CHOICES[0])
            except ValueError:
                return None
        try:
            if 2 <= column <= 6:
                return units_to_500ths(float(text), self._display_unit)
            return int(text)
        except ValueError:
            return None

    def _display_value(self, row: TsdLineRow, column: int) -> str | int:
        raw_values: tuple[str | int, ...] = (
            row.command,
            row.color_index,
            row.width_500ths,
            row.start_dlong,
            row.start_dlat,
            row.end_dlong,
            row.end_dlat,
        )
        raw_value = raw_values[column]
        if 2 <= column <= 6:
            display = units_from_500ths(float(raw_value), self._display_unit)
            decimals = measurement_unit_decimals(self._display_unit)
            return f"{display:.{decimals}f}" if decimals > 0 else int(round(display))
        return raw_value

    def set_display_unit(self, unit: str) -> None:
        if unit == self._display_unit:
            return
        self._display_unit = str(unit)
        self.headerDataChanged.emit(QtCore.Qt.Horizontal, 2, 6)
        if not self._rows:
            return
        self.dataChanged.emit(
            self.index(0, 2),
            self.index(len(self._rows) - 1, 6),
            [QtCore.Qt.DisplayRole, QtCore.Qt.EditRole],
        )

    def set_palette_colors(
        self, palette: list[QtGui.QColor] | tuple[QtGui.QColor, ...] | None
    ) -> None:
        self._palette_colors = tuple(QtGui.QColor(color) for color in (palette or ()))
        if not self._rows:
            return
        top_left = self.index(0, 1)
        bottom_right = self.index(len(self._rows) - 1, 1)
        self.dataChanged.emit(
            top_left,
            bottom_right,
            [QtCore.Qt.BackgroundRole, QtCore.Qt.ForegroundRole, QtCore.Qt.ToolTipRole],
        )

    def _color_for_index(self, color_index: int) -> QtGui.QColor | None:
        if not self._palette_colors:
            return None
        clamped_index = max(0, min(255, int(color_index)))
        if clamped_index >= len(self._palette_colors):
            return None
        return QtGui.QColor(self._palette_colors[clamped_index])

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

    def move_row(self, *, source_row: int, target_row: int) -> bool:
        if not (0 <= source_row < len(self._rows)):
            return False
        if not (0 <= target_row < len(self._rows)):
            return False
        if source_row == target_row:
            return False
        self._rows[source_row], self._rows[target_row] = (
            self._rows[target_row],
            self._rows[source_row],
        )
        top_left = self.index(min(source_row, target_row), 0)
        bottom_right = self.index(max(source_row, target_row), self.columnCount() - 1)
        self.dataChanged.emit(
            top_left, bottom_right, [QtCore.Qt.DisplayRole, QtCore.Qt.EditRole]
        )
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

    def lines_for_rows(
        self, rows: list[int] | range | None = None
    ) -> list[TrackSurfaceDetailLine]:
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
