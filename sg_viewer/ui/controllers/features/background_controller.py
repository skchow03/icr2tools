from __future__ import annotations

import logging
from pathlib import Path
from typing import Protocol

from PyQt5 import QtWidgets

from sg_viewer.ui.background_image_dialog import BackgroundImageDialog
from sg_viewer.ui.bg_calibrator_minimal import Calibrator


class BackgroundControllerHost(Protocol):
    _window: QtWidgets.QMainWindow
    _sg_settings_store: object
    _current_path: Path | None
    _background_settings_action: QtWidgets.QAction
    _calibrator_window: Calibrator | None


class BackgroundController:
    def __init__(self, host: BackgroundControllerHost, logger: logging.Logger) -> None:
        self._host = host
        self._logger = logger

    def open_background_file_dialog(self) -> None:
        options = QtWidgets.QFileDialog.Options()
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._host._window,
            "Open Background Image",
            "",
            "Image files (*.png *.jpg *.jpeg *.bmp *.pcx);;All files (*)",
            options=options,
        )
        if not file_path:
            return
        try:
            self._host._window.preview.load_background_image(Path(file_path))
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self._host._window, "Failed to load background", str(exc))
            self._logger.exception("Failed to load background image")
            return
        self._host._background_settings_action.setEnabled(True)
        self._host._window.show_status_message(f"Loaded background image {file_path}")
        self.persist_background_state()

    def show_background_settings_dialog(self) -> None:
        if not self._host._window.preview.has_background_image():
            QtWidgets.QMessageBox.information(self._host._window, "No Background", "Load a background image before adjusting its settings.")
            return
        scale, (origin_u, origin_v) = self._host._window.preview.get_background_settings()
        dialog = BackgroundImageDialog(self._host._window, scale, origin_u, origin_v)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            new_scale, new_u, new_v = dialog.get_values()
            if new_scale <= 0:
                QtWidgets.QMessageBox.warning(self._host._window, "Invalid Scale", "500ths per pixel must be greater than zero.")
                return
            self._host._window.preview.set_background_settings(new_scale, (new_u, new_v))
            self._host._window.show_status_message("Updated background image settings")
            self.persist_background_state()

    def launch_background_calibrator(self) -> None:
        background_image_path = self._host._window.preview.get_background_image_path()
        self._host._calibrator_window = Calibrator(
            initial_image_path=(str(background_image_path) if background_image_path is not None else None),
            send_callback=self.apply_calibrator_values,
            parent=self._host._window,
        )
        self._host._calibrator_window.show()
        self._host._window.show_status_message("Opened background calibrator")

    def apply_calibrator_values(self, data: dict) -> None:
        try:
            scale = float(data["units_per_pixel"])
            upper_left = data["upper_left"]
            origin_u = float(upper_left[0])
            origin_v = float(upper_left[1])
            image_path_value = data.get("image_path")
            image_path = Path(image_path_value) if isinstance(image_path_value, str) and image_path_value else None
        except (ValueError, TypeError, KeyError, IndexError):
            self._logger.warning("Invalid background calibration payload: %s", data)
            self._host._window.show_status_message("Ignored invalid calibration values from calibrator")
            return

        if scale <= 0:
            self._host._window.show_status_message("Ignored calibration values with non-positive scale")
            return

        if image_path is not None:
            try:
                self._host._window.preview.load_background_image(image_path)
            except Exception:
                self._logger.warning("Failed to load calibrator background image %s", image_path, exc_info=True)

        self._host._window.preview.set_background_settings(scale, (origin_u, origin_v))
        self._host._background_settings_action.setEnabled(self._host._window.preview.has_background_image())
        self.persist_background_state()
        self._host._window.show_status_message("Applied calibration values from background calibrator")

    def clear_background_state(self) -> None:
        self._host._window.preview.clear_background_image()
        self._host._background_settings_action.setEnabled(False)

    def apply_saved_background(self, sg_path: Path | None = None) -> None:
        path = sg_path or self._host._current_path
        if path is None:
            return
        background_data = self._host._sg_settings_store.get_background(path)
        if not background_data:
            return
        image_path, scale, origin = background_data
        if not image_path.exists():
            self._logger.info("Stored background image %s is missing", image_path)
            return
        try:
            self._host._window.preview.load_background_image(image_path)
            self._host._window.preview.set_background_settings(scale, origin)
        except Exception as exc:
            self._logger.exception("Failed to restore background image", exc_info=exc)
            self._host._window.show_status_message(f"Could not restore background image {image_path}")
            return
        self._host._background_settings_action.setEnabled(True)
        self._host._window.show_status_message(f"Restored background image {image_path} for {path.name}")

    def persist_background_state(self) -> None:
        if self._host._current_path is None:
            return
        background_path = self._host._window.preview.get_background_image_path()
        if background_path is None:
            return
        scale, origin = self._host._window.preview.get_background_settings()
        self._host._sg_settings_store.set_background(self._host._current_path, background_path, scale, origin)
