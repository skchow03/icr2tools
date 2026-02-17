from __future__ import annotations

from PyQt5 import QtWidgets

from sg_viewer.ui.presentation.units_presenter import format_fsect_dlat


def boundary_numbers_for_fsects(fsects) -> dict[int, str]:
    boundary_rows = [
        (row_index, fsect)
        for row_index, fsect in enumerate(fsects)
        if fsect.surface_type in {7, 8}
    ]
    boundary_rows.sort(
        key=lambda row_fsect: (
            min(row_fsect[1].start_dlat, row_fsect[1].end_dlat),
            max(row_fsect[1].start_dlat, row_fsect[1].end_dlat),
            row_fsect[0],
        )
    )
    return {row_index: str(boundary_number) for boundary_number, (row_index, _fsect) in enumerate(boundary_rows)}


def format_fsect_delta(fsects, row_index: int, endpoint: str, *, unit: str) -> str:
    next_row_index = row_index + 1
    if row_index < 0 or next_row_index >= len(fsects):
        return ""
    current = fsects[row_index]
    following = fsects[next_row_index]
    delta = (
        following.start_dlat - current.start_dlat
        if endpoint == "start"
        else following.end_dlat - current.end_dlat
    )
    return format_fsect_dlat(delta, unit=unit)


def reset_fsect_dlat_cell(table: QtWidgets.QTableWidget, row_index: int, column_index: int, fsect, *, unit: str) -> None:
    value = fsect.start_dlat if column_index == 2 else fsect.end_dlat
    item = table.item(row_index, column_index)
    if item is None:
        return
    table.blockSignals(True)
    item.setText(format_fsect_dlat(value, unit=unit))
    table.blockSignals(False)


def reset_fsect_delta_cell(table: QtWidgets.QTableWidget, row_index: int, column_index: int, fsects, *, unit: str) -> None:
    endpoint = "start" if column_index == 4 else "end"
    item = table.item(row_index, column_index)
    if item is None:
        return
    table.blockSignals(True)
    item.setText(format_fsect_delta(fsects, row_index, endpoint, unit=unit))
    table.blockSignals(False)


def set_fsect_delta_cell_text(table: QtWidgets.QTableWidget, row_index: int, column_index: int, value: str) -> None:
    item = table.item(row_index, column_index)
    if item is None:
        item = QtWidgets.QTableWidgetItem("")
        table.setItem(row_index, column_index, item)
    table.blockSignals(True)
    item.setText(value)
    table.blockSignals(False)
