from __future__ import annotations

import logging
from pathlib import Path

from PyQt5 import QtWidgets

from sg_viewer.heading_table_dialog import HeadingTableWindow
from sg_viewer.sg_model import SectionPreview
from sg_viewer.section_table_dialog import SectionTableWindow

logger = logging.getLogger(__name__)


class SGViewerController:
    """Coordinates actions, menus, and dialogs for the SG viewer window."""

    def __init__(self, window: QtWidgets.QMainWindow) -> None:
        self._window = window
        self._section_table_window: SectionTableWindow | None = None
        self._heading_table_window: HeadingTableWindow | None = None

        self._create_actions()
        self._create_menus()
        self._connect_signals()
        self._window.statusBar().showMessage("Select File → Open SG to begin.")

    def load_sg(self, path: Path) -> None:
        try:
            self._window.preview.load_sg_file(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self._window, "Failed to load SG", str(exc))
            logger.exception("Failed to load SG file")
            return

        self._window.statusBar().showMessage(f"Loaded {path}")
        self._window.section_table_button.setEnabled(True)
        self._window.heading_table_button.setEnabled(True)
        self._update_section_table()
        self._update_heading_table()
        self._populate_xsect_choices()
        self._refresh_elevation_profile()

    def _create_actions(self) -> None:
        self._open_action = QtWidgets.QAction("Open SG…", self._window)
        self._open_action.setShortcut("Ctrl+O")
        self._open_action.triggered.connect(self._open_file_dialog)

        self._quit_action = QtWidgets.QAction("Quit", self._window)
        self._quit_action.setShortcut("Ctrl+Q")
        self._quit_action.triggered.connect(self._window.close)

    def _create_menus(self) -> None:
        file_menu = self._window.menuBar().addMenu("&File")
        file_menu.addAction(self._open_action)
        file_menu.addSeparator()
        file_menu.addAction(self._quit_action)

    def _connect_signals(self) -> None:
        self._window.preview.selectedSectionChanged.connect(
            self._window.update_selection_sidebar
        )
        self._window.prev_button.clicked.connect(self._window.preview.select_previous_section)
        self._window.next_button.clicked.connect(self._window.preview.select_next_section)
        self._window.radii_button.toggled.connect(self._window.preview.set_show_curve_markers)
        self._window.section_table_button.clicked.connect(self._show_section_table)
        self._window.heading_table_button.clicked.connect(self._show_heading_table)
        self._window.xsect_combo.currentIndexChanged.connect(
            self._refresh_elevation_profile
        )
        self._window.fit_button.clicked.connect(self._start_manual_fit)
        self._window.preview.statusMessageEmitted.connect(
            self._window.statusBar().showMessage
        )

    def _open_file_dialog(self) -> None:
        options = QtWidgets.QFileDialog.Options()
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._window,
            "Open SG file",
            "",
            "SG files (*.sg *.SG);;All files (*)",
            options=options,
        )
        if file_path:
            self.load_sg(Path(file_path))

    def _show_section_table(self) -> None:
        sections, track_length = self._window.preview.get_section_set()
        if not sections:
            QtWidgets.QMessageBox.information(
                self._window, "No Sections", "Load an SG file to view sections."
            )
            return

        if self._section_table_window is None:
            self._section_table_window = SectionTableWindow(self._window)
            self._section_table_window.on_sections_edited(self._apply_section_table_edits)

        self._section_table_window.set_sections(sections, track_length)
        self._section_table_window.show()
        self._section_table_window.raise_()
        self._section_table_window.activateWindow()

    def _update_section_table(self) -> None:
        if self._section_table_window is None:
            return

        sections, track_length = self._window.preview.get_section_set()
        self._section_table_window.set_sections(sections, track_length)

    def _apply_section_table_edits(self, sections: list[SectionPreview]) -> None:
        self._window.preview.set_sections(sections)
        self._update_heading_table()

    def _show_heading_table(self) -> None:
        headings = self._window.preview.get_section_headings()
        if not headings:
            QtWidgets.QMessageBox.information(
                self._window, "No Headings", "Load an SG file to view headings."
            )
            return

        if self._heading_table_window is None:
            self._heading_table_window = HeadingTableWindow(self._window)

        self._heading_table_window.set_headings(headings)
        self._heading_table_window.show()
        self._heading_table_window.raise_()
        self._heading_table_window.activateWindow()

    def _update_heading_table(self) -> None:
        if self._heading_table_window is None:
            return

        headings = self._window.preview.get_section_headings()
        self._heading_table_window.set_headings(headings)

    def _populate_xsect_choices(self) -> None:
        metadata = self._window.preview.get_xsect_metadata()
        combo = self._window.xsect_combo
        combo.blockSignals(True)
        combo.clear()
        for idx, dlat in metadata:
            combo.addItem(f"{idx} (DLAT {dlat:.0f})", idx)
        combo.setEnabled(bool(metadata))
        if metadata:
            combo.setCurrentIndex(0)
        combo.blockSignals(False)

    def _refresh_elevation_profile(self) -> None:
        combo = self._window.xsect_combo
        if not combo.isEnabled():
            self._window.profile_widget.set_profile_data(None)
            return

        current_index = combo.currentData()
        if current_index is None:
            current_index = combo.currentIndex()

        profile = self._window.preview.build_elevation_profile(int(current_index))
        self._window.profile_widget.set_profile_data(profile)

    def _start_manual_fit(self) -> None:
        self._window.preview.start_manual_fit_attempt()
