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

    def on_profile_section_clicked(self, section_index: int) -> None:
        self._host._window.preview.selection_manager.set_selected_section(section_index)

    def on_profile_altitude_dragged(self, section_index: int, altitude: float) -> None:
        xsect_index = self._host._current_xsect_index()
        if xsect_index is None:
            return

        if self._host._elevation_controller.begin_drag():
            self._host._window.preview.begin_fsect_edit_session()

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
        self._host._window.preview.validate_document()
        if self._host._elevation_controller.end_drag():
            self._host._window.preview.commit_fsect_edit_session()

    def on_altitude_range_changed(self, changed: str | None = None) -> None:
        self._elevation_panel_controller.on_altitude_range_changed(changed)

    def copy_xsect_to_all(self) -> bool:
        if self._elevation_panel_controller.copy_xsect_to_all():
            self._host._sync_after_xsect_value_change()
            return True
        return False

    def on_measurement_units_changed(self) -> None:
        self._host._history.set_measurement_unit(
            str(self._host._window.measurement_units_combo.currentData())
        )
