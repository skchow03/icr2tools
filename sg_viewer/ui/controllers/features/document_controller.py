from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

from PyQt5 import QtWidgets

from icr2_core.dat.unpackdat import extract_file_bytes, list_dat_entries
from icr2_core.trk.trk2sg import trk_to_sg
from icr2_core.trk.trk_classes import TRKFile
from sg_viewer.services.export_service import ExportResult, export_sg_to_csv, export_sg_to_trk


class DocumentControllerHost(Protocol):
    _window: QtWidgets.QMainWindow
    _current_path: Path | None
    _is_untitled: bool
    _save_action: QtWidgets.QAction
    _save_current_action: QtWidgets.QAction
    _xsect_table_action: QtWidgets.QAction
    _scale_track_action: QtWidgets.QAction
    _rotate_track_action: QtWidgets.QAction
    _reverse_track_action: QtWidgets.QAction
    _raise_lower_elevations_action: QtWidgets.QAction
    _flatten_all_elevations_and_grade_action: QtWidgets.QAction
    _generate_elevation_change_action: QtWidgets.QAction
    _delete_default_style: str
    _history: object

    def _clear_background_state(self) -> None: ...
    def _apply_saved_background(self, sg_path: Path | None = None) -> None: ...
    def _apply_saved_sunny_palette(self, sg_path: Path | None = None) -> None: ...
    def _refresh_recent_menu(self) -> None: ...
    def _update_section_table(self) -> None: ...
    def _update_heading_table(self) -> None: ...
    def _update_xsect_table(self) -> None: ...
    def _populate_xsect_choices(self, preferred_index: int | None = None) -> None: ...
    def _refresh_elevation_profile(self) -> None: ...
    def _reset_altitude_range_for_track(self) -> None: ...
    def _update_track_length_display(self) -> None: ...
    def _reset_altitude_range(self, min_altitude: float, max_altitude: float) -> None: ...
    def _persist_background_state(self) -> None: ...
    def _should_confirm_reset(self) -> bool: ...
    def _clear_loaded_tsd_files(self) -> None: ...
    def _load_mrk_state_for_current_track(self) -> None: ...
    def _persist_mrk_state_for_current_track(self) -> None: ...
    def confirm_mrk_safe_reset(self, action_label: str) -> bool: ...


class DocumentController:
    def __init__(self, host: DocumentControllerHost, logger: logging.Logger) -> None:
        self._host = host
        self._logger = logger
        self._export_csv_on_save = True

    def set_export_csv_on_save(self, enabled: bool) -> None:
        self._export_csv_on_save = enabled

    def load_sg(self, path: Path) -> None:
        path = path.resolve()
        if not self._host.confirm_mrk_safe_reset("Load Another Track"):
            return
        self._host._clear_background_state()
        self._host._clear_loaded_tsd_files()
        self._logger.info("Loading SG file %s", path)
        try:
            self._host._window.preview.load_sg_file(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self._host._window, "Failed to load SG", str(exc))
            self._logger.exception("Failed to load SG file")
            return

        warnings = self._host._window.preview.last_load_warnings()
        if warnings:
            display_warnings = warnings[:5]
            extra_count = max(0, len(warnings) - len(display_warnings))
            details = "\n".join(f"• {warning}" for warning in display_warnings)
            if extra_count:
                details = f"{details}\n• ...and {extra_count} more"
            QtWidgets.QMessageBox.warning(
                self._host._window,
                "SG loaded with warnings",
                "This SG file has disconnected or invalid section links. "
                "The track has been loaded, but some sections may be unlinked.\n\n"
                f"{details}",
            )

        self._host._window.show_status_message(f"Loaded {path}")
        self._host._current_path = path
        self._host._is_untitled = False
        self._host._history.record_open(path)
        self._host._elevation_controller.reset()

        self._host._window.update_window_title(path=path, is_dirty=False)
        self._host._window.set_table_actions_enabled(True)
        self._host._window.new_straight_button.setEnabled(True)
        self._host._window.new_curve_button.setEnabled(True)
        self._host._window.delete_section_button.setEnabled(True)
        self._host._window.preview.set_trk_comparison(None)
        sections, _ = self._host._window.preview.get_section_set()
        self._host._window.set_start_finish_button.setEnabled(bool(sections))
        self._host._window.split_section_button.setEnabled(bool(sections))
        self._host._window.split_section_button.setChecked(False)
        self._host._save_action.setEnabled(True)
        self._host._save_current_action.setEnabled(True)
        self._host._apply_saved_background(path)
        self._host._apply_saved_sunny_palette(path)
        self._host._refresh_recent_menu()
        self._host._update_section_table()
        self._host._update_heading_table()
        self._host._update_xsect_table()
        self._host._populate_xsect_choices()
        self._host._reset_altitude_range_for_track()
        self._host._refresh_elevation_profile()
        self._host._update_track_length_display()
        self._host._load_mrk_state_for_current_track()

    def import_trk_file_dialog(self) -> None:
        if not self._host.confirm_mrk_safe_reset("Load Another Track"):
            return
        options = QtWidgets.QFileDialog.Options()
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._host._window,
            "Import TRK file",
            "",
            "TRK files (*.trk *.TRK);;All files (*)",
            options=options,
        )
        if not file_path:
            return

        path = Path(file_path).resolve()
        try:
            trk = TRKFile.from_trk(str(path))
            self._import_trk_data(trk, path.name)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self._host._window,
                "Failed to import TRK",
                str(exc),
            )
            self._logger.exception("Failed to import TRK file")
            return

        self._host._window.show_status_message(f"Imported {path}")
        self._finalize_imported_trk_state()

    def _finalize_imported_trk_state(self) -> None:
        self._host._current_path = None
        self._host._is_untitled = True
        self._host._elevation_controller.reset()

        self._host._window.update_window_title(path=None, is_dirty=False, is_untitled=True)
        self._host._window.set_table_actions_enabled(True)
        self._host._window.new_straight_button.setEnabled(True)
        self._host._window.new_curve_button.setEnabled(True)
        self._host._window.delete_section_button.setEnabled(True)
        self._host._window.preview.set_trk_comparison(None)
        sections, _ = self._host._window.preview.get_section_set()
        self._host._window.set_start_finish_button.setEnabled(bool(sections))
        self._host._window.split_section_button.setEnabled(bool(sections))
        self._host._window.split_section_button.setChecked(False)
        self._host._save_action.setEnabled(True)
        self._host._save_current_action.setEnabled(False)
        self._host._clear_background_state()
        self._host._load_mrk_state_for_current_track()
        self._host._update_section_table()
        self._host._update_heading_table()
        self._host._update_xsect_table()
        self._host._populate_xsect_choices()
        self._host._reset_altitude_range_for_track()
        self._host._refresh_elevation_profile()
        self._host._update_track_length_display()

    def import_trk_from_dat_file_dialog(self) -> None:
        if not self._host.confirm_mrk_safe_reset("Load Another Track"):
            return
        options = QtWidgets.QFileDialog.Options()
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._host._window,
            "Import TRK from DAT file",
            "",
            "DAT files (*.dat *.DAT);;All files (*)",
            options=options,
        )
        if not file_path:
            return

        path = Path(file_path).resolve()
        expected_trk_name = f"{path.stem}.trk"
        try:
            trk_bytes = extract_file_bytes(str(path), expected_trk_name)
            trk_entry_name = expected_trk_name
        except FileNotFoundError:
            trk_entries = [
                name
                for name, _, _ in list_dat_entries(str(path))
                if name.lower().endswith(".trk")
            ]
            if not trk_entries:
                QtWidgets.QMessageBox.critical(
                    self._host._window,
                    "Failed to import TRK from DAT",
                    f"No TRK file found inside {path.name}.",
                )
                return
            trk_entry_name = trk_entries[0]
            trk_bytes = extract_file_bytes(str(path), trk_entry_name)

        try:
            trk = TRKFile.from_bytes(trk_bytes)
            self._import_trk_data(trk, trk_entry_name)
            self._finalize_imported_trk_state()
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self._host._window,
                "Failed to import TRK from DAT",
                str(exc),
            )
            self._logger.exception("Failed to import TRK from DAT file")

    def _import_trk_data(self, trk: TRKFile, source_name: str) -> None:
        sgfile = trk_to_sg(trk)
        sgfile.rebuild_dlongs(start_index=0, start_dlong=0)
        self._host._window.preview.load_sg_data(
            sgfile,
            status_message=f"Imported {source_name} as a new SG track",
        )

    def open_file_dialog(self) -> None:
        options = QtWidgets.QFileDialog.Options()
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._host._window,
            "Open SG file",
            "",
            "SG files (*.sg *.SG);;All files (*)",
            options=options,
        )
        if file_path:
            self.load_sg(Path(file_path))

    def start_new_track(self, *, confirm: bool = True) -> None:
        if confirm and not self._host.confirm_mrk_safe_reset("Start New Track"):
            return
        if confirm and self._host._should_confirm_reset():
            response = QtWidgets.QMessageBox.question(
                self._host._window,
                "Start New Track?",
                "Any unsaved changes will be lost. Continue?",
            )
            if response != QtWidgets.QMessageBox.Yes:
                return

        self._host._clear_background_state()
        self._host._clear_loaded_tsd_files()
        self._host._current_path = None
        self._host._window.preview.start_new_track()
        self._host._active_selection = None
        self._host._window.update_selection_sidebar(None)
        self._host._window.set_table_actions_enabled(False)
        self._host._xsect_table_action.setEnabled(True)
        self._host._window.delete_section_button.setEnabled(False)
        self._host._window.delete_section_button.setChecked(False)
        self._host._window.delete_section_button.setStyleSheet(self._host._delete_default_style)
        self._host._window.split_section_button.setChecked(False)
        self._host._window.split_section_button.setEnabled(False)
        self._host._window.set_start_finish_button.setEnabled(False)
        self._host._scale_track_action.setEnabled(False)
        self._host._rotate_track_action.setEnabled(False)
        self._host._reverse_track_action.setEnabled(False)
        self._host._raise_lower_elevations_action.setEnabled(False)
        self._host._flatten_all_elevations_and_grade_action.setEnabled(False)
        self._host._generate_elevation_change_action.setEnabled(False)
        self._host._update_xsect_table()
        self._host._populate_xsect_choices()
        self._host._refresh_elevation_profile()
        self._host._reset_altitude_range(0.0, 50.0)
        self._host._save_action.setEnabled(True)
        self._host._save_current_action.setEnabled(False)
        self._host._window.new_straight_button.setEnabled(True)
        self._host._window.new_curve_button.setEnabled(True)
        self._host._window.preview.set_trk_comparison(None)
        self._host._window.show_status_message("New track ready. Click New Straight to start drawing.")
        self._host._is_untitled = True
        self._host._window.update_window_title(path=None, is_dirty=False, is_untitled=True)
        self._host._update_track_length_display()
        self._host._load_mrk_state_for_current_track()

    def save_file_dialog(self) -> None:
        if self._host._window.preview.sgfile is None:
            QtWidgets.QMessageBox.information(self._host._window, "No SG Loaded", "Load an SG file before saving.")
            return
        default_path = str(self._host._current_path) if self._host._current_path else ""
        options = QtWidgets.QFileDialog.Options()
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self._host._window, "Save SG As", default_path, "SG files (*.sg *.SG);;All files (*)", options=options
        )
        if not file_path:
            return
        path = Path(file_path)
        if path.suffix.lower() != ".sg":
            path = path.with_suffix(".sg")
        self.save_to_path(path)

    def save_current_file(self) -> None:
        if self._host._current_path is None:
            self.save_file_dialog()
            return
        self.save_to_path(self._host._current_path)

    def save_to_path(self, path: Path) -> None:
        try:
            self._host._window.preview.save_sg(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self._host._window, "Failed to save SG", str(exc))
            self._logger.exception("Failed to save SG file")
            return
        self._host._current_path = path
        self._host._window.show_status_message(f"Saved {path}")
        self._host._history.record_save(path)
        self._host._refresh_recent_menu()
        self._host._persist_background_state()
        self._host._persist_mrk_state_for_current_track()
        if self._export_csv_on_save:
            self.convert_sg_to_csv(path)
        self._host._save_current_action.setEnabled(True)
        self._host._window.update_window_title(path=self._host._current_path, is_dirty=False)

    def ensure_saved_sg(self) -> Path | None:
        if self._host._window.preview.sgfile is None:
            QtWidgets.QMessageBox.information(self._host._window, "No SG Loaded", "Load an SG file before exporting.")
            return None
        if self._host._current_path is None or self._host._window.preview.has_unsaved_changes:
            QtWidgets.QMessageBox.information(self._host._window, "Save Required", "Save the SG file before converting to TRK.")
            self.save_file_dialog()
        if self._host._current_path is None or self._host._window.preview.has_unsaved_changes:
            return None
        return self._host._current_path

    def convert_sg_to_csv(self, sg_path: Path) -> None:
        result = export_sg_to_csv(sg_path=sg_path)
        self._handle_export_result(
            result,
            title="CSV Export Failed",
            error_log="Failed to convert SG to CSV",
        )

    def convert_sg_to_trk(self) -> None:
        sg_path = self.ensure_saved_sg()
        if sg_path is None:
            return
        try:
            self._host._window.preview.enable_trk_overlay()
        except Exception as exc:
            self._logger.exception("Failed to build TRK overlay", exc_info=exc)
        default_output = sg_path.with_suffix('.trk')
        options = QtWidgets.QFileDialog.Options()
        output_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self._host._window, "Save TRK As", str(default_output), "TRK files (*.trk *.TRK);;All files (*)", options=options
        )
        if not output_path:
            return
        trk_path = Path(output_path)
        if trk_path.suffix.lower() != '.trk':
            trk_path = trk_path.with_suffix('.trk')
        result = export_sg_to_trk(sg_path=sg_path, trk_path=trk_path)
        self._handle_export_result(
            result,
            title="TRK Export Failed",
            error_log="Failed to convert SG to TRK",
        )

    def _handle_export_result(self, result: ExportResult, *, title: str, error_log: str) -> None:
        if result.stdout:
            self._logger.info(result.stdout)
        if result.stderr:
            self._logger.warning(result.stderr)

        if result.success:
            self._host._window.show_status_message(result.message)
            return

        QtWidgets.QMessageBox.warning(self._host._window, title, result.message)
        self._logger.error(error_log)
