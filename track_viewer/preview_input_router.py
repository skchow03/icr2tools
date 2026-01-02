"""Input routing for track preview interactions."""
from __future__ import annotations

from PyQt5 import QtCore, QtGui

from track_viewer.preview_coordinator import PreviewCoordinator


class PreviewInputRouter:
    """Routes Qt input events to preview interaction handlers."""

    def __init__(self, coordinator: PreviewCoordinator) -> None:
        self._coordinator = coordinator

    def handle_resize(self, size: QtCore.QSize) -> None:
        self._coordinator.handle_resize(size)

    def handle_wheel(self, event: QtGui.QWheelEvent, size: QtCore.QSize) -> bool:
        return self._coordinator.mouse_controller.handle_wheel(event, size)

    def handle_mouse_press(self, event: QtGui.QMouseEvent, size: QtCore.QSize) -> bool:
        return self._coordinator.mouse_controller.handle_mouse_press(event, size)

    def handle_mouse_move(self, event: QtGui.QMouseEvent, size: QtCore.QSize) -> bool:
        return self._coordinator.mouse_controller.handle_mouse_move(event, size)

    def handle_mouse_release(self, event: QtGui.QMouseEvent, size: QtCore.QSize) -> bool:
        return self._coordinator.mouse_controller.handle_mouse_release(event, size)

    def handle_leave(self) -> None:
        self._coordinator.mouse_controller.handle_leave()

    def handle_key_press(self, event: QtGui.QKeyEvent) -> bool:
        return self._coordinator.keyboard_controller.handle_key_press(event)

    def handle_key_release(self, event: QtGui.QKeyEvent) -> bool:
        return self._coordinator.keyboard_controller.handle_key_release(event)
