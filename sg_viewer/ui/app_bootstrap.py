from __future__ import annotations

from typing import List

from PyQt5 import QtWidgets

from sg_viewer.ui.main_window import SGViewerWindow
from sg_viewer.ui.viewer_controller import SGViewerController


class SGViewerApp(QtWidgets.QApplication):
    """Thin application wrapper for the SG viewer."""

    def __init__(self, argv: List[str]):
        super().__init__(argv)
        self.setQuitOnLastWindowClosed(True)
        self.window: SGViewerWindow | None = None


def wire_window_features(window: SGViewerWindow) -> SGViewerController:
    """Attach services/controllers and feature wiring for a window instance."""

    controller = SGViewerController(window)
    window.controller = controller
    return controller


def bootstrap_window(*, wire_features: bool = True) -> SGViewerWindow:
    """Build the main window and optionally wire interactive features."""

    window = SGViewerWindow(wire_features=False)
    if wire_features:
        wire_window_features(window)
    return window
