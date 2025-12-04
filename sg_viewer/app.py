from __future__ import annotations

import logging
from pathlib import Path
from typing import List

from PyQt5 import QtWidgets

from sg_viewer.preview_widget import SectionSelection, SGPreviewWidget


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
        self._sidebar = QtWidgets.QWidget()
        self._section_label = QtWidgets.QLabel("Section: None")
        self._type_label = QtWidgets.QLabel("Type: –")
        self._dlong_label = QtWidgets.QLabel("DLONG: –")
        self._center_label = QtWidgets.QLabel("Center: –")
        self._radius_label = QtWidgets.QLabel("Radius: –")

        sidebar_layout = QtWidgets.QVBoxLayout()
        sidebar_layout.addWidget(QtWidgets.QLabel("Selection"))
        sidebar_layout.addWidget(self._section_label)
        sidebar_layout.addWidget(self._type_label)
        sidebar_layout.addWidget(self._dlong_label)
        sidebar_layout.addWidget(self._center_label)
        sidebar_layout.addWidget(self._radius_label)
        sidebar_layout.addStretch()
        self._sidebar.setLayout(sidebar_layout)

        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(self._preview, stretch=1)
        layout.addWidget(self._sidebar)
        container.setLayout(layout)
        self.setCentralWidget(container)

        self._create_actions()
        self._create_menus()
        self.statusBar().showMessage("Select File → Open SG to begin.")
        self._preview.selectedSectionChanged.connect(self._update_selection_sidebar)

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

    def _update_selection_sidebar(self, selection: SectionSelection | None) -> None:
        if selection is None:
            self._section_label.setText("Section: None")
            self._type_label.setText("Type: –")
            self._dlong_label.setText("DLONG: –")
            self._center_label.setText("Center: –")
            self._radius_label.setText("Radius: –")
            return

        self._section_label.setText(f"Section: {selection.index}")
        self._type_label.setText(f"Type: {selection.type_name}")
        self._dlong_label.setText(
            f"DLONG: {selection.start_dlong:.0f} → {selection.end_dlong:.0f}"
        )
        if selection.center is not None and selection.radius is not None:
            cx, cy = selection.center
            self._center_label.setText(f"Center: ({cx:.1f}, {cy:.1f})")
            self._radius_label.setText(f"Radius: {selection.radius:.1f}")
        else:
            self._center_label.setText("Center: –")
            self._radius_label.setText("Radius: –")

