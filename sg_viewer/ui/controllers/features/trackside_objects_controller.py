from __future__ import annotations

import logging
import math
from dataclasses import replace
from pathlib import Path
from time import perf_counter

from PyQt5 import QtCore, QtWidgets

from sg_viewer.io.track3d_catalog import Track3DCatalog, parse_track3d_catalog
from sg_viewer.services.trackside_elevation import (
    TsoBoundaryElevationContext,
    closest_boundary_elevation_for_tso_with_context,
)
from sg_viewer.services.trackside_objects import (
    TracksideObject,
    normalize_rotation_point,
    normalize_trackside_filename,
    serialize_objects_txt,
)
from sg_viewer.ui.controllers.features.state_controllers import TsoFeatureState
from sg_viewer.ui.presentation.units_presenter import (
    measurement_unit_decimals,
    measurement_unit_label,
)
from sg_viewer.ui.tso_attributes_dialog import TracksideObjectAttributesDialog
from sg_viewer.ui.altitude_units import units_from_500ths, units_to_500ths

logger = logging.getLogger(__name__)


class TracksideObjectsController:
    def __init__(self, host: object) -> None:
        object.__setattr__(self, "_host", host)
        object.__setattr__(self, "_state", TsoFeatureState(host._window))

    def __getattr__(self, name: str):
        if name in {
            "_trackside_objects",
            "_selected_trackside_object_indices",
            "_objects_tab_selected_trackside_object_indices",
            "_tso_add_mode_active",
            "_tso_stamp_mode_active",
            "_tso_box_select_mode_active",
            "_tso_stamp_filename",
            "_auto_update_tso_relative_z",
            "_tso_persist_timer",
            "_tso_visibility_sidebar_dirty",
            "_tso_visibility_sidebar_refresh_pending",
        }:
            return self._get_state_value(name)
        return getattr(self._host, name)

    def __setattr__(self, name: str, value: object) -> None:
        if name in {"_host", "_state"}:
            object.__setattr__(self, name, value)
            return
        if name in {
            "_trackside_objects",
            "_selected_trackside_object_indices",
            "_objects_tab_selected_trackside_object_indices",
            "_tso_add_mode_active",
            "_tso_stamp_mode_active",
            "_tso_box_select_mode_active",
            "_tso_stamp_filename",
            "_auto_update_tso_relative_z",
            "_tso_persist_timer",
            "_tso_visibility_sidebar_dirty",
            "_tso_visibility_sidebar_refresh_pending",
        }:
            self._set_state_value(name, value)
            return
        setattr(self._host, name, value)

    def _get_state_value(self, name: str):
        return getattr(self._state, {
            "_trackside_objects": "trackside_objects",
            "_selected_trackside_object_indices": "selected_trackside_object_indices",
            "_objects_tab_selected_trackside_object_indices": "objects_tab_selected_trackside_object_indices",
            "_tso_add_mode_active": "add_mode_active",
            "_tso_stamp_mode_active": "stamp_mode_active",
            "_tso_box_select_mode_active": "box_select_mode_active",
            "_tso_stamp_filename": "stamp_filename",
            "_auto_update_tso_relative_z": "auto_update_relative_z",
            "_tso_persist_timer": "persist_timer",
            "_tso_visibility_sidebar_dirty": "visibility_sidebar_dirty",
            "_tso_visibility_sidebar_refresh_pending": "visibility_sidebar_refresh_pending",
        }[name])

    def _set_state_value(self, name: str, value: object) -> None:
        setattr(self._state, {
            "_trackside_objects": "trackside_objects",
            "_selected_trackside_object_indices": "selected_trackside_object_indices",
            "_objects_tab_selected_trackside_object_indices": "objects_tab_selected_trackside_object_indices",
            "_tso_add_mode_active": "add_mode_active",
            "_tso_stamp_mode_active": "stamp_mode_active",
            "_tso_box_select_mode_active": "box_select_mode_active",
            "_tso_stamp_filename": "stamp_filename",
            "_auto_update_tso_relative_z": "auto_update_relative_z",
            "_tso_persist_timer": "persist_timer",
            "_tso_visibility_sidebar_dirty": "visibility_sidebar_dirty",
            "_tso_visibility_sidebar_refresh_pending": "visibility_sidebar_refresh_pending",
        }[name], value)

    def connect_signals(self) -> None:
        h = self
        w = self._window
        h._tso_persist_timer.timeout.connect(h._persist_trackside_objects_for_current_track)
        w.tso_add_button.clicked.connect(h._on_tso_add_requested)
        w.tso_stamp_button.clicked.connect(h._on_tso_stamp_requested)
        w.tso_box_select_button.clicked.connect(h._on_tso_box_select_requested)
        w.tso_delete_button.clicked.connect(h._on_tso_delete_requested)
        w.tso_move_up_button.clicked.connect(h._on_tso_move_up_requested)
        w.tso_move_down_button.clicked.connect(h._on_tso_move_down_requested)
        w.tso_import_from_3d_button.clicked.connect(h._on_tso_import_from_3d_requested)
        w.tso_delete_all_button.clicked.connect(h._on_tso_delete_all_requested)
        w.tso_modify_elevations_button.clicked.connect(h._on_tso_modify_elevations_requested)
        w.tso_refresh_relative_boundary_button.clicked.connect(h._on_tso_refresh_relative_boundary_requested)
        w.tso_auto_update_relative_z_checkbox.toggled.connect(h._on_tso_auto_update_relative_z_toggled)
        w.tso_generate_file_button.clicked.connect(h._on_tso_generate_file_requested)
        w.tso_write_to_3d_file_button.clicked.connect(h._on_tso_write_to_3d_file_requested)
        w.tso_table.itemChanged.connect(h._on_tso_item_changed)
        w.tso_table.itemSelectionChanged.connect(h._on_tso_selection_changed)
        w.tso_table.cellClicked.connect(h._on_tso_table_cell_clicked)
        w.tso_visibility_sidebar.selectedTSOsChanged.connect(h._on_tso_visibility_row_selected)
        w.tso_visibility_sidebar.selectedTSOPillChanged.connect(h._on_tso_visibility_pill_selected)
        w.tso_visibility_sidebar.selectedTrackSectionChanged.connect(h._on_tso_visibility_track_section_selected)
        w.tso_visibility_sidebar.selectedTSOOrderChanged.connect(h._on_tso_visibility_order_changed)
        w.tso_visibility_sidebar.objectListsChanged.connect(h._on_tso_visibility_lists_changed)
        w.tso_visibility_sidebar.objectListsSaved.connect(h._on_tso_visibility_lists_saved)
        w.preview.set_trackside_object_drag_callback(h._on_preview_tso_dragged)
        w.preview.set_trackside_object_drag_end_callback(h._on_preview_tso_drag_ended)
        w.preview.set_trackside_map_click_callback(h._on_preview_tso_map_clicked)
        w.preview.set_trackside_box_select_callback(h._on_preview_tso_box_selected)

    def _refresh_tso_table(self) -> None:
        start = perf_counter()
        table = self._window.tso_table
        self._update_tso_table_headers()
        boundary_context = self._build_tso_boundary_elevation_context() if self._auto_update_tso_relative_z else None
        boundary_cache: dict[tuple[int, int, int, int, int], int | None] = {} if self._auto_update_tso_relative_z else {}
        previous_state = table.blockSignals(True)
        try:
            expected_row_count = len(self._trackside_objects)
            if table.rowCount() != expected_row_count:
                table.clearContents()
                table.setRowCount(expected_row_count)
            self._window.preview.set_trackside_objects(tuple(self._trackside_objects))
            for row, obj in enumerate(self._trackside_objects):
                relative_z = (
                    self._tso_relative_boundary_elevation(
                        obj,
                        context=boundary_context,
                        memo=boundary_cache,
                    )
                    if self._auto_update_tso_relative_z
                    else None
                )
                values = [
                    f"__TSO{row}",
                    normalize_trackside_filename(obj.filename),
                    self._format_tso_distance_for_display(int(obj.x)),
                    self._format_tso_distance_for_display(int(obj.y)),
                    self._format_tso_distance_for_display(int(obj.z)),
                    (
                        self._format_tso_distance_for_display(relative_z)
                        if relative_z is not None
                        else ""
                    ),
                ]
                for column, value in enumerate(values):
                    item = table.item(row, column)
                    if item is None:
                        item = QtWidgets.QTableWidgetItem(value)
                        table.setItem(row, column, item)
                    else:
                        item.setText(value)
                    if column == 0:
                        item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
                    else:
                        item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsEditable)
                self._ensure_tso_table_row_button(row)
        finally:
            table.blockSignals(previous_state)
        selection_model = table.selectionModel()
        if selection_model is not None:
            selection_model.clearSelection()
            for index in self._selected_trackside_object_indices:
                if 0 <= index < len(self._trackside_objects):
                    row_index = table.model().index(index, 0)
                    selection_model.select(
                        row_index,
                        QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows,
                    )
            if self._selected_trackside_object_indices:
                first_selected_index = self._selected_trackside_object_indices[0]
                if 0 <= first_selected_index < table.rowCount():
                    selected_item = table.item(first_selected_index, 0)
                    if selected_item is not None:
                        table.scrollToItem(
                            selected_item,
                            QtWidgets.QAbstractItemView.PositionAtCenter,
                        )
        self._window.preview.set_selected_trackside_object_indices(tuple(self._selected_trackside_object_indices))
        selected_index = self._selected_trackside_object_indices[0] if self._selected_trackside_object_indices else None
        self._window.preview.set_selected_trackside_object_index(selected_index)
        self._window.tso_visibility_sidebar.update_available_tso_metadata(
            tuple(range(len(self._trackside_objects))),
            {
                index: (normalize_trackside_filename(obj.filename), obj.description.strip())
                for index, obj in enumerate(self._trackside_objects)
            },
            refresh=True,
        )
        logger.debug("Refreshed TSO table in %.3f ms", (perf_counter() - start) * 1000.0)

    def _on_tso_selection_changed(self) -> None:
        table = self._window.tso_table
        selected_rows = table.selectionModel().selectedRows() if table.selectionModel() is not None else []
        selected_indices = sorted({model_index.row() for model_index in selected_rows if model_index.row() >= 0})
        self._objects_tab_selected_trackside_object_indices = selected_indices
        self._selected_trackside_object_indices = selected_indices
        selected_index = selected_indices[0] if selected_indices else None
        self._window.preview.set_selected_trackside_object_index(selected_index)
        self._window.preview.set_selected_trackside_object_indices(tuple(selected_indices))
        self._center_viewport_on_selected_tso(selected_index)
        self._apply_trackside_drag_scope()
        if selected_indices:
            self._window.show_status_message("TSO selected: right-click and drag in the preview to move selected TSOs.")

    def _center_viewport_on_selected_tso(self, selected_index: int | None) -> None:
        if selected_index is None:
            return
        if selected_index < 0 or selected_index >= len(self._trackside_objects):
            return
        selected_object = self._trackside_objects[selected_index]
        self._window.preview.center_view_on_point((float(selected_object.x), float(selected_object.y)))

    def _on_tso_visibility_row_selected(self, tso_ids: tuple[int, ...]) -> None:
        if not self._is_tso_visibility_tab_active():
            return
        selected_indices = sorted({index for index in tso_ids if 0 <= index < len(self._trackside_objects)})
        self._selected_trackside_object_indices = selected_indices
        selected_index = selected_indices[0] if selected_indices else None
        self._window.preview.set_selected_trackside_object_index(selected_index)
        self._window.preview.set_selected_trackside_object_indices(tuple(selected_indices))
        self._apply_trackside_drag_scope()

    def _on_tso_visibility_pill_selected(self, tso_id: int | None) -> None:
        self._window.preview.set_focused_trackside_object_index(tso_id)

    def _on_tso_visibility_track_section_selected(self, section_data: object) -> None:
        if isinstance(section_data, int):
            self._window.preview.selection_manager.set_selected_section(int(section_data))
            return
        if not isinstance(section_data, dict):
            return

        section_index = section_data.get("section")
        if not isinstance(section_index, int):
            return

        self._window.preview.selection_manager.set_selected_section(int(section_index))
        start_dlong = section_data.get("start_dlong")
        end_dlong = section_data.get("end_dlong")
        if isinstance(start_dlong, (int, float)):
            end_value = float(end_dlong) if isinstance(end_dlong, (int, float)) else None
            self._window.preview.selection_manager.set_selected_dlong_range(float(start_dlong), end_value)

    def _on_tso_visibility_order_changed(self, order_map: dict[int, int]) -> None:
        self._window.preview.set_trackside_order_labels(order_map)

    def _on_tso_visibility_lists_changed(self) -> None:
        self._set_tso_visibility_dirty(True)

    def _on_tso_visibility_lists_saved(self) -> None:
        self._set_tso_visibility_dirty(False)

    def _on_tso_table_cell_clicked(self, row: int, column: int) -> None:
        if column == 6:
            self._open_tso_attributes_dialog(row)

    def _open_tso_attributes_dialog(self, row: int) -> None:
        if row < 0 or row >= len(self._trackside_objects):
            return
        if self._tso_attributes_dialog is None:
            self._tso_attributes_dialog = TracksideObjectAttributesDialog(self._window)
            self._tso_attributes_dialog.objectUpdated.connect(self._on_tso_attributes_updated)
            self._tso_attributes_dialog.matchingFilenameBBoxRotationApplyRequested.connect(
                self._on_tso_attributes_apply_bbox_rotation_to_matching_filename
            )
            self._tso_attributes_dialog.objectPreviewUpdated.connect(self._on_tso_attributes_preview_updated)
            self._tso_attributes_dialog.previewEnded.connect(self._on_tso_attributes_preview_ended)
        self._tso_attributes_dialog.set_measurement_unit(self._window.current_measurement_unit())
        self._tso_attributes_dialog.edit_object(row, self._trackside_objects[row])
        self._tso_attributes_dialog.show()
        self._tso_attributes_dialog.raise_()
        self._tso_attributes_dialog.activateWindow()

    def _on_tso_attributes_updated(self, row: int, obj: object) -> None:
        if not isinstance(obj, TracksideObject):
            return
        if row < 0 or row >= len(self._trackside_objects):
            return
        self._trackside_objects[row] = obj
        self._window.preview.set_trackside_objects(tuple(self._trackside_objects))
        self._refresh_tso_table()
        self._set_trackside_objects_dirty(True)
        self._persist_tsd_state_for_current_track()

    def _on_tso_attributes_preview_updated(self, row: int, obj: object) -> None:
        if not isinstance(obj, TracksideObject):
            return
        if row < 0 or row >= len(self._trackside_objects):
            return
        preview_objects = list(self._trackside_objects)
        preview_objects[row] = obj
        self._window.preview.set_trackside_objects(tuple(preview_objects))

    def _on_tso_attributes_preview_ended(self) -> None:
        self._window.preview.set_trackside_objects(tuple(self._trackside_objects))

    def _on_tso_attributes_apply_bbox_rotation_to_matching_filename(self, row: int, obj: object) -> None:
        if not isinstance(obj, TracksideObject):
            return
        if row < 0 or row >= len(self._trackside_objects):
            return

        target_filename = normalize_trackside_filename(obj.filename)
        if not target_filename:
            return

        updated_any = False
        for index, existing in enumerate(self._trackside_objects):
            if normalize_trackside_filename(existing.filename) != target_filename:
                continue
            self._trackside_objects[index] = TracksideObject(
                filename=existing.filename,
                x=existing.x,
                y=existing.y,
                z=existing.z,
                yaw=existing.yaw,
                pitch=existing.pitch,
                tilt=existing.tilt,
                description=existing.description,
                bbox_length=obj.bbox_length,
                bbox_width=obj.bbox_width,
                rotation_point=obj.rotation_point,
            )
            updated_any = True

        if not updated_any:
            return
        self._window.preview.set_trackside_objects(tuple(self._trackside_objects))
        self._refresh_tso_table()
        self._set_trackside_objects_dirty(True)
        self._persist_tsd_state_for_current_track()

    def _on_preview_tso_dragged(self, anchor_index: int, delta_x: int, delta_y: int) -> None:
        move_indices = sorted(
            index
            for index in self._selected_trackside_object_indices
            if 0 <= index < len(self._trackside_objects)
        )
        if not move_indices:
            if anchor_index < 0 or anchor_index >= len(self._trackside_objects):
                return
            move_indices = [anchor_index]
        moved = False
        for index in move_indices:
            obj = self._trackside_objects[index]
            self._trackside_objects[index] = TracksideObject(
                filename=obj.filename,
                x=int(obj.x + delta_x),
                y=int(obj.y + delta_y),
                z=obj.z,
                yaw=obj.yaw,
                pitch=obj.pitch,
                tilt=obj.tilt,
                description=obj.description,
                bbox_length=obj.bbox_length,
                bbox_width=obj.bbox_width,
                rotation_point=obj.rotation_point,
            )
            moved = True
        if not moved:
            return
        self._selected_trackside_object_indices = move_indices
        self._window.preview.set_trackside_objects(tuple(self._trackside_objects))
        self._update_tso_table_position_cells(move_indices)

    def _on_preview_tso_drag_ended(self, _anchor_index: int | None = None) -> None:
        start = perf_counter()
        if _anchor_index is not None and _anchor_index not in self._selected_trackside_object_indices:
            if 0 <= _anchor_index < len(self._trackside_objects):
                self._selected_trackside_object_indices = [_anchor_index]
        self._update_tso_table_position_cells(self._selected_trackside_object_indices)
        self._set_trackside_objects_dirty(True)
        self._schedule_trackside_objects_persist()
        logger.debug("Handled preview TSO drag end in %.3f ms", (perf_counter() - start) * 1000.0)

    def _update_tso_table_position_cells(
        self,
        indices: list[int],
        *,
        include_z: bool = False,
        include_relative_z: bool | None = None,
    ) -> None:
        table = self._window.tso_table
        should_update_relative_z = self._auto_update_tso_relative_z if include_relative_z is None else include_relative_z
        boundary_context = self._build_tso_boundary_elevation_context() if should_update_relative_z else None
        boundary_cache: dict[tuple[int, int, int, int, int], int | None] = {}
        previous_state = table.blockSignals(True)
        try:
            for index in indices:
                if index < 0 or index >= len(self._trackside_objects):
                    continue
                obj = self._trackside_objects[index]
                x_item = table.item(index, 2)
                if x_item is not None:
                    x_item.setText(self._format_tso_distance_for_display(int(obj.x)))
                y_item = table.item(index, 3)
                if y_item is not None:
                    y_item.setText(self._format_tso_distance_for_display(int(obj.y)))
                if include_z:
                    z_item = table.item(index, 4)
                    if z_item is not None:
                        z_item.setText(self._format_tso_distance_for_display(int(obj.z)))
                relative_z_item = table.item(index, 5)
                if relative_z_item is not None and should_update_relative_z:
                    relative_z = self._tso_relative_boundary_elevation(
                        obj,
                        context=boundary_context,
                        memo=boundary_cache,
                    )
                    relative_z_item.setText(
                        self._format_tso_distance_for_display(relative_z) if relative_z is not None else ""
                    )
        finally:
            table.blockSignals(previous_state)

    def _upsert_tso_table_row(self, row: int, *, include_z: bool = True) -> None:
        if row < 0 or row >= len(self._trackside_objects):
            return
        table = self._window.tso_table
        self._update_tso_table_headers()
        previous_state = table.blockSignals(True)
        try:
            if table.rowCount() <= row:
                table.setRowCount(row + 1)
            obj = self._trackside_objects[row]
            values = [
                f"__TSO{row}",
                normalize_trackside_filename(obj.filename),
                self._format_tso_distance_for_display(int(obj.x)),
                self._format_tso_distance_for_display(int(obj.y)),
                self._format_tso_distance_for_display(int(obj.z)),
                (
                    self._format_tso_distance_for_display(relative_z)
                    if self._auto_update_tso_relative_z
                    and (relative_z := self._tso_relative_boundary_elevation(obj)) is not None
                    else ""
                ),
            ]
            for column, value in enumerate(values):
                item = table.item(row, column)
                if item is None:
                    item = QtWidgets.QTableWidgetItem(value)
                    table.setItem(row, column, item)
                else:
                    item.setText(value)
                if column == 0:
                    item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
                else:
                    item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsEditable)
            self._ensure_tso_table_row_button(row)
            self._update_tso_table_position_cells(
                [row],
                include_z=include_z,
                include_relative_z=False,
            )
        finally:
            table.blockSignals(previous_state)

    def _ensure_tso_table_row_button(self, row: int) -> None:
        table = self._window.tso_table
        existing_widget = table.cellWidget(row, 6)
        button = existing_widget if isinstance(existing_widget, QtWidgets.QPushButton) else None
        if button is None:
            button = QtWidgets.QPushButton("Edit…")
            table.setCellWidget(row, 6, button)
        try:
            button.clicked.disconnect(self._on_tso_attributes_button_clicked)
        except TypeError:
            pass
        button.setProperty("tso_row_index", row)
        button.clicked.connect(self._on_tso_attributes_button_clicked)

    def _on_tso_attributes_button_clicked(self, _checked: bool = False) -> None:
        sender = self._window.sender()
        if not isinstance(sender, QtWidgets.QPushButton):
            return
        row_index = sender.property("tso_row_index")
        if not isinstance(row_index, int):
            return
        self._open_tso_attributes_dialog(row_index)

    def _update_tso_table_headers(self) -> None:
        unit_label = measurement_unit_label(self._window.current_measurement_unit())
        self._window.tso_table.setHorizontalHeaderLabels(
            [
                "Name",
                "Filename",
                f"X ({unit_label})",
                f"Y ({unit_label})",
                f"Z ({unit_label})",
                f"Z rel. boundary ({unit_label})",
                "Attributes",
            ]
        )

    def _format_tso_distance_for_display(self, value_500ths: int) -> str:
        unit = self._window.current_measurement_unit()
        decimals = measurement_unit_decimals(unit)
        return f"{units_from_500ths(value_500ths, unit):.{decimals}f}"

    def _parse_tso_distance_from_display(self, text: str) -> int:
        unit = self._window.current_measurement_unit()
        return int(units_to_500ths(float(text.strip()), unit))

    def _build_default_tso(self, *, x: int, y: int, filename: str | None = None) -> TracksideObject:
        default_filename = filename or "object"
        if filename is None and self._trackside_objects:
            default_filename = normalize_trackside_filename(self._trackside_objects[-1].filename) or "object"
        candidate = TracksideObject(
            filename=default_filename,
            x=x,
            y=y,
            z=0,
            yaw=0,
            pitch=0,
            tilt=0,
            description="",
            bbox_length=0,
            bbox_width=0,
            rotation_point="center",
        )
        boundary_elevation = self._closest_boundary_elevation_for_tso(candidate)
        return TracksideObject(
            filename=default_filename,
            x=x,
            y=y,
            z=int(boundary_elevation) if boundary_elevation is not None else 0,
            yaw=0,
            pitch=0,
            tilt=0,
            description="",
            bbox_length=0,
            bbox_width=0,
            rotation_point="center",
        )

    def _set_tso_add_mode_active(self, active: bool) -> None:
        self._tso_add_mode_active = bool(active)
        self._window.tso_add_button.blockSignals(True)
        self._window.tso_add_button.setChecked(self._tso_add_mode_active)
        self._window.tso_add_button.blockSignals(False)
        if self._tso_add_mode_active and self._tso_stamp_mode_active:
            self._set_tso_stamp_mode_active(False)
        if self._tso_add_mode_active and self._tso_box_select_mode_active:
            self._set_tso_box_select_mode_active(False)

    def _set_tso_stamp_mode_active(self, active: bool, *, filename: str | None = None) -> None:
        self._tso_stamp_mode_active = bool(active)
        if self._tso_stamp_mode_active:
            self._tso_stamp_filename = normalize_trackside_filename(filename or "") or "object"
            if self._tso_add_mode_active:
                self._set_tso_add_mode_active(False)
            if self._tso_box_select_mode_active:
                self._set_tso_box_select_mode_active(False)
        else:
            self._tso_stamp_filename = None
        self._window.tso_stamp_button.blockSignals(True)
        self._window.tso_stamp_button.setChecked(self._tso_stamp_mode_active)
        self._window.tso_stamp_button.blockSignals(False)

    def _set_tso_box_select_mode_active(self, active: bool) -> None:
        self._tso_box_select_mode_active = bool(active)
        self._window.tso_box_select_button.blockSignals(True)
        self._window.tso_box_select_button.setChecked(self._tso_box_select_mode_active)
        self._window.tso_box_select_button.blockSignals(False)
        self._window.preview.set_trackside_box_select_enabled(self._tso_box_select_mode_active)
        if self._tso_box_select_mode_active and self._tso_add_mode_active:
            self._set_tso_add_mode_active(False)
        if self._tso_box_select_mode_active and self._tso_stamp_mode_active:
            self._set_tso_stamp_mode_active(False)

    def _on_tso_add_requested(self) -> None:
        self._set_tso_add_mode_active(self._window.tso_add_button.isChecked())
        if self._tso_add_mode_active:
            self._window.show_status_message("Add TSO active: click on the map to place one TSO.")

    def _on_tso_stamp_requested(self) -> None:
        if self._tso_stamp_mode_active:
            self._set_tso_stamp_mode_active(False)
            self._window.show_status_message("Stamp mode deactivated.")
            return
        text, ok = QtWidgets.QInputDialog.getText(
            self._window,
            "Stamp TSOs",
            "Filename:",
            text=self._tso_stamp_filename or "object",
        )
        if not ok:
            self._window.tso_stamp_button.blockSignals(True)
            self._window.tso_stamp_button.setChecked(False)
            self._window.tso_stamp_button.blockSignals(False)
            return
        normalized = normalize_trackside_filename(text)
        if not normalized:
            QtWidgets.QMessageBox.warning(self._window, "Stamp TSOs", "Filename is required.")
            self._window.tso_stamp_button.blockSignals(True)
            self._window.tso_stamp_button.setChecked(False)
            self._window.tso_stamp_button.blockSignals(False)
            return
        self._set_tso_stamp_mode_active(True, filename=normalized)
        self._window.show_status_message("Stamp mode active: click the map to place TSOs. Click Stamp again to stop.")

    def _on_tso_box_select_requested(self) -> None:
        self._set_tso_box_select_mode_active(self._window.tso_box_select_button.isChecked())
        if self._tso_box_select_mode_active:
            self._window.show_status_message("Box Select active: drag a rectangle on the track diagram to select TSOs.")
        else:
            self._window.show_status_message("Box Select deactivated.")

    def _on_preview_tso_map_clicked(self, x: int, y: int) -> bool:
        start = perf_counter()
        if not self._tso_add_mode_active and not self._tso_stamp_mode_active:
            if not self._is_objects_tab_active():
                return False
            hit_index = self._find_trackside_object_at_point(float(x), float(y))
            selected_indices = [hit_index] if hit_index is not None else []
            self._objects_tab_selected_trackside_object_indices = list(selected_indices)
            self._selected_trackside_object_indices = list(selected_indices)
            selected_index = selected_indices[0] if selected_indices else None
            self._window.preview.set_selected_trackside_object_index(selected_index)
            self._window.preview.set_selected_trackside_object_indices(tuple(selected_indices))

            table = self._window.tso_table
            selection_model = table.selectionModel()
            if selection_model is not None:
                signal_blocker = QtCore.QSignalBlocker(selection_model)
                selection_model.clearSelection()
                if selected_indices:
                    row_index = table.model().index(selected_indices[0], 0)
                    selection_model.select(
                        row_index,
                        QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows,
                    )
                del signal_blocker

            self._apply_trackside_drag_scope()
            if hit_index is not None:
                self._window.show_status_message(
                    "TSO selected: right-click and drag in the preview to move selected TSOs."
                )
            logger.debug("Handled preview TSO map click in %.3f ms", (perf_counter() - start) * 1000.0)
            return True
        filename = self._tso_stamp_filename if self._tso_stamp_mode_active else None
        step_start = perf_counter()
        self._trackside_objects.append(self._build_default_tso(x=x, y=y, filename=filename))
        logger.debug("TSO add click: build/append object %.3f ms", (perf_counter() - step_start) * 1000.0)
        new_row_index = len(self._trackside_objects) - 1
        self._selected_trackside_object_indices = [new_row_index]

        step_start = perf_counter()
        self._window.preview.set_trackside_objects(tuple(self._trackside_objects))
        logger.debug("TSO add click: preview set_trackside_objects %.3f ms", (perf_counter() - step_start) * 1000.0)

        step_start = perf_counter()
        self._upsert_tso_table_row(new_row_index)
        logger.debug("TSO add click: upsert table row %.3f ms", (perf_counter() - step_start) * 1000.0)

        step_start = perf_counter()
        self._window.preview.set_selected_trackside_object_indices(tuple(self._selected_trackside_object_indices))
        self._window.preview.set_selected_trackside_object_index(new_row_index)
        logger.debug("TSO add click: preview selection %.3f ms", (perf_counter() - step_start) * 1000.0)

        step_start = perf_counter()
        selection_model = self._window.tso_table.selectionModel()
        if selection_model is not None:
            row_index = self._window.tso_table.model().index(new_row_index, 0)
            selection_model.select(
                row_index,
                QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows,
            )
        logger.debug("TSO add click: table selection %.3f ms", (perf_counter() - step_start) * 1000.0)

        step_start = perf_counter()
        selected_item = self._window.tso_table.item(new_row_index, 0)
        if selected_item is not None:
            self._window.tso_table.scrollToItem(
                selected_item,
                QtWidgets.QAbstractItemView.PositionAtCenter,
            )
        logger.debug("TSO add click: table scroll %.3f ms", (perf_counter() - step_start) * 1000.0)

        step_start = perf_counter()
        self._mark_tso_visibility_sidebar_dirty()
        self._schedule_tso_visibility_sidebar_refresh()
        logger.debug("TSO add click: visibility sidebar deferred mark/schedule %.3f ms", (perf_counter() - step_start) * 1000.0)

        step_start = perf_counter()
        self._set_trackside_objects_dirty(True)
        self._schedule_trackside_objects_persist()
        logger.debug("TSO add click: dirty + persist schedule %.3f ms", (perf_counter() - step_start) * 1000.0)
        if self._tso_add_mode_active:
            self._set_tso_add_mode_active(False)
        logger.debug("Handled preview TSO map click in %.3f ms", (perf_counter() - start) * 1000.0)
        return True

    def _find_trackside_object_at_point(self, x: float, y: float) -> int | None:
        transform = self._window.preview.current_transform(self._window.preview.widget_size())
        scale = float(transform[0]) if transform is not None else 1.0
        apparent_half_extent = 4.0 / max(scale, 1e-9)
        for index in range(len(self._trackside_objects) - 1, -1, -1):
            obj = self._trackside_objects[index]
            yaw_radians = math.radians(float(obj.yaw) / 10.0)
            half_length = max(apparent_half_extent, float(obj.bbox_length) * 0.5)
            half_width = max(apparent_half_extent, float(obj.bbox_width) * 0.5)
            pivot_local_x, pivot_local_y = self._rotation_pivot_local_offsets(
                normalize_rotation_point(str(getattr(obj, "rotation_point", "center"))),
                half_length,
                half_width,
            )
            center_x = float(obj.x) - (
                pivot_local_x * math.cos(yaw_radians) - pivot_local_y * math.sin(yaw_radians)
            )
            center_y = float(obj.y) - (
                pivot_local_x * math.sin(yaw_radians) + pivot_local_y * math.cos(yaw_radians)
            )
            dx = float(x) - center_x
            dy = float(y) - center_y
            cos_yaw = math.cos(-yaw_radians)
            sin_yaw = math.sin(-yaw_radians)
            local_x = dx * cos_yaw - dy * sin_yaw
            local_y = dx * sin_yaw + dy * cos_yaw
            if abs(local_x) <= half_length and abs(local_y) <= half_width:
                return index
        return None

    @staticmethod
    def _rotation_pivot_local_offsets(
        rotation_point: str,
        half_length: float,
        half_width: float,
    ) -> tuple[float, float]:
        mapping = {
            "center": (0.0, 0.0),
            "top_left": (-half_length, half_width),
            "top_center": (0.0, half_width),
            "top_right": (half_length, half_width),
            "center_left": (-half_length, 0.0),
            "center_right": (half_length, 0.0),
            "bottom_left": (-half_length, -half_width),
            "bottom_center": (0.0, -half_width),
            "bottom_right": (half_length, -half_width),
        }
        return mapping.get(rotation_point, (0.0, 0.0))

    def _on_preview_tso_box_selected(self, min_x: int, min_y: int, max_x: int, max_y: int) -> None:
        selected_indices = [
            index
            for index, obj in enumerate(self._trackside_objects)
            if min_x <= int(obj.x) <= max_x and min_y <= int(obj.y) <= max_y
        ]
        self._selected_trackside_object_indices = selected_indices
        self._refresh_tso_table()
        if self._tso_box_select_mode_active:
            self._set_tso_box_select_mode_active(False)
        self._window.show_status_message(f"Selected {len(selected_indices)} TSO(s) with box selection.")


    def _on_tso_delete_requested(self) -> None:
        table = self._window.tso_table
        selected_rows = table.selectionModel().selectedRows() if table.selectionModel() is not None else []
        if not selected_rows:
            return
        rows = sorted({model_index.row() for model_index in selected_rows if model_index.row() >= 0}, reverse=True)
        if not rows:
            return
        for row in rows:
            if 0 <= row < len(self._trackside_objects):
                del self._trackside_objects[row]
        self._selected_trackside_object_indices = []
        self._refresh_tso_table()
        self._set_trackside_objects_dirty(True)
        self._persist_tsd_state_for_current_track()

    def _move_tso(self, *, direction: int) -> None:
        table = self._window.tso_table
        selected_rows = table.selectionModel().selectedRows() if table.selectionModel() is not None else []
        if not selected_rows:
            return
        source_row = min(model_index.row() for model_index in selected_rows)
        target_row = source_row + direction
        if target_row < 0 or target_row >= len(self._trackside_objects):
            return
        self._trackside_objects[source_row], self._trackside_objects[target_row] = (
            self._trackside_objects[target_row],
            self._trackside_objects[source_row],
        )
        self._window.tso_visibility_sidebar.remap_tso_ids(
            {
                source_row: target_row,
                target_row: source_row,
            }
        )
        self._selected_trackside_object_indices = [target_row]
        self._refresh_tso_table()
        self._set_trackside_objects_dirty(True)
        self._persist_tsd_state_for_current_track()

    def _on_tso_move_up_requested(self) -> None:
        self._move_tso(direction=-1)

    def _on_tso_move_down_requested(self) -> None:
        self._move_tso(direction=1)

    @staticmethod
    def _trackside_object_catalog_key(obj: TracksideObject) -> tuple[str, int, int, int, int, int, int]:
        return (
            normalize_trackside_filename(obj.filename).lower(),
            int(obj.x),
            int(obj.y),
            int(obj.z),
            int(obj.yaw),
            int(obj.pitch),
            int(obj.tilt),
        )

    @staticmethod
    def _trackside_objects_from_track3d_catalog(catalog: Track3DCatalog) -> list[TracksideObject]:
        parsed_objects: list[TracksideObject] = []
        for _label, definition in sorted(catalog.tsos.items(), key=lambda item: item[1].span.start_offset or 0):
            filename = normalize_trackside_filename(definition.extern)
            if not filename:
                continue
            parsed_objects.append(
                TracksideObject(
                    filename=filename,
                    x=int(definition.x),
                    y=int(definition.y),
                    z=int(definition.z),
                    yaw=int(definition.rot),
                    pitch=int(definition.params[4]) if len(definition.params) > 4 else 0,
                    tilt=int(definition.params[5]) if len(definition.params) > 5 else 0,
                )
            )
        return parsed_objects

    def _parse_trackside_objects_from_3d_text(self, text: str) -> list[TracksideObject]:
        """Compatibility adapter for tests; UI workflows parse the selected file directly."""
        from tempfile import NamedTemporaryFile

        with NamedTemporaryFile("w", suffix=".3d", encoding="utf-8", delete=False) as temp_file:
            temp_file.write(text)
            temp_path = Path(temp_file.name)
        try:
            return self._trackside_objects_from_track3d_catalog(parse_track3d_catalog(temp_path))
        finally:
            temp_path.unlink(missing_ok=True)

    def _on_tso_import_from_3d_requested(self) -> None:
        proceed = QtWidgets.QMessageBox.warning(
            self._window,
            "Import TSOs from .3D",
            (
                "This will clear and replace the current TSO list with TSOs parsed from "
                "the selected .3D file. Continue?"
            ),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if proceed != QtWidgets.QMessageBox.Yes:
            return

        default_path = ""
        selected_track3d = self._track3d_path_for_current_project()
        if selected_track3d is not None:
            default_path = str(selected_track3d)

        path_str, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
            self._window,
            "Open track .3D file",
            default_path,
            "Track 3D Files (*.3d *.3D);;All Files (*)",
        )
        if not path_str:
            return

        path = Path(path_str)
        try:
            catalog = parse_track3d_catalog(path)
        except OSError as exc:
            QtWidgets.QMessageBox.critical(
                self._window,
                "Import TSOs from .3D",
                f"Could not read file:\n{exc}",
            )
            return

        parsed_objects = self._trackside_objects_from_track3d_catalog(catalog)
        if not parsed_objects:
            QtWidgets.QMessageBox.information(
                self._window,
                "Import TSOs from .3D",
                "No matching __TSO DYNAMIC lines were found in that .3D file.",
            )
            return

        self._trackside_objects = parsed_objects
        self._selected_trackside_object_indices = []
        self._objects_tab_selected_trackside_object_indices = []
        self._refresh_tso_table()
        self._set_trackside_objects_dirty(True)
        self._persist_tsd_state_for_current_track()
        self._window.show_status_message(f"Imported {len(parsed_objects)} TSO(s) from {path.name}.")

    def _on_tso_delete_all_requested(self) -> None:
        if not self._trackside_objects:
            self._window.show_status_message("No TSOs to delete.")
            return
        proceed = QtWidgets.QMessageBox.warning(
            self._window,
            "Delete all TSOs",
            "This will permanently remove all TSOs from the current project. Continue?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if proceed != QtWidgets.QMessageBox.Yes:
            return
        self._trackside_objects = []
        self._selected_trackside_object_indices = []
        self._objects_tab_selected_trackside_object_indices = []
        self._refresh_tso_table()
        self._set_trackside_objects_dirty(True)
        self._persist_tsd_state_for_current_track()
        self._window.show_status_message("Deleted all TSOs from the project.")

    def _on_tso_modify_elevations_requested(self) -> None:
        if not self._trackside_objects:
            QtWidgets.QMessageBox.information(
                self._window,
                "Modify elevations",
                "There are no TSOs to update.",
            )
            return

        if self._tso_modify_elevations_dialog is not None and self._tso_modify_elevations_dialog.isVisible():
            self._tso_modify_elevations_dialog.raise_()
            self._tso_modify_elevations_dialog.activateWindow()
            return

        unit = self._window.current_measurement_unit()
        unit_label = measurement_unit_label(unit)
        decimals = measurement_unit_decimals(unit)
        step = measurement_unit_step(unit)

        dialog = QtWidgets.QDialog(self._window)
        self._tso_modify_elevations_dialog = dialog
        dialog.setWindowTitle("Modify elevations")
        dialog.setWindowModality(QtCore.Qt.NonModal)
        dialog.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, True)
        layout = QtWidgets.QVBoxLayout(dialog)

        scope_group = QtWidgets.QGroupBox("Target TSOs")
        scope_layout = QtWidgets.QVBoxLayout(scope_group)
        apply_all_radio = QtWidgets.QRadioButton("Apply to all TSOs")
        apply_all_radio.setChecked(True)
        apply_selected_radio = QtWidgets.QRadioButton("Apply to selected TSOs")
        scope_layout.addWidget(apply_all_radio)
        scope_layout.addWidget(apply_selected_radio)
        layout.addWidget(scope_group)

        options_group = QtWidgets.QGroupBox("Elevation change")
        options_layout = QtWidgets.QVBoxLayout(options_group)
        raise_lower_radio = QtWidgets.QRadioButton("Raise/lower elevations by:")
        raise_lower_radio.setChecked(True)
        set_absolute_radio = QtWidgets.QRadioButton("Set elevations to:")
        set_boundary_radio = QtWidgets.QRadioButton(
            "Set each TSO elevation to the closest track boundary elevation"
        )
        options_layout.addWidget(raise_lower_radio)
        options_layout.addWidget(set_absolute_radio)
        options_layout.addWidget(set_boundary_radio)
        layout.addWidget(options_group)

        value_spin = QtWidgets.QDoubleSpinBox(dialog)
        value_spin.setRange(-1_000_000.0, 1_000_000.0)
        value_spin.setDecimals(decimals)
        value_spin.setSingleStep(step)
        value_spin.setValue(0.0)
        value_spin.setSuffix(f" {unit_label}")
        value_label = QtWidgets.QLabel(f"Amount ({unit_label}):", dialog)
        value_row = QtWidgets.QHBoxLayout()
        value_row.addWidget(value_label)
        value_row.addWidget(value_spin)
        layout.addLayout(value_row)

        def _sync_value_input() -> None:
            if raise_lower_radio.isChecked():
                value_label.setText(f"Amount ({unit_label}):")
                value_spin.setEnabled(True)
            elif set_absolute_radio.isChecked():
                value_label.setText(f"Elevation ({unit_label}):")
                value_spin.setEnabled(True)
            else:
                value_spin.setEnabled(False)

        raise_lower_radio.toggled.connect(_sync_value_input)
        set_absolute_radio.toggled.connect(_sync_value_input)
        set_boundary_radio.toggled.connect(_sync_value_input)
        _sync_value_input()

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Apply | QtWidgets.QDialogButtonBox.Close,
            parent=dialog,
        )
        apply_button = buttons.button(QtWidgets.QDialogButtonBox.Apply)
        if apply_button is not None:
            apply_button.setDefault(True)
            apply_button.setAutoDefault(True)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.finished.connect(self._on_tso_modify_elevations_dialog_closed)

        def _apply_changes() -> None:
            if apply_selected_radio.isChecked():
                target_indices = sorted(set(self._selected_trackside_object_indices))
                if not target_indices:
                    QtWidgets.QMessageBox.information(
                        dialog,
                        "Modify elevations",
                        "No TSOs are selected. Select one or more TSOs, or choose Apply to all TSOs.",
                    )
                    return
            else:
                target_indices = list(range(len(self._trackside_objects)))

            changed = False
            skipped_boundary_matches = 0
            delta_500ths = units_to_500ths(value_spin.value(), unit)
            absolute_500ths = units_to_500ths(value_spin.value(), unit)
            for index in target_indices:
                obj = self._trackside_objects[index]
                if raise_lower_radio.isChecked():
                    z_value = int(obj.z + delta_500ths)
                elif set_absolute_radio.isChecked():
                    z_value = int(absolute_500ths)
                else:
                    boundary_elevation = self._closest_boundary_elevation_for_tso(obj)
                    if boundary_elevation is None:
                        skipped_boundary_matches += 1
                        continue
                    z_value = int(boundary_elevation)
                if obj.z == z_value:
                    continue
                self._trackside_objects[index] = TracksideObject(
                    filename=obj.filename,
                    x=obj.x,
                    y=obj.y,
                    z=z_value,
                    yaw=obj.yaw,
                    pitch=obj.pitch,
                    tilt=obj.tilt,
                    description=obj.description,
                    bbox_length=obj.bbox_length,
                    bbox_width=obj.bbox_width,
                    rotation_point=obj.rotation_point,
                )
                changed = True

            if not changed:
                if set_boundary_radio.isChecked() and skipped_boundary_matches > 0:
                    QtWidgets.QMessageBox.information(
                        dialog,
                        "Modify elevations",
                        "Could not determine boundary elevations for any targeted TSOs.",
                    )
                return

            self._refresh_tso_table()
            self._set_trackside_objects_dirty(True)
            self._persist_tsd_state_for_current_track()
            target_label = "selected TSOs" if apply_selected_radio.isChecked() else "all TSOs"
            if raise_lower_radio.isChecked():
                self._window.show_status_message(
                    f"Adjusted {target_label} elevations by {value_spin.value():g} {unit_label}."
                )
                return
            if set_absolute_radio.isChecked():
                self._window.show_status_message(
                    f"Set {target_label} elevations to {value_spin.value():g} {unit_label}."
                )
                return
            if skipped_boundary_matches > 0:
                self._window.show_status_message(
                    f"Set boundary-matched elevations for {target_label} ({skipped_boundary_matches} skipped)."
                )
                return
            self._window.show_status_message(
                f"Set {target_label} elevations to the nearest boundary elevation."
            )

        buttons.clicked.connect(
            lambda button: _apply_changes()
            if buttons.standardButton(button) == QtWidgets.QDialogButtonBox.Apply
            else None
        )
        dialog.show()

    def _on_tso_modify_elevations_dialog_closed(self) -> None:
        self._tso_modify_elevations_dialog = None

    @staticmethod

    def _closest_boundary_elevation_for_tso(self, obj: TracksideObject) -> int | None:
        context = self._build_tso_boundary_elevation_context()
        return self._closest_boundary_elevation_for_tso_with_context(obj, context=context)

    def _build_tso_boundary_elevation_context(self) -> TsoBoundaryElevationContext | None:
        section_manager = self._window.preview.section_manager
        centerline_index = section_manager.centerline_index
        sampled_dlongs = section_manager.sampled_dlongs
        sections = section_manager.sections
        track_length = float(sum(max(0.0, float(section.length)) for section in sections))
        if centerline_index is None or not sampled_dlongs or track_length <= 0.0:
            return None
        return TsoBoundaryElevationContext(
            centerline_index=centerline_index,
            sampled_dlongs=sampled_dlongs,
            sections=sections,
            track_length=track_length,
            get_section_fsects=self._window.preview.get_section_fsects,
            sample_elevation_at_dlat=self._window._sample_elevation_at_dlat,
        )

    def _closest_boundary_elevation_for_tso_with_context(
        self,
        obj: TracksideObject,
        *,
        context: TsoBoundaryElevationContext | None,
        memo: dict[tuple[int, int, int, int, int], int | None] | None = None,
    ) -> int | None:
        return closest_boundary_elevation_for_tso_with_context(obj, context=context, memo=memo)

    def _tso_relative_boundary_elevation(
        self,
        obj: TracksideObject,
        *,
        context: TsoBoundaryElevationContext | None = None,
        memo: dict[tuple[int, int, int, int, int], int | None] | None = None,
    ) -> int | None:
        boundary_elevation = self._closest_boundary_elevation_for_tso_with_context(
            obj,
            context=context if context is not None else self._build_tso_boundary_elevation_context(),
            memo=memo,
        )
        if boundary_elevation is None:
            return None
        return int(obj.z) - int(boundary_elevation)

    def _on_tso_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        row = item.row()
        if row < 0 or row >= len(self._trackside_objects):
            return
        table = self._window.tso_table
        try:
            filename = normalize_trackside_filename((table.item(row, 1).text() if table.item(row, 1) else ""))
            if not filename:
                raise ValueError
            existing = self._trackside_objects[row]
            obj = TracksideObject(
                filename=filename,
                x=self._parse_tso_distance_from_display(table.item(row, 2).text() if table.item(row, 2) else "0"),
                y=self._parse_tso_distance_from_display(table.item(row, 3).text() if table.item(row, 3) else "0"),
                z=self._parse_tso_distance_from_display(table.item(row, 4).text() if table.item(row, 4) else "0"),
                yaw=existing.yaw,
                pitch=existing.pitch,
                tilt=existing.tilt,
                description=existing.description,
                bbox_length=max(0, int(existing.bbox_length)),
                bbox_width=max(0, int(existing.bbox_width)),
                rotation_point=existing.rotation_point,
            )
            if item.column() == 5:
                relative_z = self._parse_tso_distance_from_display(table.item(row, 5).text() if table.item(row, 5) else "0")
                boundary_elevation = self._closest_boundary_elevation_for_tso_with_context(
                    obj,
                    context=self._build_tso_boundary_elevation_context(),
                )
                if boundary_elevation is None:
                    raise ValueError
                obj = replace(obj, z=int(boundary_elevation) + relative_z)
        except ValueError:
            self._refresh_tso_table()
            return
        self._trackside_objects[row] = obj
        self._window.preview.set_trackside_objects(tuple(self._trackside_objects))
        self._update_tso_table_position_cells([row], include_z=True)
        self._set_trackside_objects_dirty(True)
        self._persist_tsd_state_for_current_track()

    def _on_tso_refresh_relative_boundary_requested(self) -> None:
        self._update_tso_table_position_cells(list(range(len(self._trackside_objects))), include_z=False, include_relative_z=True)

    def _on_tso_auto_update_relative_z_toggled(self, checked: bool) -> None:
        self._auto_update_tso_relative_z = bool(checked)
        if self._current_path is not None:
            self._sg_settings_store.set_tso_auto_update_relative_z(
                self._current_path,
                self._auto_update_tso_relative_z,
            )
        if self._auto_update_tso_relative_z:
            self._refresh_tso_table()
        self._window.show_status_message("Refreshed Z rel. boundary values from current track geometry.")

    def _on_tso_generate_file_requested(self) -> None:
        if not self._trackside_objects:
            QtWidgets.QMessageBox.information(self._window, "Generate objects.txt", "No TSOs to export.")
            return
        path_str, _selected_filter = QtWidgets.QFileDialog.getSaveFileName(
            self._window,
            "Save objects.txt",
            self._dialog_default_file_path("objects.txt"),
            "Text Files (*.txt);;All files (*)",
        )
        if not path_str:
            return
        path = Path(path_str)
        try:
            path.write_text(serialize_objects_txt(self._trackside_objects), encoding="utf-8")
        except OSError as exc:
            QtWidgets.QMessageBox.critical(
                self._window,
                "Generate objects.txt",
                f"Could not save objects file:\n{exc}",
            )
            return
        self._window.show_status_message(f"Saved objects.txt to {path}")

    @staticmethod
    def _track3d_newline_style(text: str) -> str:
        first_crlf = text.find("\r\n")
        first_lf = text.find("\n")
        if first_crlf >= 0 and (first_lf < 0 or first_crlf <= first_lf):
            return "\r\n"
        return "\n"

    @staticmethod
    def _format_tso_dynamic_line(label: str, obj: TracksideObject) -> str:
        return (
            f'{label}: DYNAMIC {obj.x}, {obj.y}, {obj.z}, {obj.yaw}, '
            f'{obj.pitch}, {obj.tilt}, 1, EXTERN "{normalize_trackside_filename(obj.filename)}";'
        )

    def _replace_tso_dynamic_section_in_3d_text(
        self,
        text: str,
        catalog: Track3DCatalog | None = None,
    ) -> tuple[str, int, int]:
        if catalog is None:
            from tempfile import NamedTemporaryFile

            with NamedTemporaryFile("w", suffix=".3d", encoding="utf-8", delete=False) as temp_file:
                temp_file.write(text)
                temp_path = Path(temp_file.name)
            try:
                catalog = parse_track3d_catalog(temp_path)
            finally:
                temp_path.unlink(missing_ok=True)
        if not catalog.tsos:
            return text, 0, 0

        project_objects = list(self._trackside_objects)
        existing_by_label = sorted(catalog.tsos.items(), key=lambda item: int(item[0][5:]))
        available_labels = [label for label, _definition in existing_by_label]
        assigned_labels: dict[int, str] = {}
        used_labels: set[str] = set()

        unmatched_by_key: dict[tuple[str, int, int, int, int, int, int], list[str]] = {}
        for label, definition in existing_by_label:
            existing_obj = TracksideObject(
                filename=normalize_trackside_filename(definition.extern),
                x=int(definition.x),
                y=int(definition.y),
                z=int(definition.z),
                yaw=int(definition.rot),
                pitch=int(definition.params[4]) if len(definition.params) > 4 else 0,
                tilt=int(definition.params[5]) if len(definition.params) > 5 else 0,
            )
            unmatched_by_key.setdefault(self._trackside_object_catalog_key(existing_obj), []).append(label)

        for index, obj in enumerate(project_objects):
            labels = unmatched_by_key.get(self._trackside_object_catalog_key(obj))
            if labels:
                label = labels.pop(0)
                assigned_labels[index] = label
                used_labels.add(label)

        unused_existing_labels = [label for label in available_labels if label not in used_labels]
        for index, _obj in enumerate(project_objects):
            if index in assigned_labels:
                continue
            if unused_existing_labels:
                label = unused_existing_labels.pop(0)
            else:
                next_id = 0
                existing_ids = {int(label[5:]) for label in available_labels}
                while next_id in existing_ids:
                    next_id += 1
                label = f"__TSO{next_id}"
                available_labels.append(label)
            assigned_labels[index] = label
            used_labels.add(label)

        replacements: list[tuple[int, int, str]] = []
        newline = self._track3d_newline_style(text)
        for index, label in assigned_labels.items():
            if label not in catalog.tsos:
                continue
            span = catalog.tsos[label].span
            if span.start_offset is None or span.end_offset is None:
                continue
            replacements.append(
                (
                    span.start_offset,
                    span.end_offset,
                    self._format_tso_dynamic_line(label, project_objects[index]),
                )
            )

        deleted_labels = [label for label in catalog.tsos if label not in used_labels]
        for label in deleted_labels:
            span = catalog.tsos[label].span
            if span.start_offset is None or span.end_offset is None:
                continue
            start = span.start_offset
            end = span.end_offset
            if end < len(text) and text[end : end + 2] == "\r\n":
                end += 2
            elif end < len(text) and text[end : end + 1] == "\n":
                end += 1
            replacements.append((start, end, ""))

        new_entries = [
            self._format_tso_dynamic_line(assigned_labels[index], obj)
            for index, obj in enumerate(project_objects)
            if assigned_labels[index] not in catalog.tsos
        ]
        if new_entries:
            last_span = max(
                (definition.span for definition in catalog.tsos.values() if definition.span.end_offset is not None),
                key=lambda span: span.end_offset or 0,
            )
            insert_at = last_span.end_offset or len(text)
            line_break_follows = text[insert_at : insert_at + len(newline)] == newline
            insertion = newline + newline.join(new_entries)
            if not line_break_follows:
                insertion += newline
            replacements.append((insert_at, insert_at, insertion))

        updated = text
        for start, end, replacement in sorted(replacements, key=lambda item: item[0], reverse=True):
            updated = updated[:start] + replacement + updated[end:]
        return updated, len(catalog.tsos), len(deleted_labels)

    def _on_tso_write_to_3d_file_requested(self) -> None:
        path_str, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
            self._window,
            "Select track .3D file to update",
            str(self._track3d_path_for_current_project() or ""),
            "Track 3D Files (*.3d *.3D);;All Files (*)",
        )
        if not path_str:
            return
        path = Path(path_str)
        try:
            original_text = path.read_text(encoding="utf-8", errors="ignore")
            catalog = parse_track3d_catalog(path)
        except OSError as exc:
            QtWidgets.QMessageBox.critical(
                self._window,
                "Write to .3D file",
                f"Could not read file:\n{exc}",
            )
            return
        project_keys = {self._trackside_object_catalog_key(obj) for obj in self._trackside_objects}
        deleted_labels: list[str] = []
        for label, definition in sorted(catalog.tsos.items(), key=lambda item: int(item[0][5:])):
            obj = TracksideObject(
                filename=normalize_trackside_filename(definition.extern),
                x=int(definition.x),
                y=int(definition.y),
                z=int(definition.z),
                yaw=int(definition.rot),
                pitch=int(definition.params[4]) if len(definition.params) > 4 else 0,
                tilt=int(definition.params[5]) if len(definition.params) > 5 else 0,
            )
            if self._trackside_object_catalog_key(obj) not in project_keys:
                deleted_labels.append(label)
        if deleted_labels:
            proceed = QtWidgets.QMessageBox.warning(
                self._window,
                "Write to .3D file",
                (
                    "The selected .3D file contains catalog TSO definitions that are not present "
                    "in the current SG CREATE project and will be deleted:\n\n"
                    f"{', '.join(deleted_labels)}\n\nContinue?"
                ),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            if proceed != QtWidgets.QMessageBox.Yes:
                return
        updated_text, replaced_count, _deleted_count = self._replace_tso_dynamic_section_in_3d_text(
            original_text,
            catalog,
        )
        if replaced_count <= 0:
            QtWidgets.QMessageBox.information(
                self._window,
                "Write to .3D file",
                "No matching __TSO DYNAMIC lines were found in that .3D file.",
            )
            return
        try:
            path.write_text(updated_text, encoding="utf-8")
        except OSError as exc:
            QtWidgets.QMessageBox.critical(
                self._window,
                "Write to .3D file",
                f"Could not write file:\n{exc}",
            )
            return
        self._window.show_status_message(
            f"Updated {path.name}: replaced {replaced_count} TSO line(s) with {len(self._trackside_objects)} project TSO(s)."
        )
