from __future__ import annotations

from typing import Protocol


class ElevationUiHost(Protocol):
    _active_selection: object | None
    _window: object
    _elevation_controller: object
    _history: object

    def _current_xsect_index(self) -> int | None: ...
    def _refresh_elevation_profile(self) -> None: ...
    def _refresh_xsect_elevation_panel(self) -> None: ...
    def _refresh_xsect_elevation_table(self) -> None: ...
    def _refresh_elevation_inputs(self) -> None: ...
    def _sync_after_xsect_value_change(self) -> None: ...


class ElevationUiCoordinator:
    def __init__(self, host: ElevationUiHost, elevation_panel_controller: object) -> None:
        self._host = host
        self._elevation_panel_controller = elevation_panel_controller

    def connect_signals(self) -> None:
        host = self._host
        window = host._window
        window.xsect_combo.currentIndexChanged.connect(host._refresh_elevation_profile)
        window.copy_xsect_button.clicked.connect(self.copy_xsect_data_to_targets)
        window.generate_elevation_change_button.clicked.connect(host._open_generate_elevation_change_dialog)
        window.generateElevationChangeApplied.connect(host._on_generate_elevation_change_applied)
        window.altitude_slider.valueChanged.connect(host._on_altitude_slider_changed)
        window.altitude_slider.sliderReleased.connect(host._on_altitude_slider_released)
        window.altitude_min_spin.valueChanged.connect(lambda _value: self.on_altitude_range_changed("min"))
        window.altitude_max_spin.valueChanged.connect(lambda _value: self.on_altitude_range_changed("max"))
        window.altitude_set_range_button.clicked.connect(host._open_altitude_range_dialog)
        window.grade_spin.valueChanged.connect(host._on_grade_slider_changed)
        window.grade_spin.sliderReleased.connect(host._on_grade_edit_finished)
        window.grade_set_range_button.clicked.connect(host._open_grade_range_dialog)
        window.preview.scaleChanged.connect(host._on_scale_changed)
        window.profile_widget.sectionClicked.connect(self.on_profile_section_clicked)
        window.profile_widget.altitudeDragged.connect(self.on_profile_altitude_dragged)
        window.profile_widget.altitudeDragFinished.connect(self.on_profile_altitude_drag_finished)
        window.measurement_units_combo.currentIndexChanged.connect(host._on_measurement_units_changed)

    def on_profile_section_clicked(self, section_index: int) -> None:
        self._host._window.preview.selection_manager.set_selected_section(section_index)

    def on_profile_altitude_dragged(self, section_index: int, altitude: float) -> None:
        xsect_index = self._host._current_xsect_index()
        if xsect_index is None:
            return

        self._host._elevation_controller.begin_drag()
        self._host._window.preview.document.set_elevation_signals_suspended(True)
        if self._host._window.preview.set_section_xsect_altitude(
            section_index, xsect_index, altitude, validate=False
        ):
            self._host._refresh_elevation_profile()
            self._host._refresh_xsect_elevation_panel()
            if (
                self._host._active_selection is not None
                and self._host._active_selection.index == section_index
            ):
                self._host._refresh_elevation_inputs()

    def on_profile_altitude_drag_finished(self, section_index: int) -> None:
        _ = section_index
        self._host._window.preview.document.set_elevation_signals_suspended(False)
        self._host._elevation_controller.end_drag()
        self._host._window.preview.validate_document()

    def on_altitude_range_changed(self, changed: str | None = None) -> None:
        self._elevation_panel_controller.on_altitude_range_changed(changed)

    def copy_xsect_data_to_targets(self) -> bool:
        if self._elevation_panel_controller.copy_xsect_data_to_targets():
            self._host._sync_after_xsect_value_change()
            return True
        return False

    def on_measurement_units_changed(self) -> None:
        self._host._history.set_measurement_unit(
            str(self._host._window.measurement_units_combo.currentData())
        )
