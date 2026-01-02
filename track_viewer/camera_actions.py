"""Helper for camera add/save operations that surface user-facing messages."""
from __future__ import annotations

from PyQt5 import QtCore

from track_viewer.widget import TrackPreviewWidget


class CameraActions(QtCore.QObject):
    """Handle camera add/save flows for a preview widget."""

    infoMessage = QtCore.pyqtSignal(str, str)
    warningMessage = QtCore.pyqtSignal(str, str)

    def __init__(self, preview_widget: TrackPreviewWidget):
        super().__init__()
        self._preview_widget = preview_widget

    def add_type6_camera(self) -> None:
        self._emit_result(*self._preview_widget.add_type6_camera(), title="Add Type 6 Camera")

    def add_type7_camera(self) -> None:
        self._emit_result(*self._preview_widget.add_type7_camera(), title="Add Type 7 Camera")

    def save_cameras(self) -> None:
        self._emit_result(*self._preview_widget.save_cameras(), title="Save Cameras")

    def _emit_result(self, success: bool, message: str, *, title: str) -> None:
        target = self.infoMessage if success else self.warningMessage
        target.emit(title, message)
