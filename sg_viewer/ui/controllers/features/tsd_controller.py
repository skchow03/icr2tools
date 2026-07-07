from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace
from pathlib import Path
from time import perf_counter

from PyQt5 import QtCore, QtWidgets

from sg_viewer.model.sg_model import Point, SectionPreview
from sg_viewer.services.skid_marks import (
    SkidMarkGenerationParameters,
    generate_skid_mark_lines,
    parse_colors_csv,
    parse_skid_sections_csv,
)
from sg_viewer.services.tsd_io import (
    TrackSurfaceDetailFile,
    TrackSurfaceDetailLine,
    parse_tsd,
    serialize_tsd,
)
from sg_viewer.services.tsd_dlong_mapping import (
    adjusted_dlong_to_sg_dlong,
    build_adjusted_to_sg_ranges,
    find_adjusted_segment_index,
)
from sg_viewer.services.tsd_objects import (
    TsdDashedLinesObject,
    TsdDoubleSolidLineObject,
    TsdPitStallsObject,
    TsdTransverseLineObject,
    TsdZebraCrossingObject,
)
from sg_viewer.ui.dialogs.tsd_object_dialog import TsdObjectDialog, TsdObjectPayload


@dataclass(frozen=True)
class LoadedTsdFile:
    name: str
    lines: tuple[TrackSurfaceDetailLine, ...]
    source_path: Path | None = None


class TsdController:
    _TSD_SHOW_ALL_LABEL = "Show all TSDs"

    def __init__(self, host: object) -> None:
        object.__setattr__(self, "_host", host)

    def __getattr__(self, name: str):
        return getattr(self._host, name)

    def __setattr__(self, name: str, value) -> None:
        if name == "_host":
            object.__setattr__(self, name, value)
        else:
            setattr(self._host, name, value)

    def _on_tsd_add_line_requested(self) -> None:
        row = self._tsd_lines_model.add_default_row()
        self._window.tsd_lines_table.selectRow(row)
        self._autosize_tsd_lines_table_columns()
        self._sync_active_tsd_file_from_model()
        self._refresh_tsd_preview_lines()
        self._set_tsd_dirty(True)
        self._persist_tsd_state_for_current_track()

    def _on_tsd_delete_line_requested(self) -> None:
        selection_model = self._window.tsd_lines_table.selectionModel()
        if selection_model is None:
            return
        selected_rows = selection_model.selectedRows()
        if not selected_rows:
            return
        self._tsd_lines_model.remove_row(selected_rows[0].row())
        self._autosize_tsd_lines_table_columns()
        self._sync_active_tsd_file_from_model()
        self._refresh_tsd_preview_lines()
        self._set_tsd_dirty(True)
        self._persist_tsd_state_for_current_track()

    def _move_tsd_line(self, *, direction: int) -> None:
        selection_model = self._window.tsd_lines_table.selectionModel()
        if selection_model is None:
            return
        selected_rows = selection_model.selectedRows()
        if not selected_rows:
            return
        source_row = selected_rows[0].row()
        target_row = source_row + direction
        if not self._tsd_lines_model.move_row(source_row=source_row, target_row=target_row):
            return
        self._window.tsd_lines_table.selectRow(target_row)
        self._autosize_tsd_lines_table_columns()
        self._sync_active_tsd_file_from_model()
        self._refresh_tsd_preview_lines()
        self._set_tsd_dirty(True)
        self._persist_tsd_state_for_current_track()

    def _on_tsd_move_line_up_requested(self) -> None:
        self._move_tsd_line(direction=-1)

    def _on_tsd_move_line_down_requested(self) -> None:
        self._move_tsd_line(direction=1)

    def _save_tsd_to_path(self, path: Path, *, fail_title: str) -> TrackSurfaceDetailFile | None:
        try:
            detail_file = self._build_tsd_file_from_model()
            path.write_text(serialize_tsd(detail_file), encoding="utf-8")
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(
                self._window,
                fail_title,
                str(exc),
            )
            return None
        return detail_file

    def _on_tsd_save_file_requested(self) -> None:
        if self._active_tsd_file_index is None:
            self._on_tsd_generate_file_requested()
            return
        if self._active_tsd_file_index < 0 or self._active_tsd_file_index >= len(self._loaded_tsd_files):
            return
        active_file = self._loaded_tsd_files[self._active_tsd_file_index]
        if active_file.source_path is None:
            self._on_tsd_generate_file_requested()
            return
        detail_file = self._save_tsd_to_path(active_file.source_path, fail_title="Save TSD Failed")
        if detail_file is None:
            return
        self._upsert_loaded_tsd_file(
            active_file.source_path.name,
            tuple(detail_file.lines),
            source_path=active_file.source_path.resolve(),
        )
        self._refresh_tsd_preview_lines()
        self._persist_tsd_state_for_current_track()
        self._set_tsd_dirty(False)
        self._window.show_status_message(f"Saved TSD file {active_file.source_path.name}")

    def _on_tsd_generate_file_requested(self) -> None:
        path_str, _selected_filter = QtWidgets.QFileDialog.getSaveFileName(
            self._window,
            "Save As TSD File",
            self._dialog_default_directory(),
            "TSD Files (*.tsd)",
        )
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix.lower() != ".tsd":
            path = path.with_suffix(".tsd")

        detail_file = self._save_tsd_to_path(path, fail_title="Save As TSD Failed")
        if detail_file is None:
            return
        self._upsert_loaded_tsd_file(path.name, tuple(detail_file.lines), source_path=path.resolve())
        self._refresh_tsd_preview_lines()
        self._persist_tsd_state_for_current_track()
        self._set_tsd_dirty(False)
        self._window.show_status_message(f"Saved TSD file {path.name}")

    def _on_tsd_load_file_requested(self) -> None:
        path_str, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
            self._window,
            "Load TSD File",
            self._dialog_default_directory(),
            "TSD Files (*.tsd *.TSD);;All files (*)",
        )
        if not path_str:
            return

        path = Path(path_str)
        started = perf_counter()
        try:
            detail_file = parse_tsd(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Load TSD Failed",
                str(exc),
            )
            return

        self._add_loaded_tsd_file(path.name, tuple(detail_file.lines), select=True, source_path=path.resolve())
        self._persist_tsd_state_for_current_track()
        self._set_tsd_dirty(False)
        self._log_tsd_perf("TSD load duration", started)
        self._window.show_status_message(
            f"Loaded TSD file {path.name} ({len(self._loaded_tsd_files)} total)"
        )

    def _on_tsd_remove_file_requested(self) -> None:
        if not self._loaded_tsd_files:
            return

        selected_combo_index = self._window.tsd_files_combo.currentIndex()
        if selected_combo_index <= 0:
            if not self._confirm_tsd_file_removal(remove_all=True):
                return
            removed_count = len(self._loaded_tsd_files)
            self._loaded_tsd_files = []
            self._active_tsd_file_index = None
            self._populate_tsd_table(TrackSurfaceDetailFile(lines=()))
            self._refresh_tsd_file_combo()
            self._refresh_tsd_preview_lines()
            self._persist_tsd_state_for_current_track()
            self._set_tsd_dirty(True)
            self._window.show_status_message(
                f"Removed {removed_count} .TSD file(s) from the project."
            )
            return

        remove_index = selected_combo_index - 1
        if remove_index < 0 or remove_index >= len(self._loaded_tsd_files):
            return
        removed_file = self._loaded_tsd_files[remove_index]
        if not self._confirm_tsd_file_removal(remove_all=False, file_name=removed_file.name):
            return

        self._loaded_tsd_files.pop(remove_index)
        if not self._loaded_tsd_files:
            self._active_tsd_file_index = None
            self._populate_tsd_table(TrackSurfaceDetailFile(lines=()))
            self._refresh_tsd_file_combo()
            self._refresh_tsd_preview_lines()
        else:
            replacement_index = min(remove_index, len(self._loaded_tsd_files) - 1)
            self._set_active_tsd_file(replacement_index)
            self._refresh_tsd_file_combo(selected_index=replacement_index + 1)
            self._refresh_tsd_preview_lines()
        self._persist_tsd_state_for_current_track()
        self._set_tsd_dirty(True)
        self._window.show_status_message(f"Removed {removed_file.name} from the project.")

    def _confirm_tsd_file_removal(self, *, remove_all: bool, file_name: str | None = None) -> bool:
        if remove_all:
            message = (
                "This will remove all loaded .TSD files and all TSD lines from this project.\n"
                "The .TSD files on disk will not be deleted.\n\nContinue?"
            )
        else:
            display_name = file_name or "the selected .TSD file"
            message = (
                f"This will remove {display_name} and its TSD lines from this project.\n"
                "The .TSD file on disk will not be deleted.\n\nContinue?"
            )
        response = QtWidgets.QMessageBox.question(
            self._window,
            "Remove .TSD File from Project?",
            message,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return response == QtWidgets.QMessageBox.Yes

    def _sync_active_tsd_file_from_model(self) -> None:
        if self._active_tsd_file_index is None:
            return
        if self._active_tsd_file_index < 0 or self._active_tsd_file_index >= len(self._loaded_tsd_files):
            return
        active_file = self._loaded_tsd_files[self._active_tsd_file_index]
        self._loaded_tsd_files[self._active_tsd_file_index] = LoadedTsdFile(
            name=active_file.name,
            lines=self._tsd_lines_model.all_lines(),
            source_path=active_file.source_path,
        )

    def _clear_loaded_tsd_files(self) -> None:
        self._loaded_tsd_files = []
        self._active_tsd_file_index = None
        self._tsd_objects = []
        self._trackside_objects = []
        self._refresh_tsd_file_combo()
        self._populate_tsd_table(TrackSurfaceDetailFile(lines=()))
        self._refresh_tsd_objects_table()
        self._refresh_tso_table()
        self._window.tso_visibility_sidebar.clear_object_lists()
        self._set_tsd_dirty(False)
        self._set_trackside_objects_dirty(False)
        self._set_tso_visibility_dirty(False)

    def _add_loaded_tsd_file(
        self,
        name: str,
        lines: tuple[TrackSurfaceDetailLine, ...],
        *,
        select: bool,
        source_path: Path | None = None,
    ) -> None:
        self._loaded_tsd_files.append(LoadedTsdFile(name=name, lines=tuple(lines), source_path=source_path))
        combo = self._window.tsd_files_combo
        previous_block_state = combo.blockSignals(True)
        try:
            if combo.count() == 0:
                combo.addItem(self._TSD_SHOW_ALL_LABEL)
            combo.addItem(name)
            combo.setEnabled(True)
            if select:
                combo.setCurrentIndex(combo.count() - 1)
        finally:
            combo.blockSignals(previous_block_state)
        if select:
            self._set_active_tsd_file(len(self._loaded_tsd_files) - 1)
        self._update_tsd_remove_file_button_enabled()

    def _upsert_loaded_tsd_file(
        self,
        name: str,
        lines: tuple[TrackSurfaceDetailLine, ...],
        *,
        source_path: Path | None = None,
    ) -> None:
        if self._active_tsd_file_index is None:
            self._add_loaded_tsd_file(name, lines, select=True, source_path=source_path)
            return
        previous = self._loaded_tsd_files[self._active_tsd_file_index]
        self._loaded_tsd_files[self._active_tsd_file_index] = LoadedTsdFile(
            name=name,
            lines=tuple(lines),
            source_path=source_path or previous.source_path,
        )
        combo = self._window.tsd_files_combo
        previous_block_state = combo.blockSignals(True)
        try:
            combo.setItemText(self._active_tsd_file_index + 1, name)
        finally:
            combo.blockSignals(previous_block_state)

    def _set_active_tsd_file(self, index: int) -> None:
        if index < 0 or index >= len(self._loaded_tsd_files):
            return
        if self._active_tsd_file_index is not None and self._active_tsd_file_index != index:
            self._sync_active_tsd_file_from_model()
        self._active_tsd_file_index = index
        detail_file = TrackSurfaceDetailFile(lines=self._loaded_tsd_files[index].lines)
        self._populate_tsd_table(detail_file)

    def _on_tsd_file_selection_changed(self, index: int) -> None:
        if index <= 0:
            self._sync_active_tsd_file_from_model()
            self._active_tsd_file_index = None
            self._populate_tsd_table(TrackSurfaceDetailFile(lines=self._all_loaded_tsd_lines()))
            self._persist_tsd_state_for_current_track()
            self._update_tsd_remove_file_button_enabled()
            return
        self._set_active_tsd_file(index - 1)
        self._persist_tsd_state_for_current_track()
        self._update_tsd_remove_file_button_enabled()

    def _refresh_tsd_file_combo(self, *, selected_index: int = 0) -> None:
        combo = self._window.tsd_files_combo
        previous_block_state = combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem(self._TSD_SHOW_ALL_LABEL)
            for loaded_file in self._loaded_tsd_files:
                combo.addItem(loaded_file.name)
            combo.setEnabled(bool(self._loaded_tsd_files))
            if combo.count() > 0:
                combo.setCurrentIndex(max(0, min(selected_index, combo.count() - 1)))
        finally:
            combo.blockSignals(previous_block_state)
        self._update_tsd_remove_file_button_enabled()

    def _update_tsd_remove_file_button_enabled(self) -> None:
        self._window.tsd_remove_file_button.setEnabled(bool(self._loaded_tsd_files))

    def _all_loaded_tsd_lines(self) -> tuple[TrackSurfaceDetailLine, ...]:
        lines: list[TrackSurfaceDetailLine] = []
        for loaded_file in self._loaded_tsd_files:
            lines.extend(loaded_file.lines)
        return tuple(lines)

    def _populate_tsd_table(self, detail_file: TrackSurfaceDetailFile) -> None:
        started = perf_counter()
        self._suspend_tsd_preview_refresh = True
        table = self._window.tsd_lines_table
        previous_block_state = table.blockSignals(True)
        try:
            self._tsd_lines_model.replace_lines(detail_file.lines)
        finally:
            table.blockSignals(previous_block_state)
            self._suspend_tsd_preview_refresh = False

        self._autosize_tsd_lines_table_columns()
        self._refresh_tsd_preview_lines()
        self._log_tsd_perf("TSD table populate duration", started)

    def _on_tsd_selection_changed(
        self,
        _selected: QtCore.QItemSelection,
        _deselected: QtCore.QItemSelection,
    ) -> None:
        self._center_viewport_on_selected_tsd_line()
        self._schedule_tsd_preview_refresh()

    def _center_viewport_on_selected_tsd_line(self) -> None:
        selection_model = self._window.tsd_lines_table.selectionModel()
        if selection_model is None:
            return
        selected_rows = selection_model.selectedRows()
        if not selected_rows:
            return

        line = self._tsd_lines_model.line_at(selected_rows[0].row())
        if line is None:
            return

        center_point = self._tsd_line_center_point(line)
        if center_point is None:
            return

        self._window.preview.center_view_on_point(center_point)

    def _tsd_line_center_point(self, line: TrackSurfaceDetailLine) -> Point | None:
        sections, _ = self._window.preview.get_section_set()
        if not sections:
            return None

        adjusted_to_sg_ranges = self._last_tsd_adjusted_to_sg_ranges
        if not adjusted_to_sg_ranges[0]:
            adjusted_to_sg_ranges = self._build_adjusted_to_sg_ranges(sections)
            self._last_tsd_adjusted_to_sg_ranges = adjusted_to_sg_ranges

        preview_line = self._convert_tsd_line_for_preview(
            line,
            sections,
            adjusted_to_sg_ranges,
        )

        track_length = max(
            (float(section.start_dlong) + float(section.length) for section in sections),
            default=0.0,
        )
        if track_length <= 0.0:
            return None

        start = float(preview_line.start_dlong) % track_length
        end = float(preview_line.end_dlong) % track_length
        span = (end - start) % track_length
        if math.isclose(span, 0.0):
            return None

        midpoint_dlong = (start + span * 0.5) % track_length
        midpoint_dlat = float(preview_line.start_dlat) + (
            float(preview_line.end_dlat) - float(preview_line.start_dlat)
        ) * 0.5
        return self._point_on_track_at_dlong(sections, midpoint_dlong, midpoint_dlat, track_length)

    @staticmethod
    def _point_on_track_at_dlong(
        sections: list[SectionPreview],
        dlong: float,
        dlat: float,
        track_length: float,
    ) -> Point | None:
        if not sections or track_length <= 0.0:
            return None

        wrapped_dlong = float(dlong) % track_length
        for section in sections:
            length = float(section.length)
            if length <= 0.0:
                continue
            start = float(section.start_dlong)
            end = start + length
            in_range = start <= wrapped_dlong < end
            if end > track_length:
                wrapped_end = end - track_length
                in_range = in_range or wrapped_dlong < wrapped_end
            if not in_range:
                continue

            fraction = (wrapped_dlong - start) / length
            if end > track_length and wrapped_dlong < start:
                fraction = (wrapped_dlong + track_length - start) / length
            fraction = max(0.0, min(1.0, fraction))
            return TsdController._point_on_section(section, fraction, dlat)

        return TsdController._point_on_section(sections[-1], 1.0, dlat)

    @staticmethod
    def _point_on_section(section: SectionPreview, fraction: float, dlat: float) -> Point:
        sx, sy = section.start
        ex, ey = section.end
        center = section.center

        if center is None:
            dx = ex - sx
            dy = ey - sy
            cx = sx + dx * fraction
            cy = sy + dy * fraction
            length = math.hypot(dx, dy)
            if length <= 0.0:
                return (cx, cy)
            nx = -dy / length
            ny = dx / length
            return (cx + nx * dlat, cy + ny * dlat)

        center_x, center_y = center
        start_vec = (sx - center_x, sy - center_y)
        end_vec = (ex - center_x, ey - center_y)
        base_radius = math.hypot(start_vec[0], start_vec[1])
        if base_radius <= 0.0:
            return (sx, sy)

        start_angle = math.atan2(start_vec[1], start_vec[0])
        end_angle = math.atan2(end_vec[1], end_vec[0])

        heading = section.start_heading
        if heading is not None:
            cross = start_vec[0] * heading[1] - start_vec[1] * heading[0]
            ccw = cross > 0 if not math.isclose(cross, 0.0, abs_tol=1e-12) else (
                start_vec[0] * end_vec[1] - start_vec[1] * end_vec[0]
            ) > 0
        else:
            ccw = (start_vec[0] * end_vec[1] - start_vec[1] * end_vec[0]) > 0

        delta = end_angle - start_angle
        if ccw:
            while delta <= 0:
                delta += math.tau
        else:
            while delta >= 0:
                delta -= math.tau

        angle = start_angle + delta * fraction
        radius = max(0.0, base_radius + (-1.0 if ccw else 1.0) * dlat)
        return (
            center_x + math.cos(angle) * radius,
            center_y + math.sin(angle) * radius,
        )

    def _schedule_tsd_preview_refresh(self, *_args: object) -> None:
        if self._suspend_tsd_preview_refresh:
            return
        self._tsd_preview_refresh_timer.start()

    def _refresh_tsd_preview_lines(self) -> None:
        started = perf_counter()
        sections, _ = self._window.preview.get_section_set()

        range_started = perf_counter()
        adjusted_to_sg_ranges = self._build_adjusted_to_sg_ranges(sections)
        self._last_tsd_adjusted_to_sg_ranges = adjusted_to_sg_ranges
        self._log_tsd_perf("build adjusted_to_sg_ranges", range_started)

        convert_started = perf_counter()
        lines = list(self._all_tsd_lines())
        preview_lines = [
            self._convert_tsd_line_for_preview(line, sections, adjusted_to_sg_ranges)
            for line in lines
        ]
        self._last_tsd_preview_lines = list(preview_lines)
        self._log_tsd_perf("convert TSD lines", convert_started)

        set_started = perf_counter()
        self._window.preview.set_tsd_lines(tuple(preview_lines))
        self._log_tsd_perf("preview.set_tsd_lines", set_started)
        self._log_tsd_perf("TSD preview refresh duration", started)

    def _on_tsd_data_changed(
        self,
        top_left: QtCore.QModelIndex,
        bottom_right: QtCore.QModelIndex,
        _roles: list[int] | None = None,
    ) -> None:
        if self._suspend_tsd_preview_refresh:
            return
        if not top_left.isValid() or not bottom_right.isValid():
            self._schedule_tsd_preview_refresh()
            return
        if top_left.row() != bottom_right.row():
            self._schedule_tsd_preview_refresh()
            return

        row = top_left.row()
        line = self._tsd_lines_model.line_at(row)
        if line is None:
            self._schedule_tsd_preview_refresh()
            return

        sections, _ = self._window.preview.get_section_set()
        adjusted_to_sg_ranges = self._last_tsd_adjusted_to_sg_ranges
        if not adjusted_to_sg_ranges[0]:
            adjusted_to_sg_ranges = self._build_adjusted_to_sg_ranges(sections)
            self._last_tsd_adjusted_to_sg_ranges = adjusted_to_sg_ranges

        if row >= len(self._last_tsd_preview_lines):
            self._schedule_tsd_preview_refresh()
            return

        self._last_tsd_preview_lines[row] = self._convert_tsd_line_for_preview(
            line,
            sections,
            adjusted_to_sg_ranges,
        )
        self._window.preview.set_tsd_lines(tuple(self._last_tsd_preview_lines))
        self._autosize_tsd_lines_table_columns()
        self._sync_active_tsd_file_from_model()
        self._set_tsd_dirty(True)
        self._persist_tsd_state_for_current_track()

    def _log_tsd_perf(self, label: str, started: float) -> None:
        if not self._debug_tsd_perf:
            return
        print(f"[tsd_perf] {label}: {(perf_counter() - started) * 1000:.2f} ms")

    def _build_tsd_file_from_model(self) -> TrackSurfaceDetailFile:
        lines = self._tsd_lines_model.all_lines()
        if not lines:
            raise ValueError("No TSD lines to export.")
        return TrackSurfaceDetailFile(lines=lines)

    def _convert_tsd_line_for_preview(
        self,
        line: TrackSurfaceDetailLine,
        sections: list[SectionPreview],
        adjusted_to_sg_ranges: tuple[
            list[tuple[float, float, float, float]],
            list[float],
        ],
    ) -> TrackSurfaceDetailLine:
        if not sections:
            return line

        start_dlong = self._adjusted_dlong_to_sg_dlong(
            line.start_dlong,
            adjusted_to_sg_ranges,
        )
        end_dlong = self._adjusted_dlong_to_sg_dlong(
            line.end_dlong,
            adjusted_to_sg_ranges,
        )
        return TrackSurfaceDetailLine(
            color_index=line.color_index,
            width_500ths=line.width_500ths,
            start_dlong=start_dlong,
            start_dlat=line.start_dlat,
            end_dlong=end_dlong,
            end_dlat=line.end_dlat,
            command=line.command,
        )

    def _build_adjusted_to_sg_ranges(
        self,
        sections: list[SectionPreview],
    ) -> tuple[list[tuple[float, float, float, float]], list[float]]:
        return build_adjusted_to_sg_ranges(sections, self._window.adjusted_section_range_500ths)

    def _find_adjusted_segment_index(
        self,
        normalized_dlong: float,
        section_ranges: list[tuple[float, float, float, float]],
        section_boundaries: list[float],
    ) -> int | None:
        return find_adjusted_segment_index(normalized_dlong, section_ranges, section_boundaries)

    def _adjusted_dlong_to_sg_dlong(
        self,
        adjusted_dlong: int,
        adjusted_to_sg_ranges: tuple[
            list[tuple[float, float, float, float]],
            list[float],
        ],
    ) -> int:
        return adjusted_dlong_to_sg_dlong(adjusted_dlong, adjusted_to_sg_ranges)


    def _all_tsd_lines(self) -> tuple[TrackSurfaceDetailLine, ...]:
        lines = list(self._tsd_lines_model.all_lines())
        for obj in self._tsd_objects:
            lines.extend(obj.generated_lines())
        if self._tsd_object_dialog_preview_object is not None:
            lines.extend(self._tsd_object_dialog_preview_object.generated_lines())
        lines.extend(self._generated_skid_mark_lines)
        return tuple(lines)

    def _on_tsd_skid_marks_requested(self) -> None:
        section_columns: tuple[tuple[str, str], ...] = (
            ("Section", "Section label used only for readability in this table."),
            ("Start dLong", "Section start position along track in dlong units."),
            ("Apex dLong", "Apex position in dlong units where lateral range transitions."),
            ("End dLong", "Section end position along track in dlong units."),
            ("Min Length", "Minimum skid length to generate in dlong units."),
            ("Max Length", "Maximum skid length to generate in dlong units."),
            ("Width (dLat)", "Skid mark width (dlat span) in 1/10000 track units."),
            ("Count", "How many randomized skid marks to generate for this section."),
            ("Start dLat In", "Inside/lower dlat boundary at section start."),
            ("Start dLat Out", "Outside/upper dlat boundary at section start."),
            ("Apex dLat In", "Inside/lower dlat boundary at apex."),
            ("Apex dLat Out", "Outside/upper dlat boundary at apex."),
            ("End dLat In", "Inside/lower dlat boundary at section end."),
            ("End dLat Out", "Outside/upper dlat boundary at section end."),
        )

        def _rows_csv_to_table(table: QtWidgets.QTableWidget, rows_csv: str) -> None:
            lines = [line.strip() for line in rows_csv.splitlines() if line.strip()]
            table.setRowCount(max(1, len(lines)))
            for row_index, line in enumerate(lines):
                values = [value.strip() for value in line.split(",")]
                for column_index in range(len(section_columns)):
                    value = values[column_index] if column_index < len(values) else ""
                    table.setItem(row_index, column_index, QtWidgets.QTableWidgetItem(value))

        def _table_to_rows_csv(table: QtWidgets.QTableWidget) -> str:
            rows: list[str] = []
            for row_index in range(table.rowCount()):
                values: list[str] = []
                has_value = False
                for column_index in range(table.columnCount()):
                    item = table.item(row_index, column_index)
                    value = item.text().strip() if item is not None else ""
                    values.append(value)
                    if value:
                        has_value = True
                if has_value:
                    rows.append(",".join(values))
            return "\n".join(rows)

        dialog = QtWidgets.QDialog(self._window)
        dialog.setWindowTitle("Generate Skid Marks")
        dialog.setWindowModality(QtCore.Qt.NonModal)
        dialog.resize(1180, 520)
        layout = QtWidgets.QVBoxLayout(dialog)
        info_label = QtWidgets.QLabel(
            "This tool generates randomized skid-mark line details that follow the dLong/dLat ranges you define below. "
            "Each row describes one track section, and the generator picks random start points, lengths, and colors "
            "inside those limits. Start with one section, generate a few times, then tune boundaries and count to "
            "shape how dense and wide the marks appear. Hover each column header for details."
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        colors_edit = QtWidgets.QLineEdit(",".join(str(value) for value in self._skid_marks_colors), dialog)
        colors_edit.setToolTip("Comma-separated palette indices used when assigning skid mark colors.")
        sections_table = QtWidgets.QTableWidget(dialog)
        sections_table.setColumnCount(len(section_columns))
        sections_table.setHorizontalHeaderLabels([name for name, _tooltip in section_columns])
        sections_table.verticalHeader().setVisible(True)
        sections_table.setAlternatingRowColors(True)
        sections_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        sections_table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        sections_table.horizontalHeader().setStretchLastSection(True)
        for column_index, (_name, tooltip) in enumerate(section_columns):
            item = sections_table.horizontalHeaderItem(column_index)
            if item is not None:
                item.setToolTip(tooltip)
        _rows_csv_to_table(sections_table, self._skid_marks_rows_text)

        sections_buttons = QtWidgets.QHBoxLayout()
        add_row_button = QtWidgets.QPushButton("Add section row", dialog)
        add_row_button.setToolTip("Append a blank row for another skid-generation section.")
        remove_row_button = QtWidgets.QPushButton("Remove selected rows", dialog)
        remove_row_button.setToolTip("Delete selected section rows from the table.")
        sections_buttons.addWidget(add_row_button)
        sections_buttons.addWidget(remove_row_button)
        sections_buttons.addStretch(1)

        layout.addWidget(QtWidgets.QLabel("Colors (comma-separated palette indices):"))
        layout.addWidget(colors_edit)
        layout.addWidget(QtWidgets.QLabel("Section rows:"))
        layout.addLayout(sections_buttons)
        layout.addWidget(sections_table)
        buttons = QtWidgets.QDialogButtonBox(parent=dialog)
        randomize_button = buttons.addButton("Randomize skid marks", QtWidgets.QDialogButtonBox.ActionRole)
        save_button = buttons.addButton("Save generated .TSD…", QtWidgets.QDialogButtonBox.ActionRole)
        close_button = buttons.addButton(QtWidgets.QDialogButtonBox.Close)
        close_button.clicked.connect(dialog.reject)
        layout.addWidget(buttons)

        def _add_row() -> None:
            sections_table.insertRow(sections_table.rowCount())

        def _remove_selected_rows() -> None:
            selected_rows = sorted({index.row() for index in sections_table.selectedIndexes()}, reverse=True)
            for row_index in selected_rows:
                sections_table.removeRow(row_index)
            if sections_table.rowCount() == 0:
                sections_table.setRowCount(1)

        add_row_button.clicked.connect(_add_row)
        remove_row_button.clicked.connect(_remove_selected_rows)

        def _parse_parameters_from_dialog() -> SkidMarkGenerationParameters:
            colors = parse_colors_csv(colors_edit.text())
            sections = parse_skid_sections_csv(_table_to_rows_csv(sections_table))
            if not sections:
                raise ValueError("Add at least one section row before generating skid marks.")
            return SkidMarkGenerationParameters(colors=colors, sections=sections)

        def _persist_dialog_values() -> None:
            self._skid_marks_rows_text = _table_to_rows_csv(sections_table)
            self._skid_marks_colors = parse_colors_csv(colors_edit.text())
            self._set_tsd_dirty(True)
            self._persist_tsd_state_for_current_track()

        def _generate() -> None:
            try:
                parameters = _parse_parameters_from_dialog()
            except ValueError as exc:
                QtWidgets.QMessageBox.warning(dialog, "Skid Marks", str(exc))
                return
            self._generated_skid_mark_lines = generate_skid_mark_lines(
                parameters,
                rng=random.Random(),
            )
            _persist_dialog_values()
            self._refresh_tsd_preview_lines()
            self._window.show_status_message(
                f"Generated {len(self._generated_skid_mark_lines)} randomized skid mark lines."
            )

        def _save_generated() -> None:
            if not self._generated_skid_mark_lines:
                QtWidgets.QMessageBox.information(
                    dialog,
                    "Save Generated Skid Marks",
                    "Generate skid marks first.",
                )
                return
            output_path, _selected_filter = QtWidgets.QFileDialog.getSaveFileName(
                self._window,
                "Save Generated Skid Marks",
                self._dialog_default_file_path("skid_marks.tsd"),
                "TSD Files (*.tsd)",
            )
            if not output_path:
                return
            path = Path(output_path)
            if path.suffix.lower() != ".tsd":
                path = path.with_suffix(".tsd")
            try:
                path.write_text(
                    serialize_tsd(TrackSurfaceDetailFile(lines=self._generated_skid_mark_lines)),
                    encoding="utf-8",
                )
            except OSError as exc:
                QtWidgets.QMessageBox.critical(dialog, "Save Generated Skid Marks", str(exc))
                return
            self._window.show_status_message(f"Saved generated skid marks to {path.name}.")

        randomize_button.clicked.connect(_generate)
        save_button.clicked.connect(_save_generated)
        self._skid_marks_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _refresh_tsd_objects_table(self) -> None:
        table = self._window.tsd_objects_table
        previous_state = table.blockSignals(True)
        try:
            table.setRowCount(len(self._tsd_objects))
            for row, obj in enumerate(self._tsd_objects):
                if isinstance(obj, TsdTransverseLineObject):
                    object_type_label = "Transverse Line"
                elif isinstance(obj, TsdDoubleSolidLineObject):
                    object_type_label = "Double Solid Line"
                elif isinstance(obj, TsdDashedLinesObject):
                    object_type_label = "Dashed Lines"
                elif isinstance(obj, TsdPitStallsObject):
                    object_type_label = "Pit Stalls"
                else:
                    object_type_label = "Zebra crossing"
                start_dlong, end_dlong = self._tsd_object_dlong_range(obj)
                values = [obj.name, object_type_label, str(start_dlong), str(end_dlong)]
                for column, value in enumerate(values):
                    item = table.item(row, column)
                    if item is None:
                        item = QtWidgets.QTableWidgetItem(value)
                        table.setItem(row, column, item)
                    else:
                        item.setText(value)
                    item.setTextAlignment(int(QtCore.Qt.AlignCenter))
                    item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
                button = QtWidgets.QPushButton("Edit…")
                button.clicked.connect(
                    lambda _checked=False, row_index=row: self._open_tsd_object_attributes_dialog(row_index)
                )
                table.setCellWidget(row, 4, button)
        finally:
            table.blockSignals(previous_state)

    @staticmethod
    def _selected_row_indices(selection_model: QtCore.QItemSelectionModel | None) -> list[int]:
        if selection_model is None:
            return []
        row_indices = {index.row() for index in selection_model.selectedIndexes() if index.row() >= 0}
        return sorted(row_indices)

    def _on_tsd_add_object_requested(self) -> None:
        self._editing_tsd_object_index = None
        new_object = self._open_tsd_object_dialog()
        self._tsd_object_dialog_preview_object = None
        if new_object is None:
            self._refresh_tsd_preview_lines()
            return
        self._tsd_objects.append(new_object)
        self._refresh_tsd_objects_table()
        self._refresh_tsd_preview_lines()
        self._set_tsd_dirty(True)
        self._persist_tsd_state_for_current_track()

    def _on_tsd_objects_table_cell_clicked(self, row: int, column: int) -> None:
        if column == 4:
            self._open_tsd_object_attributes_dialog(row)

    def _on_tsd_object_selection_changed(self) -> None:
        selected_rows = self._selected_row_indices(self._window.tsd_objects_table.selectionModel())
        if not selected_rows:
            return
        self._center_viewport_on_tsd_object(selected_rows[0])

    def _center_viewport_on_tsd_object(self, row: int) -> None:
        if row < 0 or row >= len(self._tsd_objects):
            return
        center_point = self._tsd_object_center_point(self._tsd_objects[row])
        if center_point is None:
            return
        self._window.preview.center_view_on_point(center_point)

    @staticmethod
    def _tsd_object_dlong_range(
        obj: TsdZebraCrossingObject | TsdTransverseLineObject | TsdDoubleSolidLineObject | TsdDashedLinesObject | TsdPitStallsObject,
    ) -> tuple[int, int]:
        lines = obj.generated_lines()
        if not lines:
            return 0, 0
        start_dlong = min(int(line.start_dlong) for line in lines)
        end_dlong = max(int(line.end_dlong) for line in lines)
        return start_dlong, end_dlong

    def _tsd_object_center_point(
        self,
        obj: TsdZebraCrossingObject | TsdTransverseLineObject | TsdDoubleSolidLineObject | TsdDashedLinesObject | TsdPitStallsObject,
    ) -> Point | None:
        lines = obj.generated_lines()
        if not lines:
            return None
        start_dlong, end_dlong = self._tsd_object_dlong_range(obj)
        center_dlong = start_dlong + (end_dlong - start_dlong) * 0.5
        reference_line = lines[0]
        center_dlat = float(reference_line.start_dlat) + (
            float(reference_line.end_dlat) - float(reference_line.start_dlat)
        ) * 0.5
        sections, _ = self._window.preview.get_section_set()
        track_length = max(
            (float(section.start_dlong) + float(section.length) for section in sections),
            default=0.0,
        )
        if track_length <= 0.0:
            return None
        return self._point_on_track_at_dlong(
            sections,
            center_dlong % track_length,
            center_dlat,
            track_length,
        )

    def _on_tsd_remove_selected_object_requested(self) -> None:
        selected_rows = sorted(
            {
                row
                for row in self._selected_row_indices(self._window.tsd_objects_table.selectionModel())
            },
            reverse=True,
        )
        if not selected_rows:
            QtWidgets.QMessageBox.information(
                self._window,
                "Remove TSD Object",
                "Select one or more TSD objects to remove.",
            )
            return
        for row in selected_rows:
            if 0 <= row < len(self._tsd_objects):
                del self._tsd_objects[row]
        self._refresh_tsd_objects_table()
        self._refresh_tsd_preview_lines()
        self._set_tsd_dirty(True)
        self._persist_tsd_state_for_current_track()

    def _on_tsd_duplicate_object_requested(self) -> None:
        selected_rows = self._selected_row_indices(self._window.tsd_objects_table.selectionModel())
        if not selected_rows:
            QtWidgets.QMessageBox.information(
                self._window,
                "Duplicate TSD Object",
                "Select a TSD object to duplicate.",
            )
            return
        source_row = selected_rows[0]
        if source_row < 0 or source_row >= len(self._tsd_objects):
            return
        duplicated_object = replace(self._tsd_objects[source_row])
        self._tsd_objects.insert(source_row + 1, duplicated_object)
        self._refresh_tsd_objects_table()
        self._window.tsd_objects_table.selectRow(source_row + 1)
        self._center_viewport_on_tsd_object(source_row + 1)
        self._refresh_tsd_preview_lines()
        self._set_tsd_dirty(True)
        self._persist_tsd_state_for_current_track()

    def _move_tsd_object(self, *, direction: int) -> None:
        selected_rows = self._selected_row_indices(self._window.tsd_objects_table.selectionModel())
        if not selected_rows:
            return
        source_row = selected_rows[0]
        target_row = source_row + direction
        if target_row < 0 or target_row >= len(self._tsd_objects):
            return
        self._tsd_objects[source_row], self._tsd_objects[target_row] = (
            self._tsd_objects[target_row],
            self._tsd_objects[source_row],
        )
        self._refresh_tsd_objects_table()
        self._window.tsd_objects_table.selectRow(target_row)
        self._center_viewport_on_tsd_object(target_row)
        self._refresh_tsd_preview_lines()
        self._set_tsd_dirty(True)
        self._persist_tsd_state_for_current_track()

    def _on_tsd_move_object_up_requested(self) -> None:
        self._move_tsd_object(direction=-1)

    def _on_tsd_move_object_down_requested(self) -> None:
        self._move_tsd_object(direction=1)

    def _open_tsd_object_attributes_dialog(self, row: int) -> None:
        if row < 0 or row >= len(self._tsd_objects):
            return
        original_object = self._tsd_objects[row]
        self._editing_tsd_object_index = row
        updated = self._open_tsd_object_dialog(existing=self._tsd_objects[row])
        self._editing_tsd_object_index = None
        self._tsd_object_dialog_preview_object = None
        if updated is None:
            self._tsd_objects[row] = original_object
            self._refresh_tsd_preview_lines()
            return
        self._tsd_objects[row] = updated
        self._refresh_tsd_preview_lines()
        self._refresh_tsd_objects_table()
        self._set_tsd_dirty(True)
        self._persist_tsd_state_for_current_track()

    def _open_tsd_object_dialog(
        self,
        *,
        existing: TsdObjectPayload | None = None,
    ) -> TsdObjectPayload | None:
        dialog = TsdObjectDialog(
            self._window,
            self,
            object_count=len(self._tsd_objects),
            selected_section_index=self._window.preview.selection_manager.selected_section_index,
            existing=existing,
        )
        return dialog.get_payload()

    def _on_tsd_export_objects_requested(self) -> None:
        if not self._tsd_objects:
            QtWidgets.QMessageBox.information(self._window, "Export TSD Objects", "No TSD objects to export.")
            return
        output_path, _selected_filter = QtWidgets.QFileDialog.getSaveFileName(
            self._window,
            "Export TSD Objects",
            self._dialog_default_directory(),
            "TSD Files (*.tsd)",
        )
        if not output_path:
            return
        tsd_path = Path(output_path)
        if tsd_path.suffix.lower() != ".tsd":
            tsd_path = tsd_path.with_suffix(".tsd")
        combined_lines: list[TrackSurfaceDetailLine] = []
        for obj in self._tsd_objects:
            combined_lines.extend(obj.generated_lines())
        tsd_path.write_text(
            serialize_tsd(TrackSurfaceDetailFile(lines=tuple(combined_lines))),
            encoding="utf-8",
        )
        self._window.show_status_message(
            f"Exported {len(self._tsd_objects)} TSD objects into {tsd_path.name}"
        )


