from __future__ import annotations

import math
from dataclasses import replace
from typing import Protocol

from PyQt5 import QtWidgets

from sg_viewer.geometry.sg_geometry import rotate_section
from sg_viewer.geometry.topology import is_closed_loop, loop_length
from sg_viewer.model.preview_fsection import PreviewFSection
from sg_viewer.sg_document_fsects import GROUND_TYPES
from sg_viewer.services.fsect_generation_service import build_generated_fsects
from sg_viewer.model.sg_model import SectionPreview
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
    _reverse_track_action: QtWidgets.QAction
    _generate_pitwall_action: QtWidgets.QAction
    _raise_lower_elevations_action: QtWidgets.QAction
    _flatten_all_elevations_and_grade_action: QtWidgets.QAction
    _generate_elevation_change_action: QtWidgets.QAction
    _delete_default_style: str

    def _start_new_straight(self) -> None: ...
    def _start_new_curve(self) -> None: ...
    def _on_move_section_mode_changed(self, active: bool) -> None: ...
    def _sync_after_section_mutation(self) -> None: ...
    def _update_track_length_display(self) -> None: ...
    def _mark_fsects_dirty(self, dirty: bool) -> None: ...


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
        self._host._scale_track_action.setEnabled(has_sections and is_closed_loop(sections))
        self._host._rotate_track_action.setEnabled(has_sections)
        self._host._reverse_track_action.setEnabled(has_sections)
        self._host._generate_pitwall_action.setEnabled(has_sections)
        self._host._raise_lower_elevations_action.setEnabled(has_sections)
        self._host._flatten_all_elevations_and_grade_action.setEnabled(has_sections)
        self._host._generate_elevation_change_action.setEnabled(has_sections)
        self._host._save_action.setEnabled(True)
        if self._host._is_untitled:
            self._host._window.update_window_title(path=None, is_dirty=True, is_untitled=True)
        elif self._host._current_path is not None:
            self._host._window.update_window_title(path=self._host._current_path, is_dirty=True)

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

    def reverse_track(self) -> None:
        preview = self._host._window.preview
        original_transform_state = getattr(preview, "transform_state", None)

        sections, _ = self._host._window.preview.get_section_set()
        if not sections:
            QtWidgets.QMessageBox.information(
                self._host._window,
                "Reverse Track",
                "There are no track sections available to reverse.",
            )
            return

        section_count = len(sections)
        old_to_new = {old_idx: section_count - 1 - old_idx for old_idx in range(section_count)}

        reversed_sections: list[SectionPreview] = []
        reversed_fsects: list[list[PreviewFSection]] = []
        for new_idx, old_idx in enumerate(range(section_count - 1, -1, -1)):
            section = sections[old_idx]

            previous_id = old_to_new.get(section.next_id, -1)
            next_id = old_to_new.get(section.previous_id, -1)

            reversed_sections.append(
                replace(
                    section,
                    section_id=new_idx,
                    source_section_id=old_idx,
                    previous_id=previous_id,
                    next_id=next_id,
                    start=section.end,
                    end=section.start,
                    start_heading=section.end_heading,
                    end_heading=section.start_heading,
                    sang1=section.eang1,
                    sang2=section.eang2,
                    eang1=section.sang1,
                    eang2=section.sang2,
                    radius=(
                        -section.radius
                        if section.type_name == "curve" and section.radius is not None
                        else section.radius
                    ),
                )
            )

            mirrored_fsects = self._mirror_section_fsects(
                self._host._window.preview.get_section_fsects(old_idx)
            )
            reversed_fsects.append(mirrored_fsects)

        try:
            self._host._window.preview.set_sections(reversed_sections)
            if not self._host._window.preview.replace_all_fsects(reversed_fsects):
                QtWidgets.QMessageBox.warning(
                    self._host._window,
                    "Reverse Track",
                    "Unable to reverse fsect data for the reversed track.",
                )
                return

            xsect_metadata = self._host._window.preview.get_xsect_metadata()
            if len(xsect_metadata) >= 2:
                reversed_xsects = [
                    (index, -float(dlat)) for index, dlat in reversed(xsect_metadata)
                ]
                if not self._host._window.preview.set_xsect_definitions(reversed_xsects):
                    QtWidgets.QMessageBox.warning(
                        self._host._window,
                        "Reverse Track",
                        "Unable to reverse x-section DLAT order for the reversed track.",
                    )
                    return

            try:
                self._host._window.preview.apply_preview_to_sgfile()
            except ValueError:
                pass

            self._host._window.show_status_message(
                "Reversed section order, start/finish direction, fsects, and elevation/grade mapping."
            )
        finally:
            preview_controller = getattr(preview, "controller", None)
            if preview_controller is not None and original_transform_state is not None:
                preview_controller.transform_state = original_transform_state
                if hasattr(preview, "request_repaint"):
                    preview.request_repaint()

    def _mirror_section_fsects(
        self, fsects: list[PreviewFSection]
    ) -> list[PreviewFSection]:
        grounds = [fsect for fsect in fsects if int(fsect.surface_type) in GROUND_TYPES]
        boundaries = [fsect for fsect in fsects if int(fsect.surface_type) not in GROUND_TYPES]

        mirrored_boundaries = [
            PreviewFSection(
                start_dlat=-float(fsect.end_dlat),
                end_dlat=-float(fsect.start_dlat),
                surface_type=int(fsect.surface_type),
                type2=int(fsect.type2),
            )
            for fsect in boundaries
        ]

        if not grounds:
            mirrored_boundaries.sort(key=lambda fsect: (fsect.start_dlat, fsect.end_dlat))
            return mirrored_boundaries

        grounds_sorted = sorted(
            grounds, key=lambda fsect: (fsect.start_dlat + fsect.end_dlat) * 0.5
        )

        # Reversing a section swaps start/end stations. Ground strips are stored as
        # right-edge DLATs per station, so mirror computations must consume the
        # opposite station when rebuilding the new right edges.
        left_boundary_start = max(
            (float(boundary.end_dlat) for boundary in boundaries),
            default=float(grounds_sorted[-1].end_dlat),
        )
        left_boundary_end = max(
            (float(boundary.start_dlat) for boundary in boundaries),
            default=float(grounds_sorted[-1].start_dlat),
        )

        start_widths: list[float] = []
        end_widths: list[float] = []
        for idx, ground in enumerate(grounds_sorted):
            next_start = (
                float(grounds_sorted[idx + 1].end_dlat)
                if idx + 1 < len(grounds_sorted)
                else left_boundary_start
            )
            next_end = (
                float(grounds_sorted[idx + 1].start_dlat)
                if idx + 1 < len(grounds_sorted)
                else left_boundary_end
            )
            start_widths.append(next_start - float(ground.end_dlat))
            end_widths.append(next_end - float(ground.start_dlat))

        mirrored_grounds: list[PreviewFSection] = []
        current_start = -left_boundary_start
        current_end = -left_boundary_end
        for original_idx in range(len(grounds_sorted) - 1, -1, -1):
            original = grounds_sorted[original_idx]
            mirrored_grounds.append(
                PreviewFSection(
                    start_dlat=current_start,
                    end_dlat=current_end,
                    surface_type=int(original.surface_type),
                    type2=int(original.type2),
                )
            )
            current_start += start_widths[original_idx]
            current_end += end_widths[original_idx]

        mirrored_fsects = mirrored_grounds + mirrored_boundaries
        mirrored_fsects.sort(key=lambda fsect: (fsect.start_dlat, fsect.end_dlat))
        return mirrored_fsects

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
        base_fsects = build_generated_fsects(template=dialog.template(), track_width=track_width, left_grass=left_grass, right_grass=right_grass, grass_surface_type=grass_surface_type, wall_surface_type=wall_surface_type, wall_width=wall_width, fence_enabled=dialog.fence_enabled())
        fsects_by_section = [list(base_fsects) for _ in sections]
        if not self._host._window.preview.replace_all_fsects(fsects_by_section):
            QtWidgets.QMessageBox.warning(self._host._window, "Generate Fsects Failed", "Unable to apply generated fsects to the current track.")
            return
        if not self._host._window.sg_fsects_checkbox.isChecked():
            self._host._window.sg_fsects_checkbox.setChecked(True)
        self._host._mark_fsects_dirty(True)
        self._host._window.show_status_message("Generated fsects for all sections.")


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
        self._host._mark_fsects_dirty(True)
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
        self._host._mark_fsects_dirty(True)
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
        self._host._mark_fsects_dirty(True)
        self._host._window.update_selection_sidebar(selection)
        remaining = len(self._host._window.preview.get_section_fsects(selection.index))
        if remaining:
            self._host._window.fsect_table.setCurrentCell(min(row_index, remaining - 1), 0)
        self._host._update_fsect_edit_buttons()
        self._host._window.show_status_message(f"Deleted fsect row {row_index}.")
