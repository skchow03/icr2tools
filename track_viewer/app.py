"""Simple Qt application shell for the standalone track viewer."""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PyQt5 import QtWidgets, QtCore

from icr2_core.cam.helpers import CameraPosition
from track_viewer.camera_models import CameraViewListing
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
    """Utility sidebar that mirrors cursor, flag and camera details."""

    cameraSelectionChanged = QtCore.pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setMinimumWidth(220)

        self._cursor_x = self._create_readonly_field("–")
        self._cursor_y = self._create_readonly_field("–")
        self._flag_x = self._create_readonly_field("–")
        self._flag_y = self._create_readonly_field("–")
        self._camera_list = QtWidgets.QListWidget()
        self._camera_list.setMinimumHeight(120)
        self._camera_list.currentRowChanged.connect(self._on_camera_selected)
        self._tv_tabs_label = QtWidgets.QLabel("TV camera modes")
        self._tv_tabs_label.setStyleSheet("font-weight: bold")
        self._tv_tabs = QtWidgets.QTabWidget()
        self._tv_tabs.setTabBarAutoHide(True)
        self._tv_tabs.setVisible(False)
        self._tv_tabs_label.setVisible(False)
        self._tv_trees: List[QtWidgets.QTreeWidget] = []
        self._tv_camera_items: Dict[
            int, Tuple[QtWidgets.QTreeWidget, QtWidgets.QTreeWidgetItem]
        ] = {}
        self._camera_details = QtWidgets.QLabel("Select a camera to inspect.")
        self._camera_details.setWordWrap(True)
        self._camera_details.setAlignment(QtCore.Qt.AlignTop)
        self._camera_details.setStyleSheet("font-size: 12px")
        self._cameras: List[CameraPosition] = []

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

        camera_title = QtWidgets.QLabel("Track cameras")
        camera_title.setStyleSheet("font-weight: bold")
        layout.addWidget(camera_title)
        layout.addWidget(self._camera_list)

        layout.addWidget(self._tv_tabs_label)
        layout.addWidget(self._tv_tabs)

        details_title = QtWidgets.QLabel("Camera details")
        details_title.setStyleSheet("font-weight: bold")
        layout.addWidget(details_title)
        layout.addWidget(self._camera_details)

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

    def set_cameras(
        self, cameras: List[CameraPosition], views: List[CameraViewListing]
    ) -> None:
        self._cameras = cameras
        self._camera_list.blockSignals(True)
        self._camera_list.clear()
        if not cameras:
            self._camera_list.addItem("(No cameras found)")
            self._camera_list.setEnabled(False)
            self._camera_details.setText(
                "This track does not define any camera positions."
            )
            self._camera_list.setCurrentRow(-1)
        else:
            for cam in cameras:
                label = f"#{cam.index} (type {cam.camera_type})"
                item = QtWidgets.QListWidgetItem(label)
                self._camera_list.addItem(item)
            self._camera_list.setEnabled(True)
            self._camera_list.setCurrentRow(-1)
            self._camera_details.setText("Select a camera to inspect.")
        self._camera_list.blockSignals(False)
        self._update_tv_camera_tabs(views)

    def select_camera(self, index: int | None) -> None:
        self._camera_list.blockSignals(True)
        if index is None:
            self._camera_list.setCurrentRow(-1)
        else:
            self._camera_list.setCurrentRow(index)
        self._camera_list.blockSignals(False)
        self._select_tv_camera_item(index)

    def update_selected_camera_details(
        self, index: int | None, camera: Optional[CameraPosition]
    ) -> None:
        if camera is None:
            self._camera_details.setText("Select a camera to inspect.")
            if index is None:
                self.select_camera(None)
            return
        details = [
            f"Index: {camera.index}",
            f"Type: {camera.camera_type}",
            f"X: {camera.x}",
            f"Y: {camera.y}",
            f"Z: {camera.z}",
        ]
        if camera.camera_type == 6 and camera.type6 is not None:
            details.extend(
                [
                    f"Middle point: {camera.type6.middle_point}",
                    f"Start point: {camera.type6.start_point}",
                    f"Start zoom: {camera.type6.start_zoom}",
                    f"Middle point zoom: {camera.type6.middle_point_zoom}",
                    f"End point: {camera.type6.end_point}",
                    f"End zoom: {camera.type6.end_zoom}",
                ]
            )
        self._camera_details.setText("\n".join(details))
        if index is not None and self._camera_list.currentRow() != index:
            self.select_camera(index)

    def _update_tv_camera_tabs(self, views: List[CameraViewListing]) -> None:
        while self._tv_tabs.count():
            widget = self._tv_tabs.widget(0)
            self._tv_tabs.removeTab(0)
            if widget is not None:
                widget.deleteLater()
        self._tv_camera_items.clear()
        self._tv_trees = []
        if not views:
            self._tv_tabs_label.setVisible(False)
            self._tv_tabs.setVisible(False)
            return
        self._tv_tabs_label.setVisible(True)
        self._tv_tabs.setVisible(True)
        for view in views:
            tree = self._create_tv_tree()
            for entry in view.entries:
                label_index = entry.display_index
                if label_index is None:
                    label_index = entry.camera_index
                values = [
                    f"#{label_index}" if label_index is not None else "–",
                    f"{entry.camera_type}" if entry.camera_type is not None else "–",
                    self._format_dlong(entry.start_dlong),
                    self._format_dlong(entry.end_dlong),
                ]
                item = QtWidgets.QTreeWidgetItem(values)
                if entry.camera_index is not None:
                    item.setData(0, QtCore.Qt.UserRole, entry.camera_index)
                    self._tv_camera_items.setdefault(
                        entry.camera_index, (tree, item)
                    )
                else:
                    item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEnabled)
                tree.addTopLevelItem(item)
            container = QtWidgets.QWidget()
            container_layout = QtWidgets.QVBoxLayout()
            container_layout.setContentsMargins(0, 0, 0, 0)
            container_layout.addWidget(tree)
            container.setLayout(container_layout)
            self._tv_tabs.addTab(container, view.label)
            self._tv_trees.append(tree)
        self._tv_tabs.setCurrentIndex(0)

    def _create_tv_tree(self) -> QtWidgets.QTreeWidget:
        tree = QtWidgets.QTreeWidget()
        tree.setColumnCount(4)
        tree.setHeaderLabels(["ID", "Type", "Start", "End"])
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        tree.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        tree.setUniformRowHeights(True)
        tree.setMinimumHeight(120)
        tree.currentItemChanged.connect(self._handle_tv_camera_selected)
        return tree

    def _handle_tv_camera_selected(
        self,
        current: Optional[QtWidgets.QTreeWidgetItem],
        _previous: Optional[QtWidgets.QTreeWidgetItem],
    ) -> None:
        tree = self.sender()
        if not isinstance(tree, QtWidgets.QTreeWidget):
            return
        if current is None:
            self.cameraSelectionChanged.emit(None)
            return
        data = current.data(0, QtCore.Qt.UserRole)
        if data is None:
            self.cameraSelectionChanged.emit(None)
            return
        try:
            camera_index = int(data)
        except (TypeError, ValueError):
            self.cameraSelectionChanged.emit(None)
            return
        self.cameraSelectionChanged.emit(camera_index)

    def _select_tv_camera_item(self, index: int | None) -> None:
        for tree in self._tv_trees:
            blocker = QtCore.QSignalBlocker(tree)
            tree.setCurrentItem(None)
        if index is None:
            return
        tree_item = self._tv_camera_items.get(index)
        if not tree_item:
            return
        tree, item = tree_item
        with QtCore.QSignalBlocker(tree):
            tree.setCurrentItem(item)
        try:
            tab_index = self._tv_trees.index(tree)
        except ValueError:
            return
        self._tv_tabs.setCurrentIndex(tab_index)

    @staticmethod
    def _format_dlong(value: Optional[int]) -> str:
        if value is None:
            return "–"
        return f"{value}"

    def _on_camera_selected(self, index: int) -> None:
        if not self._cameras or index < 0 or index >= len(self._cameras):
            self.cameraSelectionChanged.emit(None)
            return
        self.cameraSelectionChanged.emit(index)

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
        self.visualization_widget.camerasChanged.connect(self._sidebar.set_cameras)
        self.visualization_widget.selectedCameraChanged.connect(
            self._sidebar.update_selected_camera_details
        )
        self._sidebar.cameraSelectionChanged.connect(
            self._handle_camera_selection_changed
        )
        self._sidebar.set_cameras([], [])
        self._sidebar.update_selected_camera_details(None, None)
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

    def _handle_camera_selection_changed(self, index: Optional[int]) -> None:
        self.visualization_widget.set_selected_camera(index)
