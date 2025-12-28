"""Simple Qt application shell for the standalone track viewer."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.cam.helpers import CameraPosition
from track_viewer.camera_actions import CameraActions
from track_viewer.camera_models import CameraViewListing
from track_viewer.camera_table import CameraCoordinateTable
from track_viewer.preview_widget import LpPoint, TrackPreviewWidget
from track_viewer.version import __version__
from track_viewer.window_controller import WindowController
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
    type6ParametersChanged = QtCore.pyqtSignal()

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

    def _handle_type6_parameters_changed(self) -> None:
        self.type6ParametersChanged.emit()

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


class LpRecordsModel(QtCore.QAbstractTableModel):
    """Table model that lazily renders LP records for the view."""

    _HEADERS = ["Index", "DLONG", "DLAT", "Speed (mph)", "Lateral Speed"]
    recordEdited = QtCore.pyqtSignal(int)

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._records: list[LpPoint] = []

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._records)

    def columnCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._HEADERS)

    def data(
        self, index: QtCore.QModelIndex, role: int = QtCore.Qt.DisplayRole
    ) -> object | None:
        if not index.isValid():
            return None
        if role == QtCore.Qt.TextAlignmentRole:
            return QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
        if role not in {QtCore.Qt.DisplayRole, QtCore.Qt.EditRole}:
            return None
        row = index.row()
        if row < 0 or row >= len(self._records):
            return None
        record = self._records[row]
        column = index.column()
        if column == 0:
            return str(row)
        if column == 1:
            return f"{record.dlong:.2f}" if role == QtCore.Qt.DisplayRole else record.dlong
        if column == 2:
            return f"{record.dlat:.2f}" if role == QtCore.Qt.DisplayRole else record.dlat
        if column == 3:
            return (
                f"{record.speed_mph:.2f}"
                if role == QtCore.Qt.DisplayRole
                else record.speed_mph
            )
        if column == 4:
            return (
                f"{record.lateral_speed:.2f}"
                if role == QtCore.Qt.DisplayRole
                else record.lateral_speed
            )
        return None

    def flags(self, index: QtCore.QModelIndex) -> QtCore.Qt.ItemFlags:
        if not index.isValid():
            return QtCore.Qt.NoItemFlags
        base_flags = QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable
        if index.column() in {2, 3, 4}:
            return base_flags | QtCore.Qt.ItemIsEditable
        return base_flags

    def setData(
        self, index: QtCore.QModelIndex, value: object, role: int = QtCore.Qt.EditRole
    ) -> bool:
        if role != QtCore.Qt.EditRole or not index.isValid():
            return False
        row = index.row()
        if row < 0 or row >= len(self._records):
            return False
        column = index.column()
        if column not in {2, 3, 4}:
            return False
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return False
        record = self._records[row]
        if column == 2:
            record.dlat = parsed
        elif column == 3:
            record.speed_mph = parsed
        elif column == 4:
            record.lateral_speed = parsed
        else:
            return False
        self.dataChanged.emit(index, index, [QtCore.Qt.DisplayRole, QtCore.Qt.EditRole])
        self.recordEdited.emit(row)
        return True

    def headerData(
        self,
        section: int,
        orientation: QtCore.Qt.Orientation,
        role: int = QtCore.Qt.DisplayRole,
    ) -> object | None:
        if role != QtCore.Qt.DisplayRole:
            return None
        if orientation == QtCore.Qt.Horizontal:
            if 0 <= section < len(self._HEADERS):
                return self._HEADERS[section]
            return None
        return str(section)

    def set_records(self, records: list[LpPoint]) -> None:
        self.beginResetModel()
        self._records = list(records)
        self.endResetModel()


class TrackViewerWindow(QtWidgets.QMainWindow):
    """Minimal placeholder UI that demonstrates shared state wiring."""

    def __init__(self, app_state: TrackViewerApp):
        super().__init__()
        self.app_state = app_state
        self.app_state.window = self

        self.setWindowTitle("ICR2 Track Viewer")
        self.resize(720, 480)

        self._track_list = QtWidgets.QComboBox()
        self._track_list.currentIndexChanged.connect(self._on_track_selected)

        self._lp_list = QtWidgets.QListWidget()
        self._lp_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self._lp_button_group = QtWidgets.QButtonGroup(self)
        self._lp_button_group.setExclusive(True)
        self._lp_button_group.buttonClicked.connect(self._handle_lp_radio_clicked)
        self._lp_checkboxes: dict[str, QtWidgets.QCheckBox] = {}
        self._lp_records_label = QtWidgets.QLabel("LP records")
        self._lp_records_label.setStyleSheet("font-weight: bold")
        self._lp_records_model = LpRecordsModel(self)
        self._lp_records_table = QtWidgets.QTableView()
        self._lp_records_table.setModel(self._lp_records_model)
        self._lp_records_table.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
        )
        self._lp_records_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows
        )
        self._lp_records_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self._lp_records_table.setAlternatingRowColors(True)
        if hasattr(self._lp_records_table, "setUniformRowHeights"):
            self._lp_records_table.setUniformRowHeights(True)
        header = self._lp_records_table.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        for column in range(1, 5):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.Stretch)
        self._lp_records_table.verticalHeader().setVisible(False)
        selection_model = self._lp_records_table.selectionModel()
        if selection_model is not None:
            selection_model.selectionChanged.connect(
                lambda *_: self._handle_lp_record_selected()
            )
        self._lp_records_model.recordEdited.connect(self._handle_lp_record_edited)

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
        lp_label = QtWidgets.QLabel("AI and center lines")
        lp_label.setStyleSheet("font-weight: bold")
        left_layout.addWidget(lp_label)
        left_layout.addWidget(self._lp_list)
        left_layout.addWidget(self._lp_records_label)
        self._lp_records_table.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )
        left_layout.addWidget(self._lp_records_table, 1)
        left_layout.addWidget(self._sidebar.type7_details)
        left_layout.addWidget(self._sidebar.type6_editor)
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
        self.visualization_widget.activeLpLineChanged.connect(
            self._update_lp_records_table
        )
        self.visualization_widget.aiLineLoaded.connect(self._handle_ai_line_loaded)
        self.visualization_widget.lpRecordSelected.connect(
            self._handle_lp_record_clicked
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
        self._sidebar.type6ParametersChanged.connect(
            self._handle_type6_parameters_changed
        )
        self._sidebar.set_cameras([], [])
        self._sidebar.update_selected_camera_details(None, None)
        self._add_type6_camera_button = QtWidgets.QPushButton("Add Type 6 Camera")
        self._add_type7_camera_button = QtWidgets.QPushButton("Add Type 7 Camera")
        self._boundary_button = QtWidgets.QPushButton("Hide Boundaries")
        self._boundary_button.setCheckable(True)
        self._boundary_button.setChecked(True)
        self._boundary_button.toggled.connect(self._toggle_boundaries)
        self._toggle_boundaries(self._boundary_button.isChecked())

        self._zoom_points_button = QtWidgets.QPushButton("Show Zoom Points")
        self._zoom_points_button.setCheckable(True)
        self._zoom_points_button.toggled.connect(self._toggle_zoom_points)

        self._ai_gradient_button = QtWidgets.QPushButton("Show AI Speed Gradient")
        self._ai_gradient_button.setCheckable(True)
        self._ai_gradient_button.toggled.connect(self._toggle_ai_gradient)

        self._ai_acceleration_button = QtWidgets.QPushButton(
            "Show AI Acceleration Gradient"
        )
        self._ai_acceleration_button.setCheckable(True)
        self._ai_acceleration_button.toggled.connect(
            self._toggle_ai_acceleration_gradient
        )

        self._accel_window_label = QtWidgets.QLabel()
        self._accel_window_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._accel_window_slider.setRange(1, 12)
        self._accel_window_slider.setSingleStep(1)
        self._accel_window_slider.setPageStep(1)
        self._accel_window_slider.setValue(
            self.visualization_widget.ai_acceleration_window()
        )
        self._accel_window_slider.setFixedWidth(120)
        self._accel_window_slider.valueChanged.connect(
            self._handle_accel_window_changed
        )
        self._update_accel_window_label(self._accel_window_slider.value())

        self._ai_width_label = QtWidgets.QLabel()
        self._ai_width_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._ai_width_slider.setRange(1, 8)
        self._ai_width_slider.setSingleStep(1)
        self._ai_width_slider.setPageStep(1)
        self._ai_width_slider.setValue(self.visualization_widget.ai_line_width())
        self._ai_width_slider.setFixedWidth(120)
        self._ai_width_slider.valueChanged.connect(self._handle_ai_line_width_changed)
        self._update_ai_line_width_label(self._ai_width_slider.value())

        self._ai_color_mode = "none"
        self._update_ai_color_mode("none")

        self._save_cameras_button = QtWidgets.QPushButton("Save Cameras")
        self._save_lp_button = QtWidgets.QPushButton("Save LP")
        self._save_lp_button.setEnabled(False)

        self._trk_gaps_button = QtWidgets.QPushButton("Run TRK Gaps")
        self._trk_gaps_button.setEnabled(False)

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

        self.controller = WindowController(
            self.app_state, self.visualization_widget, parent=self
        )
        self.controller.installationPathChanged.connect(self._handle_installation_path)
        self.controller.trackListUpdated.connect(self._apply_track_list_items)
        self.controller.trackLengthChanged.connect(self._sidebar.set_track_length)
        self.controller.trkGapsAvailabilityChanged.connect(self._trk_gaps_button.setEnabled)
        self.controller.aiLinesUpdated.connect(self._apply_ai_line_state)

        self.camera_actions = CameraActions(self.visualization_widget)
        self.camera_actions.infoMessage.connect(
            lambda title, message: QtWidgets.QMessageBox.information(
                self, title, message
            )
        )
        self.camera_actions.warningMessage.connect(
            lambda title, message: QtWidgets.QMessageBox.warning(
                self, title, message
            )
        )
        self._add_type6_camera_button.clicked.connect(
            self.camera_actions.add_type6_camera
        )
        self._add_type7_camera_button.clicked.connect(
            self.camera_actions.add_type7_camera
        )
        self._save_cameras_button.clicked.connect(self.camera_actions.save_cameras)
        self._save_lp_button.clicked.connect(self._handle_save_lp_line)
        self._trk_gaps_button.clicked.connect(lambda: self.controller.run_trk_gaps(self))
        self.controller.sync_ai_lines()

        self._create_menus()
        self.statusBar().showMessage("Select an ICR2 folder to get started")

        layout = QtWidgets.QVBoxLayout()

        controls = QtWidgets.QHBoxLayout()
        controls.addStretch(1)
        controls.addWidget(self._add_type6_camera_button)
        controls.addWidget(self._add_type7_camera_button)
        controls.addWidget(self._save_cameras_button)
        controls.addWidget(self._save_lp_button)
        controls.addWidget(self._trk_gaps_button)
        controls.addWidget(self._boundary_button)
        controls.addWidget(self._zoom_points_button)
        controls.addWidget(self._ai_gradient_button)
        controls.addWidget(self._ai_acceleration_button)
        controls.addWidget(self._accel_window_label)
        controls.addWidget(self._accel_window_slider)
        controls.addWidget(self._ai_width_label)
        controls.addWidget(self._ai_width_slider)
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
    def _create_menus(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        open_action = QtWidgets.QAction("Open ICR2 folder", self)
        open_action.triggered.connect(
            lambda: self.controller.select_installation_path(self)
        )
        file_menu.addAction(open_action)

        quit_action = QtWidgets.QAction("Quit", self)
        quit_action.triggered.connect(QtWidgets.qApp.quit)
        file_menu.addAction(quit_action)

        help_menu = self.menuBar().addMenu("Help")
        about_action = QtWidgets.QAction("About", self)
        about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(about_action)

    def _handle_installation_path(self, path: Path) -> None:
        self.statusBar().showMessage(str(path))

    def _show_about_dialog(self) -> None:
        QtWidgets.QMessageBox.about(
            self,
            "About ICR2 Track Viewer",
            f"ICR2 Track Viewer v{__version__}\nby SK Chow",
        )

    def _apply_track_list_items(
        self, entries: list[tuple[str, Path | None]], enabled: bool, default_index: int
    ) -> None:
        with QtCore.QSignalBlocker(self._track_list):
            self._track_list.clear()
            for label, folder in entries:
                self._track_list.addItem(label, folder)
        self._track_list.setEnabled(enabled)
        if enabled and 0 <= default_index < self._track_list.count():
            self._track_list.setCurrentIndex(default_index)
        else:
            self._track_list.setCurrentIndex(-1)

    def _on_track_selected(self, index: int) -> None:
        folder = self._track_list.itemData(index) if index >= 0 else None
        self.controller.set_selected_track(folder)

    def _apply_ai_line_state(
        self, available_files: list[str], visible_files: set[str], enabled: bool
    ) -> None:
        with QtCore.QSignalBlocker(self._lp_list):
            for button in self._lp_button_group.buttons():
                self._lp_button_group.removeButton(button)
                button.deleteLater()
            self._lp_checkboxes = {}
            self._lp_list.clear()

            active_line = self.visualization_widget.active_lp_line()
            if active_line not in {"center-line", *available_files}:
                active_line = "center-line"

            self._add_lp_list_item(
                label="Center line",
                name="center-line",
                color=None,
                visible=self.visualization_widget.center_line_visible(),
                selected=active_line == "center-line",
                enabled=enabled,
            )

            for name in available_files:
                self._add_lp_list_item(
                    label=name,
                    name=name,
                    color=self.visualization_widget.lp_color(name),
                    visible=name in visible_files,
                    selected=active_line == name,
                    enabled=enabled,
                )

            self.visualization_widget.set_active_lp_line(active_line)
        self._lp_list.setEnabled(enabled)
        self._update_lp_records_table(active_line)
        self._update_save_lp_button_state(active_line)

    def _add_lp_list_item(
        self,
        *,
        label: str,
        name: str,
        color: str | None,
        visible: bool,
        selected: bool,
        enabled: bool,
    ) -> None:
        item = QtWidgets.QListWidgetItem()
        item.setData(QtCore.Qt.UserRole, name)
        item.setFlags(QtCore.Qt.ItemIsEnabled)

        radio = QtWidgets.QRadioButton()
        radio.setProperty("lp-name", name)
        with QtCore.QSignalBlocker(radio):
            radio.setChecked(selected)
        radio.setEnabled(enabled)
        self._lp_button_group.addButton(radio)

        checkbox = QtWidgets.QCheckBox(label)
        if color:
            palette = checkbox.palette()
            palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor(color))
            checkbox.setPalette(palette)
        with QtCore.QSignalBlocker(checkbox):
            checkbox.setChecked(visible)
        checkbox.setEnabled(enabled)
        checkbox.toggled.connect(
            lambda state, line=name: self._handle_lp_visibility_changed(line, state)
        )

        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(6, 0, 6, 0)
        layout.setSpacing(8)
        layout.addWidget(radio)
        layout.addWidget(checkbox)
        layout.addStretch(1)

        container = QtWidgets.QWidget()
        container.setLayout(layout)
        item.setSizeHint(container.sizeHint())

        self._lp_list.addItem(item)
        self._lp_list.setItemWidget(item, container)
        self._lp_checkboxes[name] = checkbox

    def _toggle_boundaries(self, enabled: bool) -> None:
        text = "Hide Boundaries" if enabled else "Show Boundaries"
        self._boundary_button.setText(text)
        self.visualization_widget.set_show_boundaries(enabled)

    def _toggle_zoom_points(self, enabled: bool) -> None:
        text = "Hide Zoom Points" if enabled else "Show Zoom Points"
        self._zoom_points_button.setText(text)
        self.visualization_widget.set_show_zoom_points(enabled)

    def _toggle_ai_gradient(self, enabled: bool) -> None:
        mode = (
            "speed"
            if enabled
            else "acceleration" if self._ai_acceleration_button.isChecked() else "none"
        )
        self._update_ai_color_mode(mode)

    def _toggle_ai_acceleration_gradient(self, enabled: bool) -> None:
        mode = (
            "acceleration"
            if enabled
            else "speed" if self._ai_gradient_button.isChecked() else "none"
        )
        self._update_ai_color_mode(mode)

    def _update_ai_color_mode(self, mode: str) -> None:
        if mode not in {"none", "speed", "acceleration"}:
            mode = "none"

        self._ai_color_mode = mode

        with QtCore.QSignalBlocker(self._ai_gradient_button):
            self._ai_gradient_button.setChecked(mode == "speed")
        with QtCore.QSignalBlocker(self._ai_acceleration_button):
            self._ai_acceleration_button.setChecked(mode == "acceleration")

        speed_text = (
            "Use Solid AI Colors" if mode == "speed" else "Show AI Speed Gradient"
        )
        accel_text = (
            "Use Solid AI Colors"
            if mode == "acceleration"
            else "Show AI Acceleration Gradient"
        )
        self._ai_gradient_button.setText(speed_text)
        self._ai_acceleration_button.setText(accel_text)
        self.visualization_widget.set_ai_color_mode(mode)

    def _update_accel_window_label(self, segments: int) -> None:
        plural = "s" if segments != 1 else ""
        self._accel_window_label.setText(f"Accel avg: {segments} segment{plural}")

    def _handle_accel_window_changed(self, segments: int) -> None:
        self._update_accel_window_label(segments)
        self.visualization_widget.set_ai_acceleration_window(segments)

    def _update_ai_line_width_label(self, width: int) -> None:
        self._ai_width_label.setText(f"AI line width: {width}px")

    def _handle_ai_line_width_changed(self, width: int) -> None:
        self._update_ai_line_width_label(width)
        self.visualization_widget.set_ai_line_width(width)

    def _handle_lp_visibility_changed(self, name: str, visible: bool) -> None:
        if name == "center-line":
            self.visualization_widget.set_show_center_line(visible)
            return

        selected = set(self.visualization_widget.visible_lp_files())
        if visible:
            selected.add(name)
        else:
            selected.discard(name)
        self.controller.set_visible_lp_files(sorted(selected))

    def _handle_lp_radio_clicked(self, button: QtWidgets.QAbstractButton) -> None:
        name = button.property("lp-name")
        if isinstance(name, str):
            self.visualization_widget.set_active_lp_line(name)

    def _update_lp_records_table(self, name: str | None = None) -> None:
        lp_name = name or self.visualization_widget.active_lp_line()
        records = self.visualization_widget.ai_line_records(lp_name)
        label = "LP records"
        if lp_name and lp_name != "center-line":
            label = f"LP records: {lp_name}"
        self._lp_records_label.setText(label)
        self._lp_records_model.set_records(records)
        self._update_save_lp_button_state(lp_name)
        selection_model = self._lp_records_table.selectionModel()
        if selection_model is not None:
            selection_model.clearSelection()
        self.visualization_widget.set_selected_lp_record(None, None)

    def _handle_ai_line_loaded(self, name: str) -> None:
        if name == self.visualization_widget.active_lp_line():
            self._update_lp_records_table(name)
        self._update_save_lp_button_state(self.visualization_widget.active_lp_line())

    def _handle_lp_record_selected(self) -> None:
        selection = self._lp_records_table.selectionModel()
        if selection is None:
            return
        rows = selection.selectedRows()
        if not rows:
            self.visualization_widget.set_selected_lp_record(None, None)
            return
        row = rows[0].row()
        lp_name = self.visualization_widget.active_lp_line()
        if not lp_name or lp_name == "center-line":
            self.visualization_widget.set_selected_lp_record(None, None)
            return
        self.visualization_widget.set_selected_lp_record(lp_name, row)

    def _handle_lp_record_clicked(self, lp_name: str, row: int) -> None:
        if lp_name != self.visualization_widget.active_lp_line():
            return
        if row < 0 or row >= self._lp_records_model.rowCount():
            return
        with QtCore.QSignalBlocker(self._lp_records_table):
            self._lp_records_table.selectRow(row)
            index = self._lp_records_model.index(row, 0)
            if index.isValid():
                self._lp_records_table.scrollTo(
                    index, QtWidgets.QAbstractItemView.PositionAtCenter
                )

    def _handle_lp_record_edited(self, row: int) -> None:
        lp_name = self.visualization_widget.active_lp_line()
        if not lp_name or lp_name == "center-line":
            return
        self.visualization_widget.update_lp_record(lp_name, row)

    def _handle_save_lp_line(self) -> None:
        success, message = self.visualization_widget.save_active_lp_line()
        title = "Save LP"
        if success:
            QtWidgets.QMessageBox.information(self, title, message)
        else:
            QtWidgets.QMessageBox.warning(self, title, message)

    def _update_save_lp_button_state(self, lp_name: str | None = None) -> None:
        name = lp_name or self.visualization_widget.active_lp_line()
        enabled = (
            bool(name)
            and name != "center-line"
            and self.visualization_widget.trk is not None
            and bool(self.visualization_widget.ai_line_records(name))
        )
        self._save_lp_button.setEnabled(enabled)

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
