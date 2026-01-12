"""Helper for camera add/save operations that surface user-facing messages."""
from __future__ import annotations

from PyQt5 import QtCore

from track_viewer.preview_api import TrackPreviewApi


class CameraActions(QtCore.QObject):
    """Handle camera add/save flows for a preview widget."""

    infoMessage = QtCore.pyqtSignal(str, str)
    warningMessage = QtCore.pyqtSignal(str, str)

    def __init__(self, preview_api: TrackPreviewApi):
        super().__init__()
        self._preview_api = preview_api

    def add_type6_camera(self) -> None:
        self._emit_result(
            *self._preview_api.add_type6_camera(), title="Add Panning Camera"
        )

    def add_type2_camera(self) -> None:
        self._emit_result(
            *self._preview_api.add_type2_camera(),
            title="Add Alternate Panning Camera",
        )

    def add_type7_camera(self) -> None:
        self._emit_result(
            *self._preview_api.add_type7_camera(), title="Add Fixed Camera"
        )

    def save_cameras(self) -> None:
        self._emit_result(*self._preview_api.save_cameras(), title="Save Cameras")

    def _emit_result(self, success: bool, message: str, *, title: str) -> None:
        target = self.infoMessage if success else self.warningMessage
        target.emit(title, message)
