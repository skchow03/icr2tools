from __future__ import annotations

import logging
import math
import subprocess
import sys
from pathlib import Path

from PyQt5 import QtWidgets

from sg_viewer.geometry.topology import is_closed_loop, loop_length
from sg_viewer.models.history import FileHistory
from sg_viewer.models.sg_model import SectionPreview
from sg_viewer.ui.background_image_dialog import BackgroundImageDialog
from sg_viewer.ui.heading_table_dialog import HeadingTableWindow
from sg_viewer.ui.scale_track_dialog import ScaleTrackDialog
from sg_viewer.ui.section_table_dialog import SectionTableWindow

logger = logging.getLogger(__name__)


class SGViewerController:
    """Coordinates actions, menus, and dialogs for the SG viewer window."""

    def __init__(self, window: QtWidgets.QMainWindow) -> None:
        self._window = window
        self._section_table_window: SectionTableWindow | None = None
        self._heading_table_window: HeadingTableWindow | None = None
        self._current_path: Path | None = None
        self._history = FileHistory()
        self._new_straight_default_style = window.new_straight_button.styleSheet()
        self._new_curve_default_style = window.new_curve_button.styleSheet()
        self._delete_default_style = window.delete_section_button.styleSheet()
        self._split_default_style = window.split_section_button.styleSheet()
        self._is_untitled = False


        self._create_actions()
        self._create_menus()
        self._connect_signals()
        self._window.preview.sectionsChanged.connect(self._on_sections_changed)
        self._refresh_recent_menu()
        self._start_new_track(confirm=False)
        self._window.show_status_message(
            "Click New Straight to begin drawing or File → Open SG."
        )
        self._update_track_length_display()

    def load_sg(self, path: Path) -> None:
        path = path.resolve()
        self._clear_background_state()
        try:
            self._window.preview.load_sg_file(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self._window, "Failed to load SG", str(exc))
            logger.exception("Failed to load SG file")
            return

        self._window.show_status_message(f"Loaded {path}")
        self._current_path = path
        self._is_untitled = False
        self._history.record_open(path)

        self._window.update_window_title(
            path=path,
            is_dirty=False,
        )

        self._window.section_table_button.setEnabled(True)
        self._window.heading_table_button.setEnabled(True)
        self._window.refresh_fsects_button.setEnabled(True)
        self._window.new_straight_button.setEnabled(True)
        self._window.new_curve_button.setEnabled(True)
        self._window.delete_section_button.setEnabled(True)
        self._window.preview.set_trk_comparison(None)
        self._window.trk_compare_checkbox.blockSignals(True)
        self._window.trk_compare_checkbox.setChecked(False)
        self._window.trk_compare_checkbox.setEnabled(True)
        self._window.trk_compare_checkbox.blockSignals(False)
        sections, _ = self._window.preview.get_section_set()
        self._window.set_start_finish_button.setEnabled(bool(sections))
        self._window.split_section_button.setEnabled(bool(sections))
        self._window.split_section_button.setChecked(False)
        self._save_action.setEnabled(True)
        self._apply_saved_background(path)
        self._refresh_recent_menu()
        self._update_section_table()
        self._update_heading_table()
        self._populate_xsect_choices()
        self._refresh_elevation_profile()
        self._update_track_length_display()


    def _create_actions(self) -> None:
        self._new_action = QtWidgets.QAction("New", self._window)
        self._new_action.setShortcut("Ctrl+N")
        self._new_action.triggered.connect(self._start_new_track)


        self._open_action = QtWidgets.QAction("Open SG…", self._window)
        self._open_action.setShortcut("Ctrl+O")
        self._open_action.triggered.connect(self._open_file_dialog)

        self._open_recent_menu = QtWidgets.QMenu("Open Recent", self._window)

        self._save_action = QtWidgets.QAction("Save SG As…", self._window)
        self._save_action.setShortcut("Ctrl+Shift+S")
        self._save_action.setEnabled(True)
        self._save_action.triggered.connect(self._save_file_dialog)

        self._recalc_action = QtWidgets.QAction(
            "Recalculate Lengths && DLONGs",
            self._window,
        )
        self._recalc_action.triggered.connect(self._recalculate_dlongs)

        self._scale_track_action = QtWidgets.QAction(
            "Scale Track to Length…",
            self._window,
        )
        self._scale_track_action.setEnabled(False)
        self._scale_track_action.triggered.connect(self._scale_track)

        self._convert_trk_action = QtWidgets.QAction(
            "Convert SG to TRK…",
            self._window,
        )
        self._convert_trk_action.triggered.connect(self._convert_sg_to_trk)

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

        # self._calibrate_background_action = QtWidgets.QAction(
        #     "Open Background Calibrator", self._window
        # )
        # self._calibrate_background_action.triggered.connect(
        #     self._launch_background_calibrator
        # )

        self._quit_action = QtWidgets.QAction("Quit", self._window)
        self._quit_action.setShortcut("Ctrl+Q")
        self._quit_action.triggered.connect(self._window.close)

    def _create_menus(self) -> None:
        file_menu = self._window.menuBar().addMenu("&File")
        file_menu.addAction(self._new_action)
        file_menu.addSeparator()
        file_menu.addAction(self._open_action)
        file_menu.addMenu(self._open_recent_menu)
        file_menu.addAction(self._save_action)
        file_menu.addAction(self._open_background_action)
        file_menu.addAction(self._background_settings_action)
#        file_menu.addAction(self._calibrate_background_action)
        file_menu.addSeparator()
        file_menu.addAction(self._quit_action)

        tools_menu = self._window.menuBar().addMenu("Tools")
        tools_menu.addAction(self._recalc_action)
        tools_menu.addAction(self._scale_track_action)
        tools_menu.addAction(self._convert_trk_action)

    def _connect_signals(self) -> None:
        self._window.preview.selectedSectionChanged.connect(
            self._window.update_selection_sidebar
        )
        self._window.preview.sectionsChanged.connect(self._on_sections_changed)
        self._window.prev_button.clicked.connect(self._window.preview.select_previous_section)
        self._window.next_button.clicked.connect(self._window.preview.select_next_section)
        #self._window.new_track_button.clicked.connect(self._start_new_track)
        self._window.new_straight_button.clicked.connect(self._start_new_straight)
        self._window.new_curve_button.clicked.connect(self._start_new_curve)
        self._window.set_start_finish_button.clicked.connect(
            self._window.preview.activate_set_start_finish_mode
        )
        self._window.preview.newStraightModeChanged.connect(
            self._on_new_straight_mode_changed
        )
        self._window.preview.newCurveModeChanged.connect(self._on_new_curve_mode_changed)
        self._window.delete_section_button.toggled.connect(
            self._toggle_delete_section_mode
        )
        self._window.split_section_button.toggled.connect(
            self._toggle_split_section_mode
        )
        self._window.preview.deleteModeChanged.connect(self._on_delete_mode_changed)
        self._window.preview.splitSectionModeChanged.connect(self._on_split_mode_changed)
        self._window.radii_button.toggled.connect(self._window.preview.set_show_curve_markers)
        self._window.axes_button.toggled.connect(self._window.preview.set_show_axes)
        self._window.sg_fsects_checkbox.toggled.connect(
            self._window.preview.set_show_sg_fsects
        )
        self._window.refresh_fsects_button.clicked.connect(
            self._refresh_fsects_preview
        )
        self._window.section_table_button.clicked.connect(self._show_section_table)
        self._window.heading_table_button.clicked.connect(self._show_heading_table)
        self._window.xsect_combo.currentIndexChanged.connect(
            self._refresh_elevation_profile
        )
        self._window.trk_compare_checkbox.toggled.connect(
            self._toggle_trk_comparison
        )
        self._window.preview.scaleChanged.connect(self._on_scale_changed)

    def _should_confirm_reset(self) -> bool:
        sections, _ = self._window.preview.get_section_set()
        return self._window.preview.has_unsaved_changes or bool(sections)

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

    def _on_split_mode_changed(self, active: bool) -> None:
        button = self._window.split_section_button
        button.setChecked(active)
        if active:
            button.setStyleSheet("background-color: #3fb5b5; color: white;")
        else:
            button.setStyleSheet(self._split_default_style)

    def _on_scale_changed(self, scale: float) -> None:
        self._window.update_scale_label(scale)

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
        self._window.show_status_message(f"Loaded background image {file_path}")
        self._persist_background_state()

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
            self._window.show_status_message("Updated background image settings")
            self._persist_background_state()

    # def _launch_background_calibrator(self) -> None:
    #     calibrator_path = Path(__file__).with_name("bg_calibrator_minimal.py")
    #     if not calibrator_path.exists():
    #         QtWidgets.QMessageBox.critical(
    #             self._window,
    #             "Calibrator Not Found",
    #             f"{calibrator_path} could not be located.",
    #         )
    #         logger.error("Background calibrator script missing at %s", calibrator_path)
    #         return

    #     try:
    #         subprocess.Popen([sys.executable, str(calibrator_path)])
    #     except FileNotFoundError:
    #         QtWidgets.QMessageBox.critical(
    #             self._window,
    #             "Calibrator Not Found",
    #             f"{calibrator_path} could not be located.",
    #         )
    #         logger.exception("Failed to launch background calibrator")
    #         return

    #     self._window.show_status_message(
    #         "Opened background calibrator in a separate window"
    #     )

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

    def _start_new_track(self, *, confirm: bool = True) -> None:
        if confirm and self._should_confirm_reset():
            response = QtWidgets.QMessageBox.question(
                self._window,
                "Start New Track?",
                "Any unsaved changes will be lost. Continue?",
            )
            if response != QtWidgets.QMessageBox.Yes:
                return

        self._clear_background_state()
        self._current_path = None
        self._window.preview.start_new_track()
        self._window.update_selection_sidebar(None)
        self._window.section_table_button.setEnabled(False)
        self._window.heading_table_button.setEnabled(False)
        self._window.refresh_fsects_button.setEnabled(False)
        self._window.delete_section_button.setEnabled(False)
        self._window.split_section_button.setChecked(False)
        self._window.split_section_button.setEnabled(False)
        self._window.set_start_finish_button.setEnabled(False)
        self._scale_track_action.setEnabled(False)
        self._populate_xsect_choices()
        self._refresh_elevation_profile()
        self._save_action.setEnabled(True)
        self._window.new_straight_button.setEnabled(True)
        self._window.new_curve_button.setEnabled(True)
        self._window.preview.set_trk_comparison(None)
        self._window.trk_compare_checkbox.blockSignals(True)
        self._window.trk_compare_checkbox.setChecked(False)
        self._window.trk_compare_checkbox.setEnabled(False)
        self._window.trk_compare_checkbox.blockSignals(False)
        self._window.show_status_message(
            "New track ready. Click New Straight to start drawing."
        )
        self._is_untitled = True
        self._window.update_window_title(
            path=None,
            is_dirty=False,
            is_untitled=True,
        )
        self._update_track_length_display()



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
        self._window.show_status_message(f"Saved {path}")
        self._history.record_save(path)
        self._refresh_recent_menu()
        self._persist_background_state()
        self._convert_sg_to_csv(path)

        self._window.update_window_title(
            path=self._current_path,
            is_dirty=False,
        )

    def _recalculate_dlongs(self) -> None:
        preview = self._window.preview
        if not preview.recalculate_dlongs():
            return

        self._window.show_status_message(
            "Recalculated all curve lengths and DLONGs"
        )

    def _refresh_fsects_preview(self) -> None:
        if self._window.preview.refresh_fsections_preview():
            self._window.show_status_message(
                "Refreshed Fsects preview from current geometry."
            )
            return

        self._window.show_status_message(
            "Load an SG file with sections before refreshing Fsects preview."
        )


    def _convert_sg_to_csv(self, sg_path: Path) -> None:
        sg2csv_path = (
            Path(__file__).resolve().parents[2] / "icr2_core" / "trk" / "sg2csv.py"
        )

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
        self._window.show_status_message(
            f"Saved {sg_path} and exported CSVs next to it"
        )

    def _convert_sg_to_trk(self) -> None:
        sg_path = self._ensure_saved_sg()
        if sg_path is None:
            return
        try:
            self._window.preview.enable_trk_overlay()
        except Exception as exc:
            logger.exception("Failed to build TRK overlay", exc_info=exc)

        default_output = sg_path.with_suffix(".trk")
        options = QtWidgets.QFileDialog.Options()
        output_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self._window,
            "Save TRK As",
            str(default_output),
            "TRK files (*.trk *.TRK);;All files (*)",
            options=options,
        )
        if not output_path:
            return

        trk_path = Path(output_path)
        if trk_path.suffix.lower() != ".trk":
            trk_path = trk_path.with_suffix(".trk")

        sg2trk_path = (
            Path(__file__).resolve().parents[2] / "icr2_core" / "trk" / "sg2trk.py"
        )

        try:
            subprocess.run(
                [
                    sys.executable,
                    str(sg2trk_path),
                    str(sg_path),
                    "--format",
                    "trk",
                    "--output",
                    str(trk_path.with_suffix("")),
                ],
                cwd=sg2trk_path.parent,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:  # pragma: no cover - UI feedback only
            error_output = exc.stderr or exc.stdout or str(exc)
            QtWidgets.QMessageBox.warning(
                self._window,
                "TRK Export Failed",
                f"SG saved but TRK export failed:\n{error_output}",
            )
            logger.exception("Failed to convert SG to TRK")
            return

        if trk_path.exists():
            self._window.show_status_message(f"Saved TRK to {trk_path}")
        else:
            self._window.show_status_message("TRK export completed.")

    def _ensure_saved_sg(self) -> Path | None:
        if self._window.preview.sgfile is None:
            QtWidgets.QMessageBox.information(
                self._window, "No SG Loaded", "Load an SG file before exporting."
            )
            return None

        if self._current_path is None or self._window.preview.has_unsaved_changes:
            QtWidgets.QMessageBox.information(
                self._window,
                "Save Required",
                "Save the SG file before converting to TRK.",
            )
            self._save_file_dialog()

        if self._current_path is None or self._window.preview.has_unsaved_changes:
            return None

        return self._current_path

    def _start_new_straight(self) -> None:
        self._window.delete_section_button.setChecked(False)
        self._window.split_section_button.setChecked(False)
        if not self._window.preview.begin_new_straight():
            self._window.show_status_message(
                "Start a new track or load an SG file before creating new straights."
            )
            self._on_new_straight_mode_changed(False)
            return

        self._window.show_status_message(
            "Click to place the start of the new straight."
        )

    def _start_new_curve(self) -> None:
        self._window.delete_section_button.setChecked(False)
        self._window.split_section_button.setChecked(False)
        if not self._window.preview.begin_new_curve():
            self._window.show_status_message(
                "Create a track with an unconnected node before adding a curve."
            )
            self._on_new_curve_mode_changed(False)
            return

        self._window.show_status_message(
            "Click an unconnected node to start the new curve."
        )

    def _toggle_delete_section_mode(self, checked: bool) -> None:
        if checked:
            self._window.new_straight_button.setChecked(False)
            self._window.new_curve_button.setChecked(False)
            self._window.split_section_button.setChecked(False)
            if not self._window.preview.begin_delete_section():
                self._window.delete_section_button.setChecked(False)
                return
            self._window.show_status_message("Click a section to delete it.")
        else:
            self._window.preview.cancel_delete_section()

    def _toggle_split_section_mode(self, checked: bool) -> None:
        if checked:
            self._window.delete_section_button.setChecked(False)
            self._window.new_straight_button.setChecked(False)
            self._window.new_curve_button.setChecked(False)
            if not self._window.preview.begin_split_section():
                self._window.split_section_button.setChecked(False)
                return
            self._window.show_status_message(
                "Hover over a section to choose where to split it."
            )
        else:
            self._window.preview.cancel_split_section()

    def _refresh_recent_menu(self) -> None:
        self._open_recent_menu.clear()
        recent_paths = self._history.get_recent_paths()
        if not recent_paths:
            empty_action = QtWidgets.QAction("No recent files", self._open_recent_menu)
            empty_action.setEnabled(False)
            self._open_recent_menu.addAction(empty_action)
            return

        for path in recent_paths:
            action = QtWidgets.QAction(str(path), self._open_recent_menu)
            action.triggered.connect(lambda checked=False, p=path: self.load_sg(p))
            self._open_recent_menu.addAction(action)

    def _on_sections_changed(self) -> None:
        sections, _ = self._window.preview.get_section_set()
        has_sections = bool(sections)

        self._window.delete_section_button.setEnabled(has_sections)
        self._window.split_section_button.setEnabled(has_sections)
        if not has_sections:
            self._window.split_section_button.setChecked(False)
        self._window.set_start_finish_button.setEnabled(has_sections)
        self._window.section_table_button.setEnabled(has_sections)
        self._window.heading_table_button.setEnabled(has_sections)
        self._window.refresh_fsects_button.setEnabled(
            has_sections and self._window.preview.sgfile is not None
        )
        self._scale_track_action.setEnabled(
            has_sections and is_closed_loop(sections)
        )

        # Save is allowed once anything exists or changes
        self._save_action.setEnabled(True)

        # Mark document dirty
        if self._is_untitled:
            self._window.update_window_title(
                path=None,
                is_dirty=True,
                is_untitled=True,
            )
        elif self._current_path is not None:
            self._window.update_window_title(
                path=self._current_path,
                is_dirty=True,
            )

        self._refresh_elevation_profile()
        self._update_track_length_display()

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

    def _scale_track(self) -> None:
        sections, _ = self._window.preview.get_section_set()
        if not sections or not is_closed_loop(sections):
            QtWidgets.QMessageBox.information(
                self._window,
                "Scale Track",
                "Scaling is only available when the track forms a closed loop.",
            )
            return

        try:
            current_length = loop_length(sections)
        except ValueError:
            QtWidgets.QMessageBox.information(
                self._window,
                "Scale Track",
                "Scaling is only available when the track forms a closed loop.",
            )
            return

        dialog = ScaleTrackDialog(self._window, current_length)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return

        target_length = dialog.get_target_length()
        if target_length <= 0:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Scale Track",
                "Desired track length must be greater than zero.",
            )
            return

        if math.isclose(target_length, current_length, rel_tol=1e-6):
            self._window.show_status_message("Track already at desired length.")
            return

        status = self._window.preview.scale_track_to_length(target_length)
        if not status:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Scale Track",
                "Scaling could not be applied. Ensure the track is a valid closed loop.",
            )
            return

        self._window.show_status_message(status)
        self._update_track_length_display()

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

        profile = self._window.preview.build_elevation_profile(
            int(current_index),
            show_trk=self._window.trk_compare_checkbox.isChecked(),
        )
        self._window.profile_widget.set_profile_data(profile)

    def _toggle_trk_comparison(self, checked: bool) -> None:
        if not checked:
            self._window.preview.set_trk_comparison(None)
            self._refresh_elevation_profile()
            return

        try:
            trk = self._window.preview.enable_trk_overlay()
        except Exception as exc:
            logger.exception("Failed to build TRK comparison", exc_info=exc)
            self._window.trk_compare_checkbox.setChecked(False)
            self._window.show_status_message("Failed to build TRK comparison.")
            return
        if trk is None:
            self._window.trk_compare_checkbox.setChecked(False)
            self._window.show_status_message("Save or open an SG file to compare TRK elevation.")
            return

        self._window.preview.set_trk_comparison(trk)
        self._refresh_elevation_profile()

    def _clear_background_state(self) -> None:
        self._window.preview.clear_background_image()
        self._background_settings_action.setEnabled(False)
#        self._calibrate_background_action.setEnabled(False)

    def _apply_saved_background(self, sg_path: Path | None = None) -> None:
        path = sg_path or self._current_path
        if path is None:
            return

        background_data = self._history.get_background(path)
        if not background_data:
            return

        image_path, scale, origin = background_data
        if not image_path.exists():
            logger.info("Stored background image %s is missing", image_path)
            return

        try:
            self._window.preview.load_background_image(image_path)
            self._window.preview.set_background_settings(scale, origin)
        except Exception as exc:  # pragma: no cover - UI feedback only
            logger.exception("Failed to restore background image", exc_info=exc)
            self._window.show_status_message(
                f"Could not restore background image {image_path}"
            )
            return

        self._background_settings_action.setEnabled(True)
#        self._calibrate_background_action.setEnabled(True)
        self._window.show_status_message(
            f"Restored background image {image_path} for {path.name}"
        )

    def _persist_background_state(self) -> None:
        if self._current_path is None:
            return

        background_path = self._window.preview.get_background_image_path()
        if background_path is None:
            return

        scale, origin = self._window.preview.get_background_settings()
        self._history.set_background(self._current_path, background_path, scale, origin)

    def _update_track_length_display(self) -> None:
        text = self._window.preview.track_length_message()
        self._window.update_track_length_label(text)
