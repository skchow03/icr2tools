"""Simple Qt application shell for the standalone track viewer."""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.cam.helpers import CameraPosition
from icr2_core.lp.loader import papy_speed_to_mph
from track_viewer.controllers.camera_actions import CameraActions
from track_viewer.model.camera_models import CameraViewListing
from track_viewer.sidebar.coordinate_sidebar import CoordinateSidebar
from track_viewer.sidebar.coordinate_sidebar_vm import CoordinateSidebarViewModel
from track_viewer.services.io_service import TrackIOService, TrackTxtMetadata, TrackTxtResult
from track_viewer.sidebar.pit_editor import PitParametersEditor
from track_viewer.model.pit_models import PitParameters
from track_viewer.ai.ai_line_service import LpPoint
from track_viewer.widget.track_preview_widget import TrackPreviewWidget
from track_viewer.common.version import __version__
from track_viewer.controllers.window_controller import WindowController


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
        self._io_service = TrackIOService()
        self._track_txt_result: TrackTxtResult | None = None
        self._current_track_folder: Path | None = None

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
        self.preview_api = self.visualization_widget.api
        self.preview_api.set_lp_dlat_step(self._lp_dlat_step.value())
        self._lp_shortcut_active = False
        self._sidebar_vm = CoordinateSidebarViewModel()
        self._sidebar = CoordinateSidebar(self._sidebar_vm)
        self._pit_editor = PitParametersEditor()
        self._pit_status_label = QtWidgets.QLabel(
            "Select a track to edit pit parameters."
        )
        self._pit_status_label.setWordWrap(True)
        self._track_txt_status_label = QtWidgets.QLabel(
            "Select a track to edit track.txt parameters."
        )
        self._track_txt_status_label.setWordWrap(True)
        self._track_name_field = self._create_text_field("–")
        self._track_short_name_field = self._create_text_field("–")
        self._track_city_field = self._create_text_field("–")
        self._track_country_field = self._create_text_field("–")
        self._track_pit_window_start_field = self._create_int_field("–")
        self._track_pit_window_end_field = self._create_int_field("–")
        self._track_length_field = self._create_int_field("–")
        self._track_laps_field = self._create_int_field("–")
        self._track_full_name_field = self._create_text_field("–")
        self._cars_min_field = self._create_int_field("–")
        self._cars_max_field = self._create_int_field("–")
        self._temp_avg_field = self._create_int_field("–")
        self._temp_dev_field = self._create_int_field("–")
        self._temp2_avg_field = self._create_int_field("–")
        self._temp2_dev_field = self._create_int_field("–")
        self._qual_mode_field = QtWidgets.QComboBox()
        self._qual_mode_field.addItem("0 - timed session", 0)
        self._qual_mode_field.addItem("1 - multi-lap average", 1)
        self._qual_mode_field.addItem("2 - best single lap", 2)
        self._qual_mode_field.setCurrentIndex(-1)
        self._qual_mode_field.currentIndexChanged.connect(
            self._handle_qual_mode_changed
        )
        self._qual_value_field = self._create_int_field("–")
        self._qual_value_label = QtWidgets.QLabel("Value")
        self._blimp_x_field = self._create_int_field("–")
        self._blimp_y_field = self._create_int_field("–")
        self._gflag_field = self._create_int_field("–")
        self._ttype_field = QtWidgets.QComboBox()
        self._ttype_field.addItem("0 - short oval", 0)
        self._ttype_field.addItem("1 - mid oval", 1)
        self._ttype_field.addItem("2 - large oval", 2)
        self._ttype_field.addItem("3 - superspeedway", 3)
        self._ttype_field.addItem("4 - road course", 4)
        self._ttype_field.addItem("5 - unknown", 5)
        self._ttype_field.setCurrentIndex(-1)
        self._pacea_cars_abreast_field = self._create_int_field("–")
        self._pacea_start_dlong_field = self._create_int_field("–")
        self._pacea_right_dlat_field = self._create_int_field("–")
        self._pacea_left_dlat_field = self._create_int_field("–")
        self._pacea_unknown_field = self._create_int_field("–")
        self._pit_editor.parametersChanged.connect(self._handle_pit_params_changed)
        self._pit_editor.pitVisibilityChanged.connect(
            self._handle_pit_visibility_changed
        )
        self._pit_editor.pitStallCenterVisibilityChanged.connect(
            self._handle_pit_stall_center_visibility_changed
        )
        self._pit_editor.pitWallVisibilityChanged.connect(
            self._handle_pit_wall_visibility_changed
        )
        self._pit_save_button = QtWidgets.QPushButton("Save PIT")
        self._pit_save_button.setEnabled(False)
        self._pit_save_button.clicked.connect(self._handle_save_pit_params)
        self._track_txt_save_button = QtWidgets.QPushButton("Save Track TXT")
        self._track_txt_save_button.setEnabled(False)
        self._track_txt_save_button.clicked.connect(self._handle_save_track_txt)
        self._add_type6_camera_button = QtWidgets.QPushButton("Add Type 6 Camera")
        self._add_type7_camera_button = QtWidgets.QPushButton("Add Type 7 Camera")
        self._boundary_button = QtWidgets.QPushButton("Hide Boundaries")
        self._boundary_button.setCheckable(True)
        self._boundary_button.setChecked(True)
        self._boundary_button.toggled.connect(self._toggle_boundaries)
        self._toggle_boundaries(self._boundary_button.isChecked())
        self._section_divider_button = QtWidgets.QPushButton("Show Section Dividers")
        self._section_divider_button.setCheckable(True)
        self._section_divider_button.toggled.connect(self._toggle_section_dividers)
        self._toggle_section_dividers(self._section_divider_button.isChecked())

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
        self._accel_window_slider.setValue(self.preview_api.ai_acceleration_window())
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
        self._ai_width_slider.setValue(self.preview_api.ai_line_width())
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
        self._flag_radius_input.setValue(self.preview_api.flag_radius())
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
        lp_list_header = QtWidgets.QLabel(
            "Radio selects the active LP. Checkbox toggles visibility."
        )
        lp_list_header.setWordWrap(True)
        left_layout.addWidget(lp_list_header)
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
            self.app_state, self.preview_api, parent=self
        )
        self.controller.installationPathChanged.connect(self._handle_installation_path)
        self.controller.trackListUpdated.connect(self._apply_track_list_items)
        self.controller.trackLengthChanged.connect(self._sidebar.set_track_length)
        self.controller.trkGapsAvailabilityChanged.connect(self._trk_gaps_button.setEnabled)
        self.controller.aiLinesUpdated.connect(self._apply_ai_line_state)

        self.camera_actions = CameraActions(self.preview_api)
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
        controls.addWidget(self._section_divider_button)
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

        pit_sidebar = QtWidgets.QFrame()
        pit_sidebar.setFrameShape(QtWidgets.QFrame.StyledPanel)
        pit_layout = QtWidgets.QVBoxLayout()
        pit_layout.setSpacing(8)
        pit_title = QtWidgets.QLabel("PIT parameters")
        pit_title.setStyleSheet("font-weight: bold")
        pit_layout.addWidget(pit_title)
        pit_layout.addWidget(self._pit_status_label)
        pit_layout.addWidget(self._pit_editor)
        pit_layout.addStretch(1)
        pit_layout.addWidget(self._pit_save_button)
        pit_sidebar.setLayout(pit_layout)

        track_txt_sidebar = QtWidgets.QFrame()
        track_txt_sidebar.setFrameShape(QtWidgets.QFrame.StyledPanel)
        track_txt_layout = QtWidgets.QVBoxLayout()
        track_txt_layout.setSpacing(8)
        track_txt_title = QtWidgets.QLabel("Track TXT parameters")
        track_txt_title.setStyleSheet("font-weight: bold")
        track_txt_layout.addWidget(track_txt_title)
        track_txt_layout.addWidget(self._track_txt_status_label)
        track_txt_form = QtWidgets.QFormLayout()
        track_txt_form.setLabelAlignment(QtCore.Qt.AlignLeft)
        track_txt_form.setFormAlignment(QtCore.Qt.AlignTop)
        track_txt_form.addRow("Track name (TNAME)", self._track_name_field)
        track_txt_form.addRow("Short name (SNAME)", self._track_short_name_field)
        track_txt_form.addRow("City (CITYN)", self._track_city_field)
        track_txt_form.addRow("Country (COUNT)", self._track_country_field)
        spdwy_layout = QtWidgets.QHBoxLayout()
        spdwy_layout.setContentsMargins(0, 0, 0, 0)
        spdwy_layout.addWidget(QtWidgets.QLabel("Start"))
        spdwy_layout.addWidget(self._track_pit_window_start_field)
        spdwy_layout.addWidget(QtWidgets.QLabel("End"))
        spdwy_layout.addWidget(self._track_pit_window_end_field)
        spdwy_widget = QtWidgets.QWidget()
        spdwy_widget.setLayout(spdwy_layout)
        track_txt_form.addRow("Pit window (SPDWY)", spdwy_widget)
        track_txt_form.addRow("Length (LENGT)", self._track_length_field)
        track_txt_form.addRow("Laps (LAPS)", self._track_laps_field)
        track_txt_form.addRow("Full name (FNAME)", self._track_full_name_field)
        cars_layout = QtWidgets.QHBoxLayout()
        cars_layout.setContentsMargins(0, 0, 0, 0)
        cars_layout.addWidget(QtWidgets.QLabel("Min"))
        cars_layout.addWidget(self._cars_min_field)
        cars_layout.addWidget(QtWidgets.QLabel("Max"))
        cars_layout.addWidget(self._cars_max_field)
        cars_widget = QtWidgets.QWidget()
        cars_widget.setLayout(cars_layout)
        track_txt_form.addRow("Cars (CARS)", cars_widget)
        temp_layout = QtWidgets.QHBoxLayout()
        temp_layout.setContentsMargins(0, 0, 0, 0)
        temp_layout.addWidget(QtWidgets.QLabel("Average"))
        temp_layout.addWidget(self._temp_avg_field)
        temp_layout.addWidget(QtWidgets.QLabel("Deviation"))
        temp_layout.addWidget(self._temp_dev_field)
        temp_widget = QtWidgets.QWidget()
        temp_widget.setLayout(temp_layout)
        track_txt_form.addRow("Temperature (TEMP)", temp_widget)
        temp2_layout = QtWidgets.QHBoxLayout()
        temp2_layout.setContentsMargins(0, 0, 0, 0)
        temp2_layout.addWidget(QtWidgets.QLabel("Average"))
        temp2_layout.addWidget(self._temp2_avg_field)
        temp2_layout.addWidget(QtWidgets.QLabel("Deviation"))
        temp2_layout.addWidget(self._temp2_dev_field)
        temp2_widget = QtWidgets.QWidget()
        temp2_widget.setLayout(temp2_layout)
        track_txt_form.addRow("Temperature 2 (TEMP2)", temp2_widget)
        qual_layout = QtWidgets.QHBoxLayout()
        qual_layout.setContentsMargins(0, 0, 0, 0)
        qual_layout.addWidget(QtWidgets.QLabel("Mode"))
        qual_layout.addWidget(self._qual_mode_field)
        qual_layout.addWidget(self._qual_value_label)
        qual_layout.addWidget(self._qual_value_field)
        qual_widget = QtWidgets.QWidget()
        qual_widget.setLayout(qual_layout)
        track_txt_form.addRow("Qualifying (QUAL)", qual_widget)
        blimp_layout = QtWidgets.QHBoxLayout()
        blimp_layout.setContentsMargins(0, 0, 0, 0)
        blimp_layout.addWidget(QtWidgets.QLabel("X"))
        blimp_layout.addWidget(self._blimp_x_field)
        blimp_layout.addWidget(QtWidgets.QLabel("Y"))
        blimp_layout.addWidget(self._blimp_y_field)
        blimp_widget = QtWidgets.QWidget()
        blimp_widget.setLayout(blimp_layout)
        track_txt_form.addRow("Blimp position (BLIMP)", blimp_widget)
        track_txt_form.addRow("Green flag DLONG (GFLAG)", self._gflag_field)
        track_txt_form.addRow("Track type (TTYPE)", self._ttype_field)
        pacea_layout = QtWidgets.QGridLayout()
        pacea_layout.setContentsMargins(0, 0, 0, 0)
        pacea_layout.setHorizontalSpacing(6)
        pacea_layout.addWidget(QtWidgets.QLabel("Cars"), 0, 0)
        pacea_layout.addWidget(self._pacea_cars_abreast_field, 0, 1)
        pacea_layout.addWidget(QtWidgets.QLabel("Start DLONG"), 0, 2)
        pacea_layout.addWidget(self._pacea_start_dlong_field, 0, 3)
        pacea_layout.addWidget(QtWidgets.QLabel("Right DLAT"), 1, 0)
        pacea_layout.addWidget(self._pacea_right_dlat_field, 1, 1)
        pacea_layout.addWidget(QtWidgets.QLabel("Left DLAT"), 1, 2)
        pacea_layout.addWidget(self._pacea_left_dlat_field, 1, 3)
        pacea_layout.addWidget(QtWidgets.QLabel("Unknown"), 2, 0)
        pacea_layout.addWidget(self._pacea_unknown_field, 2, 1)
        pacea_widget = QtWidgets.QWidget()
        pacea_widget.setLayout(pacea_layout)
        track_txt_form.addRow("Pace lap (PACEA)", pacea_widget)
        track_txt_layout.addLayout(track_txt_form)
        track_txt_layout.addStretch(1)
        track_txt_layout.addWidget(self._track_txt_save_button)
        track_txt_sidebar.setLayout(track_txt_layout)

        tabs = QtWidgets.QTabWidget()
        tabs.addTab(lp_sidebar, "LP editing")
        tabs.addTab(camera_sidebar, "Camera editing")
        tabs.addTab(pit_sidebar, "PIT parameters")
        tabs.addTab(track_txt_sidebar, "Track parameters")

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

    def _create_text_field(self, placeholder: str) -> QtWidgets.QLineEdit:
        field = QtWidgets.QLineEdit()
        field.setPlaceholderText(placeholder)
        field.setFocusPolicy(QtCore.Qt.ClickFocus)
        return field

    def _create_int_field(self, placeholder: str) -> QtWidgets.QLineEdit:
        field = QtWidgets.QLineEdit()
        field.setPlaceholderText(placeholder)
        field.setFocusPolicy(QtCore.Qt.ClickFocus)
        validator = QtGui.QIntValidator(-2_147_483_648, 2_147_483_647, field)
        field.setValidator(validator)
        return field

    @staticmethod
    def _format_value(value: float) -> str:
        return f"{value:.2f}"

    def _set_track_txt_field(
        self, field: QtWidgets.QLineEdit, value: str | None
    ) -> None:
        if value is not None:
            field.setText(value)
        else:
            field.clear()

    def _set_qual_mode(self, mode: int | None) -> None:
        with QtCore.QSignalBlocker(self._qual_mode_field):
            if mode in (0, 1, 2):
                self._qual_mode_field.setCurrentIndex(mode)
            else:
                self._qual_mode_field.setCurrentIndex(-1)
        self._update_qual_value_label(mode)

    def _set_track_type(self, ttype: int | None) -> None:
        with QtCore.QSignalBlocker(self._ttype_field):
            if ttype in (0, 1, 2, 3, 4, 5):
                self._ttype_field.setCurrentIndex(ttype)
            else:
                self._ttype_field.setCurrentIndex(-1)

    def _clear_track_txt_fields(self) -> None:
        for field in (
            self._track_name_field,
            self._track_short_name_field,
            self._track_city_field,
            self._track_country_field,
            self._track_pit_window_start_field,
            self._track_pit_window_end_field,
            self._track_length_field,
            self._track_laps_field,
            self._track_full_name_field,
            self._cars_min_field,
            self._cars_max_field,
            self._temp_avg_field,
            self._temp_dev_field,
            self._temp2_avg_field,
            self._temp2_dev_field,
            self._qual_value_field,
            self._blimp_x_field,
            self._blimp_y_field,
            self._gflag_field,
            self._pacea_cars_abreast_field,
            self._pacea_start_dlong_field,
            self._pacea_right_dlat_field,
            self._pacea_left_dlat_field,
            self._pacea_unknown_field,
        ):
            field.clear()
        self._set_qual_mode(None)
        self._set_track_type(None)

    def _update_track_txt_fields(self, result: TrackTxtResult) -> None:
        if not result.exists:
            self._track_txt_status_label.setText(
                f"No {result.txt_path.name} found."
            )
        else:
            self._track_txt_status_label.setText(f"Loaded {result.txt_path.name}.")
        metadata = result.metadata
        self._set_track_txt_field(self._track_name_field, metadata.tname)
        self._set_track_txt_field(self._track_short_name_field, metadata.sname)
        self._set_track_txt_field(self._track_city_field, metadata.cityn)
        self._set_track_txt_field(self._track_country_field, metadata.count)
        pit_window_start = (
            str(metadata.spdwy_start) if metadata.spdwy_start is not None else None
        )
        pit_window_end = (
            str(metadata.spdwy_end) if metadata.spdwy_end is not None else None
        )
        self._set_track_txt_field(self._track_pit_window_start_field, pit_window_start)
        self._set_track_txt_field(self._track_pit_window_end_field, pit_window_end)
        track_length = str(metadata.lengt) if metadata.lengt is not None else None
        self._set_track_txt_field(self._track_length_field, track_length)
        laps = str(metadata.laps) if metadata.laps is not None else None
        self._set_track_txt_field(self._track_laps_field, laps)
        self._set_track_txt_field(self._track_full_name_field, metadata.fname)
        cars_min = str(metadata.cars_min) if metadata.cars_min is not None else None
        cars_max = str(metadata.cars_max) if metadata.cars_max is not None else None
        self._set_track_txt_field(self._cars_min_field, cars_min)
        self._set_track_txt_field(self._cars_max_field, cars_max)
        temp_avg = str(metadata.temp_avg) if metadata.temp_avg is not None else None
        temp_dev = str(metadata.temp_dev) if metadata.temp_dev is not None else None
        self._set_track_txt_field(self._temp_avg_field, temp_avg)
        self._set_track_txt_field(self._temp_dev_field, temp_dev)
        temp2_avg = str(metadata.temp2_avg) if metadata.temp2_avg is not None else None
        temp2_dev = str(metadata.temp2_dev) if metadata.temp2_dev is not None else None
        self._set_track_txt_field(self._temp2_avg_field, temp2_avg)
        self._set_track_txt_field(self._temp2_dev_field, temp2_dev)
        qual_mode_value = metadata.qual_session_mode
        qual_value = (
            str(metadata.qual_session_value)
            if metadata.qual_session_value is not None
            else None
        )
        self._set_qual_mode(qual_mode_value)
        self._set_track_txt_field(self._qual_value_field, qual_value)
        blimp_x = str(metadata.blimp_x) if metadata.blimp_x is not None else None
        blimp_y = str(metadata.blimp_y) if metadata.blimp_y is not None else None
        self._set_track_txt_field(self._blimp_x_field, blimp_x)
        self._set_track_txt_field(self._blimp_y_field, blimp_y)
        gflag = str(metadata.gflag) if metadata.gflag is not None else None
        self._set_track_txt_field(self._gflag_field, gflag)
        self._set_track_type(metadata.ttype)
        pacea_values = (
            metadata.pacea_cars_abreast,
            metadata.pacea_start_dlong,
            metadata.pacea_right_dlat,
            metadata.pacea_left_dlat,
            metadata.pacea_unknown,
        )
        pacea_text = [
            str(value) if value is not None else None for value in pacea_values
        ]
        self._set_track_txt_field(self._pacea_cars_abreast_field, pacea_text[0])
        self._set_track_txt_field(self._pacea_start_dlong_field, pacea_text[1])
        self._set_track_txt_field(self._pacea_right_dlat_field, pacea_text[2])
        self._set_track_txt_field(self._pacea_left_dlat_field, pacea_text[3])
        self._set_track_txt_field(self._pacea_unknown_field, pacea_text[4])

    def _handle_qual_mode_changed(self, index: int) -> None:
        mode = self._qual_mode_field.itemData(index) if index >= 0 else None
        self._update_qual_value_label(mode)

    def _update_qual_value_label(self, mode: int | None) -> None:
        if mode == 0:
            label = "Minutes"
        elif mode in (1, 2):
            label = "Laps"
        else:
            label = "Value"
        self._qual_value_label.setText(label)

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
        self._load_track_txt_data(folder)

    def _load_track_txt_data(self, folder: Path | None) -> None:
        self._current_track_folder = folder if isinstance(folder, Path) else None
        if self._current_track_folder is None:
            self._track_txt_result = None
            self._pit_editor.set_parameters(None)
            self._pit_status_label.setText("Select a track to edit pit parameters.")
            self._track_txt_status_label.setText(
                "Select a track to edit track.txt parameters."
            )
            self._clear_track_txt_fields()
            self._pit_save_button.setEnabled(False)
            self._track_txt_save_button.setEnabled(False)
            self.preview_api.set_pit_parameters(None)
            return

        result = self._io_service.load_track_txt(self._current_track_folder)
        self._track_txt_result = result
        self._update_track_txt_fields(result)
        if result.pit is None:
            self._pit_editor.set_parameters(PitParameters.empty())
            if result.exists:
                self._pit_status_label.setText(
                    (
                        f"No PIT line found in {result.txt_path.name}. "
                        "Saving will append one."
                    )
                )
            else:
                self._pit_status_label.setText(
                    f"No {result.txt_path.name} found. Saving will create it."
                )
        else:
            self._pit_editor.set_parameters(result.pit)
            self._pit_status_label.setText(f"Loaded {result.txt_path.name}.")
        self._pit_save_button.setEnabled(True)
        self._track_txt_save_button.setEnabled(True)
        self.preview_api.set_pit_parameters(self._pit_editor.parameters())
        self.preview_api.set_visible_pit_indices(
            self._pit_editor.pit_visible_indices()
        )
        self.preview_api.set_show_pit_stall_center_dlat(
            self._pit_editor.pit_stall_center_visible()
        )
        self.preview_api.set_show_pit_wall_dlat(
            self._pit_editor.pit_wall_visible()
        )

    def _handle_save_pit_params(self) -> None:
        if self._current_track_folder is None:
            QtWidgets.QMessageBox.warning(
                self, "Save PIT", "No track is currently loaded."
            )
            return
        pit_params = self._pit_editor.parameters()
        if pit_params is None:
            QtWidgets.QMessageBox.warning(
                self, "Save PIT", "No PIT parameters are available to save."
            )
            return
        lines = self._track_txt_result.lines if self._track_txt_result else []
        message = self._io_service.save_track_txt(
            self._current_track_folder, pit_params, None, lines
        )
        self.statusBar().showMessage(message, 5000)
        self._load_track_txt_data(self._current_track_folder)

    def _handle_save_track_txt(self) -> None:
        if self._current_track_folder is None:
            QtWidgets.QMessageBox.warning(
                self, "Save Track TXT", "No track is currently loaded."
            )
            return
        metadata = self._collect_track_txt_metadata()
        pit_params = self._pit_editor.parameters()
        lines = self._track_txt_result.lines if self._track_txt_result else []
        message = self._io_service.save_track_txt(
            self._current_track_folder, pit_params, metadata, lines
        )
        self.statusBar().showMessage(message, 5000)
        self._load_track_txt_data(self._current_track_folder)

    def _collect_track_txt_metadata(self) -> TrackTxtMetadata:
        metadata = (
            self._track_txt_result.metadata
            if self._track_txt_result is not None
            else TrackTxtMetadata()
        )
        metadata.tname = self._track_name_field.text().strip() or None
        metadata.sname = self._track_short_name_field.text().strip() or None
        metadata.cityn = self._track_city_field.text().strip() or None
        metadata.count = self._track_country_field.text().strip() or None
        metadata.spdwy_start = self._parse_optional_int(
            self._track_pit_window_start_field.text()
        )
        metadata.spdwy_end = self._parse_optional_int(
            self._track_pit_window_end_field.text()
        )
        if metadata.spdwy_flag is None:
            metadata.spdwy_flag = 0
        metadata.lengt = self._parse_optional_int(self._track_length_field.text())
        metadata.laps = self._parse_optional_int(self._track_laps_field.text())
        metadata.fname = self._track_full_name_field.text().strip() or None
        metadata.cars_min = self._parse_optional_int(self._cars_min_field.text())
        metadata.cars_max = self._parse_optional_int(self._cars_max_field.text())
        metadata.temp_avg = self._parse_optional_int(self._temp_avg_field.text())
        metadata.temp_dev = self._parse_optional_int(self._temp_dev_field.text())
        metadata.temp2_avg = self._parse_optional_int(self._temp2_avg_field.text())
        metadata.temp2_dev = self._parse_optional_int(self._temp2_dev_field.text())
        metadata.qual_session_mode = (
            self._qual_mode_field.currentData()
            if self._qual_mode_field.currentIndex() >= 0
            else None
        )
        metadata.qual_session_value = self._parse_optional_int(
            self._qual_value_field.text()
        )
        metadata.blimp_x = self._parse_optional_int(self._blimp_x_field.text())
        metadata.blimp_y = self._parse_optional_int(self._blimp_y_field.text())
        metadata.gflag = self._parse_optional_int(self._gflag_field.text())
        metadata.ttype = (
            self._ttype_field.currentData()
            if self._ttype_field.currentIndex() >= 0
            else None
        )
        metadata.pacea_cars_abreast = self._parse_optional_int(
            self._pacea_cars_abreast_field.text()
        )
        metadata.pacea_start_dlong = self._parse_optional_int(
            self._pacea_start_dlong_field.text()
        )
        metadata.pacea_right_dlat = self._parse_optional_int(
            self._pacea_right_dlat_field.text()
        )
        metadata.pacea_left_dlat = self._parse_optional_int(
            self._pacea_left_dlat_field.text()
        )
        metadata.pacea_unknown = self._parse_optional_int(
            self._pacea_unknown_field.text()
        )
        return metadata

    @staticmethod
    def _parse_optional_int(value: str) -> int | None:
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return int(stripped)
        except ValueError:
            return None

    def _handle_pit_params_changed(self) -> None:
        self.preview_api.set_pit_parameters(self._pit_editor.parameters())

    def _handle_pit_visibility_changed(self, indices: set[int]) -> None:
        self.preview_api.set_visible_pit_indices(indices)

    def _handle_pit_stall_center_visibility_changed(self, visible: bool) -> None:
        self.preview_api.set_show_pit_stall_center_dlat(visible)

    def _handle_pit_wall_visibility_changed(self, visible: bool) -> None:
        self.preview_api.set_show_pit_wall_dlat(visible)

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
        lp_name = self.preview_api.active_lp_line()
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
        lp_name = self.preview_api.active_lp_line()
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

            active_line = self.preview_api.active_lp_line()
            if active_line not in {"center-line", *available_files}:
                active_line = "center-line"

            self._add_lp_list_item(
                label="Center line",
                name="center-line",
                color=None,
                visible=self.preview_api.center_line_visible(),
                selected=active_line == "center-line",
                enabled=enabled,
            )

            for name in available_files:
                self._add_lp_list_item(
                    label=name,
                    name=name,
                    color=self.preview_api.lp_color(name),
                    visible=name in visible_files,
                    selected=active_line == name,
                    enabled=enabled,
                )

            self.preview_api.set_active_lp_line(active_line)
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
        self.preview_api.set_show_boundaries(enabled)

    def _toggle_section_dividers(self, enabled: bool) -> None:
        text = "Hide Section Dividers" if enabled else "Show Section Dividers"
        self._section_divider_button.setText(text)
        self.preview_api.set_show_section_dividers(enabled)

    def _toggle_zoom_points(self, enabled: bool) -> None:
        text = "Hide Zoom Points" if enabled else "Show Zoom Points"
        self._zoom_points_button.setText(text)
        self.preview_api.set_show_zoom_points(enabled)

    def _toggle_show_cameras(self, enabled: bool) -> None:
        text = "Hide Cameras" if enabled else "Show Cameras"
        self._show_cameras_button.setText(text)
        self.preview_api.set_show_cameras(enabled)

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
        self.preview_api.set_ai_color_mode(mode)

    def _update_accel_window_label(self, segments: int) -> None:
        plural = "s" if segments != 1 else ""
        self._accel_window_label.setText(f"Accel avg: {segments} segment{plural}")

    def _handle_accel_window_changed(self, segments: int) -> None:
        self._update_accel_window_label(segments)
        self.preview_api.set_ai_acceleration_window(segments)

    def _update_ai_line_width_label(self, width: int) -> None:
        self._ai_width_label.setText(f"AI line width: {width}px")

    def _handle_ai_line_width_changed(self, width: int) -> None:
        self._update_ai_line_width_label(width)
        self.preview_api.set_ai_line_width(width)

    def _handle_flag_radius_changed(self, radius: float) -> None:
        self.preview_api.set_flag_radius(radius)

    def _handle_radius_unit_toggled(self, enabled: bool) -> None:
        self.preview_api.set_radius_raw_visible(enabled)
        text = "Show Radius Feet" if enabled else "Show Radius 500ths"
        self._radius_unit_button.setText(text)

    def _handle_lp_visibility_changed(self, name: str, visible: bool) -> None:
        if name == "center-line":
            self.preview_api.set_show_center_line(visible)
            return

        selected = set(self.preview_api.visible_lp_files())
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
            self.preview_api.set_active_lp_line(name)

    def _update_lp_records_table(self, name: str | None = None) -> None:
        lp_name = name or self.preview_api.active_lp_line()
        records = self.preview_api.ai_line_records(lp_name)
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
        self.preview_api.set_selected_lp_record(None, None)
        self._set_lp_shortcut_active(False)
        self._update_lp_shortcut_button_state()
        self._update_selected_lp_index_label(None)
        if lp_name and lp_name != "center-line" and records:
            self._select_lp_record_row(0)

    def _handle_ai_line_loaded(self, name: str) -> None:
        if name == self.preview_api.active_lp_line():
            self._update_lp_records_table(name)
        self._update_save_lp_button_state(self.preview_api.active_lp_line())
        self._update_export_lp_csv_button_state(
            self.preview_api.active_lp_line()
        )
        self._update_recalculate_lateral_speed_button_state(
            self.preview_api.active_lp_line()
        )
        self._update_lp_speed_unit_button_state(
            self.preview_api.active_lp_line()
        )

    def _handle_lp_record_selected(self) -> None:
        selection = self._lp_records_table.selectionModel()
        if selection is None:
            self._update_selected_lp_index_label(None)
            return
        rows = selection.selectedRows()
        if not rows:
            self.preview_api.set_selected_lp_record(None, None)
            self._set_lp_shortcut_active(False)
            self._update_lp_shortcut_button_state()
            self._update_selected_lp_index_label(None)
            return
        row = rows[0].row()
        lp_name = self.preview_api.active_lp_line()
        if not lp_name or lp_name == "center-line":
            self.preview_api.set_selected_lp_record(None, None)
            self._set_lp_shortcut_active(False)
            self._update_lp_shortcut_button_state()
            self._update_selected_lp_index_label(None)
            return
        self.preview_api.set_selected_lp_record(lp_name, row)
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
        self.preview_api.set_lp_shortcut_active(active)
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
        self.preview_api.set_lp_dlat_step(value)

    def _handle_lp_record_clicked(self, lp_name: str, row: int) -> None:
        if lp_name != self.preview_api.active_lp_line():
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
        lp_name = self.preview_api.active_lp_line()
        if not lp_name or lp_name == "center-line":
            return
        self.preview_api.update_lp_record(lp_name, row)

    def _handle_save_lp_line(self) -> None:
        success, message = self.preview_api.save_active_lp_line()
        title = "Save LP"
        if success:
            QtWidgets.QMessageBox.information(self, title, message)
        else:
            QtWidgets.QMessageBox.warning(self, title, message)

    def _handle_export_lp_csv(self) -> None:
        lp_name = self.preview_api.active_lp_line()
        suggested = f"{lp_name}.csv" if lp_name else "lp.csv"
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export LP CSV",
            suggested,
            "CSV Files (*.csv)",
        )
        if not path:
            return
        success, message = self.preview_api.export_active_lp_csv(Path(path))
        title = "Export LP CSV"
        if success:
            QtWidgets.QMessageBox.information(self, title, message)
        else:
            QtWidgets.QMessageBox.warning(self, title, message)

    def _update_save_lp_button_state(self, lp_name: str | None = None) -> None:
        name = lp_name or self.preview_api.active_lp_line()
        enabled = (
            bool(name)
            and name != "center-line"
            and self.preview_api.trk is not None
            and bool(self.preview_api.ai_line_records(name))
        )
        self._save_lp_button.setEnabled(enabled)

    def _update_export_lp_csv_button_state(self, lp_name: str | None = None) -> None:
        name = lp_name or self.preview_api.active_lp_line()
        enabled = (
            bool(name)
            and name != "center-line"
            and bool(self.preview_api.ai_line_records(name))
        )
        self._export_lp_csv_button.setEnabled(enabled)

    def _update_recalculate_lateral_speed_button_state(
        self, lp_name: str | None = None
    ) -> None:
        name = lp_name or self.preview_api.active_lp_line()
        enabled = (
            bool(name)
            and name != "center-line"
            and bool(self.preview_api.ai_line_records(name))
        )
        self._recalculate_lateral_speed_button.setEnabled(enabled)

    def _update_lp_speed_unit_button_state(self, lp_name: str | None = None) -> None:
        name = lp_name or self.preview_api.active_lp_line()
        enabled = (
            bool(name)
            and name != "center-line"
            and bool(self.preview_api.ai_line_records(name))
        )
        self._lp_speed_unit_button.setEnabled(enabled)

    def _handle_lp_speed_unit_toggled(self, enabled: bool) -> None:
        self._lp_records_model.set_speed_raw_visible(enabled)
        text = "Show Speed MPH" if enabled else "Show Speed 500ths per frame"
        self._lp_speed_unit_button.setText(text)

    def _handle_tv_mode_selection_changed(self, mode_count: int) -> None:
        self.preview_api.set_tv_mode_count(mode_count)

    def _handle_recalculate_lateral_speed(self) -> None:
        lp_name = self.preview_api.active_lp_line()
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
        self.preview_api.set_selected_camera(index)

    def _handle_camera_dlongs_updated(
        self, camera_index: int, start: Optional[int], end: Optional[int]
    ) -> None:
        self.preview_api.update_camera_dlongs(camera_index, start, end)

    def _handle_camera_position_updated(
        self, index: int, x: Optional[int], y: Optional[int], z: Optional[int]
    ) -> None:
        self.preview_api.update_camera_position(index, x, y, z)

    def _handle_type6_parameters_changed(self) -> None:
        self.visualization_widget.update()
