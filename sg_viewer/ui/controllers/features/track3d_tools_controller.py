from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets

from sg_viewer.services.pcx_palette import read_pcx_256_palette
from sg_viewer.services.template_files import (
    copy_template_files_without_overwrite,
    parse_template_trackname_files,
    replace_template_trackname_placeholders,
)

from icr2_core.three_d.three_d_tools import ToolError, inspect_file, process_file
from sg_viewer.replacecolors import (
    DEFAULT_TRACK3D_COLORS,
    replace_color_section_from_indices,
)
from sg_viewer.ui.palette_dialog import PaletteColorDialog
from sg_viewer.ui.track3d_colors_dialog import Track3DColorDefinitionsDialog
from sg_viewer.ui.track3d_catalog_dialog import Track3DCatalogInspectorDialog
from sg_viewer.io.track3d_catalog import Track3DCatalog, parse_track3d_catalog
from sg_viewer.io.track3d_edit_plan import (
    Track3DEditPlan,
    create_timestamped_backup,
    build_selected_face_material_edit_plan,
    build_selected_object_list_edit_plan,
    build_selected_tso_definition_edit_plan,
)


@contextmanager
def _suppress_routine_workflow_messages(parent: QtWidgets.QWidget):
    original_information = QtWidgets.QMessageBox.information
    original_warning = QtWidgets.QMessageBox.warning

    def show_status(_parent, _title, text, *args, **kwargs):
        if hasattr(parent, "show_status_message"):
            parent.show_status_message(str(text).replace("\n", " "))
        buttons = args[0] if args else kwargs.get("buttons", QtWidgets.QMessageBox.Ok)
        if buttons & QtWidgets.QMessageBox.Yes:
            return QtWidgets.QMessageBox.Yes
        return QtWidgets.QMessageBox.Ok

    QtWidgets.QMessageBox.information = show_status
    QtWidgets.QMessageBox.warning = show_status
    try:
        yield
    finally:
        QtWidgets.QMessageBox.information = original_information
        QtWidgets.QMessageBox.warning = original_warning


class Track3DWorkflowProgress:
    """Modal progress dialog for the standard .3D workflow."""

    def __init__(self, parent: QtWidgets.QWidget, maximum: int) -> None:
        self._dialog = QtWidgets.QProgressDialog("", None, 0, maximum, parent)
        self._dialog.setWindowTitle("Applying Standard .3D Workflow")
        self._dialog.setWindowModality(QtCore.Qt.WindowModal)
        self._dialog.setMinimumDuration(0)
        self._dialog.setAutoClose(False)
        self._dialog.setAutoReset(False)
        self._dialog.setCancelButton(None)
        self._dialog.setValue(0)

    def update(self, value: int, message: str) -> None:
        self._dialog.setLabelText(message)
        self._dialog.setValue(value)
        self._dialog.show()
        QtWidgets.QApplication.processEvents()

    def close(self) -> None:
        self._dialog.close()
        self._dialog.deleteLater()
        QtWidgets.QApplication.processEvents()


class Track3DToolsController:
    def __init__(self, host: object) -> None:
        self._host = host

    @property
    def _window(self):
        return self._host._window

    @property
    def _sg_settings_store(self):
        return self._host._sg_settings_store

    @property
    def _current_path(self):
        return self._host._current_path

    @property
    def _project_working_directory(self):
        return self._host._project_working_directory

    @property
    def _active_selection(self):
        return self._host._active_selection

    @property
    def _trackside_objects(self):
        return self._host._trackside_objects

    @property
    def _selected_track3d_path(self):
        return self._host._track3d_palette_state.selected_track3d_path

    @_selected_track3d_path.setter
    def _selected_track3d_path(self, value):
        self._host._track3d_palette_state.selected_track3d_path = value

    @property
    def _track3d_colors(self):
        return self._host._track3d_palette_state.track3d_colors

    @_track3d_colors.setter
    def _track3d_colors(self, value):
        self._host._track3d_palette_state.track3d_colors = value

    @property
    def _sunny_palette(self):
        return self._host._track3d_palette_state.sunny_palette

    @_sunny_palette.setter
    def _sunny_palette(self, value):
        self._host._track3d_palette_state.sunny_palette = value

    @property
    def _sunny_palette_path(self):
        return self._host._track3d_palette_state.sunny_palette_path

    @_sunny_palette_path.setter
    def _sunny_palette_path(self, value):
        self._host._track3d_palette_state.sunny_palette_path = value

    @property
    def _palette_colors_dialog(self):
        return self._host._track3d_palette_state.palette_colors_dialog

    @_palette_colors_dialog.setter
    def _palette_colors_dialog(self, value):
        self._host._track3d_palette_state.palette_colors_dialog = value

    def _dialog_default_directory(self) -> str:
        return self._host._dialog_default_directory()

    def _format_tso_dynamic_line(self, label, obj) -> str:
        return self._host._format_tso_dynamic_line(label, obj)

    def _sync_tso_visibility_section_dlongs(self) -> None:
        self._host._sync_tso_visibility_section_dlongs()

    _read_pcx_256_palette = staticmethod(read_pcx_256_palette)

    def _project_folder(self) -> Path | None:
        if self._project_working_directory is not None:
            return Path(self._project_working_directory)
        if self._current_path is not None:
            return Path(self._current_path).parent
        return None

    def _on_copy_template_files_requested(self) -> None:
        project_folder = self._project_folder()
        if project_folder is None:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Copy Template Files",
                "Open or save an SG file before copying template files.",
            )
            return

        default_template = self._host._history.get_template_folder()
        start_dir = (
            str(default_template)
            if default_template is not None
            else self._dialog_default_directory()
        )
        selected = QtWidgets.QFileDialog.getExistingDirectory(
            self._window,
            "Select Template Folder",
            start_dir,
        )
        if not selected:
            return

        template_folder = Path(selected).resolve()
        if not template_folder.is_dir():
            QtWidgets.QMessageBox.warning(
                self._window,
                "Copy Template Files",
                f"Template folder does not exist:\n{template_folder}",
            )
            return

        trackname_files_text = self._window.files_trackname_replace_edit.text()
        trackname_files = parse_template_trackname_files(trackname_files_text)
        if trackname_files and self._current_path is None:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Copy Template Files",
                "Open or save an SG file before replacing <<trackname>> placeholders.",
            )
            return

        project_folder.mkdir(parents=True, exist_ok=True)
        copied_count = 0
        directory_count = 0
        skipped_files: list[Path] = []
        replaced_count = 0
        try:
            copy_result = copy_template_files_without_overwrite(
                template_folder, project_folder
            )
            copied_count = len(copy_result.copied_files)
            directory_count = copy_result.directory_count
            skipped_files = copy_result.skipped_files
            if trackname_files:
                track_name = Path(self._current_path).stem
                copied_paths = set(copy_result.copied_files)
                replace_files = [
                    path for path in trackname_files if path in copied_paths
                ]
                replaced_count = replace_template_trackname_placeholders(
                    project_folder, replace_files, track_name
                )
        except OSError as exc:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Copy Template Files",
                f"Could not copy template files:\n{exc}",
            )
            return

        self._host._history.set_template_folder(template_folder)
        self._host._history.set_template_trackname_files(trackname_files_text)
        message = f"Copied {copied_count} template file(s) and {directory_count} folder(s) to {project_folder}"
        if skipped_files:
            message += f"; skipped {len(skipped_files)} existing file(s)"
        if trackname_files:
            message += f"; replaced <<trackname>> in {replaced_count} copied file(s)"
        self._window.show_status_message(message)

        if skipped_files:
            skipped_text = "\n".join(str(path) for path in skipped_files)
            QtWidgets.QMessageBox.information(
                self._window,
                "Copy Template Files",
                "These existing project files were not copied over:\n"
                f"{skipped_text}",
            )

    def _on_template_trackname_files_changed(self) -> None:
        self._host._history.set_template_trackname_files(
            self._window.files_trackname_replace_edit.text()
        )

    def _on_create_run_bat_requested(self) -> None:
        project_folder = self._project_folder()
        if project_folder is None or self._current_path is None:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Create run .bat",
                "Open or save an SG file before creating a run batch file.",
            )
            return

        default_path = project_folder / "run.bat"
        file_path, _selected_filter = QtWidgets.QFileDialog.getSaveFileName(
            self._window,
            "Create run .bat",
            str(default_path),
            "Batch files (*.bat);;All Files (*)",
        )
        if not file_path:
            return

        track_name = Path(self._current_path).stem
        batch_text = self._build_run_bat_text(track_name)
        try:
            Path(file_path).write_text(batch_text, encoding="utf-8", newline="\r\n")
        except OSError as exc:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Create run .bat",
                f"Could not save batch file:\n{exc}",
            )
            return
        self._window.show_status_message(f"Created {file_path}")

    @staticmethod
    def _build_run_bat_text(track_name: str) -> str:
        return (
            f"sg2trk {track_name}\n"
            f"trk23d -al -pit {track_name}\n"
            f"3d23do {track_name}\n"
            f"ope {track_name}\n"
        )

    @staticmethod
    def _as_qcolors(colors: list[tuple[int, int, int]]) -> list[QtGui.QColor]:
        return [QtGui.QColor(red, green, blue) for red, green, blue in colors]

    def _load_sunny_palette_dialog(self) -> None:
        path_str, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._window,
            "Load SUNNY.PCX Palette",
            self._dialog_default_directory(),
            "PCX files (*.pcx *.PCX);;All files (*)",
        )
        if not path_str:
            return

        self._load_sunny_palette(Path(path_str))

    def _load_sunny_palette(
        self, path: Path, *, persist_for_current_track: bool = True
    ) -> bool:
        resolved_path = path.resolve()
        try:
            colors = self._read_pcx_256_palette(resolved_path)
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Load SUNNY.PCX Palette",
                f"Could not load palette from {path.name}:\n{exc}",
            )
            return False

        self._sunny_palette = self._as_qcolors(colors)
        self._sunny_palette_path = resolved_path

        if persist_for_current_track and self._current_path is not None:
            self._sg_settings_store.set_sunny_palette(self._current_path, resolved_path)

        self._window.preview.set_tsd_palette(self._sunny_palette)
        if hasattr(self._window, "set_sunny_palette_colors"):
            self._window.set_sunny_palette_colors(self._sunny_palette)
        self._window.show_status_message(
            f"Loaded SUNNY palette from {resolved_path.name} ({len(self._sunny_palette)} colors)."
        )
        return True

    def _show_palette_colors_dialog(self) -> None:
        if not self._sunny_palette:
            QtWidgets.QMessageBox.information(
                self._window,
                "SUNNY Palette",
                "Load SUNNY.PCX first from File → Import → Import SUNNY.PCX…",
            )
            return

        if self._palette_colors_dialog is None:
            self._palette_colors_dialog = PaletteColorDialog(
                self._sunny_palette, self._window
            )
        else:
            self._palette_colors_dialog.close()
            self._palette_colors_dialog = PaletteColorDialog(
                self._sunny_palette, self._window
            )

        self._palette_colors_dialog.show()
        self._palette_colors_dialog.raise_()
        self._palette_colors_dialog.activateWindow()

    def _open_three_d_tools_dialog(self) -> None:
        input_path = self._ensure_selected_track3d_file()
        if input_path is None:
            return
        operation, accepted = QtWidgets.QInputDialog.getItem(
            self._window,
            "3D Tools",
            "Choose operation:",
            (
                "Inspect see-through candidates",
                "Fix see-through elevation (save as copy)",
                "Fix see-through elevation (in place)",
            ),
            current=0,
            editable=False,
        )
        if not accepted:
            return

        try:
            if operation == "Inspect see-through candidates":
                self._run_three_d_inspect(input_path)
                return

            if operation == "Fix see-through elevation (save as copy)":
                self._run_three_d_fix(input_path, in_place=False)
                return
            self._run_three_d_fix(input_path, in_place=True)
        except ToolError as exc:
            QtWidgets.QMessageBox.warning(
                self._window,
                "3D Tools",
                f"3D tools failed:\n{exc}",
            )
        except OSError as exc:
            QtWidgets.QMessageBox.warning(
                self._window,
                "3D Tools",
                f"Could not read or write 3D file:\n{exc}",
            )

    def _run_three_d_inspect(self, input_path: Path) -> None:
        report = inspect_file(input_path)
        QtWidgets.QMessageBox.information(
            self._window,
            "3D Tools - Inspect Report",
            "\n".join(report.summary_lines()),
        )
        self._window.show_status_message(
            f"3D tools inspection complete: {input_path.name}"
        )

    def _run_three_d_fix(self, input_path: Path, *, in_place: bool) -> None:
        output_path: Path | None = None
        if not in_place:
            output_text, _selected_filter = QtWidgets.QFileDialog.getSaveFileName(
                self._window,
                "Save fixed 3D file",
                str(
                    input_path.with_name(f"{input_path.stem}_fixed{input_path.suffix}")
                ),
                "Track 3D Files (*.3d *.3D);;All Files (*)",
            )
            if not output_text:
                return
            output_path = Path(output_text)

        progress_dialog = QtWidgets.QProgressDialog(
            "Fixing see-through elevations…",
            "",
            0,
            100,
            self._window,
        )
        progress_dialog.setWindowTitle("3D Tools")
        progress_dialog.setWindowModality(QtCore.Qt.WindowModal)
        progress_dialog.setCancelButton(None)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setValue(0)
        progress_dialog.show()
        QtWidgets.QApplication.processEvents()

        try:

            def _on_progress(current: int, total: int, message: str) -> None:
                safe_total = max(total, 1)
                value = int((current / safe_total) * 100)
                progress_dialog.setLabelText(message)
                progress_dialog.setValue(max(0, min(100, value)))
                QtWidgets.QApplication.processEvents()

            report = process_file(
                input_path=input_path,
                output_path=input_path if in_place else output_path,
                fix_elevation=True,
                on_progress=_on_progress,
            )
        finally:
            progress_dialog.close()

        QtWidgets.QMessageBox.information(
            self._window,
            "3D Tools - Fix Report",
            "\n".join(report.summary_lines()),
        )
        self._window.show_status_message(f"3D tools fix complete: {input_path.name}")

    def _track3d_path_for_current_project(self) -> Path | None:
        if (
            self._selected_track3d_path is not None
            and self._selected_track3d_path.exists()
        ):
            return self._selected_track3d_path
        if self._current_path is None:
            return None
        path = self._current_path.with_suffix(".3d")
        if path.exists():
            return path
        fallback_path = self._current_path.with_suffix(".3D")
        if fallback_path.exists():
            return fallback_path
        return None

    def _set_selected_track3d_path(self, path: Path | None, *, persist: bool) -> None:
        resolved = path.resolve() if path is not None else None
        self._selected_track3d_path = resolved
        self._window.set_selected_track3d_path_text(
            str(resolved) if resolved is not None else "none"
        )
        if persist and self._current_path is not None:
            self._sg_settings_store.set_track3d_file(self._current_path, resolved)
        self._sync_tso_visibility_section_dlongs()

    def _ensure_selected_track3d_file(self) -> Path | None:
        candidate = self._track3d_path_for_current_project()
        if candidate is not None and candidate.exists():
            if self._selected_track3d_path != candidate.resolve():
                self._set_selected_track3d_path(candidate, persist=False)
            return candidate
        QtWidgets.QMessageBox.information(
            self._window,
            "3D Tools",
            "Select a track .3D file first.",
        )
        return None

    def _on_select_track3d_file_requested(self) -> None:
        default_path = ""
        selected_track3d = self._track3d_path_for_current_project()
        if selected_track3d is not None:
            default_path = str(selected_track3d)
        path_str, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
            self._window,
            "Select track .3D file",
            default_path,
            "Track 3D Files (*.3d *.3D);;All Files (*)",
        )
        if not path_str:
            return
        selected_path = Path(path_str)
        if not selected_path.exists():
            QtWidgets.QMessageBox.warning(
                self._window, "3D Tools", f"File not found:\n{selected_path}"
            )
            return
        self._set_selected_track3d_path(selected_path, persist=True)
        self._window.show_status_message(f"Selected .3D file: {selected_path.name}")

    def _on_three_d_catalog_inspector_requested(self) -> None:
        input_path = self._ensure_selected_track3d_file()
        if input_path is None:
            return
        try:
            catalog = parse_track3d_catalog(input_path)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(
                self._window, "3D Catalog Inspector", f"Could not read 3D file:\n{exc}"
            )
            return
        current_section = (
            self._active_selection.index if self._active_selection is not None else None
        )

        def jump_to_section(section: int) -> None:
            sections, _xsects = self._window.preview.get_section_set()
            if 0 <= section < len(sections):
                self._window.preview.selection_manager.set_selected_section(section)
                self._window.show_status_message(
                    f"Jumped to SG section {section} from .3D catalog inspector."
                )
            else:
                QtWidgets.QMessageBox.information(
                    self._window,
                    "3D Catalog Inspector",
                    f"Section {section} is not available in the current SG project.",
                )

        dialog = Track3DCatalogInspectorDialog(
            catalog,
            path_text=str(input_path),
            current_section=current_section,
            jump_to_section=jump_to_section,
            parent=self._window,
        )
        dialog.exec_()

    def _selected_sg_section_index(self) -> int | None:
        if self._active_selection is not None:
            return self._active_selection.index
        return self._window.selected_section_index

    def _show_track3d_text_report(self, title: str, text: str) -> None:
        dialog = QtWidgets.QDialog(self._window)
        dialog.setWindowTitle(title)
        dialog.resize(760, 520)
        layout = QtWidgets.QVBoxLayout(dialog)
        edit = QtWidgets.QPlainTextEdit()
        edit.setReadOnly(True)
        edit.setPlainText(text)
        layout.addWidget(edit)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec_()

    def _selected_section_catalog(self) -> tuple[Path, Track3DCatalog, int] | None:
        input_path = self._ensure_selected_track3d_file()
        if input_path is None:
            return None
        section = self._selected_sg_section_index()
        if section is None:
            QtWidgets.QMessageBox.information(
                self._window, "3D section tools", "Select an SG section first."
            )
            return None
        try:
            return input_path, parse_track3d_catalog(input_path), int(section)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(
                self._window, "3D section tools", f"Could not read 3D file:\n{exc}"
            )
            return None

    def _on_three_d_show_selected_section_entries(self) -> None:
        payload = self._selected_section_catalog()
        if payload is None:
            return
        path, catalog, section = payload
        faces = [face for face in catalog.faces if face.section == section]
        section_lists = [
            label
            for label, item in catalog.section_lists.items()
            if item.section == section
        ]
        object_lists = sorted({name for face in faces for name in face.object_lists})
        lines = [f".3D entries for SG section {section} in {path}", "", "FACE blocks:"]
        lines.extend(
            f"  {face.label} (lines {face.span.start_line}-{face.span.end_line}, LOD {face.lod})"
            for face in faces
        )
        lines.append("Section lists:")
        lines.extend(f"  {label}" for label in section_lists)
        lines.append("ObjectLists referenced:")
        lines.extend(f"  {label}" for label in object_lists)
        self._show_track3d_text_report(
            ".3D entries for selected SG section",
            (
                "\n".join(lines)
                if faces or section_lists or object_lists
                else "No .3D entries found."
            ),
        )

    def _on_three_d_show_selected_section_object_lists(self) -> None:
        payload = self._selected_section_catalog()
        if payload is None:
            return
        _path, catalog, section = payload
        refs = sorted(
            {
                name
                for face in catalog.faces
                if face.section == section
                for name in face.object_lists
            }
        )
        rows = []
        for name in refs:
            obj = catalog.object_lists.get(name)
            rows.append(
                f"{name}: missing definition"
                if obj is None
                else f"{name} (line {obj.line}): {', '.join(obj.items) or '(empty)'}"
            )
        self._show_track3d_text_report(
            "ObjectLists referenced by selected section",
            "\n".join(rows) or "No ObjectLists referenced by selected section.",
        )

    def _tso_labels_for_section(
        self, catalog: Track3DCatalog, section: int
    ) -> list[str]:
        return sorted(
            {
                item
                for face in catalog.faces
                if face.section == section
                for name in face.object_lists
                for item in (
                    catalog.object_lists.get(name).items
                    if catalog.object_lists.get(name)
                    else []
                )
                if item.startswith("__TSO")
            },
            key=lambda x: int(x[5:]) if x[5:].isdigit() else x,
        )

    def _on_three_d_show_selected_section_tsos(self) -> None:
        payload = self._selected_section_catalog()
        if payload is None:
            return
        _path, catalog, section = payload
        rows = []
        for label in self._tso_labels_for_section(catalog, section):
            tso = catalog.tsos.get(label)
            rows.append(
                f'{label}: EXTERN "{tso.extern}" at ({tso.x}, {tso.y}, {tso.z})'
                if tso
                else f"{label}: missing definition"
            )
        self._show_track3d_text_report(
            "TSOs used by selected section",
            "\n".join(rows) or "No TSOs used by selected section.",
        )

    def _selected_section_object_list_plan(self) -> Track3DEditPlan | None:
        payload = self._selected_section_catalog()
        if payload is None:
            return None
        path, _catalog, section = payload
        return build_selected_object_list_edit_plan(
            path, self._window.tso_visibility_sidebar.object_lists, section=section
        )

    def _confirm_and_apply_track3d_plan(
        self, title: str, plan: Track3DEditPlan
    ) -> bool:
        if not plan.edits:
            QtWidgets.QMessageBox.information(
                self._window, title, "No changes are available for the selected scope."
            )
            return False
        diff = plan.preview_unified_diff(context=3)
        warning_text = "\n".join(plan.warnings)
        message = "Review the diff before applying edits in place. A timestamped backup will be created."
        if warning_text:
            message += f"\n\nWarnings:\n{warning_text}"
        box = QtWidgets.QMessageBox(self._window)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle(title)
        box.setText(message)
        box.setDetailedText(diff or "(No textual diff)")
        box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        box.setDefaultButton(QtWidgets.QMessageBox.No)
        if box.exec_() != QtWidgets.QMessageBox.Yes:
            return False
        try:
            backup_path = plan.write()
        except OSError as exc:
            QtWidgets.QMessageBox.critical(
                self._window, title, f"Could not apply edits:\n{exc}"
            )
            return False
        self._window.show_status_message(
            f"Updated {plan.original_path.name}; backup saved to {backup_path.name}."
        )
        return True

    def _on_three_d_preview_selected_object_lists(self) -> None:
        plan = self._selected_section_object_list_plan()
        if plan is None:
            return
        diff = (
            plan.preview_unified_diff(context=3)
            if plan.edits
            else "No ObjectList changes for selected section."
        )
        if plan.warnings:
            diff = "Warnings:\n" + "\n".join(plan.warnings) + "\n\n" + diff
        self._show_track3d_text_report(
            "Preview ObjectList changes for selected section", diff
        )

    def _on_three_d_apply_selected_object_lists(self) -> None:
        plan = self._selected_section_object_list_plan()
        if plan is not None:
            self._confirm_and_apply_track3d_plan("Apply ObjectList changes", plan)

    def _on_three_d_apply_selected_tso_definitions(self) -> None:
        payload = self._selected_section_catalog()
        if payload is None:
            return
        path, catalog, section = payload
        replacements = {}
        for label in self._tso_labels_for_section(catalog, section):
            index_text = label.removeprefix("__TSO")
            if not index_text.isdigit():
                continue
            index = int(index_text)
            if 0 <= index < len(self._trackside_objects):
                replacements[label] = self._format_tso_dynamic_line(
                    label, self._trackside_objects[index]
                )
        plan = build_selected_tso_definition_edit_plan(path, replacements)
        self._confirm_and_apply_track3d_plan("Apply selected TSO definitions", plan)

    def _on_three_d_apply_selected_face_materials(self) -> None:
        payload = self._selected_section_catalog()
        if payload is None:
            return
        path, _catalog, section = payload
        text, ok = QtWidgets.QInputDialog.getMultiLineText(
            self._window,
            "Replace materials in selected FACE spans",
            "Enter one replacement per line as old=new. Only FACE blocks for the selected SG section are edited.",
            "",
        )
        if not ok:
            return
        replacements = {}
        for raw_line in text.splitlines():
            if "=" not in raw_line:
                continue
            old, new = [part.strip() for part in raw_line.split("=", 1)]
            if old and new:
                replacements[old] = new
        if not replacements:
            QtWidgets.QMessageBox.information(
                self._window,
                "Replace materials",
                "No material replacements were entered.",
            )
            return
        plan = build_selected_face_material_edit_plan(
            path, section=section, material_replacements=replacements
        )
        self._confirm_and_apply_track3d_plan(
            "Replace materials in selected FACE spans", plan
        )

    def _on_edit_track3d_colors_requested(self) -> None:
        dialog = Track3DColorDefinitionsDialog(
            colors=self._track3d_colors,
            palette=self._sunny_palette,
            parent=self._window,
        )
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        self._track3d_colors = dialog.selected_colors()
        self._window.set_selected_colors_path_text("custom")
        if self._current_path is not None:
            self._sg_settings_store.set_track3d_colors(
                self._current_path, self._track3d_colors
            )
        self._window.show_status_message("Updated 3D polygon color mappings.")

    def _on_three_d_inspect_requested(self) -> None:
        input_path = self._ensure_selected_track3d_file()
        if input_path is None:
            return
        try:
            self._run_three_d_inspect(input_path)
        except ToolError as exc:
            QtWidgets.QMessageBox.warning(
                self._window, "3D Tools", f"3D tools failed:\n{exc}"
            )
        except OSError as exc:
            QtWidgets.QMessageBox.warning(
                self._window, "3D Tools", f"Could not read 3D file:\n{exc}"
            )

    def _on_three_d_fix_copy_requested(self) -> None:
        input_path = self._ensure_selected_track3d_file()
        if input_path is None:
            return
        try:
            self._run_three_d_fix(input_path, in_place=False)
        except ToolError as exc:
            QtWidgets.QMessageBox.warning(
                self._window, "3D Tools", f"3D tools failed:\n{exc}"
            )
        except OSError as exc:
            QtWidgets.QMessageBox.warning(
                self._window, "3D Tools", f"Could not read or write 3D file:\n{exc}"
            )

    def _on_three_d_fix_in_place_requested(self, confirm: bool = True) -> None:
        input_path = self._ensure_selected_track3d_file()
        if input_path is None:
            return
        if confirm:
            proceed = QtWidgets.QMessageBox.warning(
                self._window,
                "3D Tools",
                "This will edit the selected .3D file in place. Continue?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if proceed != QtWidgets.QMessageBox.Yes:
                return
        try:
            self._run_three_d_fix(input_path, in_place=True)
        except ToolError as exc:
            QtWidgets.QMessageBox.warning(
                self._window, "3D Tools", f"3D tools failed:\n{exc}"
            )
        except OSError as exc:
            QtWidgets.QMessageBox.warning(
                self._window, "3D Tools", f"Could not read or write 3D file:\n{exc}"
            )

    def _on_three_d_apply_color_replacements_requested(self) -> None:
        input_path = self._ensure_selected_track3d_file()
        if input_path is None:
            return
        try:
            replacement_count = replace_color_section_from_indices(
                input_path, self._track3d_colors
            )
        except OSError as exc:
            QtWidgets.QMessageBox.warning(
                self._window, "3D Tools", f"Could not update colors:\n{exc}"
            )
            return
        QtWidgets.QMessageBox.information(
            self._window,
            "3D Tools - Color Fix",
            f"Updated {replacement_count} color definition(s) in:\n{input_path}",
        )
        self._window.show_status_message(
            f"3D tools color fix complete: {input_path.name} ({replacement_count} updated)"
        )

    def _run_three_d_workflow_steps(self, steps: tuple[str, ...]) -> None:
        if not steps:
            QtWidgets.QMessageBox.information(
                self._window,
                "Apply Selected to .3D",
                "Select at least one standard workflow step to apply.",
            )
            return
        step_actions = {
            "tso": self._host._trackside_objects_controller._on_tso_write_to_3d_file_requested,
            "object_lists": lambda: self._window.tso_visibility_sidebar._on_save_to_track3d_requested(
                create_backup=False
            ),
            "detail_lists": lambda: self._window.tso_visibility_sidebar._on_save_detail_lists_to_track3d_requested(
                create_backup=False
            ),
            "see_through": lambda: self._on_three_d_fix_in_place_requested(
                confirm=False
            ),
            "colors": self._on_three_d_apply_color_replacements_requested,
        }
        step_labels = {
            "tso": "Saving TSOs",
            "object_lists": "Saving ObjectLists",
            "detail_lists": "Saving DetailLists",
            "see_through": "Fixing see-through polygons",
            "colors": "Applying color replacements",
        }
        progress = Track3DWorkflowProgress(self._window, len(steps))
        progress.update(0, "Preparing standard .3D workflow…")
        try:
            backup_path = None
            if self._window.three_d_workflow_create_backup():
                input_path = self._ensure_selected_track3d_file()
                if input_path is None:
                    return
                try:
                    backup_path = create_timestamped_backup(input_path)
                except OSError as exc:
                    QtWidgets.QMessageBox.warning(
                        self._window,
                        "Apply Selected to .3D",
                        f"Could not create backup before applying workflow:\n{exc}",
                    )
                    return
            with _suppress_routine_workflow_messages(self._window):
                for index, step in enumerate(steps, start=1):
                    action = step_actions.get(step)
                    if action is not None:
                        progress.update(index - 1, f"{step_labels.get(step, step)}…")
                        action()
                        progress.update(
                            index, f"Finished {step_labels.get(step, step).lower()}."
                        )
            status = "Applied selected standard .3D workflow steps."
            if backup_path is not None:
                status += f" Backup created: {backup_path.name}."
            self._window.show_status_message(status)
        finally:
            progress.close()

    def _on_three_d_apply_selected_workflow_requested(self) -> None:
        self._run_three_d_workflow_steps(self._window.selected_three_d_workflow_steps())

    def _on_three_d_apply_all_workflow_requested(self) -> None:
        self._run_three_d_workflow_steps(
            ("tso", "object_lists", "detail_lists", "see_through", "colors")
        )

    def _apply_saved_sunny_palette(self, sg_path: Path | None = None) -> None:
        path = sg_path or self._current_path
        if path is None:
            return
        palette_path = self._sg_settings_store.get_sunny_palette(path)
        if palette_path is None:
            return
        self._load_sunny_palette(palette_path, persist_for_current_track=False)
