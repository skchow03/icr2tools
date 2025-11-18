"""Simple Qt application shell for the standalone track viewer."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt5 import QtWidgets, QtCore


class TrackViewerApp(QtWidgets.QApplication):
    """Thin wrapper that stores shared state for the viewer."""

    def __init__(self, argv: List[str]):
        super().__init__(argv)
        self.setQuitOnLastWindowClosed(True)

        self.installation_path: Optional[Path] = None
        self.tracks: List[str] = []
        self.window: Optional["TrackViewerWindow"] = None

    def update_tracks(self, tracks: List[str]) -> None:
        self.tracks = tracks


class TrackViewerWindow(QtWidgets.QMainWindow):
    """Minimal placeholder UI that demonstrates shared state wiring."""

    def __init__(self, app_state: TrackViewerApp):
        super().__init__()
        self.app_state = app_state
        self.app_state.window = self

        self.setWindowTitle("ICR2 Track Viewer")
        self.resize(720, 480)

        self._path_display = QtWidgets.QLineEdit()
        self._path_display.setReadOnly(True)
        self._browse_button = QtWidgets.QPushButton("Select Folder…")
        self._browse_button.clicked.connect(self._select_installation_path)

        self._track_list = QtWidgets.QListWidget()
        self._track_list.currentTextChanged.connect(self._update_visualization)

        self.visualization_widget = QtWidgets.QLabel("Select a track to preview.")
        self.visualization_widget.setAlignment(QtCore.Qt.AlignCenter)
        self.visualization_widget.setMinimumHeight(180)
        self.visualization_widget.setFrameShape(QtWidgets.QFrame.StyledPanel)

        layout = QtWidgets.QVBoxLayout()
        header = QtWidgets.QHBoxLayout()
        header.addWidget(QtWidgets.QLabel("ICR2 Installation:"))
        header.addWidget(self._path_display, stretch=1)
        header.addWidget(self._browse_button)
        layout.addLayout(header)

        body = QtWidgets.QSplitter()
        body.setOrientation(QtCore.Qt.Horizontal)
        body.addWidget(self._track_list)
        body.addWidget(self.visualization_widget)
        body.setSizes([200, 500])
        layout.addWidget(body, stretch=1)

        wrapper = QtWidgets.QWidget()
        wrapper.setLayout(layout)
        self.setCentralWidget(wrapper)

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def _select_installation_path(self) -> None:
        start_dir = str(self.app_state.installation_path or Path.home())
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select IndyCar Racing II folder",
            start_dir,
        )
        if folder:
            self.app_state.installation_path = Path(folder)
            self._path_display.setText(str(self.app_state.installation_path))
            self._load_tracks()

    def _load_tracks(self) -> None:
        if not self.app_state.installation_path:
            return

        track_dir = self.app_state.installation_path / "tracks"
        tracks: List[str] = []
        if track_dir.exists() and track_dir.is_dir():
            for path in sorted(track_dir.glob("*.trk")):
                tracks.append(path.name)

        self.app_state.update_tracks(tracks)
        self._track_list.clear()
        if not tracks:
            self._track_list.addItem("(No .TRK files found)")
            self._track_list.setEnabled(False)
        else:
            self._track_list.setEnabled(True)
            self._track_list.addItems(tracks)
            self._track_list.setCurrentRow(0)

    def _update_visualization(self, track_name: str) -> None:
        if not track_name:
            return
        if track_name.startswith("("):
            self.visualization_widget.setText("Select a valid track file to preview.")
            return

        self.visualization_widget.setText(
            f"Preview for {track_name}\n\n" "Rendering coming soon…"
        )
