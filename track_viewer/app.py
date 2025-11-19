"""Simple Qt application shell for the standalone track viewer."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt5 import QtWidgets, QtCore

from track_viewer.preview_widget import TrackPreviewWidget


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


class CoordinateSidebar(QtWidgets.QFrame):
    """Utility sidebar that mirrors cursor and flag coordinates."""

    def __init__(self) -> None:
        super().__init__()
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setMinimumWidth(200)

        self._cursor_x = self._create_readonly_field("–")
        self._cursor_y = self._create_readonly_field("–")
        self._flag_x = self._create_readonly_field("–")
        self._flag_y = self._create_readonly_field("–")

        layout = QtWidgets.QVBoxLayout()
        layout.setSpacing(12)

        cursor_title = QtWidgets.QLabel("Cursor position")
        cursor_title.setStyleSheet("font-weight: bold")
        layout.addWidget(cursor_title)
        cursor_form = QtWidgets.QFormLayout()
        cursor_form.addRow("X", self._cursor_x)
        cursor_form.addRow("Y", self._cursor_y)
        layout.addLayout(cursor_form)

        flag_title = QtWidgets.QLabel("Selected flag")
        flag_title.setStyleSheet("font-weight: bold")
        layout.addWidget(flag_title)
        flag_form = QtWidgets.QFormLayout()
        flag_form.addRow("X", self._flag_x)
        flag_form.addRow("Y", self._flag_y)
        layout.addLayout(flag_form)

        hint = QtWidgets.QLabel(
            "Left click to drop/select flags.\n"
            "Right click a flag to remove it."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #bbbbbb; font-size: 11px")
        layout.addWidget(hint)

        layout.addStretch(1)
        self.setLayout(layout)

    def update_cursor_position(self, coords: Optional[tuple[float, float]]) -> None:
        if coords is None:
            self._cursor_x.clear()
            self._cursor_y.clear()
            return
        self._cursor_x.setText(self._format_value(coords[0]))
        self._cursor_y.setText(self._format_value(coords[1]))

    def update_flag_position(self, coords: Optional[tuple[float, float]]) -> None:
        if coords is None:
            self._flag_x.clear()
            self._flag_y.clear()
            return
        self._flag_x.setText(self._format_value(coords[0]))
        self._flag_y.setText(self._format_value(coords[1]))

    def _create_readonly_field(self, placeholder: str) -> QtWidgets.QLineEdit:
        field = QtWidgets.QLineEdit()
        field.setReadOnly(True)
        field.setPlaceholderText(placeholder)
        field.setFocusPolicy(QtCore.Qt.ClickFocus)
        return field

    @staticmethod
    def _format_value(value: float) -> str:
        return f"{value:.2f}"


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
        self._track_list.currentItemChanged.connect(self._on_track_selected)

        self.visualization_widget = TrackPreviewWidget()
        self.visualization_widget.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self._sidebar = CoordinateSidebar()
        self.visualization_widget.cursorPositionChanged.connect(
            self._sidebar.update_cursor_position
        )
        self.visualization_widget.selectedFlagChanged.connect(
            self._sidebar.update_flag_position
        )
        self._center_line_button = QtWidgets.QPushButton("Hide Center Line")
        self._center_line_button.setCheckable(True)
        self._center_line_button.setChecked(True)
        self._center_line_button.toggled.connect(self._toggle_center_line)
        self._toggle_center_line(self._center_line_button.isChecked())

        self._show_cameras_button = QtWidgets.QPushButton("Show Cameras")
        self._show_cameras_button.setCheckable(True)
        self._show_cameras_button.setChecked(True)
        self._show_cameras_button.toggled.connect(
            self.visualization_widget.set_show_cameras
        )

        layout = QtWidgets.QVBoxLayout()
        header = QtWidgets.QHBoxLayout()
        header.addWidget(QtWidgets.QLabel("ICR2 Installation:"))
        header.addWidget(self._path_display, stretch=1)
        header.addWidget(self._browse_button)
        layout.addLayout(header)

        controls = QtWidgets.QHBoxLayout()
        controls.addStretch(1)
        controls.addWidget(self._center_line_button)
        controls.addWidget(self._show_cameras_button)
        layout.addLayout(controls)

        body = QtWidgets.QSplitter()
        body.setOrientation(QtCore.Qt.Horizontal)
        body.addWidget(self._track_list)
        body.addWidget(self.visualization_widget)
        body.addWidget(self._sidebar)
        body.setSizes([200, 420, 200])
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

    def _tracks_root(self) -> Optional[Path]:
        if not self.app_state.installation_path:
            return None
        candidates = [
            self.app_state.installation_path / "TRACKS",
            self.app_state.installation_path / "tracks",
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.is_dir():
                return candidate
        return None

    def _load_tracks(self) -> None:
        track_root = self._tracks_root()
        self._track_list.clear()
        self.visualization_widget.clear()

        if not track_root:
            self.app_state.update_tracks([])
            self._track_list.addItem("(TRACKS folder not found)")
            self._track_list.setEnabled(False)
            return

        folders = [
            path
            for path in sorted(track_root.iterdir(), key=lambda p: p.name.lower())
            if path.is_dir()
        ]
        self.app_state.update_tracks([folder.name for folder in folders])
        if not folders:
            self._track_list.addItem("(No track folders found)")
            self._track_list.setEnabled(False)
            return

        self._track_list.setEnabled(True)
        for folder in folders:
            item = QtWidgets.QListWidgetItem(folder.name)
            item.setData(QtCore.Qt.UserRole, folder)
            self._track_list.addItem(item)
        self._track_list.setCurrentRow(0)

    def _on_track_selected(
        self,
        current: Optional[QtWidgets.QListWidgetItem],
        _previous: Optional[QtWidgets.QListWidgetItem],
    ) -> None:
        if not current:
            self.visualization_widget.clear()
            return

        folder = current.data(QtCore.Qt.UserRole)
        if not isinstance(folder, Path):
            self.visualization_widget.clear("Select a valid track folder.")
            return

        self.visualization_widget.load_track(folder)

    def _toggle_center_line(self, enabled: bool) -> None:
        text = "Hide Center Line" if enabled else "Show Center Line"
        self._center_line_button.setText(text)
        self.visualization_widget.set_show_center_line(enabled)
