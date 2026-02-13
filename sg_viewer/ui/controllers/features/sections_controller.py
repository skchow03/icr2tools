from __future__ import annotations

import math
from typing import Protocol

from PyQt5 import QtWidgets

from sg_viewer.geometry.sg_geometry import rotate_section
from sg_viewer.geometry.topology import is_closed_loop, loop_length
from sg_viewer.model.preview_fsection import PreviewFSection
from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.rendering.fsection_style_map import FENCE_TYPE2
from sg_viewer.ui.generate_fsects_dialog import GenerateFsectsDialog
from sg_viewer.ui.rotate_track_dialog import RotateTrackDialog
from sg_viewer.ui.scale_track_dialog import ScaleTrackDialog


class SectionsControllerHost(Protocol):
    _window: QtWidgets.QMainWindow
    _active_selection: object | None
    _is_untitled: bool
    _current_path: object
    _section_table_action: QtWidgets.QAction
    _heading_table_action: QtWidgets.QAction
    _save_action: QtWidgets.QAction
    _scale_track_action: QtWidgets.QAction
    _rotate_track_action: QtWidgets.QAction
    _raise_lower_elevations_action: QtWidgets.QAction
    _delete_default_style: str

    def _start_new_straight(self) -> None: ...
    def _start_new_curve(self) -> None: ...
    def _on_move_section_mode_changed(self, active: bool) -> None: ...
    def _refresh_elevation_profile(self) -> None: ...
    def _refresh_elevation_inputs(self) -> None: ...
    def _update_track_length_display(self) -> None: ...
    def _update_copy_xsect_button(self) -> None: ...
    def _update_copy_fsects_buttons(self) -> None: ...
    def _update_fsect_edit_buttons(self) -> None: ...


class SectionsController:
    def __init__(self, host: SectionsControllerHost) -> None:
        self._host = host

    def toggle_delete_section_mode(self, checked: bool) -> None:
        if checked:
            self._host._window.new_straight_button.setChecked(False)
            self._host._window.new_curve_button.setChecked(False)
            self._host._window.split_section_button.setChecked(False)
            if not self._host._window.preview.begin_delete_section():
                self._host._window.delete_section_button.setChecked(False)
                return
            self._host._window.show_status_message("Click a section to delete it.")
        else:
            self._host._window.preview.cancel_delete_section()

    def toggle_new_straight_mode(self, checked: bool) -> None:
        if checked:
            self._host._window.delete_section_button.setChecked(False)
            self._host._window.new_curve_button.setChecked(False)
            self._host._window.split_section_button.setChecked(False)
            self._host._start_new_straight()
            return
        self._host._window.preview.cancel_creation()

    def toggle_new_curve_mode(self, checked: bool) -> None:
        if checked:
            self._host._window.delete_section_button.setChecked(False)
            self._host._window.new_straight_button.setChecked(False)
            self._host._window.split_section_button.setChecked(False)
            self._host._start_new_curve()
            return
        self._host._window.preview.cancel_creation()

    def toggle_split_section_mode(self, checked: bool) -> None:
        if checked:
            self._host._window.delete_section_button.setChecked(False)
            self._host._window.new_straight_button.setChecked(False)
            self._host._window.new_curve_button.setChecked(False)
            if not self._host._window.preview.begin_split_section():
                self._host._window.split_section_button.setChecked(False)
                return
            self._host._window.show_status_message("Hover over a section to choose where to split it.")
        else:
            self._host._window.preview.cancel_split_section()

    def toggle_move_section_mode(self, checked: bool) -> None:
        self._host._window.preview.set_section_drag_enabled(checked)
        self._host._on_move_section_mode_changed(checked)

    def start_new_straight(self) -> None:
        self._host._window.delete_section_button.setChecked(False)
        self._host._window.split_section_button.setChecked(False)
        if not self._host._window.preview.begin_new_straight():
            self._host._window.show_status_message("Start a new track or load an SG file before creating new straights.")
            self._host._on_new_straight_mode_changed(False)
            return
        self._host._window.show_status_message("Click to place the start of the new straight.")

    def start_new_curve(self) -> None:
        self._host._window.delete_section_button.setChecked(False)
        self._host._window.split_section_button.setChecked(False)
        if not self._host._window.preview.begin_new_curve():
            self._host._window.show_status_message("Create a track with an unconnected node before adding a curve.")
            self._host._on_new_curve_mode_changed(False)
            return
        self._host._window.show_status_message("Click an unconnected node to start the new curve.")

    def on_sections_changed(self) -> None:
        sections, _ = self._host._window.preview.get_section_set()
        has_sections = bool(sections)
        self._host._window.delete_section_button.setEnabled(has_sections)
        self._host._window.split_section_button.setEnabled(has_sections)
        self._host._window.move_section_button.setEnabled(has_sections)
        if not has_sections:
            self._host._window.delete_section_button.setChecked(False)
            self._host._window.delete_section_button.setStyleSheet(self._host._delete_default_style)
            self._host._window.split_section_button.setChecked(False)
        self._host._window.set_start_finish_button.setEnabled(has_sections)
        self._host._section_table_action.setEnabled(has_sections)
        self._host._heading_table_action.setEnabled(has_sections)
        self._host._window.refresh_fsects_button.setEnabled(has_sections and self._host._window.preview.sgfile is not None)
        self._host._scale_track_action.setEnabled(has_sections and is_closed_loop(sections))
        self._host._rotate_track_action.setEnabled(has_sections)
        self._host._raise_lower_elevations_action.setEnabled(has_sections)
        self._host._save_action.setEnabled(True)
        if self._host._is_untitled:
            self._host._window.update_window_title(path=None, is_dirty=True, is_untitled=True)
        elif self._host._current_path is not None:
            self._host._window.update_window_title(path=self._host._current_path, is_dirty=True)
        if not self._host._elevation_controller.defer_refresh_if_dragging(is_interaction_dragging=self._host._window.preview.is_interaction_dragging):
            self._host._refresh_elevation_profile()
        self._host._refresh_elevation_inputs()
        self._host._update_track_length_display()
        self._host._update_copy_xsect_button()
        self._host._update_copy_fsects_buttons()
        self._host._update_fsect_edit_buttons()

    def scale_track(self) -> None:
        sections, _ = self._host._window.preview.get_section_set()
        if not sections or not is_closed_loop(sections):
            QtWidgets.QMessageBox.information(self._host._window, "Scale Track", "Scaling is only available when the track forms a closed loop.")
            return
        try:
            current_length = loop_length(sections)
        except ValueError:
            QtWidgets.QMessageBox.information(self._host._window, "Scale Track", "Scaling is only available when the track forms a closed loop.")
            return
        dialog = ScaleTrackDialog(self._host._window, current_length)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        target_length = dialog.get_target_length()
        if target_length <= 0:
            QtWidgets.QMessageBox.warning(self._host._window, "Scale Track", "Desired track length must be greater than zero.")
            return
        if math.isclose(target_length, current_length, rel_tol=1e-6):
            self._host._window.show_status_message("Track already at desired length.")
            return
        status = self._host._window.preview.scale_track_to_length(target_length)
        if not status:
            QtWidgets.QMessageBox.warning(self._host._window, "Scale Track", "Scaling could not be applied. Ensure the track is a valid closed loop.")
            return
        self._host._window.show_status_message(status)
        self._host._update_track_length_display()

    def open_rotate_track_dialog(self) -> None:
        sections, _ = self._host._window.preview.get_section_set()
        if not sections:
            QtWidgets.QMessageBox.information(self._host._window, "Rotate Track", "There are no track sections available to rotate.")
            return
        original_sections = list(sections)
        dialog = RotateTrackDialog(self._host._window)
        dialog.angleChanged.connect(lambda angle_deg: self.apply_track_rotation_preview(original_sections, angle_deg))
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            self._host._window.preview.set_sections(original_sections)
            return
        self._host._window.show_status_message(f"Rotated track by {dialog.angle_degrees():+.1f}° around origin.")

    def apply_track_rotation_preview(self, base_sections: list[SectionPreview], angle_degrees: float) -> None:
        angle_radians = math.radians(angle_degrees)
        rotated_sections = [rotate_section(section, angle_radians) for section in base_sections]
        self._host._window.preview.set_sections(rotated_sections)

    def open_generate_fsects_dialog(self) -> None:
        sections, _ = self._host._window.preview.get_section_set()
        if not sections:
            QtWidgets.QMessageBox.information(self._host._window, "No Sections", "There are no track sections available for fsect generation.")
            return
        dialog = GenerateFsectsDialog(self._host._window, unit_label=self._host._window.fsect_display_unit_label(), decimals=self._host._window.fsect_display_decimals(), step=self._host._window.fsect_display_step(), track_width=30.0, left_grass_width=10.0, right_grass_width=10.0, grass_surface_type=0, wall_surface_type=7, fence_enabled=False)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        track_width = self._host._window.fsect_dlat_from_display_units(dialog.track_width())
        left_grass = self._host._window.fsect_dlat_from_display_units(dialog.left_grass_width())
        right_grass = self._host._window.fsect_dlat_from_display_units(dialog.right_grass_width())
        grass_surface_type = dialog.grass_surface_type()
        wall_surface_type = dialog.wall_surface_type()
        if track_width <= 0:
            QtWidgets.QMessageBox.warning(self._host._window, "Invalid Track Width", "Track width must be greater than zero.")
            return
        if left_grass < 0 or right_grass < 0:
            QtWidgets.QMessageBox.warning(self._host._window, "Invalid Grass Width", "Grass widths must be zero or greater.")
            return
        wall_width = self._host._window.fsect_dlat_from_display_units(self._host._window.fsect_display_step())
        if wall_width <= 0:
            wall_width = 1.0
        base_fsects = self.build_generated_fsects(template=dialog.template(), track_width=track_width, left_grass=left_grass, right_grass=right_grass, grass_surface_type=grass_surface_type, wall_surface_type=wall_surface_type, wall_width=wall_width, fence_enabled=dialog.fence_enabled())
        fsects_by_section = [list(base_fsects) for _ in sections]
        if not self._host._window.preview.replace_all_fsects(fsects_by_section):
            QtWidgets.QMessageBox.warning(self._host._window, "Generate Fsects Failed", "Unable to apply generated fsects to the current track.")
            return
        if not self._host._window.sg_fsects_checkbox.isChecked():
            self._host._window.sg_fsects_checkbox.setChecked(True)
        self._host._window.show_status_message("Generated fsects for all sections.")

    @staticmethod
    def build_generated_fsects(*, template: str, track_width: float, left_grass: float, right_grass: float, grass_surface_type: int, wall_surface_type: int, wall_width: float, fence_enabled: bool) -> list[PreviewFSection]:
        fence_type2 = min(FENCE_TYPE2) if fence_enabled and FENCE_TYPE2 else 0
        def wall(start: float, end: float) -> PreviewFSection:
            return PreviewFSection(start_dlat=start, end_dlat=start, surface_type=wall_surface_type, type2=fence_type2)
        def surface(start: float, end: float, surface_type: int) -> PreviewFSection:
            return PreviewFSection(start_dlat=start, end_dlat=start, surface_type=surface_type, type2=0)
        fsects: list[PreviewFSection] = []
        half_track = track_width * 0.5
        if template == "street":
            fsects.append(wall(-half_track, -half_track)); fsects.append(surface(-half_track, half_track, 5)); fsects.append(wall(half_track, half_track + wall_width)); return fsects
        if template == "oval":
            fsects.append(wall(-half_track, -half_track)); fsects.append(surface(-half_track, half_track, 5))
            if left_grass > 0: fsects.append(surface(half_track, half_track + left_grass, grass_surface_type))
            fsects.append(wall(half_track + left_grass, half_track + left_grass + wall_width)); return fsects
        fsects.append(wall(-half_track - right_grass, -half_track - right_grass))
        if right_grass > 0: fsects.append(surface(-half_track - right_grass, -half_track, grass_surface_type))
        fsects.append(surface(-half_track, half_track, 5))
        if left_grass > 0: fsects.append(surface(half_track, half_track + left_grass, grass_surface_type))
        fsects.append(wall(half_track + left_grass, half_track + left_grass + wall_width))
        return fsects

    def copy_fsects_to_previous(self) -> None:
        self.copy_fsects_to_neighbor(direction="previous")

    def copy_fsects_to_next(self) -> None:
        self.copy_fsects_to_neighbor(direction="next")

    def copy_fsects_to_neighbor(self, *, direction: str) -> None:
        selection = self._host._active_selection
        if selection is None:
            return
        target_index = selection.previous_id if direction == "previous" else selection.next_id if direction == "next" else -1
        sections, _ = self._host._window.preview.get_section_set()
        if target_index < 0 or target_index >= len(sections):
            QtWidgets.QMessageBox.information(self._host._window, "Copy Fsects", f"No {direction} section is connected to this section.")
            return
        edge = "start" if direction == "previous" else "end"
        if not self._host._window.preview.copy_section_fsects(selection.index, target_index, edge=edge):
            QtWidgets.QMessageBox.warning(self._host._window, "Copy Failed", "Unable to copy fsect data to the requested section.")
            return
        self._host._window.preview.selection_manager.set_selected_section(target_index)
        self._host._window.show_status_message(f"Copied fsects from section {selection.index} to {direction} section {target_index}.")

    def add_fsect_below_selected(self) -> None:
        selection = self._host._active_selection
        if selection is None:
            return
        section_index = selection.index
        fsects = self._host._window.preview.get_section_fsects(section_index)
        if not fsects:
            new_fsect = PreviewFSection(start_dlat=-300000, end_dlat=-300000, surface_type=7, type2=0)
            insert_index = 0
        else:
            row_index = self._host._window.fsect_table.currentRow()
            if row_index < 0 or row_index >= len(fsects):
                self._host._window.show_status_message("Select an Fsect row to add below.")
                return
            current = fsects[row_index]
            new_fsect = PreviewFSection(start_dlat=current.start_dlat, end_dlat=current.end_dlat, surface_type=current.surface_type, type2=current.type2)
            insert_index = row_index + 1
        self._host._window.preview.insert_fsection(section_index, insert_index, new_fsect)
        self._host._window.update_selection_sidebar(selection)
        self._host._window.fsect_table.setCurrentCell(insert_index, 0)
        self._host._update_fsect_edit_buttons()
        self._host._window.show_status_message(f"Added fsect at row {insert_index}.")

    def delete_selected_fsect(self) -> None:
        selection = self._host._active_selection
        if selection is None:
            return
        row_index = self._host._window.fsect_table.currentRow()
        fsects = self._host._window.preview.get_section_fsects(selection.index)
        if row_index < 0 or row_index >= len(fsects):
            self._host._window.show_status_message("Select an Fsect row to delete.")
            return
        self._host._window.preview.delete_fsection(selection.index, row_index)
        self._host._window.update_selection_sidebar(selection)
        remaining = len(self._host._window.preview.get_section_fsects(selection.index))
        if remaining:
            self._host._window.fsect_table.setCurrentCell(min(row_index, remaining - 1), 0)
        self._host._update_fsect_edit_buttons()
        self._host._window.show_status_message(f"Deleted fsect row {row_index}.")
