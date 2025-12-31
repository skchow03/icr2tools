"""Simple Qt application shell for the standalone track viewer."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.cam.helpers import CameraPosition
from icr2_core.lp.loader import papy_speed_to_mph
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

    _INSTALLATION_PATH_KEY = "installation_path"

    def __init__(self, argv: List[str]):
        super().__init__(argv)
        self.setQuitOnLastWindowClosed(True)

        QtCore.QCoreApplication.setOrganizationName("icr2tools")
        QtCore.QCoreApplication.setApplicationName("ICR2 Track Viewer")
        self.settings = QtCore.QSettings()

        self.installation_path = self._load_installation_path()
        self.tracks: List[str] = []
        self.window: Optional["TrackViewerWindow"] = None

    def _load_installation_path(self) -> Optional[Path]:
        stored_path = self.settings.value(self._INSTALLATION_PATH_KEY, type=str)
        if not stored_path:
            return None
        path = Path(stored_path)
        return path if path.exists() else None

    def set_installation_path(self, path: Optional[Path]) -> None:
        self.installation_path = path
        if path is None:
            self.settings.remove(self._INSTALLATION_PATH_KEY)
        else:
            self.settings.setValue(self._INSTALLATION_PATH_KEY, str(path))

    def update_tracks(self, tracks: List[str]) -> None:
        self.tracks = tracks


class CoordinateSidebar(QtWidgets.QFrame):
    """Utility sidebar that mirrors cursor and camera details."""

    cameraSelectionChanged = QtCore.pyqtSignal(object)
    cameraDlongsUpdated = QtCore.pyqtSignal(int, object, object)
    cameraPositionUpdated = QtCore.pyqtSignal(int, object, object, object)
    type6ParametersChanged = QtCore.pyqtSignal()
    tvModeCountChanged = QtCore.pyqtSignal(int)

    def __init__(self) -> None:
        super().__init__()
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setMinimumWidth(220)
        self._track_length: int | None = None

        self._cursor_x = self._create_readonly_field("–")
        self._cursor_y = self._create_readonly_field("–")
        self._camera_list = QtWidgets.QComboBox()
        self._camera_list.setMinimumWidth(160)
        self._camera_list.currentIndexChanged.connect(self._on_camera_selected)
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
        self._tv_panel.modeCountChanged.connect(self.tvModeCountChanged)
        self._camera_table.positionUpdated.connect(self._handle_camera_position_updated)
        self._type6_editor.set_tv_dlongs_provider(self._tv_panel.camera_dlongs)
        self._type6_editor.parametersChanged.connect(self._handle_type6_parameters_changed)

        layout = QtWidgets.QVBoxLayout()
        layout.setSpacing(12)

        camera_title = QtWidgets.QLabel("Track cameras")
        camera_title.setStyleSheet("font-weight: bold")
        layout.addWidget(camera_title)
        layout.addWidget(self._camera_list)

        layout.addWidget(self._tv_panel)

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

    def set_tv_mode_count(self, count: int) -> None:
        self._tv_panel.set_mode_count(count)

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
            self._camera_list.setCurrentIndex(-1)
        else:
            for cam in cameras:
                label = f"#{cam.index} (type {cam.camera_type})"
                self._camera_list.addItem(label)
            self._camera_list.setEnabled(True)
            self._camera_details.setText("Select a camera to inspect.")
            self._camera_list.setCurrentIndex(-1)
        self._camera_list.blockSignals(False)

    def select_camera(self, index: int | None) -> None:
        self._camera_list.blockSignals(True)
        if index is None:
            self._camera_list.setCurrentIndex(-1)
        else:
            self._camera_list.setCurrentIndex(index)
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
        if index is not None and self._camera_list.currentIndex() != index:
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

    _HEADERS = [
        "Index",
        "DLONG",
        "DLAT",
        "Speed (mph)",
        "Lateral Speed",
    ]
    recordEdited = QtCore.pyqtSignal(int)
    _LATERAL_SPEED_FACTOR = 31680000 / 54000
    _SPEED_RAW_FACTOR = 5280 / 9

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._records: list[LpPoint] = []
        self._show_speed_raw = False

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
            return (
                f"{record.dlong:.0f}" if role == QtCore.Qt.DisplayRole else record.dlong
            )
        if column == 2:
            return (
                f"{record.dlat:.0f}" if role == QtCore.Qt.DisplayRole else record.dlat
            )
        if column == 3:
            if self._show_speed_raw:
                return (
                    str(record.speed_raw)
                    if role == QtCore.Qt.DisplayRole
                    else record.speed_raw
                )
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
            if self._show_speed_raw:
                speed_raw = int(round(parsed))
                record.speed_raw = speed_raw
                record.speed_mph = papy_speed_to_mph(speed_raw)
            else:
                record.speed_mph = parsed
                record.speed_raw = int(round(parsed * self._SPEED_RAW_FACTOR))
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
                if section == 3:
                    return (
                        "Speed (500ths/frame)"
                        if self._show_speed_raw
                        else "Speed (mph)"
                    )
                return self._HEADERS[section]
            return None
        return str(section)

    def set_records(self, records: list[LpPoint]) -> None:
        self.beginResetModel()
        self._records = list(records)
        self.endResetModel()

    def set_speed_raw_visible(self, enabled: bool) -> None:
        if self._show_speed_raw == enabled:
            return
        self._show_speed_raw = enabled
        self.headerDataChanged.emit(QtCore.Qt.Horizontal, 3, 3)
        if self._records:
            start = self.index(0, 3)
            end = self.index(len(self._records) - 1, 3)
            self.dataChanged.emit(start, end, [QtCore.Qt.DisplayRole, QtCore.Qt.EditRole])

    def recalculate_lateral_speeds(self) -> bool:
        if len(self._records) < 3:
            return False
        total_records = len(self._records)
        recalculated = [0.0] * total_records
        for index in range(total_records):
            prev_record = self._records[(index - 1) % total_records]
            next_record = self._records[(index + 1) % total_records]
            record = self._records[index]
            dlong_delta = next_record.dlong - prev_record.dlong
            if dlong_delta == 0:
                lateral_speed = 0.0
            else:
                lateral_speed = (
                    (next_record.dlat - prev_record.dlat)
                    / dlong_delta
                    * (record.speed_mph * self._LATERAL_SPEED_FACTOR)
                )
            recalculated[(index - 2) % total_records] = lateral_speed
        for index, lateral_speed in enumerate(recalculated):
            self._records[index].lateral_speed = lateral_speed
        start = self.index(0, 4)
        end = self.index(total_records - 1, 4)
        self.dataChanged.emit(start, end, [QtCore.Qt.DisplayRole, QtCore.Qt.EditRole])
        return True


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
        self._lp_speed_unit_button = QtWidgets.QPushButton(
            "Show Speed 500ths per frame"
        )
        self._lp_speed_unit_button.setCheckable(True)
        self._lp_speed_unit_button.setEnabled(False)
        self._lp_speed_unit_button.toggled.connect(
            self._handle_lp_speed_unit_toggled
        )
        self._recalculate_lateral_speed_button = QtWidgets.QPushButton(
            "Recalculate Lateral Speed"
        )
        self._recalculate_lateral_speed_button.setEnabled(False)
        self._recalculate_lateral_speed_button.clicked.connect(
            self._handle_recalculate_lateral_speed
        )
        self._lp_dlat_step = QtWidgets.QSpinBox()
        self._lp_dlat_step.setRange(1, 1_000_000)
        self._lp_dlat_step.setSingleStep(500)
        self._lp_dlat_step.setValue(6000)
        self._lp_dlat_step.setSuffix(" DLAT")
        self._lp_dlat_step.setToolTip(
            "Arrow key step size for adjusting selected LP DLAT values."
        )
        self._lp_dlat_step.valueChanged.connect(self._handle_lp_dlat_step_changed)
        self._lp_shortcut_button = QtWidgets.QPushButton("Enable LP arrow-key editing")
        self._lp_shortcut_button.setCheckable(True)
        self._lp_shortcut_button.setEnabled(False)
        self._lp_shortcut_button.toggled.connect(self._handle_lp_shortcut_toggled)
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

        # Allow multi-line headers
        header.setTextElideMode(QtCore.Qt.ElideNone)
        header.setDefaultAlignment(QtCore.Qt.AlignCenter | QtCore.Qt.AlignVCenter)
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)

        # Force header to be tall enough for wrapping
        header.setMinimumHeight(56)

        # This is REQUIRED even though it looks unrelated
        self._lp_records_table.setWordWrap(True)

        self._lp_records_table.verticalHeader().setVisible(False)
        selection_model = self._lp_records_table.selectionModel()
        if selection_model is not None:
            selection_model.selectionChanged.connect(
                lambda *_: self._handle_lp_record_selected()
            )
        self._lp_records_model.recordEdited.connect(self._handle_lp_record_edited)

        self.visualization_widget = TrackPreviewWidget()
        self.visualization_widget.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.visualization_widget.set_lp_dlat_step(self._lp_dlat_step.value())
        self._lp_shortcut_active = False
        self._sidebar = CoordinateSidebar()
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
        self._export_lp_csv_button = QtWidgets.QPushButton("Export LP CSV")
        self._export_lp_csv_button.setEnabled(False)

        self._trk_gaps_button = QtWidgets.QPushButton("Run TRK Gaps")
        self._trk_gaps_button.setEnabled(False)

        self._show_cameras_button = QtWidgets.QPushButton("Hide Cameras")
        self._show_cameras_button.setCheckable(True)
        self._show_cameras_button.setChecked(True)
        self._show_cameras_button.toggled.connect(self._toggle_show_cameras)
        self._flag_radius_input = QtWidgets.QDoubleSpinBox()
        self._flag_radius_input.setRange(0.0, 2147483647.0)
        self._flag_radius_input.setDecimals(2)
        self._flag_radius_input.setSingleStep(1.0)
        self._flag_radius_input.setValue(self.visualization_widget.flag_radius())
        self._flag_radius_input.setFixedWidth(110)
        self._flag_radius_input.setToolTip(
            "Draw a dotted circle around flags when radius is greater than zero."
        )
        self._flag_radius_input.valueChanged.connect(
            self._handle_flag_radius_changed
        )
        self._radius_unit_button = QtWidgets.QPushButton("Show Radius 500ths")
        self._radius_unit_button.setCheckable(True)
        self._radius_unit_button.setToolTip(
            "Toggle centerline curve radius units between feet and 500ths."
        )
        self._radius_unit_button.toggled.connect(self._handle_radius_unit_toggled)
        self._selected_flag_x = self._create_readonly_field("–")
        self._selected_flag_y = self._create_readonly_field("–")
        selected_flag_title = QtWidgets.QLabel("Selected Flag")
        selected_flag_title.setStyleSheet("font-weight: bold")
        selected_flag_layout = QtWidgets.QHBoxLayout()
        selected_flag_layout.setContentsMargins(0, 0, 0, 0)
        selected_flag_layout.setSpacing(6)
        selected_flag_layout.addWidget(selected_flag_title)
        selected_flag_layout.addWidget(QtWidgets.QLabel("X"))
        selected_flag_layout.addWidget(self._selected_flag_x)
        selected_flag_layout.addWidget(QtWidgets.QLabel("Y"))
        selected_flag_layout.addWidget(self._selected_flag_y)
        selected_flag_widget = QtWidgets.QWidget()
        selected_flag_widget.setLayout(selected_flag_layout)
        selected_flag_widget.setToolTip(
            "Left click to drop/select flags.\nRight click a flag to remove it."
        )
        lp_sidebar = QtWidgets.QFrame()
        lp_sidebar.setFrameShape(QtWidgets.QFrame.StyledPanel)
        left_layout = QtWidgets.QVBoxLayout()
        left_layout.setSpacing(8)
        lp_label = QtWidgets.QLabel("AI and center lines")
        lp_label.setStyleSheet("font-weight: bold")
        left_layout.addWidget(lp_label)
        left_layout.addWidget(self._lp_list)
        lp_records_header = QtWidgets.QHBoxLayout()
        lp_records_header.addWidget(self._lp_records_label)
        lp_records_header.addStretch(1)
        left_layout.addLayout(lp_records_header)
        dlat_step_layout = QtWidgets.QHBoxLayout()
        dlat_step_layout.addWidget(self._lp_shortcut_button)
        dlat_step_layout.addStretch(1)
        dlat_step_layout.addWidget(QtWidgets.QLabel("DLAT step"))
        dlat_step_layout.addWidget(self._lp_dlat_step)
        left_layout.addLayout(dlat_step_layout)
        left_layout.addWidget(self._lp_speed_unit_button)
        left_layout.addWidget(self._recalculate_lateral_speed_button)
        left_layout.addWidget(self._save_lp_button)
        left_layout.addWidget(self._export_lp_csv_button)
        ai_speed_layout = QtWidgets.QHBoxLayout()
        ai_speed_layout.addWidget(self._ai_gradient_button)
        ai_speed_layout.addStretch(1)
        ai_speed_layout.addWidget(self._ai_width_label)
        ai_speed_layout.addWidget(self._ai_width_slider)
        left_layout.addLayout(ai_speed_layout)
        accel_layout = QtWidgets.QHBoxLayout()
        accel_layout.addWidget(self._ai_acceleration_button)
        accel_layout.addStretch(1)
        accel_layout.addWidget(self._accel_window_label)
        accel_layout.addWidget(self._accel_window_slider)
        left_layout.addLayout(accel_layout)
        self._lp_records_table.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )
        left_layout.addWidget(self._lp_records_table, 1)
        lp_sidebar.setLayout(left_layout)
        self.visualization_widget.cursorPositionChanged.connect(
            self._sidebar.update_cursor_position
        )
        self.visualization_widget.selectedFlagChanged.connect(
            self._update_selected_flag_position
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
        self.visualization_widget.diagramClicked.connect(
            self._handle_lp_shortcut_activation
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
        self._sidebar.tvModeCountChanged.connect(
            self._handle_tv_mode_selection_changed
        )
        self._sidebar.set_cameras([], [])
        self._sidebar.update_selected_camera_details(None, None)

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
        self._export_lp_csv_button.clicked.connect(self._handle_export_lp_csv)
        self._trk_gaps_button.clicked.connect(lambda: self.controller.run_trk_gaps(self))
        self.controller.sync_ai_lines()

        self._create_menus()
        self.statusBar().showMessage("Select an ICR2 folder to get started")
        if self.app_state.installation_path:
            self.controller.set_installation_path(self.app_state.installation_path)

        layout = QtWidgets.QVBoxLayout()

        controls = QtWidgets.QHBoxLayout()
        track_label = QtWidgets.QLabel("Tracks")
        track_label.setStyleSheet("font-weight: bold")
        controls.addWidget(track_label)
        controls.addWidget(self._track_list)
        controls.addWidget(selected_flag_widget)
        controls.addWidget(QtWidgets.QLabel("Flag radius"))
        controls.addWidget(self._flag_radius_input)
        controls.addWidget(self._radius_unit_button)
        controls.addStretch(1)
        controls.addWidget(self._trk_gaps_button)
        controls.addWidget(self._boundary_button)
        layout.addLayout(controls)

        camera_sidebar = QtWidgets.QFrame()
        right_sidebar_layout = QtWidgets.QVBoxLayout()
        right_sidebar_layout.setContentsMargins(0, 0, 0, 0)
        right_sidebar_layout.setSpacing(8)
        view_settings_title = QtWidgets.QLabel("View camera settings")
        view_settings_title.setStyleSheet("font-weight: bold")
        view_settings_layout = QtWidgets.QVBoxLayout()
        view_settings_layout.setContentsMargins(0, 0, 0, 0)
        view_settings_layout.setSpacing(4)
        view_settings_layout.addWidget(view_settings_title)
        view_settings_layout.addWidget(self._show_cameras_button)
        view_settings_layout.addWidget(self._zoom_points_button)
        view_settings_widget = QtWidgets.QWidget()
        view_settings_widget.setLayout(view_settings_layout)
        right_sidebar_layout.addWidget(view_settings_widget)
        right_sidebar_layout.addWidget(self._sidebar)
        right_sidebar_layout.addWidget(self._sidebar.type7_details)
        right_sidebar_layout.addWidget(self._sidebar.type6_editor)
        type_button_layout = QtWidgets.QHBoxLayout()
        type_button_layout.addWidget(self._add_type6_camera_button)
        type_button_layout.addWidget(self._add_type7_camera_button)
        right_sidebar_layout.addLayout(type_button_layout)
        right_sidebar_layout.addWidget(self._save_cameras_button)
        right_sidebar_layout.addStretch(1)
        camera_sidebar.setLayout(right_sidebar_layout)

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(lp_sidebar, "LP editing")
        tabs.addTab(camera_sidebar, "Camera editing")

        body = QtWidgets.QSplitter()
        body.setOrientation(QtCore.Qt.Horizontal)
        body.addWidget(tabs)
        body.addWidget(self.visualization_widget)
        body.setSizes([260, 640])
        layout.addWidget(body, stretch=1)

        wrapper = QtWidgets.QWidget()
        wrapper.setLayout(layout)
        self.setCentralWidget(wrapper)

        QtWidgets.QApplication.instance().installEventFilter(self)

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def _create_readonly_field(self, placeholder: str) -> QtWidgets.QLineEdit:
        field = QtWidgets.QLineEdit()
        field.setReadOnly(True)
        field.setPlaceholderText(placeholder)
        field.setFocusPolicy(QtCore.Qt.ClickFocus)
        return field

    @staticmethod
    def _format_value(value: float) -> str:
        return f"{value:.2f}"

    def _update_selected_flag_position(
        self, coords: Optional[tuple[float, float]]
    ) -> None:
        if coords is None:
            self._selected_flag_x.clear()
            self._selected_flag_y.clear()
            return
        self._selected_flag_x.setText(self._format_value(coords[0]))
        self._selected_flag_y.setText(self._format_value(coords[1]))

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

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:  # noqa: N802
        if (
            event.type() == QtCore.QEvent.KeyPress
            and isinstance(obj, QtWidgets.QWidget)
            and obj.window() is self
        ):
            if self._lp_shortcut_active:
                if self._handle_lp_shortcut(event, ignore_focus=True):
                    return True
                self._set_lp_shortcut_active(False)
            if self._handle_lp_shortcut(event):
                return True
        return super().eventFilter(obj, event)

    def _handle_lp_shortcut(
        self, event: QtGui.QKeyEvent, *, ignore_focus: bool = False
    ) -> bool:
        key = event.key()
        if key not in {
            QtCore.Qt.Key_Up,
            QtCore.Qt.Key_Down,
            QtCore.Qt.Key_Left,
            QtCore.Qt.Key_Right,
        }:
            return False
        if not self._can_handle_lp_shortcut(ignore_focus=ignore_focus):
            return False
        if key == QtCore.Qt.Key_Up:
            return self._move_lp_record_selection(1)
        if key == QtCore.Qt.Key_Down:
            return self._move_lp_record_selection(-1)
        if key == QtCore.Qt.Key_Left:
            return self._adjust_lp_record_dlat(self._lp_dlat_step.value())
        if key == QtCore.Qt.Key_Right:
            return self._adjust_lp_record_dlat(-self._lp_dlat_step.value())
        return False

    def _can_handle_lp_shortcut(self, *, ignore_focus: bool = False) -> bool:
        lp_name = self.visualization_widget.active_lp_line()
        if not lp_name or lp_name == "center-line":
            return False
        if not ignore_focus and not self._lp_shortcut_active:
            return False
        if not ignore_focus:
            if (
                self._lp_records_table.state()
                == QtWidgets.QAbstractItemView.EditingState
            ):
                return False
            focus = self.focusWidget()
            if not self._lp_shortcut_focus_allowed(focus):
                return False
            if isinstance(focus, (QtWidgets.QLineEdit, QtWidgets.QAbstractSpinBox)):
                return False
        return True

    def _lp_shortcut_focus_allowed(self, focus: QtWidgets.QWidget | None) -> bool:
        if focus is None:
            return False
        if focus is self.visualization_widget:
            return True
        if focus is self._lp_records_table:
            return True
        return self._lp_records_table.isAncestorOf(focus)

    def _current_lp_selection(self) -> tuple[str, int] | None:
        lp_name = self.visualization_widget.active_lp_line()
        if not lp_name or lp_name == "center-line":
            return None
        selection = self._lp_records_table.selectionModel()
        if selection is None:
            return None
        rows = selection.selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        if row < 0 or row >= self._lp_records_model.rowCount():
            return None
        return lp_name, row

    def _move_lp_record_selection(self, delta: int) -> bool:
        current = self._current_lp_selection()
        if current is None:
            return False
        _, row = current
        total_rows = self._lp_records_model.rowCount()
        if total_rows <= 0:
            return False
        target = max(0, min(total_rows - 1, row + delta))
        if target == row:
            return True
        with QtCore.QSignalBlocker(self._lp_records_table):
            self._lp_records_table.selectRow(target)
        self._handle_lp_record_selected()
        index = self._lp_records_model.index(target, 0)
        if index.isValid():
            self._lp_records_table.scrollTo(
                index, QtWidgets.QAbstractItemView.PositionAtCenter
            )
        return True

    def _adjust_lp_record_dlat(self, delta: int) -> bool:
        current = self._current_lp_selection()
        if current is None:
            return False
        _, row = current
        index = self._lp_records_model.index(row, 2)
        if not index.isValid():
            return False
        current_value = self._lp_records_model.data(index, QtCore.Qt.EditRole)
        try:
            next_value = float(current_value) + float(delta)
        except (TypeError, ValueError):
            return False
        return self._lp_records_model.setData(index, next_value, QtCore.Qt.EditRole)

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

    def _toggle_show_cameras(self, enabled: bool) -> None:
        text = "Hide Cameras" if enabled else "Show Cameras"
        self._show_cameras_button.setText(text)
        self.visualization_widget.set_show_cameras(enabled)

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

    def _handle_flag_radius_changed(self, radius: float) -> None:
        self.visualization_widget.set_flag_radius(radius)

    def _handle_radius_unit_toggled(self, enabled: bool) -> None:
        self.visualization_widget.set_radius_raw_visible(enabled)
        text = "Show Radius Feet" if enabled else "Show Radius 500ths"
        self._radius_unit_button.setText(text)

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
            if name != "center-line":
                checkbox = self._lp_checkboxes.get(name)
                if checkbox is not None and not checkbox.isChecked():
                    checkbox.setChecked(True)
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
        self._update_export_lp_csv_button_state(lp_name)
        self._update_recalculate_lateral_speed_button_state(lp_name)
        self._update_lp_speed_unit_button_state(lp_name)
        selection_model = self._lp_records_table.selectionModel()
        if selection_model is not None:
            selection_model.clearSelection()
        self.visualization_widget.set_selected_lp_record(None, None)
        self._set_lp_shortcut_active(False)
        self._update_lp_shortcut_button_state()
        self._update_selected_lp_index_label(None)
        if lp_name and lp_name != "center-line" and records:
            self._select_lp_record_row(0)

    def _handle_ai_line_loaded(self, name: str) -> None:
        if name == self.visualization_widget.active_lp_line():
            self._update_lp_records_table(name)
        self._update_save_lp_button_state(self.visualization_widget.active_lp_line())
        self._update_export_lp_csv_button_state(
            self.visualization_widget.active_lp_line()
        )
        self._update_recalculate_lateral_speed_button_state(
            self.visualization_widget.active_lp_line()
        )
        self._update_lp_speed_unit_button_state(
            self.visualization_widget.active_lp_line()
        )

    def _handle_lp_record_selected(self) -> None:
        selection = self._lp_records_table.selectionModel()
        if selection is None:
            self._update_selected_lp_index_label(None)
            return
        rows = selection.selectedRows()
        if not rows:
            self.visualization_widget.set_selected_lp_record(None, None)
            self._set_lp_shortcut_active(False)
            self._update_lp_shortcut_button_state()
            self._update_selected_lp_index_label(None)
            return
        row = rows[0].row()
        lp_name = self.visualization_widget.active_lp_line()
        if not lp_name or lp_name == "center-line":
            self.visualization_widget.set_selected_lp_record(None, None)
            self._set_lp_shortcut_active(False)
            self._update_lp_shortcut_button_state()
            self._update_selected_lp_index_label(None)
            return
        self.visualization_widget.set_selected_lp_record(lp_name, row)
        self._update_lp_shortcut_button_state()
        self._update_selected_lp_index_label(row)

    def _handle_lp_shortcut_activation(self) -> None:
        if self._current_lp_selection() is None:
            self._set_lp_shortcut_active(False)
            return
        self._set_lp_shortcut_active(True)

    def _handle_lp_shortcut_toggled(self, active: bool) -> None:
        if active and self._current_lp_selection() is None:
            self._set_lp_shortcut_active(False)
            return
        self._set_lp_shortcut_active(active)

    def _set_lp_shortcut_active(self, active: bool) -> None:
        if self._lp_shortcut_active == active:
            return
        self._lp_shortcut_active = active
        self.visualization_widget.set_lp_shortcut_active(active)
        text = (
            "Disable LP arrow-key editing"
            if active
            else "Enable LP arrow-key editing"
        )
        with QtCore.QSignalBlocker(self._lp_shortcut_button):
            self._lp_shortcut_button.setChecked(active)
            self._lp_shortcut_button.setText(text)
        if active:
            self.visualization_widget.setStyleSheet(
                "QFrame { border: 2px solid #e53935; }"
            )
        else:
            self.visualization_widget.setStyleSheet("")
        self._update_lp_shortcut_button_state()

    def _update_lp_shortcut_button_state(self) -> None:
        has_selection = self._current_lp_selection() is not None
        self._lp_shortcut_button.setEnabled(has_selection)
        if not has_selection:
            with QtCore.QSignalBlocker(self._lp_shortcut_button):
                self._lp_shortcut_button.setChecked(False)
                self._lp_shortcut_button.setText("Enable LP arrow-key editing")

    def _handle_lp_dlat_step_changed(self, value: int) -> None:
        self.visualization_widget.set_lp_dlat_step(value)

    def _handle_lp_record_clicked(self, lp_name: str, row: int) -> None:
        if lp_name != self.visualization_widget.active_lp_line():
            return
        if row < 0 or row >= self._lp_records_model.rowCount():
            return
        self._select_lp_record_row(row)

    def _select_lp_record_row(self, row: int) -> None:
        with QtCore.QSignalBlocker(self._lp_records_table):
            self._lp_records_table.selectRow(row)
        self._handle_lp_record_selected()
        index = self._lp_records_model.index(row, 0)
        if index.isValid():
            self._lp_records_table.scrollTo(
                index, QtWidgets.QAbstractItemView.PositionAtCenter
            )

    def _update_selected_lp_index_label(self, row: int | None) -> None:
        self.visualization_widget.update()

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

    def _handle_export_lp_csv(self) -> None:
        lp_name = self.visualization_widget.active_lp_line()
        suggested = f"{lp_name}.csv" if lp_name else "lp.csv"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export LP CSV",
            suggested,
            "CSV Files (*.csv)",
        )
        if not path:
            return
        success, message = self.visualization_widget.export_active_lp_csv(Path(path))
        title = "Export LP CSV"
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

    def _update_export_lp_csv_button_state(self, lp_name: str | None = None) -> None:
        name = lp_name or self.visualization_widget.active_lp_line()
        enabled = (
            bool(name)
            and name != "center-line"
            and bool(self.visualization_widget.ai_line_records(name))
        )
        self._export_lp_csv_button.setEnabled(enabled)

    def _update_recalculate_lateral_speed_button_state(
        self, lp_name: str | None = None
    ) -> None:
        name = lp_name or self.visualization_widget.active_lp_line()
        enabled = (
            bool(name)
            and name != "center-line"
            and bool(self.visualization_widget.ai_line_records(name))
        )
        self._recalculate_lateral_speed_button.setEnabled(enabled)

    def _update_lp_speed_unit_button_state(self, lp_name: str | None = None) -> None:
        name = lp_name or self.visualization_widget.active_lp_line()
        enabled = (
            bool(name)
            and name != "center-line"
            and bool(self.visualization_widget.ai_line_records(name))
        )
        self._lp_speed_unit_button.setEnabled(enabled)

    def _handle_lp_speed_unit_toggled(self, enabled: bool) -> None:
        self._lp_records_model.set_speed_raw_visible(enabled)
        text = "Show Speed MPH" if enabled else "Show Speed 500ths per frame"
        self._lp_speed_unit_button.setText(text)

    def _handle_tv_mode_selection_changed(self, mode_count: int) -> None:
        self.visualization_widget.set_tv_mode_count(mode_count)

    def _handle_recalculate_lateral_speed(self) -> None:
        lp_name = self.visualization_widget.active_lp_line()
        if not lp_name or lp_name == "center-line":
            return
        if self._lp_records_model.recalculate_lateral_speeds():
            self.visualization_widget.update()

    def _sync_tv_mode_selector(
        self, _cameras: list[CameraPosition], views: list[CameraViewListing]
    ) -> None:
        if not views:
            target_count = 1
        else:
            max_view = max((view.view for view in views), default=1)
            target_count = 1 if max_view <= 1 else 2
        self._sidebar.set_tv_mode_count(target_count)

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
