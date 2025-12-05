from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from PyQt5 import QtWidgets, QtCore

from sg_viewer.elevation_profile import ElevationProfileWidget
from sg_viewer.preview_widget import (
    SectionGeometry,
    SectionHeadingData,
    SectionSelection,
    SGPreviewWidget,
)
from sg_viewer.section_properties import SectionPropertiesPanel
from sg_viewer.editor_state import EditorState


class SGViewerApp(QtWidgets.QApplication):
    """Thin application wrapper for the SG viewer."""

    def __init__(self, argv: List[str]):
        super().__init__(argv)
        self.setQuitOnLastWindowClosed(True)
        self.window: SGViewerWindow | None = None


class SectionTableWindow(QtWidgets.QDialog):
    """Displays a table of section endpoints and gaps."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Section Table")
        self.resize(720, 480)

        layout = QtWidgets.QVBoxLayout()
        self._table = QtWidgets.QTableWidget()
        self._table.setColumnCount(6)
        self._table.setHorizontalHeaderLabels(
            ["Section", "Start X", "Start Y", "End X", "End Y", "Gap → Next"]
        )
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.Stretch)

        layout.addWidget(self._table)
        self.setLayout(layout)

    def set_sections(self, sections: list[SectionGeometry]) -> None:
        self._table.setRowCount(len(sections))
        for row, section in enumerate(sections):
            values = [
                str(section.index),
                f"{section.start_x:.1f}",
                f"{section.start_y:.1f}",
                f"{section.end_x:.1f}",
                f"{section.end_y:.1f}",
                f"{section.gap_to_next:.1f}",
            ]
            for col, value in enumerate(values):
                self._table.setItem(row, col, QtWidgets.QTableWidgetItem(value))


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
    """Main SG viewer + editor window."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SG Editor")
        self.resize(1200, 800)

        # ---------------------------------------------------------
        # Core widgets
        # ---------------------------------------------------------
        self._preview = SGPreviewWidget()
        self._state: EditorState | None = None

        # Section properties panel
        self._properties = SectionPropertiesPanel(self)
        self._properties.set_state(None)

        # ---------------------------------------------------------
        # Dock: Section Properties Panel
        # ---------------------------------------------------------
        dock = QtWidgets.QDockWidget("Section Properties", self)
        dock.setWidget(self._properties)
        dock.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        self.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)

        # ---------------------------------------------------------
        # Sidebar UI (selection, tools, tables)
        # ---------------------------------------------------------
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

        # ---------------------------------------------------------
        # Sidebar layout
        # ---------------------------------------------------------
        sidebar_layout = QtWidgets.QVBoxLayout()
        nav_layout = QtWidgets.QHBoxLayout()
        nav_layout.addWidget(self._prev_button)
        nav_layout.addWidget(self._next_button)
        sidebar_layout.addLayout(nav_layout)

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

        # ---------------------------------------------------------
        # Main layout: preview on left, sidebar on right
        # ---------------------------------------------------------
        preview_column = QtWidgets.QWidget()
        preview_layout = QtWidgets.QVBoxLayout()
        preview_layout.addWidget(self._preview, stretch=5)

        profile_controls = QtWidgets.QHBoxLayout()
        profile_controls.addWidget(QtWidgets.QLabel("Elevation X-Section:"))
        profile_controls.addWidget(self._xsect_combo)

        preview_layout.addLayout(profile_controls)
        preview_layout.addWidget(self._profile_widget, stretch=2)

        preview_column.setLayout(preview_layout)

        container = QtWidgets.QWidget()
        main_layout = QtWidgets.QHBoxLayout()
        main_layout.addWidget(preview_column, stretch=1)
        main_layout.addWidget(self._sidebar)
        container.setLayout(main_layout)

        self.setCentralWidget(container)

        # ---------------------------------------------------------
        # Menus / actions
        # ---------------------------------------------------------
        self._create_actions()
        self._create_menus()

        # ---------------------------------------------------------
        # Signals
        # ---------------------------------------------------------
        self._preview.selectedSectionChanged.connect(self._update_selection_sidebar)
        self._preview.selectedSectionChanged.connect(self._properties.on_section_changed)

        self._prev_button.clicked.connect(self._preview.select_previous_section)
        self._next_button.clicked.connect(self._preview.select_next_section)

        self._radii_button.toggled.connect(self._preview.set_show_curve_markers)

        self._section_table_button.clicked.connect(self._show_section_table)
        self._heading_table_button.clicked.connect(self._show_heading_table)
        self._xsect_combo.currentIndexChanged.connect(self._refresh_elevation_profile)

        self.statusBar().showMessage("Select File → Open SG to begin.")

    # ------------------------------------------------------------------
    # File loading + EditorState integration
    # ------------------------------------------------------------------
    def load_sg(self, path: Path) -> None:
        try:
            self._preview.load_sg_file(path)
            self._state = self._preview._state  # sync EditorState
            self._properties.set_state(self._state)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Failed to load SG", str(exc))
            logging.exception("Failed to load SG file")
            return

        self.statusBar().showMessage(f"Loaded {path}")
        self._section_table_button.setEnabled(True)
        self._heading_table_button.setEnabled(True)

        self._update_section_table()
        self._update_heading_table()
        self._populate_xsect_choices()
        self._refresh_elevation_profile()

    # ------------------------------------------------------------------
    # Menus
    # ------------------------------------------------------------------
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
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open SG file",
            "",
            "SG files (*.sg *.SG);;All files (*)",
        )
        if file_path:
            self.load_sg(Path(file_path))

    # ------------------------------------------------------------------
    # Selection sidebar updates
    # ------------------------------------------------------------------
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

        if selection.start_heading:
            sx, sy = selection.start_heading
            self._start_heading_label.setText(f"Start Heading: ({sx:.5f}, {sy:.5f})")
        else:
            self._start_heading_label.setText("Start Heading: –")

        if selection.end_heading:
            ex, ey = selection.end_heading
            self._end_heading_label.setText(f"End Heading: ({ex:.5f}, {ey:.5f})")
        else:
            self._end_heading_label.setText("End Heading: –")

        selected_range = self._preview.get_section_range(selection.index)
        self._profile_widget.set_selected_range(selected_range)

    # ------------------------------------------------------------------
    # Tables
    # ------------------------------------------------------------------
    def _show_section_table(self) -> None:
        sections = self._preview.get_section_geometries()
        if not sections:
            QtWidgets.QMessageBox.information(
                self, "No Sections", "Load an SG file to view sections."
            )
            return

        if self._section_table_window is None:
            self._section_table_window = SectionTableWindow(self)

        self._section_table_window.set_sections(sections)
        self._section_table_window.show()
        self._section_table_window.raise_()

    def _update_section_table(self) -> None:
        if self._section_table_window:
            sections = self._preview.get_section_geometries()
            self._section_table_window.set_sections(sections)

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

    def _update_heading_table(self) -> None:
        if self._heading_table_window:
            headings = self._preview.get_section_headings()
            self._heading_table_window.set_headings(headings)

    # ------------------------------------------------------------------
    # Elevation profile
    # ------------------------------------------------------------------
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
