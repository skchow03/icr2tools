from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Protocol

from PyQt5 import QtWidgets

from icr2_core.dat.unpackdat import extract_file_bytes, list_dat_entries
from icr2_core.trk.sg_classes import SGFile
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
    def _load_tsd_state_for_current_track(self) -> None: ...
    def _persist_tsd_state_for_current_track(self) -> None: ...
    def _load_mrk_wall_heights_for_current_track(self) -> None: ...
    def _persist_mrk_wall_heights_for_current_track(self) -> None: ...
    def confirm_discard_unsaved_for_action(self, action_label: str) -> bool: ...
    def _mark_elevation_grade_dirty(self, dirty: bool) -> None: ...
    def _mark_fsects_dirty(self, dirty: bool) -> None: ...
    def _settings_path_for(self, sg_path: Path) -> Path: ...


class DocumentController:
    PROJECT_SG_DATA_VERSION = 1

    def __init__(self, host: DocumentControllerHost, logger: logging.Logger) -> None:
        self._host = host
        self._logger = logger
        self._export_csv_on_save = True

    def set_export_csv_on_save(self, enabled: bool) -> None:
        self._export_csv_on_save = enabled

    def load_sg(self, path: Path) -> None:
        self._load_sg(path, attach_path=True)

    def import_sg(self, path: Path) -> None:
        self._load_sg(path, attach_path=False)

    def _load_sg(self, path: Path, *, attach_path: bool) -> None:
        path = path.resolve()
        if not self._host.confirm_discard_unsaved_for_action("Load Another Track"):
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

        if attach_path:
            self._host._window.show_status_message(f"Loaded {path}")
            self._host._current_path = path
            self._host._is_untitled = False
            self._host._history.record_open(path)
        else:
            self._host._window.show_status_message(f"Imported {path} into project")
            self._host._current_path = None
            self._host._is_untitled = True
        self._host._elevation_controller.reset()

        self._host._window.update_window_title(
            path=self._host._current_path,
            is_dirty=False,
            is_untitled=self._host._is_untitled,
        )
        self._host._mark_elevation_grade_dirty(False)
        self._host._mark_fsects_dirty(False)
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
        self._host._save_current_action.setEnabled(attach_path)
        self._host._apply_saved_background(path if attach_path else None)
        self._host._apply_saved_sunny_palette(path if attach_path else None)
        self._host._refresh_recent_menu()
        self._host._update_section_table()
        self._host._update_heading_table()
        self._host._update_xsect_table()
        self._host._populate_xsect_choices()
        self._host._reset_altitude_range_for_track()
        self._host._refresh_elevation_profile()
        self._host._update_track_length_display()
        self._host._load_mrk_wall_heights_for_current_track()
        self._host._load_mrk_state_for_current_track()
        self._host._load_tsd_state_for_current_track()

    def import_trk_file_dialog(self) -> None:
        if not self._host.confirm_discard_unsaved_for_action("Load Another Track"):
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
        self._host._load_mrk_wall_heights_for_current_track()
        self._host._load_mrk_state_for_current_track()
        self._host._load_tsd_state_for_current_track()
        self._host._update_section_table()
        self._host._update_heading_table()
        self._host._update_xsect_table()
        self._host._populate_xsect_choices()
        self._host._reset_altitude_range_for_track()
        self._host._refresh_elevation_profile()
        self._host._update_track_length_display()

    def import_trk_from_dat_file_dialog(self) -> None:
        if not self._host.confirm_discard_unsaved_for_action("Load Another Track"):
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

    def import_sg_file_dialog(self) -> None:
        options = QtWidgets.QFileDialog.Options()
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._host._window,
            "Import SG file",
            "",
            "SG files (*.sg *.SG);;All files (*)",
            options=options,
        )
        if file_path:
            self.import_sg(Path(file_path))

    def open_project_file_dialog(self) -> None:
        options = QtWidgets.QFileDialog.Options()
        project_path_str, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._host._window,
            "Open Project file",
            "",
            "SG Project files (*.sgc *.SGC);;All files (*)",
            options=options,
        )
        if not project_path_str:
            return
        project_path = Path(project_path_str).resolve()
        try:
            payload = json.loads(project_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Project file must contain a JSON object.")
            raw_sg_file = payload.get("sg_file")
            if raw_sg_file is not None and (not isinstance(raw_sg_file, str) or not raw_sg_file.strip()):
                raise ValueError("Project 'sg_file' path must be a non-empty string when provided.")
            if isinstance(raw_sg_file, str):
                sg_path = Path(raw_sg_file)
                if not sg_path.is_absolute():
                    sg_path = (project_path.parent / sg_path).resolve()
                else:
                    sg_path = sg_path.resolve()
            else:
                sg_path = project_path.with_suffix(".sg")

            if not sg_path.exists():
                raise ValueError(f"Referenced SG file does not exist: {sg_path}")

            embedded_sg = payload.get("sg_data")
            if raw_sg_file is None:
                if embedded_sg is not None:
                    self._load_project_embedded_sg(project_path, sg_path, embedded_sg)
                    return
                raise ValueError("Project file must include either 'sg_data' or an 'sg_file' path.")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            QtWidgets.QMessageBox.critical(self._host._window, "Failed to open project", str(exc))
            self._logger.exception("Failed to open project file")
            return
        self.load_sg(sg_path)

    def save_project_file_dialog(self) -> None:
        if self._host._window.preview.sgfile is None:
            QtWidgets.QMessageBox.information(self._host._window, "No SG Loaded", "Load an SG file before saving.")
            return
        default_path = ""
        if self._host._current_path is not None:
            default_path = str(self._host._settings_path_for(self._host._current_path))
        options = QtWidgets.QFileDialog.Options()
        project_path_str, _ = QtWidgets.QFileDialog.getSaveFileName(
            self._host._window,
            "Save Project As",
            default_path,
            "SG Project files (*.sgc *.SGC);;All files (*)",
            options=options,
        )
        if not project_path_str:
            return

        project_path = Path(project_path_str)
        if project_path.suffix.lower() != ".sgc":
            project_path = project_path.with_suffix(".sgc")

        sg_path = project_path.with_suffix(".sg")
        self.save_to_path(sg_path)

    def start_new_track(self, *, confirm: bool = True) -> None:
        if confirm and not self._host.confirm_discard_unsaved_for_action("Start New Track"):
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
        self._host._mark_elevation_grade_dirty(False)
        self._host._mark_fsects_dirty(False)
        self._host._update_track_length_display()
        self._host._load_mrk_wall_heights_for_current_track()
        self._host._load_mrk_state_for_current_track()
        self._host._load_tsd_state_for_current_track()

    def save_file_dialog(self) -> None:
        if self._host._window.preview.sgfile is None:
            QtWidgets.QMessageBox.information(self._host._window, "No SG Loaded", "Load an SG file before saving.")
            return
        default_path = str(self._host._current_path) if self._host._current_path else ""
        options = QtWidgets.QFileDialog.Options()
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self._host._window, "Export to SG file", default_path, "SG files (*.sg *.SG);;All files (*)", options=options
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
        self._host._window.show_status_message(f"Saved {path} and project {self._host._settings_path_for(path)}")
        self._host._history.record_save(path)
        self._host._refresh_recent_menu()
        self._host._persist_background_state()
        self._host._persist_mrk_state_for_current_track()
        self._host._persist_mrk_wall_heights_for_current_track()
        self._host._persist_tsd_state_for_current_track()
        self._persist_project_sg_reference(path)
        self._host._save_current_action.setEnabled(True)
        self._host._window.update_window_title(path=self._host._current_path, is_dirty=False)
        self._host._mark_elevation_grade_dirty(False)
        self._host._mark_fsects_dirty(False)

    def _load_project_embedded_sg(self, project_path: Path, sg_path: Path, embedded_sg: object) -> None:
        if not self._host.confirm_discard_unsaved_for_action("Load Another Track"):
            return
        self._host._clear_background_state()
        self._host._clear_loaded_tsd_files()

        sgfile = self._deserialize_sg_data_payload(embedded_sg)
        self._host._window.preview.load_sg_data(
            sgfile,
            status_message=f"Loaded {project_path.name}",
        )

        self._host._window.show_status_message(f"Loaded project {project_path}")
        self._host._current_path = sg_path
        self._host._is_untitled = False
        self._host._history.record_open(project_path)
        self._host._elevation_controller.reset()

        self._host._window.update_window_title(path=sg_path, is_dirty=False)
        self._host._mark_elevation_grade_dirty(False)
        self._host._mark_fsects_dirty(False)
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
        self._host._apply_saved_background(sg_path)
        self._host._apply_saved_sunny_palette(sg_path)
        self._host._refresh_recent_menu()
        self._host._update_section_table()
        self._host._update_heading_table()
        self._host._update_xsect_table()
        self._host._populate_xsect_choices()
        self._host._reset_altitude_range_for_track()
        self._host._refresh_elevation_profile()
        self._host._update_track_length_display()
        self._host._load_mrk_wall_heights_for_current_track()
        self._host._load_mrk_state_for_current_track()
        self._host._load_tsd_state_for_current_track()

    def _persist_project_sg_reference(self, sg_path: Path) -> None:
        settings_path = self._host._settings_path_for(sg_path)
        payload: dict[str, object] = {}
        if settings_path.exists():
            try:
                loaded_payload = json.loads(settings_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                loaded_payload = {}
            if isinstance(loaded_payload, dict):
                payload = loaded_payload

        payload["sg_file"] = sg_path.name
        payload.pop("sg_data", None)
        settings_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    def _serialize_sg_data_payload(self, sgfile: SGFile) -> dict[str, object]:
        sections: list[dict[str, object]] = []
        for section in sgfile.sects:
            num_fsects = int(getattr(section, "num_fsects", 0))
            sections.append(
                {
                    "type": int(section.type),
                    "sec_next": int(section.sec_next),
                    "sec_prev": int(section.sec_prev),
                    "start_x": int(section.start_x),
                    "start_y": int(section.start_y),
                    "end_x": int(section.end_x),
                    "end_y": int(section.end_y),
                    "start_dlong": int(section.start_dlong),
                    "length": int(section.length),
                    "center_x": int(section.center_x),
                    "center_y": int(section.center_y),
                    "sang1": int(section.sang1),
                    "sang2": int(section.sang2),
                    "eang1": int(section.eang1),
                    "eang2": int(section.eang2),
                    "radius": int(section.radius),
                    "num1": int(section.num1),
                    "alt": [int(value) for value in list(section.alt)],
                    "grade": [int(value) for value in list(section.grade)],
                    "num_fsects": num_fsects,
                    "ftype1": [int(value) for value in list(section.ftype1)[:num_fsects]],
                    "ftype2": [int(value) for value in list(section.ftype2)[:num_fsects]],
                    "fstart": [int(value) for value in list(section.fstart)[:num_fsects]],
                    "fend": [int(value) for value in list(section.fend)[:num_fsects]],
                }
            )

        return {
            "version": self.PROJECT_SG_DATA_VERSION,
            "header": [int(value) for value in list(sgfile.header)],
            "num_sects": int(sgfile.num_sects),
            "num_xsects": int(sgfile.num_xsects),
            "xsect_dlats": [int(value) for value in list(sgfile.xsect_dlats)],
            "sections": sections,
        }

    def _deserialize_sg_data_payload(self, payload: object) -> SGFile:
        if not isinstance(payload, dict):
            raise ValueError("Project 'sg_data' must be an object.")
        version = payload.get("version")
        if version != self.PROJECT_SG_DATA_VERSION:
            raise ValueError(f"Unsupported project SG data version: {version!r}")

        num_xsects = int(payload.get("num_xsects", 0))
        if num_xsects < 0:
            raise ValueError("Project 'num_xsects' must be >= 0.")

        header = [int(value) for value in list(payload.get("header", []))]
        while len(header) < 6:
            header.append(0)
        header = header[:6]
        header[5] = num_xsects

        xsect_dlats = [int(value) for value in list(payload.get("xsect_dlats", []))]
        if len(xsect_dlats) != num_xsects:
            raise ValueError("Project 'xsect_dlats' length must equal 'num_xsects'.")

        raw_sections = payload.get("sections")
        if not isinstance(raw_sections, list):
            raise ValueError("Project 'sections' must be an array.")

        sections: list[SGFile.Section] = []
        for raw_section in raw_sections:
            if not isinstance(raw_section, dict):
                raise ValueError("Each project section must be an object.")

            section_data = [0] * (58 + 2 * num_xsects)
            ordered_fields = (
                "type",
                "sec_next",
                "sec_prev",
                "start_x",
                "start_y",
                "end_x",
                "end_y",
                "start_dlong",
                "length",
                "center_x",
                "center_y",
                "sang1",
                "sang2",
                "eang1",
                "eang2",
                "radius",
                "num1",
            )
            for index, key in enumerate(ordered_fields):
                section_data[index] = int(raw_section.get(key, 0))

            altitudes = [int(value) for value in list(raw_section.get("alt", []))]
            grades = [int(value) for value in list(raw_section.get("grade", []))]
            if len(altitudes) != num_xsects or len(grades) != num_xsects:
                raise ValueError("Each project section must include alt/grade values for every xsect.")
            for xsect_index in range(num_xsects):
                section_data[17 + 2 * xsect_index] = altitudes[xsect_index]
                section_data[18 + 2 * xsect_index] = grades[xsect_index]

            fsect_start = 17 + 2 * num_xsects
            max_fsects = 40
            requested_num_fsects = int(raw_section.get("num_fsects", 0))
            requested_num_fsects = max(0, min(requested_num_fsects, max_fsects))
            ftype1 = [int(value) for value in list(raw_section.get("ftype1", []))]
            ftype2 = [int(value) for value in list(raw_section.get("ftype2", []))]
            fstart = [int(value) for value in list(raw_section.get("fstart", []))]
            fend = [int(value) for value in list(raw_section.get("fend", []))]
            actual_num_fsects = min(requested_num_fsects, len(ftype1), len(ftype2), len(fstart), len(fend), max_fsects)
            section_data[fsect_start] = actual_num_fsects
            for fsect_index in range(actual_num_fsects):
                section_data[fsect_start + 1 + 4 * fsect_index] = ftype1[fsect_index]
                section_data[fsect_start + 2 + 4 * fsect_index] = ftype2[fsect_index]
                section_data[fsect_start + 3 + 4 * fsect_index] = fstart[fsect_index]
                section_data[fsect_start + 4 + 4 * fsect_index] = fend[fsect_index]

            sections.append(SGFile.Section(section_data, num_xsects))

        num_sects = int(payload.get("num_sects", len(sections)))
        if num_sects != len(sections):
            num_sects = len(sections)
        header[4] = num_sects
        return SGFile(header, num_sects, num_xsects, xsect_dlats, sections)

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
