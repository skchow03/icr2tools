"""Simple Qt application shell for the standalone track viewer."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt5 import QtCore, QtWidgets

from icr2_core.cam.helpers import CameraPosition
from track_viewer.camera_models import CameraViewListing
from track_viewer.camera_table import CameraCoordinateTable
from track_viewer.preview_widget import TrackPreviewWidget
from track_viewer.tv_modes_panel import TvModesPanel
from track_viewer.type6_editor import Type6Editor
from track_viewer.type7_details import Type7Details


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
    cameraDlongsUpdated = QtCore.pyqtSignal(int, object, object)
    cameraPositionUpdated = QtCore.pyqtSignal(int, object, object, object)

    def __init__(self) -> None:
        super().__init__()
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setMinimumWidth(220)
        self._track_length: int | None = None

        self._cursor_x = self._create_readonly_field("–")
        self._cursor_y = self._create_readonly_field("–")
        self._flag_x = self._create_readonly_field("–")
        self._flag_y = self._create_readonly_field("–")
        self._camera_list = QtWidgets.QListWidget()
        self._camera_list.setMinimumHeight(120)
        self._camera_list.currentRowChanged.connect(self._on_camera_selected)
        self._tv_panel = TvModesPanel()
        self._camera_table = CameraCoordinateTable()
        self._camera_details = QtWidgets.QLabel("Select a camera to inspect.")
        self._camera_details.setTextFormat(QtCore.Qt.RichText)
        self._camera_details.setWordWrap(True)
        self._camera_details.setAlignment(QtCore.Qt.AlignTop)
        self._camera_details.setStyleSheet("font-size: 12px")
        self._type6_editor = Type6Editor()
        self._type7_details = Type7Details()
        self._cameras: List[CameraPosition] = []
        self._selected_camera_index: int | None = None

        self._tv_panel.cameraSelected.connect(self.cameraSelectionChanged)
        self._tv_panel.dlongsUpdated.connect(self.cameraDlongsUpdated)
        self._camera_table.positionUpdated.connect(self._handle_camera_position_updated)
        self._type6_editor.set_tv_dlongs_provider(self._tv_panel.camera_dlongs)
        self._type6_editor.parametersChanged.connect(self._handle_type6_parameters_changed)

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

        layout.addWidget(self._tv_panel)

        details_title = QtWidgets.QLabel("Camera details")
        details_title.setStyleSheet("font-weight: bold")
        layout.addWidget(details_title)
        layout.addWidget(self._camera_details)

        coords_title = QtWidgets.QLabel("World coordinates")
        coords_title.setStyleSheet("font-weight: bold")
        layout.addWidget(coords_title)
        layout.addWidget(self._camera_table)

        layout.addStretch(1)
        self.setLayout(layout)

    @property
    def type6_editor(self) -> Type6Editor:
        return self._type6_editor

    @property
    def type7_details(self) -> Type7Details:
        return self._type7_details

    def set_track_length(self, track_length: Optional[int]) -> None:
        self._track_length = track_length if track_length is not None else None
        self._tv_panel.set_track_length(self._track_length)
        self._type6_editor.set_track_length(self._track_length)

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
        self._camera_views = views
        self._selected_camera_index = None
        self._camera_table.set_camera(None, None)
        self._type6_editor.set_camera(None, None)
        self._type7_details.set_camera(None, None)
        self._tv_panel.set_views(views, cameras)
        self._camera_list.blockSignals(True)
        self._camera_list.clear()
        if not cameras:
            self._camera_list.addItem("(No cameras found)")
            self._camera_list.setEnabled(False)
            self._camera_details.setText("This track does not define any camera positions.")
            self._camera_list.setCurrentRow(-1)
        else:
            for cam in cameras:
                label = f"#{cam.index} (type {cam.camera_type})"
                item = QtWidgets.QListWidgetItem(label)
                self._camera_list.addItem(item)
            self._camera_list.setEnabled(True)
            self._camera_details.setText("Select a camera to inspect.")
            self._camera_list.setCurrentRow(-1)
        self._camera_list.blockSignals(False)

    def select_camera(self, index: int | None) -> None:
        self._camera_list.blockSignals(True)
        if index is None:
            self._camera_list.setCurrentRow(-1)
        else:
            self._camera_list.setCurrentRow(index)
        self._camera_list.blockSignals(False)
        self._tv_panel.select_camera(index)
        if index is None:
            self._camera_table.setCurrentCell(-1, -1)
        elif self._camera_table.isEnabled():
            self._camera_table.setCurrentCell(0, 0)

    def update_selected_camera_details(
        self, index: int | None, camera: Optional[CameraPosition]
    ) -> None:
        if camera is None:
            self._camera_details.setText("Select a camera to inspect.")
            self._selected_camera_index = None
            self._camera_table.set_camera(None, None)
            self._type6_editor.set_camera(None, None)
            self._type7_details.set_camera(None, None)
            if index is None:
                self.select_camera(None)
            return
        self._selected_camera_index = index
        self._camera_table.set_camera(index, camera)

        details = [f"Index: {camera.index}", f"Type: {camera.camera_type}"]

        if camera.camera_type == 6 and camera.type6 is not None:
            details.append("Type 6 parameters can be edited below.")
            self._type6_editor.set_camera(index, camera)
        else:
            self._type6_editor.set_camera(None, None)

        if camera.camera_type == 7 and camera.type7 is not None:
            params = camera.type7
            details.append("Type 7 parameters:")
            details.append(
                "Z-axis rotation: {0}, vertical rotation: {1}, tilt: {2}, zoom: {3}".format(
                    params.z_axis_rotation,
                    params.vertical_rotation,
                    params.tilt,
                    params.zoom,
                )
            )
            details.append(
                "Unknowns: {0}, {1}, {2}, {3}".format(
                    params.unknown1,
                    params.unknown2,
                    params.unknown3,
                    params.unknown4,
                )
            )
            self._type7_details.set_camera(index, camera)
        else:
            self._type7_details.set_camera(None, None)

        self._camera_details.setText("<br>".join(details))
        if index is not None and self._camera_list.currentRow() != index:
            self.select_camera(index)

    def _handle_camera_position_updated(
        self, index: int, x: Optional[int], y: Optional[int], z: Optional[int]
    ) -> None:
        if (
            self._selected_camera_index is not None
            and index == self._selected_camera_index
            and 0 <= index < len(self._cameras)
        ):
            self.update_selected_camera_details(index, self._cameras[index])
        self.cameraPositionUpdated.emit(index, x, y, z)

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
        left_sidebar = QtWidgets.QFrame()
        left_sidebar.setFrameShape(QtWidgets.QFrame.StyledPanel)
        left_layout = QtWidgets.QVBoxLayout()
        left_layout.setSpacing(8)
        track_label = QtWidgets.QLabel("Tracks")
        track_label.setStyleSheet("font-weight: bold")
        left_layout.addWidget(track_label)
        left_layout.addWidget(self._track_list)
        left_layout.addWidget(self._sidebar.type7_details)
        left_layout.addWidget(self._sidebar.type6_editor)
        left_layout.addStretch(1)
        left_sidebar.setLayout(left_layout)
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
        self.visualization_widget.camerasChanged.connect(
            self._sync_tv_mode_selector
        )
        self._sidebar.type7_details.parametersChanged.connect(
            self.visualization_widget.update
        )
        self._sidebar.cameraSelectionChanged.connect(
            self._handle_camera_selection_changed
        )
        self._sidebar.cameraDlongsUpdated.connect(
            self._handle_camera_dlongs_updated
        )
        self._sidebar.cameraPositionUpdated.connect(
            self._handle_camera_position_updated
        )
        self._sidebar.set_cameras([], [])
        self._sidebar.update_selected_camera_details(None, None)
        self._add_type6_camera_button = QtWidgets.QPushButton("Add Type 6 Camera")
        self._add_type6_camera_button.clicked.connect(self._add_type6_camera)
        self._add_type7_camera_button = QtWidgets.QPushButton("Add Type 7 Camera")
        self._add_type7_camera_button.clicked.connect(self._add_type7_camera)
        self._center_line_button = QtWidgets.QPushButton("Hide Center Line")
        self._center_line_button.setCheckable(True)
        self._center_line_button.setChecked(True)
        self._center_line_button.toggled.connect(self._toggle_center_line)
        self._toggle_center_line(self._center_line_button.isChecked())

        self._zoom_points_button = QtWidgets.QPushButton("Show Zoom Points")
        self._zoom_points_button.setCheckable(True)
        self._zoom_points_button.toggled.connect(self._toggle_zoom_points)

        self._save_cameras_button = QtWidgets.QPushButton("Save Cameras")
        self._save_cameras_button.clicked.connect(self._save_cameras)

        self._show_cameras_button = QtWidgets.QPushButton("Show Cameras")
        self._show_cameras_button.setCheckable(True)
        self._show_cameras_button.setChecked(True)
        self._show_cameras_button.toggled.connect(
            self.visualization_widget.set_show_cameras
        )

        self._tv_mode_selector = QtWidgets.QComboBox()
        self._tv_mode_selector.addItems(["One TV mode", "Two TV modes"])
        self._tv_mode_selector.currentIndexChanged.connect(
            self._handle_tv_mode_selection_changed
        )

        layout = QtWidgets.QVBoxLayout()
        header = QtWidgets.QHBoxLayout()
        header.addWidget(QtWidgets.QLabel("ICR2 Installation:"))
        header.addWidget(self._path_display, stretch=1)
        header.addWidget(self._browse_button)
        layout.addLayout(header)

        controls = QtWidgets.QHBoxLayout()
        controls.addStretch(1)
        controls.addWidget(self._add_type6_camera_button)
        controls.addWidget(self._add_type7_camera_button)
        controls.addWidget(self._save_cameras_button)
        controls.addWidget(self._center_line_button)
        controls.addWidget(self._zoom_points_button)
        controls.addWidget(self._show_cameras_button)
        controls.addWidget(self._tv_mode_selector)
        layout.addLayout(controls)

        body = QtWidgets.QSplitter()
        body.setOrientation(QtCore.Qt.Horizontal)
        body.addWidget(left_sidebar)
        body.addWidget(self.visualization_widget)
        body.addWidget(self._sidebar)
        body.setSizes([220, 420, 200])
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
        self._sidebar.set_track_length(None)

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
            self._sidebar.set_track_length(None)
            return

        folder = current.data(QtCore.Qt.UserRole)
        if not isinstance(folder, Path):
            self.visualization_widget.clear("Select a valid track folder.")
            self._sidebar.set_track_length(None)
            return

        self.visualization_widget.load_track(folder)
        self._sidebar.set_track_length(self.visualization_widget.track_length())

    def _toggle_center_line(self, enabled: bool) -> None:
        text = "Hide Center Line" if enabled else "Show Center Line"
        self._center_line_button.setText(text)
        self.visualization_widget.set_show_center_line(enabled)

    def _toggle_zoom_points(self, enabled: bool) -> None:
        text = "Hide Zoom Points" if enabled else "Show Zoom Points"
        self._zoom_points_button.setText(text)
        self.visualization_widget.set_show_zoom_points(enabled)

    def _handle_tv_mode_selection_changed(self, index: int) -> None:
        mode_count = 1 if index <= 0 else 2
        self.visualization_widget.set_tv_mode_count(mode_count)

    def _sync_tv_mode_selector(
        self, _cameras: list[CameraPosition], views: list[CameraViewListing]
    ) -> None:
        if not views:
            target_index = 0
        else:
            max_view = max((view.view for view in views), default=1)
            target_index = 0 if max_view <= 1 else 1
        with QtCore.QSignalBlocker(self._tv_mode_selector):
            self._tv_mode_selector.setCurrentIndex(target_index)

    def _add_type6_camera(self) -> None:
        success, message = self.visualization_widget.add_type6_camera()
        title = "Add Type 6 Camera"
        if success:
            QtWidgets.QMessageBox.information(self, title, message)
        else:
            QtWidgets.QMessageBox.warning(self, title, message)

    def _add_type7_camera(self) -> None:
        success, message = self.visualization_widget.add_type7_camera()
        title = "Add Type 7 Camera"
        if success:
            QtWidgets.QMessageBox.information(self, title, message)
        else:
            QtWidgets.QMessageBox.warning(self, title, message)

    def _save_cameras(self) -> None:
        success, message = self.visualization_widget.save_cameras()
        if success:
            QtWidgets.QMessageBox.information(self, "Save Cameras", message)
        else:
            QtWidgets.QMessageBox.warning(self, "Save Cameras", message)

    def _handle_camera_selection_changed(self, index: Optional[int]) -> None:
        self.visualization_widget.set_selected_camera(index)

    def _handle_camera_dlongs_updated(
        self, camera_index: int, start: Optional[int], end: Optional[int]
    ) -> None:
        self.visualization_widget.update_camera_dlongs(camera_index, start, end)

    def _handle_camera_position_updated(
        self, index: int, x: Optional[int], y: Optional[int], z: Optional[int]
    ) -> None:
        self.visualization_widget.update_camera_position(index, x, y, z)

    def _handle_type6_parameters_changed(self) -> None:
        self.visualization_widget.update()
