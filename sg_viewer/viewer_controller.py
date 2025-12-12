from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from PyQt5 import QtWidgets

from sg_viewer.background_image_dialog import BackgroundImageDialog
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
        self._current_path: Path | None = None
        self._new_straight_default_style = window.new_straight_button.styleSheet()
        self._new_curve_default_style = window.new_curve_button.styleSheet()
        self._delete_default_style = window.delete_section_button.styleSheet()

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
        self._current_path = path
        self._window.section_table_button.setEnabled(True)
        self._window.heading_table_button.setEnabled(True)
        self._window.new_straight_button.setEnabled(True)
        self._window.new_curve_button.setEnabled(True)
        self._window.delete_section_button.setEnabled(True)
        self._save_action.setEnabled(True)
        self._update_section_table()
        self._update_heading_table()
        self._populate_xsect_choices()
        self._refresh_elevation_profile()

    def _create_actions(self) -> None:
        self._open_action = QtWidgets.QAction("Open SG…", self._window)
        self._open_action.setShortcut("Ctrl+O")
        self._open_action.triggered.connect(self._open_file_dialog)

        self._save_action = QtWidgets.QAction("Save SG As…", self._window)
        self._save_action.setShortcut("Ctrl+Shift+S")
        self._save_action.setEnabled(False)
        self._save_action.triggered.connect(self._save_file_dialog)

        self._open_background_action = QtWidgets.QAction(
            "Load Background Image…", self._window
        )
        self._open_background_action.setShortcut("Ctrl+B")
        self._open_background_action.triggered.connect(
            self._open_background_file_dialog
        )

        self._background_settings_action = QtWidgets.QAction(
            "Background Image Settings…", self._window
        )
        self._background_settings_action.setEnabled(False)
        self._background_settings_action.triggered.connect(
            self._show_background_settings_dialog
        )

        self._quit_action = QtWidgets.QAction("Quit", self._window)
        self._quit_action.setShortcut("Ctrl+Q")
        self._quit_action.triggered.connect(self._window.close)

    def _create_menus(self) -> None:
        file_menu = self._window.menuBar().addMenu("&File")
        file_menu.addAction(self._open_action)
        file_menu.addAction(self._save_action)
        file_menu.addAction(self._open_background_action)
        file_menu.addAction(self._background_settings_action)
        file_menu.addSeparator()
        file_menu.addAction(self._quit_action)

    def _connect_signals(self) -> None:
        self._window.preview.selectedSectionChanged.connect(
            self._window.update_selection_sidebar
        )
        self._window.prev_button.clicked.connect(self._window.preview.select_previous_section)
        self._window.next_button.clicked.connect(self._window.preview.select_next_section)
        self._window.new_straight_button.clicked.connect(self._start_new_straight)
        self._window.new_curve_button.clicked.connect(self._start_new_curve)
        self._window.preview.newStraightModeChanged.connect(
            self._on_new_straight_mode_changed
        )
        self._window.preview.newCurveModeChanged.connect(self._on_new_curve_mode_changed)
        self._window.delete_section_button.toggled.connect(
            self._toggle_delete_section_mode
        )
        self._window.preview.deleteModeChanged.connect(self._on_delete_mode_changed)
        self._window.radii_button.toggled.connect(self._window.preview.set_show_curve_markers)
        self._window.section_table_button.clicked.connect(self._show_section_table)
        self._window.heading_table_button.clicked.connect(self._show_heading_table)
        self._window.xsect_combo.currentIndexChanged.connect(
            self._refresh_elevation_profile
        )

    def _on_new_straight_mode_changed(self, active: bool) -> None:
        button = self._window.new_straight_button
        button.setChecked(active)
        if active:
            button.setStyleSheet("background-color: #3f51b5; color: white;")
        else:
            button.setStyleSheet(self._new_straight_default_style)

    def _on_new_curve_mode_changed(self, active: bool) -> None:
        button = self._window.new_curve_button
        button.setChecked(active)
        if active:
            button.setStyleSheet("background-color: #3f51b5; color: white;")
        else:
            button.setStyleSheet(self._new_curve_default_style)

    def _on_delete_mode_changed(self, active: bool) -> None:
        button = self._window.delete_section_button
        button.setChecked(active)
        if active:
            button.setStyleSheet("background-color: #b53f3f; color: white;")
        else:
            button.setStyleSheet(self._delete_default_style)

    def _open_background_file_dialog(self) -> None:
        options = QtWidgets.QFileDialog.Options()
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._window,
            "Open Background Image",
            "",
            "Image files (*.png *.jpg *.jpeg *.bmp *.pcx);;All files (*)",
            options=options,
        )
        if not file_path:
            return

        try:
            self._window.preview.load_background_image(Path(file_path))
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self._window, "Failed to load background", str(exc)
            )
            logger.exception("Failed to load background image")
            return

        self._background_settings_action.setEnabled(True)
        self._window.statusBar().showMessage(f"Loaded background image {file_path}")

    def _show_background_settings_dialog(self) -> None:
        if not self._window.preview.has_background_image():
            QtWidgets.QMessageBox.information(
                self._window,
                "No Background",
                "Load a background image before adjusting its settings.",
            )
            return

        scale, (origin_u, origin_v) = self._window.preview.get_background_settings()
        dialog = BackgroundImageDialog(self._window, scale, origin_u, origin_v)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            new_scale, new_u, new_v = dialog.get_values()
            if new_scale <= 0:
                QtWidgets.QMessageBox.warning(
                    self._window,
                    "Invalid Scale",
                    "500ths per pixel must be greater than zero.",
                )
                return
            self._window.preview.set_background_settings(
                new_scale, (new_u, new_v)
            )
            self._window.statusBar().showMessage("Updated background image settings")

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

    def _save_file_dialog(self) -> None:
        if self._window.preview.sgfile is None:
            QtWidgets.QMessageBox.information(
                self._window, "No SG Loaded", "Load an SG file before saving."
            )
            return

        default_path = str(self._current_path) if self._current_path else ""
        options = QtWidgets.QFileDialog.Options()
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self._window,
            "Save SG As",
            default_path,
            "SG files (*.sg *.SG);;All files (*)",
            options=options,
        )
        if not file_path:
            return

        path = Path(file_path)
        if path.suffix.lower() != ".sg":
            path = path.with_suffix(".sg")

        try:
            self._window.preview.save_sg(path)
        except Exception as exc:  # pragma: no cover - UI feedback only
            QtWidgets.QMessageBox.critical(
                self._window, "Failed to save SG", str(exc)
            )
            logger.exception("Failed to save SG file")
            return

        self._current_path = path
        self._window.statusBar().showMessage(f"Saved {path}")
        self._convert_sg_to_csv(path)

    def _convert_sg_to_csv(self, sg_path: Path) -> None:
        sg2csv_path = Path(__file__).resolve().parent.parent / "icr2_core" / "trk" / "sg2csv.py"

        try:
            result = subprocess.run(
                [sys.executable, str(sg2csv_path), str(sg_path)],
                cwd=sg2csv_path.parent,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:  # pragma: no cover - UI feedback only
            error_output = exc.stderr or exc.stdout or str(exc)
            QtWidgets.QMessageBox.warning(
                self._window,
                "CSV Export Failed",
                f"SG saved but CSV export failed:\n{error_output}",
            )
            logger.exception("Failed to convert SG to CSV")
            return

        if result.stdout:
            logger.info(result.stdout)
        self._window.statusBar().showMessage(
            f"Saved {sg_path} and exported CSVs next to it"
        )

    def _start_new_straight(self) -> None:
        self._window.delete_section_button.setChecked(False)
        if not self._window.preview.begin_new_straight():
            self._window.statusBar().showMessage(
                "Load an SG file before creating new straights."
            )
            self._on_new_straight_mode_changed(False)
            return

        self._window.statusBar().showMessage(
            "Click to place the start of the new straight."
        )

    def _start_new_curve(self) -> None:
        self._window.delete_section_button.setChecked(False)
        if not self._window.preview.begin_new_curve():
            self._window.statusBar().showMessage(
                "Load an SG file and click an unconnected node to start a curve."
            )
            self._on_new_curve_mode_changed(False)
            return

        self._window.statusBar().showMessage(
            "Click an unconnected node to start the new curve."
        )

    def _toggle_delete_section_mode(self, checked: bool) -> None:
        if checked:
            self._window.new_straight_button.setChecked(False)
            self._window.new_curve_button.setChecked(False)
            if not self._window.preview.begin_delete_section():
                self._window.delete_section_button.setChecked(False)
                return
            self._window.statusBar().showMessage("Click a section to delete it.")
        else:
            self._window.preview.cancel_delete_section()

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
