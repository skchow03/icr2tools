from __future__ import annotations

from pathlib import Path
from typing import Protocol

from PyQt5 import QtWidgets


class FileMenuHost(Protocol):
    _window: QtWidgets.QMainWindow
    _open_recent_menu: QtWidgets.QMenu
    _history: object

    def load_sg(self, path: Path) -> None: ...


class FileMenuCoordinator:
    """Coordinates file-menu behavior and delegates persistence tasks."""

    def __init__(self, host: FileMenuHost, document_controller: object) -> None:
        self._host = host
        self._document_controller = document_controller

    def import_sg_file_dialog(self) -> None:
        self._document_controller.import_sg_file_dialog()

    def import_trk_file_dialog(self) -> None:
        self._document_controller.import_trk_file_dialog()

    def import_trk_from_dat_file_dialog(self) -> None:
        self._document_controller.import_trk_from_dat_file_dialog()

    def save_file_dialog(self) -> None:
        self._document_controller.save_file_dialog()

    def open_project_file_dialog(self) -> None:
        self._document_controller.open_project_file_dialog()

    def save_project_file_dialog(self) -> None:
        self._document_controller.save_project_file_dialog()

    def save_current_file(self) -> None:
        self._document_controller.save_current_file()

    def save_to_path(self, path: Path) -> None:
        self._document_controller.save_to_path(path)

    def convert_sg_to_trk(self) -> None:
        self._document_controller.convert_sg_to_trk()

    def ensure_saved_sg(self) -> Path | None:
        return self._document_controller.ensure_saved_sg()

    def refresh_recent_menu(self) -> None:
        self._host._open_recent_menu.clear()
        recent_paths = self._host._history.get_recent_paths()
        if not recent_paths:
            empty_action = QtWidgets.QAction("No recent files", self._host._open_recent_menu)
            empty_action.setEnabled(False)
            self._host._open_recent_menu.addAction(empty_action)
            return

        for path in recent_paths:
            action = QtWidgets.QAction(str(path), self._host._open_recent_menu)
            action.triggered.connect(lambda checked=False, p=path: self._host.load_sg(p))
            self._host._open_recent_menu.addAction(action)
