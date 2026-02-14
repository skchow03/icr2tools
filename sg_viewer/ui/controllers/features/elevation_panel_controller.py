from __future__ import annotations

from typing import Protocol

from PyQt5 import QtWidgets

from sg_viewer.ui.altitude_units import feet_to_slider_units, units_from_500ths
from sg_viewer.ui.elevation_profile import elevation_profile_alt_bounds
from sg_viewer.ui.xsect_elevation import XsectElevationData


class ElevationPanelHost(Protocol):
    _window: QtWidgets.QMainWindow
    _active_selection: object | None
    _elevation_controller: object

    def _current_xsect_index(self) -> int | None: ...
    def _current_samples_per_section(self) -> int: ...
    def _update_copy_xsect_button(self) -> None: ...
    def _apply_altitude_edit(self) -> None: ...
    def _apply_grade_edit(self) -> None: ...
    def _refresh_elevation_inputs(self) -> None: ...
    def _sync_after_xsect_value_change(self) -> None: ...


class ElevationPanelController:
    def __init__(self, host: ElevationPanelHost) -> None:
        self._host = host

    def populate_xsect_choices(self, preferred_index: int | None = None) -> None:
        metadata = self._host._window.preview.get_xsect_metadata()
        combo = self._host._window.xsect_combo
        unit = str(self._host._window.measurement_units_combo.currentData())
        unit_label = {"feet": "ft", "meter": "m", "inch": "in", "500ths": "500ths"}.get(unit, "500ths")
        decimals = {"feet": 1, "meter": 3, "inch": 1, "500ths": 0}.get(unit, 0)
        combo.blockSignals(True); combo.clear()
        for idx, dlat in metadata:
            display_dlat = units_from_500ths(dlat, unit)
            formatted_dlat = f"{int(round(display_dlat))}" if decimals == 0 else f"{display_dlat:.{decimals}f}".rstrip("0").rstrip(".")
            combo.addItem(f"{idx} (DLAT {formatted_dlat} {unit_label})", idx)
        combo.setEnabled(bool(metadata))
        if metadata:
            target_index = max(0, min(preferred_index if preferred_index is not None else 0, len(metadata)-1))
            combo.setCurrentIndex(target_index)
        combo.blockSignals(False)
        self._host._update_copy_xsect_button()

    def refresh_elevation_profile(self) -> None:
        combo = self._host._window.xsect_combo
        if not combo.isEnabled():
            self._host._window.preview.set_selected_xsect_index(None)
            self._host._window.profile_widget.set_profile_data(None)
            self._host._elevation_controller.current_profile = None
            self._host._refresh_elevation_inputs()
            self.refresh_xsect_elevation_panel()
            return
        current_index = combo.currentData()
        if current_index is None:
            current_index = combo.currentIndex()
        self._host._window.preview.set_selected_xsect_index(int(current_index))
        samples_per_section = self._host._current_samples_per_section()
        profile = self._host._window.preview.build_elevation_profile(int(current_index), samples_per_section=samples_per_section)
        if profile is not None:
            profile.unit = self._host._window.xsect_altitude_unit()
            profile.unit_label = self._host._window.xsect_altitude_unit_label()
            profile.decimals = self._host._window.xsect_altitude_display_decimals()
            if self._host._elevation_controller.should_lock_bounds():
                global_bounds = self._host._elevation_controller.current_profile.y_range
            else:
                global_bounds = self._host._window.preview.get_elevation_profile_bounds(samples_per_section=samples_per_section)
            if global_bounds is not None:
                profile.y_range = global_bounds
        self._host._window.profile_widget.set_profile_data(profile)
        self._host._elevation_controller.current_profile = profile
        self._host._refresh_elevation_inputs()
        self._host._update_copy_xsect_button()
        self.refresh_xsect_elevation_panel()

    def refresh_elevation_inputs(self) -> None:
        selected = self._host._active_selection
        xsect_index = self._host._current_xsect_index()
        has_selection = selected is not None and xsect_index is not None
        altitude: int | None = None
        grade: int | None = None
        if has_selection and selected is not None and xsect_index is not None:
            altitude, grade = self._host._window.preview.get_section_xsect_values(
                selected.index, xsect_index
            )

        self._host._window.update_elevation_inputs(altitude, grade, has_selection)
        self._host._window.set_altitude_inputs_enabled(has_selection)
        self._host._window.set_grade_inputs_enabled(has_selection)

    def on_altitude_slider_changed(self, value: int) -> None:
        self._host._window.update_altitude_display(value)
        self._host._elevation_controller.begin_edit()
        self._host._apply_altitude_edit()

    def on_altitude_slider_released(self) -> None:
        self._host._window.preview.validate_document()
        if self._host._elevation_controller.end_edit():
            self.refresh_elevation_profile()

    def on_grade_slider_changed(self, value: int) -> None:
        _ = value
        self._host._elevation_controller.begin_edit()
        self._host._apply_grade_edit()

    def on_grade_edit_finished(self) -> None:
        self._host._window.preview.validate_document()
        if self._host._elevation_controller.end_edit():
            self.refresh_elevation_profile()

    def on_altitude_range_changed(self, changed: str | None = None) -> None:
        min_value = self._host._window.altitude_min_spin.value()
        max_value = self._host._window.altitude_max_spin.value()
        if min_value >= max_value:
            if changed == "max":
                min_value = max_value - 0.1
                self._host._window.altitude_min_spin.blockSignals(True)
                self._host._window.altitude_min_spin.setValue(min_value)
                self._host._window.altitude_min_spin.blockSignals(False)
            else:
                max_value = min_value + 0.1
                self._host._window.altitude_max_spin.blockSignals(True)
                self._host._window.altitude_max_spin.setValue(max_value)
                self._host._window.altitude_max_spin.blockSignals(False)
        slider_min = feet_to_slider_units(min_value)
        slider_max = feet_to_slider_units(max_value)
        self._host._window.set_altitude_slider_bounds(slider_min, slider_max)
        self.refresh_elevation_profile()

    def open_altitude_range_dialog(self) -> None:
        if self._host._window.show_altitude_range_dialog():
            self.on_altitude_range_changed()

    def open_grade_range_dialog(self) -> None:
        self._host._window.show_grade_range_dialog()

    def open_raise_lower_elevations_dialog(self) -> None:
        self._host._window.show_raise_lower_elevations_dialog()

    def open_flatten_all_elevations_and_grade_dialog(self) -> bool:
        return self._host._window.show_flatten_all_elevations_and_grade_dialog()

    def copy_xsect_to_all(self) -> bool:
        xsect_index = self._host._current_xsect_index()
        if xsect_index is None:
            return False
        response = QtWidgets.QMessageBox.question(
            self._host._window, "Copy X-Section", f"Copy X-section {xsect_index} altitude and grade data to all x-sections?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No, QtWidgets.QMessageBox.No,
        )
        if response != QtWidgets.QMessageBox.Yes:
            return False
        if not self._host._window.preview.copy_xsect_data_to_all(xsect_index):
            QtWidgets.QMessageBox.warning(self._host._window, "Copy Failed", "Unable to copy x-section data. Ensure all sections have elevation data.")
            return False
        self._host._window.show_status_message(f"Copied x-section {xsect_index} data to all x-sections.")
        return True

    def refresh_xsect_elevation_panel(self) -> None:
        selection = self._host._active_selection
        if selection is None:
            self._host._window.xsect_elevation_widget.set_xsect_data(None)
            self.refresh_xsect_elevation_table()
            return
        altitudes = self._host._window.preview.get_section_xsect_altitudes(selection.index)
        metadata = self._host._window.preview.get_xsect_metadata()
        xsect_dlats = [dlat for _, dlat in metadata] if metadata else None
        y_range = elevation_profile_alt_bounds(self._host._elevation_controller.current_profile) if self._host._elevation_controller.current_profile is not None else None
        self._host._window.xsect_elevation_widget.set_xsect_data(XsectElevationData(section_index=selection.index, altitudes=[float(v) if v is not None else None for v in altitudes], xsect_dlats=xsect_dlats, selected_xsect_index=self._host._current_xsect_index(), y_range=y_range, unit=self._host._window.xsect_altitude_unit(), unit_label=self._host._window.xsect_altitude_unit_label(), decimals=self._host._window.xsect_altitude_display_decimals()))
        self.refresh_xsect_elevation_table()

    def refresh_xsect_elevation_table(self) -> None:
        selection = self._host._active_selection
        if selection is None:
            self._host._window.update_xsect_elevation_table([], [], None, enabled=False)
            return
        altitudes = self._host._window.preview.get_section_xsect_altitudes(selection.index)
        grades = self._host._window.preview.get_section_xsect_grades(selection.index)
        self._host._window.update_xsect_elevation_table(altitudes, grades, self._host._current_xsect_index(), enabled=bool(altitudes) and bool(grades))

    def on_xsect_table_cell_changed(self, row_index: int, column_index: int) -> None:
        if self._host._window.is_updating_xsect_table or column_index not in (1, 2):
            return
        selection = self._host._active_selection
        if selection is None:
            return
        item = self._host._window.xsect_elevation_table.item(row_index, column_index)
        if item is None:
            return
        text = item.text().strip()
        if not text:
            self.refresh_xsect_elevation_table(); return
        if column_index == 1:
            try: display_value = float(text)
            except ValueError: self.refresh_xsect_elevation_table(); return
            altitude = self._host._window.xsect_altitude_from_display_units(display_value)
            if self._host._window.preview.set_section_xsect_altitude(selection.index, row_index, altitude, validate=False):
                self._host._sync_after_xsect_value_change()
        else:
            try: grade = int(text)
            except ValueError: self.refresh_xsect_elevation_table(); return
            if self._host._window.preview.set_section_xsect_grade(selection.index, row_index, grade, validate=False):
                self._host._sync_after_xsect_value_change()
        if row_index == self._host._current_xsect_index():
            self._host._refresh_elevation_inputs()
