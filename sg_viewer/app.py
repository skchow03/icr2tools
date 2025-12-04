from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from PyQt5 import QtWidgets

from sg_viewer.preview_widget import SGPreviewWidget


class SGViewerApp(QtWidgets.QApplication):
    """Thin application wrapper for the SG viewer."""

    def __init__(self, argv: List[str]):
        super().__init__(argv)
        self.setQuitOnLastWindowClosed(True)
        self.window: SGViewerWindow | None = None


class SGViewerWindow(QtWidgets.QMainWindow):
    """Single-window utility that previews SG centrelines."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SG Viewer")
        self.resize(960, 720)

        self._preview = SGPreviewWidget()
        self.setCentralWidget(self._preview)

        self._create_actions()
        self._create_menus()
        self.statusBar().showMessage("Select File → Open SG to begin.")

    def load_sg(self, path: Path) -> None:
        try:
            self._preview.load_sg_file(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Failed to load SG", str(exc))
            logging.exception("Failed to load SG file")
        else:
            self.statusBar().showMessage(f"Loaded {path}")

    def _create_actions(self) -> None:
        self._open_action = QtWidgets.QAction("Open SG…", self)
        self._open_action.setShortcut("Ctrl+O")
        self._open_action.triggered.connect(self._open_file_dialog)

        self._quit_action = QtWidgets.QAction("Quit", self)
        self._quit_action.setShortcut("Ctrl+Q")
        self._quit_action.triggered.connect(self.close)

    def _create_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self._open_action)
        file_menu.addSeparator()
        file_menu.addAction(self._quit_action)

    def _open_file_dialog(self) -> None:
        options = QtWidgets.QFileDialog.Options()
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open SG file",
            "",
            "SG files (*.sg *.SG);;All files (*)",
            options=options,
        )
        if file_path:
            self.load_sg(Path(file_path))

