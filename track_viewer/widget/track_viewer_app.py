"""Application wiring for the track viewer."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt5 import QtGui, QtWidgets

from track_viewer import config as viewer_config


class TrackViewerApp(QtWidgets.QApplication):
    """Thin wrapper that stores shared state for the viewer."""

    def __init__(self, argv: List[str], main_script_path: Optional[Path] = None):
        surface_format = QtGui.QSurfaceFormat()
        surface_format.setSamples(4)
        QtGui.QSurfaceFormat.setDefaultFormat(surface_format)
        super().__init__(argv)
        self.setQuitOnLastWindowClosed(True)

        self._main_script_path = main_script_path
        self.installation_path = viewer_config.load_installation_path(
            self._main_script_path
        )
        self.tracks: List[str] = []
        self.window: Optional["TrackViewerWindow"] = None

    def load_lp_colors(self) -> dict[str, str]:
        return viewer_config.load_lp_colors(self._main_script_path)

    def save_lp_colors(self, lp_colors: dict[str, str]) -> None:
        viewer_config.save_lp_colors(lp_colors, self._main_script_path)

    def load_pit_colors(self) -> tuple[dict[int, str], dict[int, str]]:
        return viewer_config.load_pit_colors(self._main_script_path)

    def save_pit_colors(
        self, dlong_colors: dict[int, str], dlat_colors: dict[int, str]
    ) -> None:
        viewer_config.save_pit_colors(dlong_colors, dlat_colors, self._main_script_path)

    def set_installation_path(self, path: Optional[Path]) -> None:
        self.installation_path = path
        if path is None:
            return
        viewer_config.save_installation_path(path, self._main_script_path)

    def update_tracks(self, tracks: List[str]) -> None:
        self.tracks = tracks
