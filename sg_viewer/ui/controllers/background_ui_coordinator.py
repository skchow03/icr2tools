from __future__ import annotations


class BackgroundUiCoordinator:
    def __init__(self, background_controller: object) -> None:
        self._background_controller = background_controller

    def open_background_file_dialog(self) -> None:
        self._background_controller.open_background_file_dialog()

    def show_background_settings_dialog(self) -> None:
        self._background_controller.show_background_settings_dialog()

    def launch_background_calibrator(self) -> None:
        self._background_controller.launch_background_calibrator()

    def apply_calibrator_values(self, data: dict) -> None:
        self._background_controller.apply_calibrator_values(data)

    def clear_background_state(self) -> None:
        self._background_controller.clear_background_state()

    def apply_saved_background(self, sg_path=None) -> None:
        self._background_controller.apply_saved_background(sg_path)

    def persist_background_state(self) -> None:
        self._background_controller.persist_background_state()
