from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import List

from dataclasses import replace

from PyQt5 import QtCore, QtWidgets

from sg_viewer.elevation_profile import ElevationProfileWidget
from sg_viewer.preview_widget import (
    SectionHeadingData,
    SectionSelection,
    SGPreviewWidget,
)
from sg_viewer.preview_loader import SectionPreview


class SGViewerApp(QtWidgets.QApplication):
    """Thin application wrapper for the SG viewer."""

    def __init__(self, argv: List[str]):
        super().__init__(argv)
        self.setQuitOnLastWindowClosed(True)
        self.window: SGViewerWindow | None = None


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

    def _apply_after_editor_close(self, editor, hint):
        if self._is_updating:
            return

        # Same logic you had in _apply_pending_edits, but fast
        updated_sections = self._build_sections_from_table()
        self._sections = updated_sections

        # Send to preview immediately
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

    def _handle_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._is_updating:
            return

        self._pending_edit = True
        self._apply_button.setEnabled(True)
        # self._apply_timer.start()

    def _apply_pending_edits(self, *_args) -> None:
        # If you kept the timer, you can keep this guard.
        self._apply_timer.stop()
        if self._is_updating or not self._pending_edit:
            return

        updated_sections = self._build_sections_from_table()
        self._pending_edit = False
        self._sections = updated_sections

        # Send the updated sections to the preview window.
        self.sectionsEdited.emit(updated_sections)

        # Do NOT call set_sections() here; that repopulates the table and
        # resizes columns again, which is slow and redundant.
        self._apply_button.setEnabled(False)


    def _build_sections_from_table(self) -> list[SectionPreview]:
        def _parse_float(value: str) -> float | None:
            value = value.strip()
            if not value or value == "–":
                return None
            try:
                return float(value)
            except ValueError:
                return None

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

        def _parse_int(value: str, default: int) -> int:
            try:
                return int(value)
            except ValueError:
                return default

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

            section_id = _parse_int(section_item.text(), original.section_id) if section_item else original.section_id
            prev_id = _parse_int(prev_item.text(), original.previous_id) if prev_item else original.previous_id
            next_id = _parse_int(next_item.text(), original.next_id) if next_item else original.next_id

            start = (start_x, start_y) if start_x is not None and start_y is not None else original.start
            end = (end_x, end_y) if end_x is not None and end_y is not None else original.end

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


class HeadingTableWindow(QtWidgets.QDialog):
    """Displays start/end headings and deltas between sections."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Heading Table")
        self.resize(780, 520)

        layout = QtWidgets.QVBoxLayout()
        self._table = QtWidgets.QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(
            [
                "Section",
                "Start X",
                "Start Y",
                "End X",
                "End Y",
                "Δ to Next (deg)",
            ]
        )
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        layout.addWidget(self._table)
        self.setLayout(layout)

    def set_headings(self, headings: list[SectionHeadingData]) -> None:
        self._table.setRowCount(len(headings))

        def _fmt(value: float | None) -> str:
            return "–" if value is None else f"{value:.5f}"

        for row, entry in enumerate(headings):
            values = [
                str(entry.index),
                _fmt(entry.start_heading[0] if entry.start_heading else None),
                _fmt(entry.start_heading[1] if entry.start_heading else None),
                _fmt(entry.end_heading[0] if entry.end_heading else None),
                _fmt(entry.end_heading[1] if entry.end_heading else None),
                _fmt(entry.delta_to_next),
            ]
            for col, value in enumerate(values):
                self._table.setItem(row, col, QtWidgets.QTableWidgetItem(value))

class SGViewerWindow(QtWidgets.QMainWindow):
    """Single-window utility that previews SG centrelines."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SG Viewer")
        self.resize(960, 720)

        self._preview = SGPreviewWidget()
        self._sidebar = QtWidgets.QWidget()
        self._prev_button = QtWidgets.QPushButton("Previous Section")
        self._next_button = QtWidgets.QPushButton("Next Section")
        self._radii_button = QtWidgets.QPushButton("Radii")
        self._radii_button.setCheckable(True)
        self._radii_button.setChecked(True)
        self._section_table_button = QtWidgets.QPushButton("Section Table")
        self._section_table_button.setEnabled(False)
        self._heading_table_button = QtWidgets.QPushButton("Heading Table")
        self._heading_table_button.setEnabled(False)
        self._profile_widget = ElevationProfileWidget()
        self._xsect_combo = QtWidgets.QComboBox()
        self._xsect_combo.setEnabled(False)
        self._section_label = QtWidgets.QLabel("Section: None")
        self._type_label = QtWidgets.QLabel("Type: –")
        self._dlong_label = QtWidgets.QLabel("DLONG: –")
        self._center_label = QtWidgets.QLabel("Center: –")
        self._radius_label = QtWidgets.QLabel("Radius: –")
        self._start_heading_label = QtWidgets.QLabel("Start Heading: –")
        self._end_heading_label = QtWidgets.QLabel("End Heading: –")
        self._section_table_window: SectionTableWindow | None = None
        self._heading_table_window: HeadingTableWindow | None = None

        sidebar_layout = QtWidgets.QVBoxLayout()
        navigation_layout = QtWidgets.QHBoxLayout()
        navigation_layout.addWidget(self._prev_button)
        navigation_layout.addWidget(self._next_button)
        sidebar_layout.addLayout(navigation_layout)
        sidebar_layout.addWidget(self._radii_button)
        sidebar_layout.addWidget(self._section_table_button)
        sidebar_layout.addWidget(self._heading_table_button)
        sidebar_layout.addWidget(QtWidgets.QLabel("Selection"))
        sidebar_layout.addWidget(self._section_label)
        sidebar_layout.addWidget(self._type_label)
        sidebar_layout.addWidget(self._dlong_label)
        sidebar_layout.addWidget(self._center_label)
        sidebar_layout.addWidget(self._radius_label)
        sidebar_layout.addWidget(self._start_heading_label)
        sidebar_layout.addWidget(self._end_heading_label)
        sidebar_layout.addStretch()
        self._sidebar.setLayout(sidebar_layout)

        preview_column = QtWidgets.QWidget()
        preview_column_layout = QtWidgets.QVBoxLayout()
        preview_column_layout.addWidget(self._preview, stretch=5)

        profile_controls = QtWidgets.QHBoxLayout()
        profile_controls.addWidget(QtWidgets.QLabel("Elevation X-Section:"))
        profile_controls.addWidget(self._xsect_combo)
        preview_column_layout.addLayout(profile_controls)
        preview_column_layout.addWidget(self._profile_widget, stretch=2)
        preview_column.setLayout(preview_column_layout)

        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(preview_column, stretch=1)
        layout.addWidget(self._sidebar)
        container.setLayout(layout)
        self.setCentralWidget(container)

        self._create_actions()
        self._create_menus()
        self.statusBar().showMessage("Select File → Open SG to begin.")
        self._preview.selectedSectionChanged.connect(self._update_selection_sidebar)
        self._prev_button.clicked.connect(self._preview.select_previous_section)
        self._next_button.clicked.connect(self._preview.select_next_section)
        self._radii_button.toggled.connect(self._preview.set_show_curve_markers)
        self._section_table_button.clicked.connect(self._show_section_table)
        self._heading_table_button.clicked.connect(self._show_heading_table)
        self._xsect_combo.currentIndexChanged.connect(self._refresh_elevation_profile)

    def load_sg(self, path: Path) -> None:
        try:
            self._preview.load_sg_file(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Failed to load SG", str(exc))
            logging.exception("Failed to load SG file")
        else:
            self.statusBar().showMessage(f"Loaded {path}")
            self._section_table_button.setEnabled(True)
            self._heading_table_button.setEnabled(True)
            self._update_section_table()
            self._update_heading_table()
            self._populate_xsect_choices()
            self._refresh_elevation_profile()

    def _create_actions(self) -> None:
        self._open_action = QtWidgets.QAction("Open SG…", self)
        self._open_action.setShortcut("Ctrl+O")
        self._open_action.triggered.connect(self._open_file_dialog)

        self._quit_action = QtWidgets.QAction("Quit", self)
        self._quit_action.setShortcut("Ctrl+Q")
        self._quit_action.triggered.connect(self.close)

    def _create_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self._open_action)
        file_menu.addSeparator()
        file_menu.addAction(self._quit_action)

    def _open_file_dialog(self) -> None:
        options = QtWidgets.QFileDialog.Options()
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open SG file",
            "",
            "SG files (*.sg *.SG);;All files (*)",
            options=options,
        )
        if file_path:
            self.load_sg(Path(file_path))

    def _update_selection_sidebar(self, selection: SectionSelection | None) -> None:
        if selection is None:
            self._section_label.setText("Section: None")
            self._type_label.setText("Type: –")
            self._dlong_label.setText("DLONG: –")
            self._center_label.setText("Center: –")
            self._radius_label.setText("Radius: –")
            self._start_heading_label.setText("Start Heading: –")
            self._end_heading_label.setText("End Heading: –")
            self._profile_widget.set_selected_range(None)
            return

        self._section_label.setText(f"Section: {selection.index}")
        self._type_label.setText(f"Type: {selection.type_name}")
        self._dlong_label.setText(
            f"DLONG: {selection.start_dlong:.0f} → {selection.end_dlong:.0f}"
        )
        if selection.center is not None and selection.radius is not None:
            cx, cy = selection.center
            self._center_label.setText(f"Center: ({cx:.1f}, {cy:.1f})")
            self._radius_label.setText(f"Radius: {selection.radius:.1f}")
        else:
            self._center_label.setText("Center: –")
            self._radius_label.setText("Radius: –")

        if selection.start_heading is not None:
            sx, sy = selection.start_heading
            self._start_heading_label.setText(
                f"Start Heading: ({sx:.5f}, {sy:.5f})"
            )
        else:
            self._start_heading_label.setText("Start Heading: –")

        if selection.end_heading is not None:
            ex, ey = selection.end_heading
            self._end_heading_label.setText(f"End Heading: ({ex:.5f}, {ey:.5f})")
        else:
            self._end_heading_label.setText("End Heading: –")

        selected_range = self._preview.get_section_range(selection.index)
        self._profile_widget.set_selected_range(selected_range)

    def _show_section_table(self) -> None:
        sections, track_length = self._preview.get_section_set()
        if not sections:
            QtWidgets.QMessageBox.information(
                self, "No Sections", "Load an SG file to view sections."
            )
            return

        if self._section_table_window is None:
            self._section_table_window = SectionTableWindow(self)
            self._section_table_window.sectionsEdited.connect(
                self._apply_section_table_edits
            )

        self._section_table_window.set_sections(sections, track_length)
        self._section_table_window.show()
        self._section_table_window.raise_()
        self._section_table_window.activateWindow()

    def _update_section_table(self) -> None:
        if self._section_table_window is None:
            return

        sections, track_length = self._preview.get_section_set()
        self._section_table_window.set_sections(sections, track_length)

    def _apply_section_table_edits(
        self, sections: list[SectionPreview]
    ) -> None:
        self._preview.set_sections(sections)
        self._update_heading_table()

    def _show_heading_table(self) -> None:
        headings = self._preview.get_section_headings()
        if not headings:
            QtWidgets.QMessageBox.information(
                self, "No Headings", "Load an SG file to view headings."
            )
            return

        if self._heading_table_window is None:
            self._heading_table_window = HeadingTableWindow(self)

        self._heading_table_window.set_headings(headings)
        self._heading_table_window.show()
        self._heading_table_window.raise_()
        self._heading_table_window.activateWindow()

    def _update_heading_table(self) -> None:
        if self._heading_table_window is None:
            return

        headings = self._preview.get_section_headings()
        self._heading_table_window.set_headings(headings)

    def _populate_xsect_choices(self) -> None:
        metadata = self._preview.get_xsect_metadata()
        self._xsect_combo.blockSignals(True)
        self._xsect_combo.clear()
        for idx, dlat in metadata:
            self._xsect_combo.addItem(f"{idx} (DLAT {dlat:.0f})", idx)
        self._xsect_combo.setEnabled(bool(metadata))
        if metadata:
            self._xsect_combo.setCurrentIndex(0)
        self._xsect_combo.blockSignals(False)

    def _refresh_elevation_profile(self) -> None:
        if not self._xsect_combo.isEnabled():
            self._profile_widget.set_profile_data(None)
            return

        current_index = self._xsect_combo.currentData()
        if current_index is None:
            current_index = self._xsect_combo.currentIndex()

        profile = self._preview.build_elevation_profile(int(current_index))
        self._profile_widget.set_profile_data(profile)

