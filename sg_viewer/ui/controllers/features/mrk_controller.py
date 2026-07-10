from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Callable

from PyQt5 import QtCore, QtGui, QtWidgets

from sg_viewer.services.mrk_logic import (
    auto_detect_mrk_side,
    mrk_target_length_for_surface_type,
    normalize_mrk_side,
)
from sg_viewer.services.mrk_io import (
    MarkBoundaryEntry,
    MarkFile,
    MarkTrackPosition,
    MarkUvRect,
    serialize_mrk,
)
from sg_viewer.ui.altitude_units import units_from_500ths
from sg_viewer.ui.color_utils import parse_hex_color
from sg_viewer.ui.manual_wall_height_dialog import (
    ManualWallHeightOverride,
    ManualWallHeightOverridesDialog,
)
from sg_viewer.ui.mrk_textures_dialog import (
    MrkTextureDefinition,
    MrkTexturePatternDialog,
    MrkTexturesDialog,
)

logger = logging.getLogger(__name__)


class MrkExportLocationsDialog(QtWidgets.QDialog):
    """Dialog for project-persisted MRK/pitwall export locations."""

    def __init__(
        self,
        pitwall_path: Path,
        mrk_path: Path,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("MRK Export Locations")
        self._pitwall_edit = QtWidgets.QLineEdit(str(pitwall_path))
        self._mrk_edit = QtWidgets.QLineEdit(str(mrk_path))

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        form.addRow(
            "pitwall.txt:",
            self._path_row(
                self._pitwall_edit,
                "Select pitwall.txt Location",
                "Text Files (*.txt);;All Files (*)",
            ),
        )
        form.addRow(
            "<track>.mrk:",
            self._path_row(
                self._mrk_edit,
                "Select MRK File Location",
                "MRK Files (*.mrk);;All Files (*)",
            ),
        )
        layout.addLayout(form)
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _path_row(
        self, edit: QtWidgets.QLineEdit, title: str, file_filter: str
    ) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget(self)
        layout = QtWidgets.QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(edit)
        button = QtWidgets.QPushButton("Browse...")
        button.clicked.connect(lambda: self._browse(edit, title, file_filter))
        layout.addWidget(button)
        return widget

    def _browse(self, edit: QtWidgets.QLineEdit, title: str, file_filter: str) -> None:
        path_str, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, title, edit.text(), file_filter
        )
        if path_str:
            edit.setText(path_str)

    def paths(self) -> tuple[Path, Path]:
        return Path(self._pitwall_edit.text()).expanduser(), Path(self._mrk_edit.text()).expanduser()


class _MrkTexturePatternDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(
        self,
        parent: QtWidgets.QWidget,
        color_lookup_provider: Callable[[], dict[str, QtGui.QColor]],
    ) -> None:
        super().__init__(parent)
        self._color_lookup_provider = color_lookup_provider
        self._show_color_boxes = True

    def set_show_color_boxes(self, show_color_boxes: bool) -> None:
        self._show_color_boxes = bool(show_color_boxes)

    def paint(
        self,
        painter: QtGui.QPainter,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> None:
        pattern_text = str(index.data(QtCore.Qt.DisplayRole) or "").strip()
        if not self._show_color_boxes:
            super().paint(painter, option, index)
            return
        texture_names = [token.strip() for token in pattern_text.split(",") if token.strip()]
        color_lookup = self._color_lookup_provider()
        colors = [color_lookup.get(name) for name in texture_names]
        colors = [color for color in colors if color is not None and color.isValid()]
        if not colors:
            super().paint(painter, option, index)
            return

        painter.save()
        style = option.widget.style() if option.widget is not None else QtWidgets.QApplication.style()
        style.drawPrimitive(QtWidgets.QStyle.PE_PanelItemViewItem, option, painter, option.widget)

        rect = option.rect.adjusted(4, 4, -4, -4)
        if rect.width() > 0 and rect.height() > 0:
            segment_width = rect.width() / float(len(colors))
            for segment_index, color in enumerate(colors):
                left = rect.left() + int(round(segment_index * segment_width))
                right = rect.left() + int(round((segment_index + 1) * segment_width))
                segment_rect = QtCore.QRect(left, rect.top(), max(1, right - left), rect.height())
                painter.fillRect(segment_rect, color)
            painter.setPen(QtGui.QPen(option.palette.mid().color()))
            painter.drawRect(rect)
        painter.restore()

    def sizeHint(
        self,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> QtCore.QSize:
        base_size = super().sizeHint(option, index)
        return QtCore.QSize(base_size.width(), max(base_size.height(), 22))


class MrkController:
    def __init__(self, host: object) -> None:
        self._host = host
        self._mrk_texture_pattern_delegate = _MrkTexturePatternDelegate(
            self._window.mrk_entries_table,
            self._mrk_texture_color_lookup,
        )
        self._window.mrk_entries_table.setItemDelegateForColumn(5, self._mrk_texture_pattern_delegate)
        self._mrk_texture_pattern_delegate.set_show_color_boxes(
            self._window.mrk_texture_pattern_show_colors_checkbox.isChecked()
        )

    def __getattr__(self, name: str):
        return getattr(self._host, name)

    @property
    def _mrk_texture_definitions(self): return self._host._mrk_state.texture_definitions
    @_mrk_texture_definitions.setter
    def _mrk_texture_definitions(self, value): self._host._mrk_state.texture_definitions = value
    @property
    def _mrk_is_dirty(self): return self._host._mrk_state.is_dirty
    @_mrk_is_dirty.setter
    def _mrk_is_dirty(self, value): self._host._mrk_state.is_dirty = value
    @property
    def _manual_wall_height_overrides(self): return self._host._mrk_state.manual_wall_height_overrides
    @_manual_wall_height_overrides.setter
    def _manual_wall_height_overrides(self, value): self._host._mrk_state.manual_wall_height_overrides = value

    def connect_signals(self) -> None:
        h = self._host
        w = self._window
        w.mrk_add_entry_button.clicked.connect(self._on_mrk_add_entry_requested)
        w.mrk_delete_entry_button.clicked.connect(self._on_mrk_delete_entry_requested)
        w.mrk_move_up_button.clicked.connect(self._on_mrk_move_up_requested)
        w.mrk_move_down_button.clicked.connect(self._on_mrk_move_down_requested)
        w.mrk_sort_by_section_button.clicked.connect(self._on_mrk_sort_by_section_requested)
        w.mrk_sort_by_boundary_button.clicked.connect(self._on_mrk_sort_by_boundary_requested)
        w.mrk_textures_button.clicked.connect(self._on_mrk_textures_requested)
        w.mrk_generate_file_button.clicked.connect(self._on_mrk_generate_file_requested)
        w.mrk_export_locations_button.clicked.connect(self._on_mrk_export_locations_requested)
        w.mrk_save_button.clicked.connect(self._on_mrk_save_requested)
        w.mrk_load_button.clicked.connect(self._on_mrk_load_requested)
        w.mrk_texture_pattern_show_colors_checkbox.toggled.connect(self._on_mrk_texture_pattern_display_mode_changed)
        w.generate_pitwall_button.clicked.connect(self._generate_pitwall_txt)
        w.manual_wall_height_overrides_button.clicked.connect(self._on_manual_wall_height_overrides_requested)
        w.pitwall_wall_height_spin.valueChanged.connect(self._on_mrk_wall_height_changed)
        w.pitwall_armco_height_spin.valueChanged.connect(self._on_mrk_armco_height_changed)
        w.pitwall_length_multiplier_spin.valueChanged.connect(self._on_mrk_length_multiplier_changed)
        w.preview.set_mrk_length_multiplier(w.pitwall_length_multiplier())
        h._mrk_add_entry_action.triggered.connect(self._on_mrk_add_entry_requested)
        h._mrk_delete_entry_action.triggered.connect(self._on_mrk_delete_entry_requested)
        h._mrk_move_up_action.triggered.connect(self._on_mrk_move_up_requested)
        h._mrk_move_down_action.triggered.connect(self._on_mrk_move_down_requested)
        h._mrk_textures_action.triggered.connect(self._on_mrk_textures_requested)
        h._mrk_generate_file_action.triggered.connect(self._on_mrk_generate_file_requested)
        h._mrk_save_entries_action.triggered.connect(self._on_mrk_save_requested)
        h._mrk_load_entries_action.triggered.connect(self._on_mrk_load_requested)
        w.mrk_entries_table.itemSelectionChanged.connect(self._on_mrk_entry_selection_changed)
        w.mrk_entries_table.itemChanged.connect(self._on_mrk_entry_item_changed)
        w.mrk_entries_table.cellDoubleClicked.connect(self._on_mrk_entry_cell_double_clicked)

    def _on_manual_wall_height_overrides_requested(self) -> None:
        dialog = ManualWallHeightOverridesDialog(
            list(self._manual_wall_height_overrides),
            self._window,
        )
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        self._manual_wall_height_overrides = dialog.overrides()
        self._persist_manual_wall_height_overrides_for_current_track()
        self._window.set_wall_defaults_override_count(
            len(self._manual_wall_height_overrides)
        )
        self._window.show_status_message(
            f"Saved {len(self._manual_wall_height_overrides)} manual wall height override(s)."
        )

    def _default_export_paths(self) -> tuple[Path, Path]:
        base_dir = Path(self._dialog_default_directory())
        track_name = self._current_path.stem if self._current_path is not None else "track"
        return base_dir / "pitwall.txt", base_dir / f"{track_name}.mrk"

    def _configured_export_paths(self) -> tuple[Path, Path]:
        pitwall_path, mrk_path = self._default_export_paths()
        if self._current_path is not None:
            locations = self._sg_settings_store.get_mrk_export_locations(self._current_path)
            pitwall_path = locations.get("pitwall_txt", pitwall_path)
            mrk_path = locations.get("mrk_file", mrk_path)
        return pitwall_path, mrk_path

    def _persist_export_paths(self, pitwall_path: Path, mrk_path: Path) -> None:
        if self._current_path is None:
            return
        self._sg_settings_store.set_mrk_export_locations(
            self._current_path, pitwall_path, mrk_path
        )

    def _on_mrk_export_locations_requested(self) -> None:
        pitwall_path, mrk_path = self._configured_export_paths()
        dialog = MrkExportLocationsDialog(pitwall_path, mrk_path, self._window)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        pitwall_path, mrk_path = dialog.paths()
        if not pitwall_path.suffix:
            pitwall_path = pitwall_path.with_suffix(".txt")
        if mrk_path.suffix.lower() != ".mrk":
            mrk_path = mrk_path.with_suffix(".mrk")
        self._persist_export_paths(pitwall_path, mrk_path)
        self._window.show_status_message("Updated MRK export locations.")

    def _pitwall_export_path(self) -> Path | None:
        pitwall_path, _mrk_path = self._configured_export_paths()
        return pitwall_path if pitwall_path.suffix else pitwall_path.with_suffix(".txt")

    def _mrk_export_path(self) -> Path | None:
        _pitwall_path, mrk_path = self._configured_export_paths()
        return mrk_path if mrk_path.suffix.lower() == ".mrk" else mrk_path.with_suffix(".mrk")

    def _confirm_export_overwrite(self, path: Path) -> bool:
        if not path.exists():
            return True
        response = QtWidgets.QMessageBox.warning(
            self._window,
            "Overwrite Export File",
            f"{path} already exists. Overwrite the previous version?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return response == QtWidgets.QMessageBox.Yes

    def _generate_pitwall_txt(self) -> None:
        sections, _ = self._window.preview.get_section_set()
        if not sections:
            QtWidgets.QMessageBox.information(
                self._window,
                "Generate pitwall.txt",
                "There are no track sections available.",
            )
            return

        wall_height = self._window.pitwall_wall_height_500ths()
        armco_height = self._window.pitwall_armco_height_500ths()

        path = self._pitwall_export_path()
        if path is None or not self._confirm_export_overwrite(path):
            return

        generated_entries: list[tuple[int, int, int, int]] = []
        for section_index, _section in enumerate(sections):
            section_range = self._window.adjusted_section_range_500ths(section_index)
            if section_range is None:
                fallback_range = self._window.preview.get_section_range(section_index)
                if fallback_range is None:
                    continue
                start_dlong = int(round(fallback_range[0]))
                end_dlong = int(round(fallback_range[1]))
            else:
                start_dlong, end_dlong = section_range

            fsects = self._window.preview.get_section_fsects(section_index)
            boundary_rows = [
                (row_index, fsect)
                for row_index, fsect in enumerate(fsects)
                if fsect.surface_type in {7, 8}
            ]
            boundary_rows.sort(
                key=lambda row_fsect: (
                    min(row_fsect[1].start_dlat, row_fsect[1].end_dlat),
                    max(row_fsect[1].start_dlat, row_fsect[1].end_dlat),
                    row_fsect[0],
                )
            )
            for boundary_number, (_row_index, fsect) in enumerate(boundary_rows):
                height = wall_height if fsect.surface_type == 7 else armco_height
                generated_entries.append((boundary_number, start_dlong, end_dlong, height))

        lines = self._pitwall_lines_with_manual_overrides(generated_entries)

        try:
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as exc:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Generate pitwall.txt",
                f"Could not save pitwall file:\n{exc}",
            )
            return

        self._window.show_status_message(f"Generated {path.name} successfully.")

    def _confirm_discard_unsaved_mrk(self, title: str, action_description: str) -> bool:
        if not self._mrk_is_dirty:
            return True
        response = QtWidgets.QMessageBox.question(
            self._window,
            title,
            f"You have unsaved MRK changes. Continue and {action_description} without saving?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return response == QtWidgets.QMessageBox.Yes

    def _set_mrk_dirty(self, dirty: bool) -> None:
        self._mrk_is_dirty = dirty
        self._window.set_sidebar_tab_dirty("Walls", dirty)

    def _persist_mrk_state_for_current_track(self) -> None:
        if self._current_path is None:
            return
        self._sg_settings_store.set_mrk_state(self._current_path, self._collect_mrk_state())

    def _load_mrk_state_for_current_track(self) -> None:
        self._set_mrk_dirty(False)
        self._mrk_texture_definitions = ()
        table = self._window.mrk_entries_table
        table.blockSignals(True)
        table.setRowCount(0)
        table.blockSignals(False)

        if self._current_path is None:
            self._update_mrk_highlights_from_table()
            return

        state = self._sg_settings_store.get_mrk_state(self._current_path)
        if not isinstance(state, dict):
            self._update_mrk_highlights_from_table()
            return

        try:
            self._apply_mrk_state(state, mark_dirty=False)
        except ValueError:
            logger.warning("Unable to restore MRK state for %s", self._current_path, exc_info=True)
            self._mrk_texture_definitions = ()
            table.blockSignals(True)
            table.setRowCount(0)
            table.blockSignals(False)
            self._update_mrk_highlights_from_table()

    def _pitwall_lines_with_manual_overrides(
        self, generated_entries: list[tuple[int, int, int, int]]
    ) -> list[str]:
        overrides = [override.normalized() for override in self._manual_wall_height_overrides]
        output_entries: list[tuple[int, int, int, int]] = []
        for boundary, start, end, height in generated_entries:
            segments = [(min(start, end), max(start, end), height)]
            for override in overrides:
                if override.boundary != boundary:
                    continue
                next_segments: list[tuple[int, int, int]] = []
                for seg_start, seg_end, seg_height in segments:
                    overlap_start = max(seg_start, override.start_dlong)
                    overlap_end = min(seg_end, override.end_dlong)
                    if overlap_start >= overlap_end:
                        next_segments.append((seg_start, seg_end, seg_height))
                        continue
                    if seg_start < overlap_start:
                        next_segments.append((seg_start, overlap_start, seg_height))
                    if overlap_end < seg_end:
                        next_segments.append((overlap_end, seg_end, seg_height))
                segments = next_segments
            output_entries.extend((boundary, seg_start, seg_end, seg_height) for seg_start, seg_end, seg_height in segments)
        output_entries.extend((item.boundary, item.start_dlong, item.end_dlong, item.height) for item in overrides)
        output_entries.sort(key=lambda item: (item[1], item[2], item[0], item[3]))
        return [
            f"BOUNDARY {boundary}: {start} {end} HEIGHT {height}"
            for boundary, start, end, height in output_entries
            if start != end
        ]

    def _persist_manual_wall_height_overrides_for_current_track(self) -> None:
        if self._current_path is None:
            return
        self._sg_settings_store.set_manual_wall_height_overrides(
            self._current_path,
            [override.__dict__ for override in self._manual_wall_height_overrides],
        )

    def _load_manual_wall_height_overrides_for_current_track(self) -> None:
        self._manual_wall_height_overrides = []
        if self._current_path is None:
            self._window.set_wall_defaults_override_count(0)
            return
        self._manual_wall_height_overrides = [
            ManualWallHeightOverride(
                int(entry["boundary"]),
                int(entry["start_dlong"]),
                int(entry["end_dlong"]),
                int(entry["height"]),
            )
            for entry in self._sg_settings_store.get_manual_wall_height_overrides(self._current_path)
        ]
        self._window.set_wall_defaults_override_count(
            len(self._manual_wall_height_overrides)
        )

    def _persist_mrk_wall_heights_for_current_track(self) -> None:
        if self._current_path is None:
            return
        self._sg_settings_store.set_mrk_wall_heights(
            self._current_path,
            self._window.pitwall_wall_height_500ths(),
            self._window.pitwall_armco_height_500ths(),
            self._window.pitwall_length_multiplier(),
        )

    def _load_mrk_wall_heights_for_current_track(self) -> None:
        if self._current_path is None:
            return
        heights = self._sg_settings_store.get_mrk_wall_heights(self._current_path)
        if heights is None:
            return
        unit = self._window.current_measurement_unit()
        wall_height_500ths, armco_height_500ths, length_multiplier = heights
        self._window.pitwall_wall_height_spin.setValue(units_from_500ths(wall_height_500ths, unit))
        self._window.pitwall_armco_height_spin.setValue(units_from_500ths(armco_height_500ths, unit))
        self._window.pitwall_length_multiplier_spin.setValue(length_multiplier)

    def _on_mrk_wall_select_requested(self) -> None:
        table = self._window.mrk_entries_table
        selected_rows = table.selectionModel().selectedRows()
        if not selected_rows:
            self._window.preview.set_selected_mrk_wall(None, None, None)
            self._window.preview.set_selected_mrk_wall_range(None, None, None, None, None)
            self._update_mrk_highlights_from_table()
            return
        row = selected_rows[0].row()
        section_index = self._table_int_value(table, row, 0)
        boundary_index = self._table_int_value(table, row, 1)
        wall_index = self._table_int_value(table, row, 2)
        wall_count = max(1, self._table_int_value(table, row, 3))
        self._window.preview.set_selected_mrk_wall(
            boundary_index,
            section_index,
            wall_index,
        )
        model = self._window.preview.sg_preview_model
        end_section = section_index
        end_wall = wall_index + wall_count - 1
        if model is not None:
            try:
                positions = list(
                    self._iter_mrk_wall_positions(
                        model,
                        section_index=section_index,
                        boundary_index=boundary_index,
                        wall_index=wall_index,
                        wall_count=wall_count,
                    )
                )
            except ValueError:
                positions = []
            if positions:
                end_section, end_wall, _wall_ranges = positions[-1]
        self._window.preview.set_selected_mrk_wall_range(
            boundary_index,
            section_index,
            wall_index,
            end_section,
            end_wall,
        )
        self._update_mrk_highlights_from_table()

    def _on_mrk_add_entry_requested(self) -> None:
        table = self._window.mrk_entries_table
        selected_rows = table.selectionModel().selectedRows() if table.selectionModel() is not None else []
        if table.rowCount() == 0 or not selected_rows:
            row = 0
        else:
            row = selected_rows[0].row() + 1
        table.insertRow(row)
        values = [0, 0, 0, 1]
        for column, value in enumerate(values):
            item = QtWidgets.QTableWidgetItem(str(int(value)))
            item.setTextAlignment(int(QtCore.Qt.AlignCenter))
            table.setItem(row, column, item)
        self._set_mrk_side_cell(row, self._auto_detect_mrk_side(0, 0))
        table.setItem(row, 5, QtWidgets.QTableWidgetItem(""))
        table.setItem(row, 6, QtWidgets.QTableWidgetItem(""))
        table.selectRow(row)
        self._set_mrk_dirty(True)
        self._update_mrk_highlights_from_table()
        self._autosize_mrk_table_columns()

    def _on_mrk_delete_entry_requested(self) -> None:
        table = self._window.mrk_entries_table
        selected_rows = table.selectionModel().selectedRows()
        if not selected_rows:
            return
        table.removeRow(selected_rows[0].row())
        self._set_mrk_dirty(True)
        self._update_mrk_highlights_from_table()
        self._autosize_mrk_table_columns()

    def _move_mrk_entry(self, *, direction: int) -> None:
        table = self._window.mrk_entries_table
        selected_rows = table.selectionModel().selectedRows()
        if not selected_rows:
            return
        source_row = min(model_index.row() for model_index in selected_rows)
        target_row = source_row + direction
        if target_row < 0 or target_row >= table.rowCount():
            return

        source_values = [self._table_text_value(table, source_row, column) for column in range(7)]
        target_values = [self._table_text_value(table, target_row, column) for column in range(7)]

        table.blockSignals(True)
        for column in range(7):
            if column == 4:
                self._set_mrk_side_cell(source_row, target_values[column])
                self._set_mrk_side_cell(target_row, source_values[column])
                continue
            source_item = table.item(source_row, column)
            target_item = table.item(target_row, column)
            source_text = source_values[column]
            target_text = target_values[column]
            if source_item is None:
                source_item = QtWidgets.QTableWidgetItem()
                table.setItem(source_row, column, source_item)
            if target_item is None:
                target_item = QtWidgets.QTableWidgetItem()
                table.setItem(target_row, column, target_item)
            source_item.setText(target_text)
            target_item.setText(source_text)
            if column in {0, 1, 2, 3}:
                source_item.setTextAlignment(int(QtCore.Qt.AlignCenter))
                target_item.setTextAlignment(int(QtCore.Qt.AlignCenter))
        table.blockSignals(False)
        table.selectRow(target_row)
        self._set_mrk_dirty(True)
        self._update_mrk_highlights_from_table()
        self._autosize_mrk_table_columns()

    def _on_mrk_move_up_requested(self) -> None:
        self._move_mrk_entry(direction=-1)

    def _on_mrk_move_down_requested(self) -> None:
        self._move_mrk_entry(direction=1)

    def _sort_mrk_entries(self, sort_columns: tuple[int, ...]) -> None:
        table = self._window.mrk_entries_table
        row_count = table.rowCount()
        if row_count < 2:
            return

        rows = [
            [self._table_text_value(table, row, column) for column in range(7)]
            for row in range(row_count)
        ]

        def _sort_key(row_values: list[str]) -> tuple[object, ...]:
            key: list[object] = []
            for column in sort_columns:
                if column in {0, 1, 2, 3}:
                    try:
                        key.append(int(row_values[column].strip()))
                    except (TypeError, ValueError):
                        key.append(0)
                else:
                    key.append(row_values[column].casefold())
            return tuple(key)

        sorted_rows = sorted(rows, key=_sort_key)
        if sorted_rows == rows:
            return

        table.blockSignals(True)
        for row, row_values in enumerate(sorted_rows):
            for column, value in enumerate(row_values):
                if column == 4:
                    self._set_mrk_side_cell(row, value)
                    continue
                item = table.item(row, column)
                if item is None:
                    item = QtWidgets.QTableWidgetItem()
                    table.setItem(row, column, item)
                item.setText(value)
                if column in {0, 1, 2, 3}:
                    item.setTextAlignment(int(QtCore.Qt.AlignCenter))
        table.blockSignals(False)
        table.selectRow(0)
        self._set_mrk_dirty(True)
        self._update_mrk_highlights_from_table()
        self._autosize_mrk_table_columns()

    def _on_mrk_sort_by_section_requested(self) -> None:
        self._sort_mrk_entries((0, 1, 2))

    def _on_mrk_sort_by_boundary_requested(self) -> None:
        self._sort_mrk_entries((1, 0, 2))

    def _on_mrk_textures_requested(self) -> None:
        dialog = MrkTexturesDialog(self._window, self._mrk_texture_definitions)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        try:
            self._mrk_texture_definitions = dialog.texture_definitions()
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self._window, "Invalid MRK Texture", str(exc))
            return
        self._set_mrk_dirty(True)
        self._window.mrk_entries_table.viewport().update()
        self._update_mrk_highlights_from_table()
        self._autosize_mrk_table_columns()

    def _mrk_texture_color_lookup(self) -> dict[str, QtGui.QColor]:
        color_lookup: dict[str, QtGui.QColor] = {}
        for definition in self._mrk_texture_definitions:
            color = parse_hex_color(definition.highlight_color)
            if color is None:
                continue
            color_lookup[definition.texture_name] = color
        return color_lookup

    def _default_texture_pattern_for_wall_count(self, wall_count: int) -> str:
        if not self._mrk_texture_definitions:
            return ""
        cycle = [definition.texture_name for definition in self._mrk_texture_definitions]
        pattern = [cycle[index % len(cycle)] for index in range(max(0, wall_count))]
        return ",".join(pattern)

    def _normalize_mrk_side(self, value: str) -> str:
        return normalize_mrk_side(value)

    def _set_mrk_side_cell(self, row: int, side: str) -> None:
        table = self._window.mrk_entries_table
        combo = QtWidgets.QComboBox(table)
        combo.addItems(["Left", "Right"])
        combo.setCurrentText(self._normalize_mrk_side(side))
        combo.currentTextChanged.connect(lambda _value: self._on_mrk_side_changed())
        table.setCellWidget(row, 4, combo)

    def _on_mrk_side_changed(self) -> None:
        self._set_mrk_dirty(True)
        self._refresh_selected_mrk_wall_from_table()
        self._update_mrk_highlights_from_table()

    def _mrk_side_for_row(self, row: int) -> str:
        widget = self._window.mrk_entries_table.cellWidget(row, 4)
        if isinstance(widget, QtWidgets.QComboBox):
            return self._normalize_mrk_side(widget.currentText())
        return self._normalize_mrk_side(self._table_text_value(self._window.mrk_entries_table, row, 4))

    def _auto_detect_mrk_side(self, section_index: int, boundary_index: int) -> str:
        return auto_detect_mrk_side(self._window.preview.sg_preview_model, section_index, boundary_index)

    def _on_mrk_entry_selection_changed(self) -> None:
        table = self._window.mrk_entries_table
        selected_rows = table.selectionModel().selectedRows()
        if not selected_rows:
            return
        self._on_mrk_wall_select_requested()

    def _refresh_selected_mrk_wall_from_table(self) -> None:
        """Refresh viewport MRK brackets when the selected table row changes in-place."""
        table = self._window.mrk_entries_table
        selection_model = table.selectionModel()
        if selection_model is None:
            return
        if selection_model.selectedRows():
            self._on_mrk_wall_select_requested()

    def _allowed_mrk_texture_names(self) -> set[str]:
        return {definition.texture_name for definition in self._mrk_texture_definitions}

    def _on_mrk_entry_cell_double_clicked(self, row: int, column: int) -> None:
        if column != 5:
            return
        if not self._mrk_texture_definitions:
            QtWidgets.QMessageBox.information(
                self._window,
                "No MRK Textures Defined",
                "Define MRK textures first using the Textures dialog.",
            )
            return
        table = self._window.mrk_entries_table
        existing_item = table.item(row, 5)
        current = [] if existing_item is None else [token.strip() for token in existing_item.text().split(",") if token.strip()]
        dialog = MrkTexturePatternDialog(
            self._window,
            [definition.texture_name for definition in self._mrk_texture_definitions],
            current,
        )
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        updated = ",".join(dialog.selected_pattern())
        table.blockSignals(True)
        if existing_item is None:
            table.setItem(row, 5, QtWidgets.QTableWidgetItem(updated))
        else:
            existing_item.setText(updated)
        table.blockSignals(False)
        self._set_mrk_dirty(True)
        self._update_mrk_highlights_from_table()
        self._autosize_mrk_table_columns()

    def _on_mrk_entry_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        row = item.row()
        column = item.column()
        table = self._window.mrk_entries_table
        if column in {0, 1, 2, 3}:
            raw = item.text().strip()
            try:
                value = max(0, int(raw))
            except ValueError:
                value = 0
            table.blockSignals(True)
            item.setText(str(value))
            item.setTextAlignment(int(QtCore.Qt.AlignCenter))
            table.blockSignals(False)
        if column == 4:
            table.blockSignals(True)
            item.setText(self._normalize_mrk_side(item.text()))
            item.setTextAlignment(int(QtCore.Qt.AlignCenter))
            table.blockSignals(False)
        if column == 5:
            allowed = self._allowed_mrk_texture_names()
            tokens = [token.strip() for token in item.text().split(",") if token.strip()]
            if allowed and any(token not in allowed for token in tokens):
                QtWidgets.QMessageBox.warning(
                    self._window,
                    "Invalid Texture Pattern",
                    "Texture pattern entries must reference predefined texture names.",
                )
                table.blockSignals(True)
                item.setText(
                    self._default_texture_pattern_for_wall_count(
                        int(table.item(row, 3).text()) if table.item(row, 3) else 1
                    )
                )
                table.blockSignals(False)
        self._set_mrk_dirty(True)
        if column in {0, 1, 2, 3, 4}:
            self._refresh_selected_mrk_wall_from_table()
        self._update_mrk_highlights_from_table()
        self._autosize_mrk_table_columns()

    def _update_mrk_highlights_from_table(self) -> None:
        table = self._window.mrk_entries_table
        highlights: list[tuple[int, int, int, int, str]] = []
        color_lookup = {definition.texture_name: definition.highlight_color for definition in self._mrk_texture_definitions}
        model = self._window.preview.sg_preview_model

        def _parse_non_negative_int(item: QtWidgets.QTableWidgetItem | None) -> int | None:
            if item is None:
                return None
            try:
                return max(0, int(item.text().strip()))
            except (TypeError, ValueError):
                return None

        for row in range(table.rowCount()):
            section_index = _parse_non_negative_int(table.item(row, 0))
            boundary_index = _parse_non_negative_int(table.item(row, 1))
            wall_index = _parse_non_negative_int(table.item(row, 2))
            wall_count = _parse_non_negative_int(table.item(row, 3))
            if None in {section_index, boundary_index, wall_index, wall_count}:
                continue

            pattern_item = table.item(row, 5)
            textures = [] if pattern_item is None else [token.strip() for token in pattern_item.text().split(",") if token.strip()]
            if model is None:
                wall_positions = [(section_index, wall_index + offset) for offset in range(max(0, wall_count))]
            else:
                try:
                    wall_positions = [
                        (position_section, position_wall)
                        for position_section, position_wall, _wall_ranges in self._iter_mrk_wall_positions(
                            model,
                            section_index=section_index,
                            boundary_index=boundary_index,
                            wall_index=wall_index,
                            wall_count=wall_count,
                        )
                    ]
                except ValueError:
                    continue

            for offset, (position_section, position_wall) in enumerate(wall_positions):
                texture_name = textures[offset % len(textures)] if textures else ""
                if not texture_name:
                    continue
                color = color_lookup.get(texture_name)
                if not color:
                    continue
                highlights.append((boundary_index, position_section, position_wall, 1, color))
        self._window.preview.set_highlighted_mrk_walls(highlights)

    def _collect_mrk_state(self) -> dict[str, object]:
        table = self._window.mrk_entries_table
        entries: list[dict[str, object]] = []
        for row in range(table.rowCount()):
            entries.append(
                {
                    "track_section": self._table_int_value(table, row, 0),
                    "boundary": self._table_int_value(table, row, 1),
                    "starting_wall": self._table_int_value(table, row, 2),
                    "wall_count": self._table_int_value(table, row, 3),
                    "side": self._table_text_value(table, row, 4) or "Left",
                    "texture_pattern": self._table_text_value(table, row, 5),
                    "description": self._table_text_value(table, row, 6),
                }
            )
        texture_definitions = [
            {
                "texture_name": definition.texture_name,
                "mip_filename": definition.mip_name,
                "upper_left_u": definition.upper_left_u,
                "upper_left_v": definition.upper_left_v,
                "lower_right_u": definition.lower_right_u,
                "lower_right_v": definition.lower_right_v,
                "highlight_color": definition.highlight_color,
            }
            for definition in self._mrk_texture_definitions
        ]
        return {
            "format": "sg_viewer_mrk",
            "version": 2,
            "texture_definitions": texture_definitions,
            "entries": entries,
        }

    def _apply_mrk_state(self, state: dict[str, object], *, mark_dirty: bool = True) -> None:
        textures_raw = state.get("texture_definitions", [])
        entries_raw = state.get("entries", [])
        if not isinstance(textures_raw, list) or not isinstance(entries_raw, list):
            raise ValueError("JSON must include list fields 'texture_definitions' and 'entries'.")

        texture_definitions: list[MrkTextureDefinition] = []
        for index, raw in enumerate(textures_raw):
            if not isinstance(raw, dict):
                raise ValueError(f"Texture definition #{index + 1} must be an object.")
            texture_definitions.append(
                MrkTextureDefinition(
                    texture_name=str(raw.get("texture_name", "")).strip(),
                    mip_name=str(raw.get("mip_filename", raw.get("mip_name", ""))).strip(),
                    upper_left_u=int(raw.get("upper_left_u", 0)),
                    upper_left_v=int(raw.get("upper_left_v", 0)),
                    lower_right_u=int(raw.get("lower_right_u", 0)),
                    lower_right_v=int(raw.get("lower_right_v", 0)),
                    highlight_color=str(raw.get("highlight_color", "#FFFF00")).strip() or "#FFFF00",
                )
            )

        table = self._window.mrk_entries_table
        table.blockSignals(True)
        table.setRowCount(0)
        for index, raw in enumerate(entries_raw):
            if not isinstance(raw, dict):
                table.blockSignals(False)
                raise ValueError(f"MRK entry #{index + 1} must be an object.")
            row = table.rowCount()
            table.insertRow(row)
            values = [
                int(raw.get("track_section", 0)),
                int(raw.get("boundary", 0)),
                int(raw.get("starting_wall", 0)),
                max(1, int(raw.get("wall_count", 1))),
                str(raw.get("side", "Left")).strip() or "Left",
                str(raw.get("texture_pattern", "")).strip(),
                str(raw.get("description", "")).strip(),
            ]
            for column, value in enumerate(values):
                if column == 4:
                    self._set_mrk_side_cell(row, str(value))
                    continue
                item = QtWidgets.QTableWidgetItem(str(value))
                if column < 5:
                    item.setTextAlignment(int(QtCore.Qt.AlignCenter))
                table.setItem(row, column, item)
        table.blockSignals(False)

        self._mrk_texture_definitions = tuple(texture_definitions)
        self._window.mrk_entries_table.viewport().update()
        self._set_mrk_dirty(mark_dirty)
        self._update_mrk_highlights_from_table()

    def _table_int_value(self, table: QtWidgets.QTableWidget, row: int, column: int) -> int:
        item = table.item(row, column)
        if item is None:
            return 0
        try:
            return int(item.text().strip())
        except (TypeError, ValueError):
            return 0

    def _table_text_value(self, table: QtWidgets.QTableWidget, row: int, column: int) -> str:
        widget = table.cellWidget(row, column)
        if isinstance(widget, QtWidgets.QComboBox):
            return widget.currentText().strip()
        item = table.item(row, column)
        return "" if item is None else item.text().strip()

    def _on_mrk_save_requested(self) -> None:
        path_str, _selected_filter = QtWidgets.QFileDialog.getSaveFileName(
            self._window,
            "Export MRK Entries and Textures",
            self._dialog_default_directory(),
            "JSON Files (*.json)",
        )
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        payload = self._collect_mrk_state()
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._window.show_status_message(f"Exported MRK data to {path.name}")

    def _on_mrk_generate_file_requested(self) -> None:
        path = self._mrk_export_path()
        if path is None or not self._confirm_export_overwrite(path):
            return

        try:
            mark_file = self._build_mark_file_from_table()
            path.write_text(serialize_mrk(mark_file), encoding="utf-8")
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Generate MRK Failed",
                str(exc),
            )
            return
        self._window.show_status_message(f"Generated MRK file {path.name}")

    def _build_mark_file_from_table(self) -> MarkFile:
        model = self._window.preview.sg_preview_model
        if model is None:
            raise ValueError("No SG preview model is available for MRK generation.")

        texture_lookup = {
            definition.texture_name: definition for definition in self._mrk_texture_definitions
        }
        table = self._window.mrk_entries_table
        entries: list[MarkBoundaryEntry] = []
        pointer_index = 1

        for row in range(table.rowCount()):
            section_index = self._table_int_value(table, row, 0)
            boundary_index = self._table_int_value(table, row, 1)
            wall_index = self._table_int_value(table, row, 2)
            wall_count = max(0, self._table_int_value(table, row, 3))
            if wall_count <= 0:
                continue
            side = self._mrk_side_for_row(row)

            textures = [
                token.strip()
                for token in self._table_text_value(table, row, 5).split(",")
                if token.strip()
            ]
            if not textures:
                raise ValueError(f"Row {row + 1}: texture pattern is required.")

            wall_ranges = self._wall_ranges_for_section_boundary(
                model,
                section_index=section_index,
                boundary_index=boundary_index,
            )
            if not wall_ranges:
                raise ValueError(
                    f"Row {row + 1}: no wall geometry found for section {section_index}, boundary {boundary_index}."
                )

            for offset, (current_section, current_wall, current_wall_ranges) in enumerate(
                self._iter_mrk_wall_positions(
                    model,
                    section_index=section_index,
                    boundary_index=boundary_index,
                    wall_index=wall_index,
                    wall_count=wall_count,
                )
            ):
                texture_name = textures[offset % len(textures)]
                texture = texture_lookup.get(texture_name)
                if texture is None:
                    raise ValueError(
                        f"Row {row + 1}: texture {texture_name!r} is not defined in MRK textures."
                    )
                start_distance, end_distance = current_wall_ranges[current_wall]
                entries.append(
                    MarkBoundaryEntry(
                        pointer_name=f"mrk{pointer_index}",
                        boundary_id=boundary_index,
                        mip_name=texture.mip_name,
                        uv_rect=MarkUvRect(
                            upper_left_u=texture.lower_right_u if side == "Right" else texture.upper_left_u,
                            upper_left_v=texture.upper_left_v,
                            lower_right_u=texture.upper_left_u if side == "Right" else texture.lower_right_u,
                            lower_right_v=texture.lower_right_v,
                        ),
                        start=self._mark_track_position(current_section, start_distance, current_wall_ranges),
                        end=self._mark_track_position(current_section, end_distance, current_wall_ranges),
                    )
                )
                pointer_index += 1

        if not entries:
            raise ValueError("No MRK entries to export.")
        return MarkFile(entries=tuple(entries))

    def _wall_ranges_for_section_boundary(
        self,
        model,
        *,
        section_index: int,
        boundary_index: int,
    ) -> list[tuple[float, float]]:
        if section_index < 0 or section_index >= len(model.fsects):
            return []
        fsect = model.fsects[section_index]
        if boundary_index < 0 or boundary_index >= len(fsect.boundaries):
            return []
        boundary = fsect.boundaries[boundary_index]
        boundary_attrs = getattr(boundary, "attrs", None)
        boundary_surface_type = 0
        if boundary_attrs is not None:
            boundary_surface_type = int(boundary_attrs.get("type1", 0))
        target_length = self._mrk_target_length_for_surface_type(boundary_surface_type)
        points = [
            (float(point[0]), float(point[1]))
            for point in boundary.points
            if point is not None
        ]
        if len(points) < 2:
            return []
        segment_lengths = [
            math.hypot(points[index + 1][0] - points[index][0], points[index + 1][1] - points[index][1])
            for index in range(len(points) - 1)
        ]
        total = sum(segment_lengths)
        if total <= 0.0:
            return []
        segment_count = max(1, int(round(total / target_length)))
        spacing = total / float(segment_count)
        cuts = [0.0]
        cuts.extend(spacing * index for index in range(1, segment_count))
        cuts.append(total)
        return [(cuts[index], cuts[index + 1]) for index in range(len(cuts) - 1)]

    def _mrk_target_length_for_surface_type(self, surface_type: int) -> float:
        return mrk_target_length_for_surface_type(
            surface_type,
            length_multiplier=self._window.pitwall_length_multiplier(),
            armco_height_500ths=self._window.pitwall_armco_height_500ths(),
            wall_height_500ths=self._window.pitwall_wall_height_500ths(),
        )

    def _mark_track_position(
        self,
        section_index: int,
        distance_along_boundary: float,
        wall_ranges: list[tuple[float, float]],
    ) -> MarkTrackPosition:
        total = wall_ranges[-1][1] if wall_ranges else 0.0
        if total <= 0.0:
            fraction = 0.0
        else:
            fraction = distance_along_boundary / total
        fraction = max(0.0, min(1.0, fraction))
        return MarkTrackPosition(section=section_index, fraction=fraction)

    def _iter_mrk_wall_positions(
        self,
        model,
        *,
        section_index: int,
        boundary_index: int,
        wall_index: int,
        wall_count: int,
    ) -> list[tuple[int, int, list[tuple[float, float]]]]:
        if wall_count <= 0:
            return []

        if section_index < 0 or section_index >= len(model.fsects):
            raise ValueError(f"Track section {section_index} is out of range.")

        current_section = section_index
        current_wall_index = max(0, wall_index)
        remaining = wall_count
        positions: list[tuple[int, int, list[tuple[float, float]]]] = []

        while remaining > 0:
            if current_section >= len(model.fsects):
                raise ValueError(
                    f"Track section {section_index} with starting wall {wall_index} and wall count {wall_count} "
                    "extends beyond available section geometry."
                )

            wall_ranges = self._wall_ranges_for_section_boundary(
                model,
                section_index=current_section,
                boundary_index=boundary_index,
            )
            if not wall_ranges:
                raise ValueError(
                    f"No wall geometry found for section {current_section}, boundary {boundary_index}."
                )

            wall_total = len(wall_ranges)
            if current_wall_index >= wall_total:
                current_wall_index -= wall_total
                current_section += 1
                continue

            available = wall_total - current_wall_index
            take = min(remaining, available)
            for offset in range(take):
                positions.append((current_section, current_wall_index + offset, wall_ranges))
            remaining -= take
            current_section += 1
            current_wall_index = 0

        return positions

    def _on_mrk_load_requested(self) -> None:
        path_str, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
            self._window,
            "Import MRK Entries and Textures",
            self._dialog_default_directory(),
            "JSON Files (*.json)",
        )
        if not path_str:
            return
        path = Path(path_str)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Top-level JSON value must be an object.")
            self._apply_mrk_state(payload, mark_dirty=True)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Import MRK JSON Failed",
                str(exc),
            )
            return
        self._autosize_mrk_table_columns()
        self._window.show_status_message(f"Imported MRK data from {path.name}")

    def _on_mrk_wall_height_changed(self, _value: float) -> None:
        self._window.preview.set_mrk_wall_height_500ths(
            self._window.pitwall_wall_height_500ths()
        )
        self._persist_mrk_wall_heights_for_current_track()
        self._update_mrk_highlights_from_table()

    def _on_mrk_armco_height_changed(self, _value: float) -> None:
        self._window.preview.set_mrk_armco_height_500ths(
            self._window.pitwall_armco_height_500ths()
        )
        self._persist_mrk_wall_heights_for_current_track()
        self._update_mrk_highlights_from_table()

    def _on_mrk_length_multiplier_changed(self, _value: float) -> None:
        self._window.preview.set_mrk_length_multiplier(
            self._window.pitwall_length_multiplier()
        )
        self._persist_mrk_wall_heights_for_current_track()
        self._update_mrk_highlights_from_table()

    def _on_mrk_texture_pattern_display_mode_changed(self, checked: bool) -> None:
        self._mrk_texture_pattern_delegate.set_show_color_boxes(checked)
        self._window.mrk_entries_table.viewport().update()
        self._autosize_mrk_table_columns()

    def _autosize_mrk_table_columns(self) -> None:
        self._window.mrk_entries_table.resizeColumnsToContents()
