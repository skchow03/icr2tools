from __future__ import annotations

import math
from dataclasses import replace
from typing import Callable

from PyQt5 import QtCore, QtWidgets

from sg_viewer.sg_model import SectionPreview


def _parse_float(value: str) -> float | None:
    value = value.strip()
    if not value or value == "–":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_int(value: str, default: int) -> int:
    try:
        return int(value)
    except ValueError:
        return default


def _point_from_heading(
    center: tuple[float, float] | None,
    heading: tuple[float, float] | None,
    radius: float | None,
    reference: tuple[float, float] | None,
) -> tuple[float, float] | None:
    if center is None or heading is None or radius is None or radius <= 0:
        return None

    hx, hy = heading
    length = math.hypot(hx, hy)
    if length <= 0:
        return None

    nx, ny = hx / length, hy / length
    cx, cy = center
    candidates = [
        (cx - ny * radius, cy + nx * radius),
        (cx + ny * radius, cy - nx * radius),
    ]

    if reference is None:
        return candidates[0]

    def _distance_sq(point: tuple[float, float]) -> float:
        dx = point[0] - reference[0]
        dy = point[1] - reference[1]
        return dx * dx + dy * dy

    return min(candidates, key=_distance_sq)


class SectionTableWindow(QtWidgets.QDialog):
    """Displays a table of section endpoints and gaps."""

    sectionsEdited = QtCore.pyqtSignal(list)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Section Table")
        self.resize(720, 480)

        self._sections: list[SectionPreview] = []
        self._track_length: float | None = None
        self._is_updating = False
        self._pending_edit = False

        self._apply_timer = QtCore.QTimer(self)
        self._apply_timer.setInterval(500)
        self._apply_timer.setSingleShot(True)
        self._apply_timer.timeout.connect(self._apply_pending_edits)

        layout = QtWidgets.QVBoxLayout()
        self._table = QtWidgets.QTableWidget()
        self._table.setColumnCount(16)
        self._table.setHorizontalHeaderLabels(
            [
                "Section",
                "Type",
                "Prev",
                "Next",
                "Start X",
                "Start Y",
                "End X",
                "End Y",
                "Gap → Next",
                "Center X",
                "Center Y",
                "SAng1",
                "SAng2",
                "EAng1",
                "EAng2",
                "Radius",
            ]
        )
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.AllEditTriggers)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeToContents
        )
        self._table.itemChanged.connect(self._handle_item_changed)
        self._table.itemDelegate().closeEditor.connect(self._apply_after_editor_close)

        layout.addWidget(self._table)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addStretch()
        self._apply_button = QtWidgets.QPushButton("Apply")
        self._apply_button.setEnabled(False)
        self._apply_button.clicked.connect(self._apply_pending_edits)
        button_row.addWidget(self._apply_button)
        layout.addLayout(button_row)
        self.setLayout(layout)
        self._columns_resized_once = False

    def set_sections(
        self, sections: list[SectionPreview], track_length: float | None
    ) -> None:
        self._sections = list(sections)
        self._track_length = track_length
        self._is_updating = True
        self._pending_edit = False
        self._apply_timer.stop()
        self._apply_button.setEnabled(False)
        try:
            self._populate_rows()
        finally:
            self._is_updating = False

        if not self._columns_resized_once:
            self._resize_columns()
            self._columns_resized_once = True

    def on_sections_edited(self, callback: Callable[[list[SectionPreview]], None]) -> None:
        self.sectionsEdited.connect(callback)

    def _apply_after_editor_close(self, editor, hint):
        if self._is_updating:
            return

        updated_sections = self._build_sections_from_table()
        self._sections = updated_sections
        self.sectionsEdited.emit(updated_sections)

    def _populate_rows(self) -> None:
        def _fmt(value: float | None, precision: int = 1) -> str:
            if value is None:
                return "–"
            if float(value).is_integer():
                return f"{int(value)}"
            return f"{value:.{precision}f}"

        self._table.blockSignals(True)
        self._table.clearContents()

        self._table.setRowCount(len(self._sections))
        total_sections = len(self._sections)
        for row, section in enumerate(self._sections):
            end_dlong = section.start_dlong + section.length
            gap = None
            if self._track_length:
                end_dlong = end_dlong % self._track_length
                next_section = self._sections[(row + 1) % total_sections]
                next_start = next_section.start_dlong % self._track_length
                gap = (next_start - end_dlong) % self._track_length

            values = [
                str(section.section_id),
                section.type_name.title(),
                str(section.previous_id),
                str(section.next_id),
                _fmt(section.start[0]),
                _fmt(section.start[1]),
                _fmt(section.end[0]),
                _fmt(section.end[1]),
                _fmt(gap) if gap is not None else "–",
                _fmt(section.center[0]) if section.center else "–",
                _fmt(section.center[1]) if section.center else "–",
                _fmt(section.sang1, 5),
                _fmt(section.sang2, 5),
                _fmt(section.eang1, 5),
                _fmt(section.eang2, 5),
                _fmt(section.radius) if section.radius is not None else "–",
            ]
            for col, value in enumerate(values):
                self._table.setItem(row, col, QtWidgets.QTableWidgetItem(value))
        self._table.blockSignals(False)

    def _resize_columns(self) -> None:
        self._table.resizeColumnsToContents()

    def _handle_item_changed(self, _item: QtWidgets.QTableWidgetItem) -> None:
        if self._is_updating:
            return

        self._pending_edit = True
        self._apply_button.setEnabled(True)

    def _apply_pending_edits(self, *_args) -> None:
        self._apply_timer.stop()
        if self._is_updating or not self._pending_edit:
            return

        updated_sections = self._build_sections_from_table()
        self._pending_edit = False
        self._sections = updated_sections

        self.sectionsEdited.emit(updated_sections)
        self._apply_button.setEnabled(False)

    def _build_sections_from_table(self) -> list[SectionPreview]:
        updated: list[SectionPreview] = []
        for row, original in enumerate(self._sections):
            section_item = self._table.item(row, 0)
            type_item = self._table.item(row, 1)
            prev_item = self._table.item(row, 2)
            next_item = self._table.item(row, 3)

            def _cell_text(column: int) -> str:
                cell = self._table.item(row, column)
                return cell.text() if cell is not None else ""

            start_x = _parse_float(_cell_text(4))
            start_y = _parse_float(_cell_text(5))
            end_x = _parse_float(_cell_text(6))
            end_y = _parse_float(_cell_text(7))

            center_x = _parse_float(_cell_text(9))
            center_y = _parse_float(_cell_text(10))
            sang1 = _parse_float(_cell_text(11))
            sang2 = _parse_float(_cell_text(12))
            eang1 = _parse_float(_cell_text(13))
            eang2 = _parse_float(_cell_text(14))
            radius = _parse_float(_cell_text(15))

            type_text = type_item.text() if type_item else original.type_name
            type_name = type_text.lower().strip()
            if type_name not in {"curve", "straight"}:
                type_name = original.type_name

            section_id = (
                _parse_int(section_item.text(), original.section_id)
                if section_item
                else original.section_id
            )
            prev_id = (
                _parse_int(prev_item.text(), original.previous_id)
                if prev_item
                else original.previous_id
            )
            next_id = (
                _parse_int(next_item.text(), original.next_id)
                if next_item
                else original.next_id
            )

            start = (
                (start_x, start_y)
                if start_x is not None and start_y is not None
                else original.start
            )
            end = (
                (end_x, end_y) if end_x is not None and end_y is not None else original.end
            )

            center = None
            if center_x is not None and center_y is not None:
                center = (center_x, center_y)

            start_heading = None
            end_heading = None
            if sang1 is not None and sang2 is not None:
                start_heading = (sang1, sang2)
            if eang1 is not None and eang2 is not None:
                end_heading = (eang1, eang2)

            if type_name == "curve" and center is not None and radius is not None:
                recalculated_start = _point_from_heading(center, start_heading, radius, start)
                recalculated_end = _point_from_heading(center, end_heading, radius, end)

                if recalculated_start is not None:
                    start = recalculated_start
                if recalculated_end is not None:
                    end = recalculated_end

            polyline: list[tuple[float, float]]
            if original.polyline:
                polyline = list(original.polyline)
                polyline[0] = start
                polyline[-1] = end
            else:
                polyline = [start, end]

            updated.append(
                replace(
                    original,
                    section_id=section_id,
                    type_name=type_name,
                    previous_id=prev_id,
                    next_id=next_id,
                    start=start,
                    end=end,
                    center=center,
                    sang1=sang1,
                    sang2=sang2,
                    eang1=eang1,
                    eang2=eang2,
                    radius=radius,
                    start_heading=start_heading,
                    end_heading=end_heading,
                    polyline=polyline,
                )
            )

        return updated
