"""Compatibility exports for SG viewer UI app objects."""

from sg_viewer.ui.app_bootstrap import SGViewerApp, bootstrap_window, wire_window_features
from sg_viewer.ui.main_window import SGViewerWindow

__all__ = [
    "SGViewerApp",
    "SGViewerWindow",
    "bootstrap_window",
    "wire_window_features",
]
