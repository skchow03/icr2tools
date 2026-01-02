"""Keyboard interaction handlers for the track preview widget."""
from __future__ import annotations

from PyQt5 import QtGui


class TrackPreviewKeyboardController:
    """Handles keyboard-based interactions for the track preview widget."""

    def handle_key_press(self, event: QtGui.QKeyEvent) -> bool:
        return False

    def handle_key_release(self, event: QtGui.QKeyEvent) -> bool:
        return False
