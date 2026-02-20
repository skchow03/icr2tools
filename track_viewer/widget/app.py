"""Simple Qt application shell for the standalone track viewer."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, Optional, Sequence

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.cam.helpers import CameraPosition
from icr2_core.lp.rpy import Rpy
from track_viewer.model.camera_models import CameraViewListing
from track_viewer.sidebar.coordinate_sidebar import CoordinateSidebar
from track_viewer.sidebar.coordinate_sidebar_vm import CoordinateSidebarViewModel
from track_viewer.model.replay_models import ReplayLapInfo
from track_viewer.services.io_service import TrackTxtResult
from track_viewer.model.pit_models import (
    PIT_DLAT_LINE_COLORS,
    PIT_DLONG_LINE_COLORS,
    PitParameters,
)
from track_viewer.model.trk_sections_model import TrkSectionsModel
from track_viewer.widget.track_map_preview_dialog import TrackMapPreviewDialog
from track_viewer.widget.lp_speed_graph import LpSpeedGraphWidget
from track_viewer.widget.track_preview_widget import TrackPreviewWidget
from track_viewer.common.version import __version__
from track_viewer.controllers.window_controller import WindowController
from track_viewer.common.preview_constants import LP_COLORS, LP_FILE_NAMES
from track_viewer.common.weather_compass import turns_to_unit_vector
from track_viewer.widget.track_viewer_app import TrackViewerApp
from track_viewer.widget.track_txt_fields import TrackTxtFieldMixin
from track_viewer.widget.tabs.lp_tab import LpTabBuilder
from track_viewer.widget.tabs.pit_tab import PitTabBuilder
from track_viewer.widget.tabs.replay_tab import ReplayTabBuilder
from track_viewer.widget.tabs.track_txt_tab import TrackTxtTabBuilder
from track_viewer.widget.tabs.tire_txt_tab import TireTxtTabBuilder
from track_viewer.widget.tabs.weather_tab import WeatherTabBuilder




class TrackViewerWindow(TrackTxtFieldMixin, QtWidgets.QMainWindow):
    """Minimal placeholder UI that demonstrates shared state wiring."""

    _RPY_FPS = 15.0

    def __init__(self, app_state: TrackViewerApp):
        super().__init__()
        self.app_state = app_state
        self.app_state.window = self
        self._trk_map_preview_window: QtWidgets.QWidget | None = None
        self._camera_dirty = False
        self._tab_titles: dict[int, str] = {}
        self._lp_tab: QtWidgets.QWidget | None = None
        self._camera_tab: QtWidgets.QWidget | None = None
        self._pit_tab: QtWidgets.QWidget | None = None
        self._track_tab: QtWidgets.QWidget | None = None
        self._weather_tab: QtWidgets.QWidget | None = None
        self._tire_tab: QtWidgets.QWidget | None = None
        self._replay_tab: QtWidgets.QWidget | None = None
        self._closing = False

        self.setWindowTitle("SG CREATE")
        self.resize(720, 480)

        self._track_list = QtWidgets.QComboBox()
        self._track_list.currentIndexChanged.connect(self._on_track_selected)
        self._trk_sections_model = TrkSectionsModel(self)
        self._trk_sections_table = QtWidgets.QTableView()
        self._trk_sections_table.setModel(self._trk_sections_model)
        self._trk_sections_table.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers
        )
        self._trk_sections_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows
        )
        self._trk_sections_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self._trk_sections_table.setAlternatingRowColors(True)
        trk_header = self._trk_sections_table.horizontalHeader()
        trk_header.setTextElideMode(QtCore.Qt.ElideNone)
        trk_header.setDefaultAlignment(QtCore.Qt.AlignCenter | QtCore.Qt.AlignVCenter)
        trk_header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        trk_header.setMinimumHeight(56)
        self._trk_sections_table.setWordWrap(True)
        self._trk_sections_table.verticalHeader().setVisible(False)

        self.visualization_widget = TrackPreviewWidget()
        if hasattr(self.visualization_widget, "setFrameShape"):
            self.visualization_widget.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.preview_api = self.visualization_widget.api
        self._apply_saved_lp_colors()
        self._apply_saved_pit_colors()
        self._lp_speed_graph = LpSpeedGraphWidget()
        self._lp_speed_graph_zoom_x_in = QtWidgets.QPushButton("Zoom X+")
        self._lp_speed_graph_zoom_x_out = QtWidgets.QPushButton("Zoom X-")
        self._lp_speed_graph_zoom_y_in = QtWidgets.QPushButton("Zoom Y+")
        self._lp_speed_graph_zoom_y_out = QtWidgets.QPushButton("Zoom Y-")
        self._lp_speed_graph_follow_selection = QtWidgets.QCheckBox(
            "Center on selection"
        )
        self._lp_speed_graph_follow_selection.setChecked(True)
        self._lp_speed_graph_zoom_x_in.clicked.connect(
            lambda: self._lp_speed_graph.zoom_x(1.2)
        )
        self._lp_speed_graph_zoom_x_out.clicked.connect(
            lambda: self._lp_speed_graph.zoom_x(1 / 1.2)
        )
        self._lp_speed_graph_zoom_y_in.clicked.connect(
            lambda: self._lp_speed_graph.zoom_y(1.2)
        )
        self._lp_speed_graph_zoom_y_out.clicked.connect(
            lambda: self._lp_speed_graph.zoom_y(1 / 1.2)
        )
        self._lp_speed_graph_follow_selection.toggled.connect(
            self._lp_speed_graph.set_follow_selection
        )
        self._lp_speed_graph_container = QtWidgets.QFrame()
        self._lp_speed_graph_container.setFrameShape(QtWidgets.QFrame.StyledPanel)
        lp_speed_graph_layout = QtWidgets.QVBoxLayout()
        lp_speed_graph_layout.setContentsMargins(8, 6, 8, 6)
        lp_speed_graph_layout.setSpacing(6)
        lp_speed_graph_label = QtWidgets.QLabel("LP speed vs DLONG")
        lp_speed_graph_label.setStyleSheet("font-weight: bold")
        lp_speed_graph_layout.addWidget(lp_speed_graph_label)
        lp_speed_graph_layout.addWidget(self._lp_speed_graph)
        lp_speed_zoom_layout = QtWidgets.QHBoxLayout()
        lp_speed_zoom_layout.addWidget(self._lp_speed_graph_zoom_x_in)
        lp_speed_zoom_layout.addWidget(self._lp_speed_graph_zoom_x_out)
        lp_speed_zoom_layout.addSpacing(8)
        lp_speed_zoom_layout.addWidget(self._lp_speed_graph_zoom_y_in)
        lp_speed_zoom_layout.addWidget(self._lp_speed_graph_zoom_y_out)
        lp_speed_zoom_layout.addStretch(1)
        lp_speed_zoom_layout.addWidget(self._lp_speed_graph_follow_selection)
        lp_speed_graph_layout.addLayout(lp_speed_zoom_layout)
        self._lp_speed_graph_container.setLayout(lp_speed_graph_layout)
        self._sidebar_vm = CoordinateSidebarViewModel()
        self._sidebar = CoordinateSidebar(self._sidebar_vm)
        self._trk_status_label = QtWidgets.QLabel(
            "Select a track to view TRK sections."
        )
        self._trk_status_label.setWordWrap(True)

        self._save_cameras_button = QtWidgets.QPushButton("Save Cameras")
        self._save_lp_button = QtWidgets.QPushButton("Save Selected LP")
        self._save_lp_button.setEnabled(False)
        self._save_all_lp_button = QtWidgets.QPushButton("Save All LPs")
        self._save_all_lp_button.setEnabled(False)
        self._export_lp_csv_button = QtWidgets.QPushButton("Export LP CSV")
        self._export_lp_csv_button.setEnabled(False)
        self._import_lp_csv_button = QtWidgets.QPushButton("Import LP CSV")
        self._import_lp_csv_button.setEnabled(False)
        self._export_all_lp_csv_button = QtWidgets.QPushButton(
            "Export All LPs to CSV"
        )
        self._export_all_lp_csv_button.setEnabled(False)
        self._generate_lp_button = QtWidgets.QPushButton("Generate LP Line")
        self._generate_lp_button.setEnabled(False)
        self._lp_tab = LpTabBuilder(self).build()
        self.preview_api.set_lp_dlat_step(self._lp_dlat_step.value())
        self._pit_tab = PitTabBuilder(self).build()
        self._track_tab = TrackTxtTabBuilder(self).build()
        self._tire_tab = TireTxtTabBuilder(self).build()
        self._weather_tab = WeatherTabBuilder(self).build()
        self._replay_tab = ReplayTabBuilder(self).build()
        self._connect_track_txt_dirty_signals()

        self._trk_gaps_action = QtWidgets.QAction("Run TRK Gaps", self)
        self._trk_gaps_action.setEnabled(False)
        self._trk_to_sg_action = QtWidgets.QAction("Convert TRK to SG", self)
        self._trk_to_sg_action.setEnabled(False)
        self._trk_to_csv_action = QtWidgets.QAction(
            "Convert TRK to CSV files", self
        )
        self._trk_to_csv_action.setEnabled(False)
        self._trk_map_preview_action = QtWidgets.QAction("Preview Track Map", self)
        self._trk_map_preview_action.setEnabled(False)
        self._view_trk_data_action = QtWidgets.QAction("View TRK data", self)
        self._view_trk_data_action.triggered.connect(self._show_trk_data_window)
        self._show_boundaries_action = QtWidgets.QAction("Show Boundaries", self)
        self._show_boundaries_action.setCheckable(True)
        self._show_boundaries_action.setChecked(True)
        self._show_boundaries_action.toggled.connect(self._toggle_boundaries)
        self._show_section_dividers_action = QtWidgets.QAction(
            "Show Section Dividers", self
        )
        self._show_section_dividers_action.setCheckable(True)
        self._show_section_dividers_action.toggled.connect(
            self._toggle_section_dividers
        )
        self._trk_data_window: QtWidgets.QDialog | None = None
        self._toggle_boundaries(self._show_boundaries_action.isChecked())
        self._toggle_section_dividers(
            self._show_section_dividers_action.isChecked()
        )

        self._flag_draw_button = QtWidgets.QPushButton("Draw Flag")
        self._flag_draw_button.setCheckable(True)
        self._flag_draw_button.setChecked(self.preview_api.flag_drawing_enabled())
        self._flag_draw_button.setToolTip(
            "Toggle to enable placing flags by clicking the track diagram."
        )
        self._flag_draw_button.toggled.connect(self._toggle_flag_drawing)
        self._toggle_flag_drawing(self._flag_draw_button.isChecked())
        self._flag_radius_input = QtWidgets.QDoubleSpinBox()
        self._flag_radius_input.setRange(0.0, 2147483647.0)
        self._flag_radius_input.setDecimals(2)
        self._flag_radius_input.setSingleStep(100000.0)
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
            "Enable Draw Flag to drop flags.\nLeft click to select flags.\nRight click a flag to remove it."
        )
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
        self.visualization_widget.cameraPositionChanged.connect(
            lambda _index: self._mark_camera_dirty()
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
        self.visualization_widget.weatherCompassHeadingAdjustChanged.connect(
            self._handle_weather_compass_heading_adjust_changed
        )
        self.visualization_widget.weatherCompassWindDirectionChanged.connect(
            self._handle_weather_compass_wind_direction_changed
        )
        self._sidebar.type7_details.parametersChanged.connect(
            self._handle_type7_parameters_changed
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
        self._sidebar.cameraAssignmentChanged.connect(
            self._handle_camera_assignment_changed
        )
        self._sidebar.type6ParametersChanged.connect(
            self._handle_type6_parameters_changed
        )
        self._sidebar.tvModeCountChanged.connect(
            self._handle_tv_mode_selection_changed
        )
        self._sidebar.tvModeViewChanged.connect(
            self._handle_tv_mode_view_changed
        )
        self._sidebar.showCurrentTvOnlyChanged.connect(
            self._handle_show_current_tv_only_changed
        )
        self._sidebar.zoomPointsToggled.connect(self._toggle_zoom_points)
        self._sidebar.set_cameras([], [])
        self._sidebar.update_selected_camera_details(None, None)

        self.controller = WindowController(
            self.app_state, self.preview_api, parent=self
        )
        self.controller.installationPathChanged.connect(self._handle_installation_path)
        self.controller.trackListUpdated.connect(self._apply_track_list_items)
        self.controller.trackLengthChanged.connect(self._sidebar.set_track_length)
        self.controller.trkGapsAvailabilityChanged.connect(
            self._trk_gaps_action.setEnabled
        )
        self.controller.trkGapsAvailabilityChanged.connect(
            self._trk_to_sg_action.setEnabled
        )
        self.controller.trkGapsAvailabilityChanged.connect(
            self._trk_to_csv_action.setEnabled
        )
        self.controller.trkSourceChanged.connect(self._handle_trk_source_changed)
        self.controller.aiLinesUpdated.connect(self._apply_ai_line_state)

        self._sidebar.addType6Requested.connect(
            lambda: self._handle_add_camera(
                self.preview_api.add_type6_camera, "Add Panning Camera"
            )
        )
        self._sidebar.addType2Requested.connect(
            lambda: self._handle_add_camera(
                self.preview_api.add_type2_camera,
                "Add Alternate Panning Camera",
            )
        )
        self._sidebar.addType7Requested.connect(
            lambda: self._handle_add_camera(
                self.preview_api.add_type7_camera, "Add Fixed Camera"
            )
        )
        self._save_cameras_button.clicked.connect(self._handle_save_cameras)
        self._save_lp_button.clicked.connect(self._handle_save_lp_line)
        self._save_all_lp_button.clicked.connect(self._handle_save_all_lp_lines)
        self._export_lp_csv_button.clicked.connect(self._handle_export_lp_csv)
        self._import_lp_csv_button.clicked.connect(self._handle_import_lp_csv)
        self._export_all_lp_csv_button.clicked.connect(
            self._handle_export_all_lp_csv
        )
        self._generate_lp_button.clicked.connect(self._handle_generate_lp_line)
        self._trk_gaps_action.triggered.connect(
            lambda: self.controller.run_trk_gaps(self)
        )
        self._trk_to_sg_action.triggered.connect(
            lambda: self.controller.convert_trk_to_sg(self)
        )
        self._trk_to_csv_action.triggered.connect(
            lambda: self.controller.convert_trk_to_csv(self)
        )
        self._trk_map_preview_action.triggered.connect(
            self._handle_trk_map_preview
        )
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
        controls.addWidget(self._flag_draw_button)
        controls.addWidget(QtWidgets.QLabel("Flag radius"))
        controls.addWidget(self._flag_radius_input)
        controls.addWidget(self._radius_unit_button)
        controls.addStretch(1)
        layout.addLayout(controls)

        camera_sidebar = QtWidgets.QFrame()
        right_sidebar_layout = QtWidgets.QVBoxLayout()
        right_sidebar_layout.setContentsMargins(0, 0, 0, 0)
        right_sidebar_layout.setSpacing(8)
        right_sidebar_layout.addWidget(self._sidebar)
        right_sidebar_layout.addWidget(self._sidebar.type7_details)
        right_sidebar_layout.addWidget(self._sidebar.type6_editor)
        right_sidebar_layout.addWidget(self._save_cameras_button)
        right_sidebar_layout.addStretch(1)
        camera_sidebar.setLayout(right_sidebar_layout)


        trk_sidebar = QtWidgets.QFrame()
        trk_sidebar.setFrameShape(QtWidgets.QFrame.StyledPanel)
        trk_layout = QtWidgets.QVBoxLayout()
        trk_layout.setSpacing(8)
        trk_title = QtWidgets.QLabel("TRK section geometry")
        trk_title.setStyleSheet("font-weight: bold")
        trk_layout.addWidget(trk_title)
        trk_layout.addWidget(self._trk_status_label)
        trk_layout.addWidget(self._trk_sections_table, 1)
        trk_sidebar.setLayout(trk_layout)
        trk_scroll = QtWidgets.QScrollArea()
        trk_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        trk_scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        trk_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        trk_scroll.setWidgetResizable(True)
        trk_scroll.setWidget(trk_sidebar)
        self._trk_scroll = trk_scroll


        tabs = QtWidgets.QTabWidget()
        self._tabs = tabs
        tabs.addTab(
            self._lp_tab,
            self.style().standardIcon(QtWidgets.QStyle.SP_FileDialogInfoView),
            "LP",
        )
        self._camera_tab = camera_sidebar
        tabs.addTab(
            camera_sidebar,
            self.style().standardIcon(QtWidgets.QStyle.SP_DesktopIcon),
            "Cameras",
        )
        tabs.addTab(
            self._pit_tab,
            self.style().standardIcon(QtWidgets.QStyle.SP_DialogApplyButton),
            "Pit",
        )
        tabs.addTab(
            self._track_tab,
            self.style().standardIcon(QtWidgets.QStyle.SP_DirHomeIcon),
            "Track",
        )
        tabs.addTab(
            self._weather_tab,
            self.style().standardIcon(QtWidgets.QStyle.SP_BrowserReload),
            "Weather",
        )
        tabs.addTab(
            self._tire_tab,
            self.style().standardIcon(QtWidgets.QStyle.SP_DriveHDIcon),
            "Tires",
        )
        tabs.addTab(
            self._replay_tab,
            self.style().standardIcon(QtWidgets.QStyle.SP_MediaPlay),
            "Replays",
        )

        body = QtWidgets.QSplitter()
        body.setOrientation(QtCore.Qt.Horizontal)
        tabs.currentChanged.connect(self._handle_tab_changed)
        body.addWidget(tabs)
        right_panel = QtWidgets.QWidget()
        right_layout = QtWidgets.QVBoxLayout()
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)
        right_layout.addWidget(self.visualization_widget, stretch=1)
        right_layout.addWidget(self._lp_speed_graph_container)
        right_panel.setLayout(right_layout)
        body.addWidget(right_panel)
        body.setSizes([260, 640])
        layout.addWidget(body, stretch=1)

        wrapper = QtWidgets.QWidget()
        wrapper.setLayout(layout)
        self.setCentralWidget(wrapper)

        self._handle_tab_changed(self._tabs.currentIndex())
        self._cache_tab_titles()
        self._update_dirty_tab_labels()
        QtWidgets.QApplication.instance().installEventFilter(self)

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        if self._closing:
            event.accept()
            return
        if not self._confirm_discard_unsaved("close the app"):
            event.ignore()
            return
        self._closing = True
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # UI helpers
    # ------------------------------------------------------------------
    def _create_readonly_field(self, placeholder: str) -> QtWidgets.QLineEdit:
        field = QtWidgets.QLineEdit()
        field.setReadOnly(True)
        field.setPlaceholderText(placeholder)
        field.setFocusPolicy(QtCore.Qt.ClickFocus)
        field.setMinimumWidth(0)
        field.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        return field

    def _create_text_field(self, placeholder: str) -> QtWidgets.QLineEdit:
        field = QtWidgets.QLineEdit()
        field.setPlaceholderText(placeholder)
        field.setFocusPolicy(QtCore.Qt.ClickFocus)
        field.setMinimumWidth(0)
        field.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        return field

    def _create_int_field(self, placeholder: str) -> QtWidgets.QLineEdit:
        field = QtWidgets.QLineEdit()
        field.setPlaceholderText(placeholder)
        field.setFocusPolicy(QtCore.Qt.ClickFocus)
        validator = QtGui.QIntValidator(-2_147_483_648, 2_147_483_647, field)
        field.setValidator(validator)
        field.setMinimumWidth(0)
        field.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        return field

    def _build_compound_grid(
        self, fields: Sequence[QtWidgets.QLineEdit]
    ) -> QtWidgets.QWidget:
        grid = QtWidgets.QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        headers = ["Soft", "Medium", "Hard", "Rain"]
        for column, label in enumerate(headers, start=1):
            grid.addWidget(QtWidgets.QLabel(label), 0, column)
        grid.addWidget(QtWidgets.QLabel("Dry"), 1, 0)
        grid.addWidget(QtWidgets.QLabel("Wet"), 2, 0)
        for index, field in enumerate(fields[:8]):
            row = 1 if index < 4 else 2
            column = (index % 4) + 1
            grid.addWidget(field, row, column)
        widget = QtWidgets.QWidget()
        widget.setLayout(grid)
        return widget

    def _build_number_row(
        self,
        fields: Sequence[QtWidgets.QLineEdit],
        *,
        show_labels: bool = True,
    ) -> QtWidgets.QWidget:
        grid = QtWidgets.QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(6)
        for index, field in enumerate(fields):
            if show_labels:
                grid.addWidget(QtWidgets.QLabel(str(index + 1)), 0, index)
                grid.addWidget(field, 1, index)
            else:
                grid.addWidget(field, 0, index)
        widget = QtWidgets.QWidget()
        widget.setLayout(grid)
        return widget

    @staticmethod
    def _format_value(value: float) -> str:
        return f"{value:.2f}"

    def _handle_tab_changed(self, index: int) -> None:
        widget = self._tabs.widget(index)
        self.preview_api.set_show_weather_compass(widget is self._weather_tab)
        show_cameras = widget is self._camera_tab
        self.preview_api.set_show_cameras(show_cameras)
        self.preview_api.set_camera_selection_enabled(show_cameras)
        self.preview_api.set_show_camera_guidance(show_cameras)
        lp_tab_active = widget is self._lp_tab
        self.preview_api.set_lp_editing_tab_active(lp_tab_active)
        self.preview_api.set_replay_tab_active(widget is self._replay_tab)
        self._lp_speed_graph_container.setVisible(lp_tab_active)
        if not lp_tab_active:
            self._set_lp_shortcut_active(False)
        else:
            lp_name = self.preview_api.active_lp_line()
            records = self.preview_api.ai_line_records(lp_name)
            self._update_lp_speed_graph(lp_name, records)
        self._sync_pit_preview_for_tab()

    def _lp_tab_active(self) -> bool:
        return self._tabs.currentWidget() is self._lp_tab

    def _cache_tab_titles(self) -> None:
        self._tab_titles = {}
        if not hasattr(self, "_tabs"):
            return
        for index in range(self._tabs.count()):
            title = self._tabs.tabText(index)
            if title.endswith(" *"):
                title = title[:-2]
            self._tab_titles[index] = title

    def _tab_base_title(self, index: int) -> str:
        title = self._tab_titles.get(index)
        if title is None:
            title = self._tabs.tabText(index)
            if title.endswith(" *"):
                title = title[:-2]
            self._tab_titles[index] = title
        return title

    def _set_tab_dirty(self, widget: QtWidgets.QWidget, dirty: bool) -> None:
        if not hasattr(self, "_tabs"):
            return
        index = self._tabs.indexOf(widget)
        if index < 0:
            return
        base_title = self._tab_base_title(index)
        title = f"{base_title} *" if dirty else base_title
        if self._tabs.tabText(index) != title:
            self._tabs.setTabText(index, title)

    def _update_dirty_tab_labels(self) -> None:
        self._set_tab_dirty(self._lp_tab, self._lp_tab_dirty())
        self._set_tab_dirty(self._camera_tab, self._camera_dirty)
        self._set_tab_dirty(self._pit_tab, self._pit_tab_dirty())
        self._set_tab_dirty(self._track_tab, self._track_tab_dirty())
        self._set_tab_dirty(self._weather_tab, self._weather_tab_dirty())
        self._set_tab_dirty(self._tire_tab, self._tire_tab_dirty())

    def _lp_tab_dirty(self) -> bool:
        if self.preview_api.trk is None:
            return False
        return any(
            self.preview_api.lp_line_dirty(name)
            for name in self.preview_api.available_lp_files()
        )

    def _pit_tab_dirty(self) -> bool:
        if self.controller.track_txt_result is None:
            return False
        baseline_count = 2 if self.controller.track_txt_result.pit2 is not None else 1
        if self._pit_lane_count() != baseline_count:
            return True
        pit_params = self._pit_editors[0].parameters()
        if pit_params != self.controller.track_txt_result.pit:
            return True
        pit2_params = (
            self._pit_editors[1].parameters()
            if self._pit_lane_count() == 2
            else None
        )
        if pit2_params != self.controller.track_txt_result.pit2:
            return True
        return False

    def _has_unsaved_changes(self) -> bool:
        return any(
            (
                self._lp_tab_dirty(),
                self._camera_dirty,
                self._pit_tab_dirty(),
                self._track_tab_dirty(),
                self._weather_tab_dirty(),
                self._tire_tab_dirty(),
            )
        )

    def _confirm_discard_unsaved(self, action: str) -> bool:
        if not self._has_unsaved_changes():
            return True
        message_box = QtWidgets.QMessageBox(self)
        message_box.setIcon(QtWidgets.QMessageBox.Question)
        message_box.setWindowTitle("Unsaved Changes")
        message_box.setText(
            f"There are unsaved changes. Are you sure you want to {action}?"
        )
        discard_text = (
            "Close without saving"
            if action == "close the app"
            else "Leave track without saving"
        )
        discard_button = message_box.addButton(
            discard_text, QtWidgets.QMessageBox.DestructiveRole
        )
        cancel_button = message_box.addButton(
            "Cancel", QtWidgets.QMessageBox.RejectRole
        )
        message_box.setDefaultButton(cancel_button)
        message_box.exec()
        return message_box.clickedButton() == discard_button

    def _set_camera_dirty(self, dirty: bool) -> None:
        if self._camera_dirty == dirty:
            return
        self._camera_dirty = dirty
        self._update_dirty_tab_labels()

    def _mark_camera_dirty(self) -> None:
        self._set_camera_dirty(True)

    def _handle_add_camera(
        self, action: Callable[[], tuple[bool, str]], title: str
    ) -> None:
        success, message = action()
        if success:
            self._mark_camera_dirty()
            QtWidgets.QMessageBox.information(self, title, message)
        else:
            QtWidgets.QMessageBox.warning(self, title, message)

    def _handle_save_cameras(self) -> None:
        success, message = self.preview_api.save_cameras()
        title = "Save Cameras"
        if success:
            QtWidgets.QMessageBox.information(self, title, message)
            self._set_camera_dirty(False)
        else:
            QtWidgets.QMessageBox.warning(self, title, message)

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

        open_trk_action = QtWidgets.QAction("Open TRK WIP", self)
        open_trk_action.triggered.connect(self._handle_open_trk_wip)
        file_menu.addAction(open_trk_action)

        quit_action = QtWidgets.QAction("Quit", self)
        quit_action.triggered.connect(QtWidgets.qApp.quit)
        file_menu.addAction(quit_action)

        view_menu = self.menuBar().addMenu("View")
        view_menu.addAction(self._view_trk_data_action)
        view_menu.addSeparator()
        view_menu.addAction(self._show_boundaries_action)
        view_menu.addAction(self._show_section_dividers_action)

        tools_menu = self.menuBar().addMenu("Tools")
        tools_menu.addAction(self._trk_gaps_action)
        tools_menu.addAction(self._trk_to_sg_action)
        tools_menu.addAction(self._trk_to_csv_action)
        tools_menu.addAction(self._trk_map_preview_action)

        help_menu = self.menuBar().addMenu("Help")
        about_action = QtWidgets.QAction("About", self)
        about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(about_action)

    def _show_trk_data_window(self) -> None:
        if self._trk_data_window is None:
            window = QtWidgets.QDialog(self)
            window.setWindowTitle("TRK Data")
            layout = QtWidgets.QVBoxLayout()
            layout.setContentsMargins(0, 0, 0, 0)
            layout.addWidget(self._trk_scroll)
            window.setLayout(layout)
            window.resize(420, 640)
            self._trk_data_window = window
        self._trk_data_window.show()
        self._trk_data_window.raise_()
        self._trk_data_window.activateWindow()

    def _handle_open_trk_wip(self) -> None:
        if not self._confirm_discard_unsaved("open a TRK file"):
            return
        start_dir = str(self.app_state.installation_path or Path.home())
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open TRK file",
            start_dir,
            "TRK Files (*.trk);;All Files (*)",
        )
        if not path:
            return
        self.controller.load_trk_wip(Path(path))
        with QtCore.QSignalBlocker(self._track_list):
            self._track_list.setCurrentIndex(-1)
        self._load_track_txt_data(None)
        self._set_camera_dirty(False)
        self._update_dirty_tab_labels()
        self._load_trk_data()

    def _handle_trk_source_changed(self, is_wip: bool) -> None:
        self._set_tabs_enabled(not is_wip)

    def _set_tabs_enabled(self, enabled: bool) -> None:
        if not hasattr(self, "_tabs"):
            return
        for index in range(self._tabs.count()):
            self._tabs.setTabEnabled(index, enabled)

    def _handle_installation_path(self, path: Path) -> None:
        self.statusBar().showMessage(str(path))

    def _show_about_dialog(self) -> None:
        QtWidgets.QMessageBox.about(
            self,
            "About SG CREATE",
            f"SG CREATE v{__version__}\nby SK Chow",
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
        if folder == self.controller.current_track_folder:
            return
        if not self._confirm_discard_unsaved("switch tracks"):
            with QtCore.QSignalBlocker(self._track_list):
                current_index = self._track_list.findData(
                    self.controller.current_track_folder
                )
                self._track_list.setCurrentIndex(current_index)
            return
        self.controller.set_selected_track(folder)
        self._load_track_txt_data(folder)
        self._set_camera_dirty(False)
        self._update_dirty_tab_labels()
        self._load_trk_data()

    def _pit_lane_count(self) -> int:
        count = self._pit_lane_count_combo.currentData()
        return int(count) if count is not None else 1

    def _set_pit_lane_count(self, count: int) -> None:
        index = self._pit_lane_count_combo.findData(count)
        if index >= 0:
            with QtCore.QSignalBlocker(self._pit_lane_count_combo):
                self._pit_lane_count_combo.setCurrentIndex(index)
        self._update_pit_tabs(count)

    def _active_pit_lane_index(self) -> int:
        return max(0, self._pit_tabs.currentIndex())

    def _update_pit_tabs(self, count: int) -> None:
        pit2_index = self._pit_tabs.indexOf(self._pit_editors[1])
        if count == 2 and pit2_index == -1:
            self._pit_tabs.addTab(self._pit_editors[1], "PIT2")
        elif count == 1 and pit2_index != -1:
            self._pit_tabs.removeTab(pit2_index)
            self._pit_tabs.setCurrentIndex(0)

    def _is_pit_tab_active(self) -> bool:
        if not hasattr(self, "_tabs") or not hasattr(self, "_pit_tab"):
            return False
        return self._tabs.widget(self._tabs.currentIndex()) is self._pit_tab

    def _clear_pit_preview(self) -> None:
        self.preview_api.set_pit_parameters(None)
        self.preview_api.set_visible_pit_indices(set())
        self.preview_api.set_show_pit_stall_center_dlat(False)
        self.preview_api.set_show_pit_wall_dlat(False)
        self.preview_api.set_show_pit_stall_cars(False)

    def _sync_pit_preview_for_tab(self) -> None:
        if self._is_pit_tab_active():
            self._apply_active_pit_editor_to_preview()
        else:
            self._clear_pit_preview()

    def _apply_active_pit_editor_to_preview(self) -> None:
        if not self._is_pit_tab_active():
            self._clear_pit_preview()
            return
        editor = self._pit_editors[self._active_pit_lane_index()]
        self.preview_api.set_pit_parameters(editor.parameters())
        self.preview_api.set_visible_pit_indices(editor.pit_visible_indices())
        self.preview_api.set_show_pit_stall_center_dlat(
            editor.pit_stall_center_visible()
        )
        self.preview_api.set_show_pit_wall_dlat(editor.pit_wall_visible())
        self.preview_api.set_show_pit_stall_cars(editor.pit_stall_cars_visible())

    def _load_track_txt_data(
        self, folder: Path | None, result: TrackTxtResult | None = None
    ) -> None:
        if result is None:
            result = self.controller.load_track_txt(folder)
        if result is None:
            self._load_replay_list(None)
            for editor in self._pit_editors:
                editor.set_parameters(None)
            self._set_pit_lane_count(1)
            self._pit_status_label.setText("Select a track to edit pit parameters.")
            status_text = "Select a track to edit track.txt parameters."
            self._track_txt_status_label.setText(status_text)
            self._track_txt_tire_status_label.setText(status_text)
            self._track_txt_weather_status_label.setText(status_text)
            self._clear_track_txt_fields()
            self._pit_save_button.setEnabled(False)
            self._track_txt_save_button.setEnabled(False)
            self._track_txt_tire_save_button.setEnabled(False)
            self._track_txt_weather_save_button.setEnabled(False)
            self.preview_api.set_pit_parameters(None)
            self._update_dirty_tab_labels()
            return
        self._load_replay_list(self.controller.current_track_folder)
        self._update_track_txt_fields(result)
        lane_count = 2 if result.pit2 is not None else 1
        self._set_pit_lane_count(lane_count)
        self._pit_editors[0].set_parameters(result.pit or PitParameters.empty())
        self._pit_editors[1].set_parameters(result.pit2 or PitParameters.empty())
        if not result.exists:
            self._pit_status_label.setText(
                f"No {result.txt_path.name} found. Saving will create it."
            )
        elif result.pit is None:
            self._pit_status_label.setText(
                (
                    f"No PIT line found in {result.txt_path.name}. "
                    "Saving will append one."
                )
            )
        elif lane_count == 2 and result.pit2 is None:
            self._pit_status_label.setText(
                (
                    f"No PIT2 line found in {result.txt_path.name}. "
                    "Saving will append one."
                )
            )
        else:
            self._pit_status_label.setText(f"Loaded {result.txt_path.name}.")
        self._pit_save_button.setEnabled(True)
        self._track_txt_save_button.setEnabled(True)
        self._track_txt_tire_save_button.setEnabled(True)
        self._track_txt_weather_save_button.setEnabled(True)
        self._apply_active_pit_editor_to_preview()
        self._update_dirty_tab_labels()

    def _load_replay_list(self, folder: Path | None) -> None:
        self._replay_list.clear()
        self._replay_laps_table.setRowCount(0)
        with QtCore.QSignalBlocker(self._replay_car_combo):
            self._replay_car_combo.clear()
        self._replay_car_combo.setEnabled(False)
        self._current_replay = None
        self._current_replay_path = None
        self.preview_api.set_replay_lap_samples(None)
        if folder is None:
            self._replay_status_label.setText("Select a track to view replay laps.")
            return
        replay_files = self.controller.load_replay_paths(folder)
        if not replay_files:
            self._replay_status_label.setText(
                f"No .RPY files found in {folder.name}."
            )
            return
        for replay in replay_files:
            item = QtWidgets.QListWidgetItem(replay.name)
            item.setData(QtCore.Qt.UserRole, replay)
            self._replay_list.addItem(item)
        self._replay_status_label.setText(
            f"Loaded {len(replay_files)} replay file(s)."
        )

    def _handle_replay_selected(self, row: int) -> None:
        item = self._replay_list.item(row) if row >= 0 else None
        self._replay_laps_table.setRowCount(0)
        with QtCore.QSignalBlocker(self._replay_car_combo):
            self._replay_car_combo.clear()
        self._replay_car_combo.setEnabled(False)
        self._current_replay = None
        self._current_replay_path = None
        self.preview_api.set_replay_lap_samples(None)
        self._update_replay_lp_controls()
        if item is None:
            return
        replay_path = item.data(QtCore.Qt.UserRole)
        if not isinstance(replay_path, Path):
            return
        try:
            rpy = Rpy(str(replay_path))
        except (OSError, ValueError) as exc:
            self._replay_status_label.setText(
                f"Unable to load {replay_path.name}: {exc}"
            )
            return
        if not rpy.cars or not rpy.car_index:
            self._replay_status_label.setText(
                f"No car data found in {replay_path.name}."
            )
            return
        self._current_replay = rpy
        self._current_replay_path = replay_path
        with QtCore.QSignalBlocker(self._replay_car_combo):
            self._replay_car_combo.clear()
            for display_index, car_id in enumerate(rpy.car_index):
                self._replay_car_combo.addItem(
                    f"Car {display_index}",
                    car_id,
                )
            self._replay_car_combo.setEnabled(True)
            if self._replay_car_combo.count() > 0:
                default_index = self._first_replay_car_with_laps(rpy)
                self._replay_car_combo.setCurrentIndex(default_index)
        self._update_replay_laps()
        self._update_replay_lp_controls()

    def _handle_replay_car_selected(self, index: int) -> None:
        if index < 0:
            return
        self.preview_api.set_replay_lap_samples(None)
        self._update_replay_laps()
        self._update_replay_lp_controls()

    def _handle_replay_lap_selected(
        self, row: int, column: int, previous_row: int, previous_column: int
    ) -> None:
        if row < 0 or self._current_replay is None:
            self.preview_api.set_replay_lap_samples(None)
            return
        item = self._replay_laps_table.item(row, 1)
        lap_info = item.data(QtCore.Qt.UserRole) if item else None
        if not isinstance(lap_info, ReplayLapInfo):
            self.preview_api.set_replay_lap_samples(None)
            return
        car_id = self._replay_car_combo.currentData()
        if car_id is None or car_id not in self._current_replay.car_index:
            self.preview_api.set_replay_lap_samples(None)
            return
        car_index = self._current_replay.car_index.index(car_id)
        dlong = self._current_replay.cars[car_index].dlong
        dlat = self._current_replay.cars[car_index].dlat
        start = max(0, lap_info.start_frame)
        end = min(len(dlong), lap_info.end_frame)
        if end <= start:
            self.preview_api.set_replay_lap_samples(None)
            return
        samples = [
            (float(dlong[index]), float(dlat[index]))
            for index in range(start, end)
        ]
        label = f"Lap {lap_info.lap_number} - {lap_info.status}"
        self.preview_api.set_replay_lap_samples(
            samples, label=label, fps=self._RPY_FPS
        )
        self._update_replay_lp_controls()

    def _handle_replay_lp_target_changed(self, _index: int) -> None:
        self._update_replay_lp_controls()

    def _handle_replay_lap_radio_toggled(
        self, button: QtWidgets.QAbstractButton, checked: bool
    ) -> None:
        if not checked:
            if self._replay_selected_lap_for_generation == button.property("lap_info"):
                self._replay_selected_lap_for_generation = None
                self._update_replay_lp_controls()
            return
        lap_info = button.property("lap_info")
        if isinstance(lap_info, ReplayLapInfo):
            self._replay_selected_lap_for_generation = lap_info
            row = button.property("row")
            if isinstance(row, int):
                self._replay_laps_table.setCurrentCell(row, 1)
        self._update_replay_lp_controls()

    def _selected_replay_lap_info(self) -> ReplayLapInfo | None:
        row = self._replay_laps_table.currentRow()
        if row < 0:
            return None
        item = self._replay_laps_table.item(row, 1)
        lap_info = item.data(QtCore.Qt.UserRole) if item else None
        if isinstance(lap_info, ReplayLapInfo):
            return lap_info
        return None

    def _selected_replay_generation_lap_info(self) -> ReplayLapInfo | None:
        if isinstance(self._replay_selected_lap_for_generation, ReplayLapInfo):
            return self._replay_selected_lap_for_generation
        return None

    def _current_replay_lp_target(self) -> str | None:
        name = self._replay_lp_combo.currentData()
        if isinstance(name, str) and name:
            return name
        return None

    def _update_replay_lp_controls(self) -> None:
        has_track = self.preview_api.trk is not None
        has_replay = self._current_replay is not None
        has_lap = self._selected_replay_generation_lap_info() is not None
        has_lp_target = self._current_replay_lp_target() is not None
        self._replay_generate_lp_button.setEnabled(
            has_track and has_replay and has_lap and has_lp_target
        )
        self._replay_copy_speeds_button.setEnabled(
            has_track and has_replay and has_lap and has_lp_target
        )

    def _handle_generate_replay_lp(self) -> None:
        lp_name = self._current_replay_lp_target()
        if not lp_name or lp_name == "center-line":
            QtWidgets.QMessageBox.warning(
                self, "Generate LP from Replay", "Select a valid LP line to replace."
            )
            return
        if self.preview_api.trk is None:
            QtWidgets.QMessageBox.warning(
                self,
                "Generate LP from Replay",
                "Load a track before generating an LP line.",
            )
            return
        if self._current_replay is None:
            QtWidgets.QMessageBox.warning(
                self,
                "Generate LP from Replay",
                "Select a replay file before generating an LP line.",
            )
            return
        lap_info = self._selected_replay_generation_lap_info()
        if lap_info is None:
            QtWidgets.QMessageBox.warning(
                self,
                "Generate LP from Replay",
                "Select a complete replay lap to generate an LP line.",
            )
            return
        car_id = self._replay_car_combo.currentData()
        if car_id is None:
            QtWidgets.QMessageBox.warning(
                self,
                "Generate LP from Replay",
                "Select a replay car before generating an LP line.",
            )
            return
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Generate LP from Replay",
            f"This will overwrite the currently loaded {lp_name} LP.",
            QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Cancel,
        )
        if confirm != QtWidgets.QMessageBox.Ok:
            return
        success, message = self.preview_api.generate_lp_line_from_replay(
            lp_name,
            self._current_replay,
            int(car_id),
            lap_info.start_frame,
            lap_info.end_frame,
        )
        title = "Generate LP from Replay"
        if success:
            checkbox = self._lp_checkboxes.get(lp_name)
            if checkbox is not None and not checkbox.isChecked():
                with QtCore.QSignalBlocker(checkbox):
                    checkbox.setChecked(True)
                selected = set(self.preview_api.visible_lp_files())
                selected.add(lp_name)
                self.controller.set_visible_lp_files(sorted(selected))
            self._set_active_lp_line_in_ui(lp_name)
            self._update_lp_records_table(lp_name)
            self.visualization_widget.update()
            self._update_lp_dirty_indicator(lp_name)
            QtWidgets.QMessageBox.information(self, title, message)
        else:
            QtWidgets.QMessageBox.warning(self, title, message)

    def _handle_copy_replay_speeds(self) -> None:
        lp_name = self._current_replay_lp_target()
        if not lp_name or lp_name == "center-line":
            QtWidgets.QMessageBox.warning(
                self,
                "Copy Replay Speeds",
                "Select a valid LP line to update speeds.",
            )
            return
        if self.preview_api.trk is None:
            QtWidgets.QMessageBox.warning(
                self,
                "Copy Replay Speeds",
                "Load a track before copying replay speeds.",
            )
            return
        if self._current_replay is None:
            QtWidgets.QMessageBox.warning(
                self,
                "Copy Replay Speeds",
                "Select a replay file before copying speeds.",
            )
            return
        lap_info = self._selected_replay_generation_lap_info()
        if lap_info is None:
            QtWidgets.QMessageBox.warning(
                self,
                "Copy Replay Speeds",
                "Select a complete replay lap to copy speeds.",
            )
            return
        car_id = self._replay_car_combo.currentData()
        if car_id is None:
            QtWidgets.QMessageBox.warning(
                self,
                "Copy Replay Speeds",
                "Select a replay car before copying speeds.",
            )
            return
        confirm = QtWidgets.QMessageBox.question(
            self,
            "Copy Replay Speeds",
            f"This will update only the speeds in the {lp_name} LP.",
            QtWidgets.QMessageBox.Ok | QtWidgets.QMessageBox.Cancel,
            QtWidgets.QMessageBox.Cancel,
        )
        if confirm != QtWidgets.QMessageBox.Ok:
            return
        success, message = self.preview_api.copy_lp_speeds_from_replay(
            lp_name,
            self._current_replay,
            int(car_id),
            lap_info.start_frame,
            lap_info.end_frame,
        )
        title = "Copy Replay Speeds"
        if success:
            self._set_active_lp_line_in_ui(lp_name)
            self._update_lp_records_table(lp_name)
            self.visualization_widget.update()
            self._update_lp_dirty_indicator(lp_name)
            QtWidgets.QMessageBox.information(self, title, message)
        else:
            QtWidgets.QMessageBox.warning(self, title, message)

    def _update_replay_laps(self) -> None:
        self._replay_laps_table.setRowCount(0)
        for button in self._replay_lap_button_group.buttons():
            self._replay_lap_button_group.removeButton(button)
            button.deleteLater()
        self._replay_selected_lap_for_generation = None
        if self._current_replay is None or self._current_replay_path is None:
            return
        car_id = self._replay_car_combo.currentData()
        if car_id is None:
            return
        laps = self._calculate_rpy_laps(self._current_replay, car_id)
        if not laps:
            self._replay_status_label.setText(
                f"No lap data found in {self._current_replay_path.name} for car {car_id}."
            )
            self.preview_api.set_replay_lap_samples(None)
            return
        self._replay_status_label.setText(
            f"Loaded {len(laps)} lap(s) from {self._current_replay_path.name} for car {car_id}."
        )
        self._replay_laps_table.setRowCount(len(laps))
        for row_index, lap in enumerate(laps):
            lap_number = lap.lap_number
            status = lap.status
            frames = lap.frames
            time_text = lap.time_text
            if status == "Complete":
                radio_button = QtWidgets.QRadioButton()
                radio_button.setProperty("lap_info", lap)
                radio_button.setProperty("row", row_index)
                self._replay_lap_button_group.addButton(radio_button)
                self._replay_laps_table.setCellWidget(
                    row_index, 0, radio_button
                )
            first_item = self._set_replay_cell(
                row_index, 1, str(lap_number), QtCore.Qt.AlignRight
            )
            first_item.setData(QtCore.Qt.UserRole, lap)
            self._set_replay_cell(row_index, 2, status, QtCore.Qt.AlignLeft)
            self._set_replay_cell(row_index, 3, str(frames), QtCore.Qt.AlignRight)
            self._set_replay_cell(row_index, 4, time_text, QtCore.Qt.AlignRight)
        if laps:
            self._replay_laps_table.setCurrentCell(0, 1)

    def _calculate_rpy_laps(
        self, rpy: Rpy, car_id: int
    ) -> list[ReplayLapInfo]:
        if not rpy.cars:
            return []
        if car_id not in rpy.car_index:
            return []
        car_index = rpy.car_index.index(car_id)
        dlong = rpy.cars[car_index].dlong
        if not dlong:
            return []
        min_dlong = min(dlong)
        max_dlong = max(dlong)
        dlong_range = max_dlong - min_dlong
        if dlong_range <= 0:
            return []
        drop_threshold = max(10_000, int(dlong_range * 0.5))
        lap_frames: list[int] = []
        for i in range(1, len(dlong)):
            if dlong[i] < dlong[i - 1] - drop_threshold:
                lap_frames.append(i)
        laps: list[ReplayLapInfo] = []
        start_frame = 0
        lap_number = 1
        for boundary in lap_frames:
            frames = boundary - start_frame
            if frames <= 0:
                start_frame = boundary
                continue
            status = "Complete"
            if start_frame == 0 and abs(dlong[0]) > drop_threshold:
                status = "Incomplete"
            laps.append(
                ReplayLapInfo(
                    lap_number=lap_number,
                    status=status,
                    frames=frames,
                    time_text=self._format_lap_time(frames),
                    start_frame=start_frame,
                    end_frame=boundary,
                )
            )
            lap_number += 1
            start_frame = boundary
        if start_frame < len(dlong):
            frames = len(dlong) - start_frame
            if frames > 0:
                laps.append(
                    ReplayLapInfo(
                        lap_number=lap_number,
                        status="Incomplete",
                        frames=frames,
                        time_text=self._format_lap_time(frames),
                        start_frame=start_frame,
                        end_frame=len(dlong),
                    )
                )
        return laps

    def _first_replay_car_with_laps(self, rpy: Rpy) -> int:
        for display_index, car_id in enumerate(rpy.car_index):
            if self._calculate_rpy_laps(rpy, car_id):
                return display_index
        return 0

    def _format_lap_time(self, frames: int) -> str:
        total_seconds = frames / self._RPY_FPS
        minutes = int(total_seconds // 60)
        seconds = total_seconds - minutes * 60
        return f"{minutes}:{seconds:06.3f}"

    def _set_replay_cell(
        self, row: int, column: int, text: str, alignment: QtCore.Qt.Alignment
    ) -> QtWidgets.QTableWidgetItem:
        item = QtWidgets.QTableWidgetItem(text)
        item.setTextAlignment(alignment | QtCore.Qt.AlignVCenter)
        self._replay_laps_table.setItem(row, column, item)
        return item

    def _load_trk_data(self) -> None:
        trk = self.preview_api.trk
        if trk is None:
            self._trk_status_label.setText("Select a track to view TRK sections.")
            self._trk_sections_model.set_sections([])
            self._trk_map_preview_action.setEnabled(False)
            return
        sections = trk.sects or []
        self._trk_status_label.setText(f"Loaded {len(sections)} sections.")
        self._trk_sections_model.set_sections(sections)
        self._trk_map_preview_action.setEnabled(True)

    def _handle_trk_map_preview(self) -> None:
        centerline = self.preview_api.sampled_centerline()
        if not centerline:
            QtWidgets.QMessageBox.warning(
                self, "Track Map Preview", "No centerline data is available."
            )
            return
        self._show_trk_map_preview(centerline)

    def _build_trk_map_image(
        self,
        centerline: list[tuple[float, float]],
        flip_marker: bool,
        rotation_steps: int,
    ) -> QtGui.QImage:
        width = 183
        height = 86
        margin = 6
        image = QtGui.QImage(width, height, QtGui.QImage.Format_Mono)
        image.setColorTable([QtGui.qRgb(0, 0, 0), QtGui.qRgb(255, 255, 255)])
        image.fill(0)

        rotation_steps = rotation_steps % 4
        if rotation_steps:
            angle = -rotation_steps * (math.pi / 2)
            cos_angle = math.cos(angle)
            sin_angle = math.sin(angle)
            xs = [point[0] for point in centerline]
            ys = [point[1] for point in centerline]
            center_x = (min(xs) + max(xs)) / 2
            center_y = (min(ys) + max(ys)) / 2

            def rotate_point(point: tuple[float, float]) -> tuple[float, float]:
                dx = point[0] - center_x
                dy = point[1] - center_y
                return (
                    center_x + dx * cos_angle - dy * sin_angle,
                    center_y + dx * sin_angle + dy * cos_angle,
                )

            rotated = [rotate_point(point) for point in centerline]
        else:
            rotated = list(centerline)

        xs = [point[0] for point in rotated]
        ys = [point[1] for point in rotated]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        span_x = max(max_x - min_x, 1e-6)
        span_y = max(max_y - min_y, 1e-6)
        available_width = width - 2 * margin
        available_height = height - 2 * margin
        scale = min(available_width / span_x, available_height / span_y)
        draw_width = span_x * scale
        draw_height = span_y * scale
        offset_x = margin + (available_width - draw_width) / 2
        offset_y = margin + (available_height - draw_height) / 2

        def map_point(point: tuple[float, float]) -> QtCore.QPointF:
            x = offset_x + (point[0] - min_x) * scale
            y = offset_y + (max_y - point[1]) * scale
            return QtCore.QPointF(x, y)

        mapped = [map_point(point) for point in rotated]
        painter = QtGui.QPainter(image)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing, False)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, False)
        track_pen = QtGui.QPen(QtCore.Qt.white, 3)
        track_pen.setCapStyle(QtCore.Qt.RoundCap)
        track_pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setPen(track_pen)
        painter.setBrush(QtCore.Qt.NoBrush)

        path = QtGui.QPainterPath()
        path.moveTo(mapped[0])
        for point in mapped[1:]:
            path.lineTo(point)
        painter.drawPath(path)

        self._draw_start_finish_marker(painter, mapped, flip_marker)
        self._draw_north_marker(
            painter, mapped, width, height, margin, rotation_steps
        )

        painter.end()
        return image

    def _draw_start_finish_marker(
        self,
        painter: QtGui.QPainter,
        mapped: list[QtCore.QPointF],
        flip_marker: bool,
    ) -> None:
        if len(mapped) < 2:
            return
        start = mapped[0]
        next_point = mapped[1]
        direction = next_point - start
        length = (direction.x() ** 2 + direction.y() ** 2) ** 0.5
        if length <= 0:
            return
        direction /= length
        perpendicular = QtCore.QPointF(-direction.y(), direction.x())
        if flip_marker:
            perpendicular = -perpendicular

        perpendicular_length = 8.0
        along_length = 10.0
        arrow_length = 7.0
        arrow_width = 6.0

        kink = start + perpendicular * perpendicular_length
        arrow_tip = kink + direction * along_length

        marker_pen = QtGui.QPen(QtCore.Qt.white, 2)
        marker_pen.setCapStyle(QtCore.Qt.RoundCap)
        marker_pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setPen(marker_pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawLine(start, kink)
        painter.drawLine(kink, arrow_tip)

        base_center = arrow_tip - direction * arrow_length
        left = base_center + perpendicular * (arrow_width / 2)
        right = base_center - perpendicular * (arrow_width / 2)
        arrow = QtGui.QPolygonF([arrow_tip, left, right])
        painter.setBrush(QtCore.Qt.white)
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawPolygon(arrow)

    def _draw_north_marker(
        self,
        painter: QtGui.QPainter,
        mapped: list[QtCore.QPointF],
        width: int,
        height: int,
        margin: int,
        rotation_steps: int,
    ) -> None:
        font = QtGui.QFont(painter.font())
        font.setPointSizeF(8.0)
        painter.setFont(font)
        metrics = QtGui.QFontMetrics(font)
        text = "N"
        text_width = metrics.horizontalAdvance(text)
        text_height = metrics.height()
        arrow_height = 11
        arrow_width = max(8, text_width)
        gap = 2
        total_width = arrow_width
        total_height = arrow_height + gap + text_height
        total_size = max(total_width, total_height)

        candidates = []
        cols = 5
        rows = 3
        for row in range(rows):
            for col in range(cols):
                x = margin + col * (width - 2 * margin - total_size) / max(cols - 1, 1)
                y = margin + row * (height - 2 * margin - total_size) / max(
                    rows - 1, 1
                )
                candidates.append(QtCore.QPointF(x, y))

        def distance_squared(point: QtCore.QPointF) -> float:
            return point.x() ** 2 + point.y() ** 2

        best = QtCore.QPointF(margin, margin)
        best_score = -1.0
        for candidate in candidates:
            center = QtCore.QPointF(
                candidate.x() + total_size / 2, candidate.y() + total_size / 2
            )
            min_distance = None
            for track_point in mapped:
                delta = track_point - center
                score = distance_squared(delta)
                if min_distance is None or score < min_distance:
                    min_distance = score
            if min_distance is not None and min_distance > best_score:
                best_score = min_distance
                best = candidate

        center = QtCore.QPointF(best.x() + total_size / 2, best.y() + total_size / 2)
        heading_turns = self.preview_api.weather_compass_heading_turns()
        heading_turns = (heading_turns + rotation_steps * 0.25) % 1.0
        dx, dy = turns_to_unit_vector(heading_turns)
        direction = QtCore.QPointF(dx, dy)
        perpendicular = QtCore.QPointF(-direction.y(), direction.x())
        group_length = arrow_height + gap + text_height
        arrow_tip = QtCore.QPointF(
            center.x() + direction.x() * (group_length / 2),
            center.y() + direction.y() * (group_length / 2),
        )
        base_center = QtCore.QPointF(
            arrow_tip.x() - direction.x() * arrow_height,
            arrow_tip.y() - direction.y() * arrow_height,
        )
        arrow_left = QtCore.QPointF(
            base_center.x() + perpendicular.x() * (arrow_width / 2),
            base_center.y() + perpendicular.y() * (arrow_width / 2),
        )
        arrow_right = QtCore.QPointF(
            base_center.x() - perpendicular.x() * (arrow_width / 2),
            base_center.y() - perpendicular.y() * (arrow_width / 2),
        )
        arrow = QtGui.QPolygonF([arrow_tip, arrow_left, arrow_right])
        painter.setBrush(QtCore.Qt.white)
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawPolygon(arrow)

        painter.setPen(QtCore.Qt.white)
        text_center = QtCore.QPointF(
            arrow_tip.x() - direction.x() * (arrow_height + gap + text_height / 2),
            arrow_tip.y() - direction.y() * (arrow_height + gap + text_height / 2),
        )
        text_x = text_center.x() - text_width / 2
        text_y = text_center.y() + (metrics.ascent() - metrics.descent()) / 2
        painter.drawText(QtCore.QPointF(text_x, text_y), text)

    def _show_trk_map_preview(
        self, centerline: list[tuple[float, float]]
    ) -> None:
        def build_pixmap(flip_marker: bool, rotation_steps: int) -> QtGui.QPixmap:
            image = self._build_trk_map_image(
                centerline, flip_marker, rotation_steps
            )
            return QtGui.QPixmap.fromImage(image)

        pixmap = build_pixmap(False, 0)
        window = TrackMapPreviewDialog(self, pixmap, rebuild_pixmap=build_pixmap)
        window.show()
        self._trk_map_preview_window = window

    def _handle_save_pit_params(self) -> None:
        pit_params = self._pit_editors[0].parameters()
        pit2_params = None
        if self._pit_lane_count() == 2:
            pit2_params = self._pit_editors[1].parameters()
        lines = (
            self.controller.track_txt_result.lines
            if self.controller.track_txt_result
            else []
        )
        success, message, result = self.controller.save_pit_params(
            pit_params,
            pit2_params,
            lines,
            require_pit2=self._pit_lane_count() == 2,
        )
        if not success:
            QtWidgets.QMessageBox.warning(self, "Save PIT", message)
            return
        self.statusBar().showMessage(message, 5000)
        self._load_track_txt_data(self.controller.current_track_folder, result)

    def _handle_save_track_txt(self) -> None:
        metadata = self._collect_track_txt_metadata()
        pit_params = self._pit_editors[0].parameters()
        pit2_params = (
            self._pit_editors[1].parameters()
            if self._pit_lane_count() == 2
            else None
        )
        lines = (
            self.controller.track_txt_result.lines
            if self.controller.track_txt_result
            else []
        )
        success, message, result = self.controller.save_track_txt(
            pit_params,
            pit2_params,
            metadata,
            lines,
        )
        if not success:
            QtWidgets.QMessageBox.warning(self, "Save Track TXT", message)
            return
        self.statusBar().showMessage(message, 5000)
        self._load_track_txt_data(self.controller.current_track_folder, result)

    def _handle_pit_lane_count_changed(self, _index: int) -> None:
        count = self._pit_lane_count()
        self._update_pit_tabs(count)
        if count == 1:
            self._pit_tabs.setCurrentIndex(0)
        self._apply_active_pit_editor_to_preview()
        self._update_dirty_tab_labels()

    def _handle_pit_tab_changed(self, _index: int) -> None:
        self._apply_active_pit_editor_to_preview()

    def _handle_pit_params_changed(self, lane_index: int) -> None:
        if lane_index != self._active_pit_lane_index():
            return
        self.preview_api.set_pit_parameters(
            self._pit_editors[lane_index].parameters()
        )
        self._update_dirty_tab_labels()

    def _handle_pit_visibility_changed(
        self, lane_index: int, indices: set[int]
    ) -> None:
        if lane_index != self._active_pit_lane_index():
            return
        self.preview_api.set_visible_pit_indices(indices)

    def _handle_pit_stall_center_visibility_changed(
        self, lane_index: int, visible: bool
    ) -> None:
        if lane_index != self._active_pit_lane_index():
            return
        self.preview_api.set_show_pit_stall_center_dlat(visible)

    def _handle_pit_stall_cars_visibility_changed(
        self, lane_index: int, visible: bool
    ) -> None:
        if lane_index != self._active_pit_lane_index():
            return
        self.preview_api.set_show_pit_stall_cars(visible)

    def _handle_pit_wall_visibility_changed(
        self, lane_index: int, visible: bool
    ) -> None:
        if lane_index != self._active_pit_lane_index():
            return
        self.preview_api.set_show_pit_wall_dlat(visible)

    def eventFilter(self, obj: QtCore.QObject, event: QtCore.QEvent) -> bool:  # noqa: N802
        if (
            event.type() == QtCore.QEvent.KeyPress
            and isinstance(obj, QtWidgets.QWidget)
            and obj.window() is self
        ):
            if self.preview_api.lp_shortcut_active():
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
            QtCore.Qt.Key_PageUp,
            QtCore.Qt.Key_PageDown,
            QtCore.Qt.Key_A,
            QtCore.Qt.Key_D,
            QtCore.Qt.Key_W,
            QtCore.Qt.Key_S,
        }:
            return False
        if not self._can_handle_lp_shortcut(ignore_focus=ignore_focus):
            return False
        if key == QtCore.Qt.Key_Up:
            return self._move_lp_record_selection(1)
        if key == QtCore.Qt.Key_Down:
            return self._move_lp_record_selection(-1)
        if key == QtCore.Qt.Key_D:
            return self._move_lp_record_selection(1)
        if key == QtCore.Qt.Key_A:
            return self._move_lp_record_selection(-1)
        if key == QtCore.Qt.Key_Left:
            return self._adjust_lp_record_dlat(self.preview_api.lp_dlat_step())
        if key == QtCore.Qt.Key_Right:
            return self._adjust_lp_record_dlat(-self.preview_api.lp_dlat_step())
        if key == QtCore.Qt.Key_W:
            return self._adjust_lp_record_speed(1)
        if key == QtCore.Qt.Key_S:
            return self._adjust_lp_record_speed(-1)
        if key == QtCore.Qt.Key_PageUp:
            return self._copy_lp_record_fields(1)
        if key == QtCore.Qt.Key_PageDown:
            return self._copy_lp_record_fields(-1)
        return False

    def _can_handle_lp_shortcut(self, *, ignore_focus: bool = False) -> bool:
        if not self._lp_tab_active():
            return False
        lp_name = self.preview_api.active_lp_line()
        if not lp_name or lp_name == "center-line":
            return False
        if not ignore_focus and not self.preview_api.lp_shortcut_active():
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
        selection = self.preview_api.selected_lp_record()
        if selection is None:
            return None
        lp_name, row = selection
        if lp_name != self.preview_api.active_lp_line():
            return None
        if row < 0 or row >= self._lp_records_model.rowCount():
            return None
        return lp_name, row

    def _move_lp_record_selection(self, delta: int) -> bool:
        if self._current_lp_selection() is None:
            return False
        self.preview_api.step_lp_selection(delta)
        self._sync_lp_table_selection()
        return True

    def _adjust_lp_record_dlat(self, delta: int) -> bool:
        current = self._current_lp_selection()
        if current is None:
            return False
        self.preview_api.adjust_selected_lp_dlat(delta)
        self._refresh_lp_record_row(current[1])
        self._handle_lp_data_changed(current[0])
        return True

    def _adjust_lp_record_speed(self, delta: float) -> bool:
        current = self._current_lp_selection()
        if current is None:
            return False
        self.preview_api.adjust_selected_lp_speed(delta)
        self._refresh_lp_record_row(current[1])
        self._handle_lp_data_changed(current[0])
        return True

    def _copy_lp_record_fields(self, delta: int) -> bool:
        current = self._current_lp_selection()
        if current is None:
            return False
        self.preview_api.copy_selected_lp_fields(delta)
        self._sync_lp_table_selection()
        selection = self._current_lp_selection()
        if selection is None:
            return False
        self._refresh_lp_record_row(selection[1])
        self._handle_lp_data_changed(selection[0])
        return True

    def _apply_ai_line_state(
        self, available_files: list[str], visible_files: set[str], enabled: bool
    ) -> None:
        with QtCore.QSignalBlocker(self._lp_list):
            for button in self._lp_button_group.buttons():
                self._lp_button_group.removeButton(button)
                button.deleteLater()
            self._lp_checkboxes = {}
            self._lp_name_cells = {}
            self._lp_name_labels = {}
            self._lp_dirty_labels = {}
            self._lp_list.setRowCount(0)
            self._lp_list.clearContents()

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
                show_select=False,
            )

            for name in available_files:
                self._add_lp_list_item(
                    label=name,
                    name=name,
                    color=self.preview_api.lp_color(name),
                    visible=name in visible_files,
                    selected=active_line == name,
                    enabled=enabled,
                    show_select=True,
                )

            self.preview_api.set_active_lp_line(active_line)
        self._lp_list.setEnabled(enabled)
        self._update_export_all_lp_csv_button_state()
        self._update_lp_records_table(active_line)
        self._update_save_lp_button_state(active_line)
        self._update_generate_lp_button_state(active_line)
        self._sync_replay_lp_targets(available_files, enabled)

    def _add_lp_list_item(
        self,
        *,
        label: str,
        name: str,
        color: str | None,
        visible: bool,
        selected: bool,
        enabled: bool,
        show_select: bool,
    ) -> None:
        radio = None
        if show_select:
            radio = QtWidgets.QRadioButton()
            radio.setProperty("lp-name", name)
            with QtCore.QSignalBlocker(radio):
                radio.setChecked(selected)
            radio.setEnabled(enabled)
            self._lp_button_group.addButton(radio)

        checkbox = QtWidgets.QCheckBox()
        with QtCore.QSignalBlocker(checkbox):
            checkbox.setChecked(visible)
        checkbox.setEnabled(enabled)
        checkbox.toggled.connect(
            lambda state, line=name: self._handle_lp_visibility_changed(line, state)
        )

        row = self._lp_list.rowCount()
        self._lp_list.insertRow(row)

        name_container = QtWidgets.QWidget()
        name_layout = QtWidgets.QHBoxLayout()
        name_layout.setContentsMargins(6, 2, 6, 2)
        name_layout.setSpacing(6)
        name_label = QtWidgets.QLabel(label)
        name_layout.addWidget(name_label)
        name_layout.addStretch(1)
        name_container.setLayout(name_layout)
        self._lp_list.setCellWidget(row, 0, name_container)

        select_container = QtWidgets.QWidget()
        select_layout = QtWidgets.QHBoxLayout()
        select_layout.setContentsMargins(0, 0, 0, 0)
        select_layout.addStretch(1)
        if radio is not None:
            select_layout.addWidget(radio)
        select_layout.addStretch(1)
        select_container.setLayout(select_layout)
        self._lp_list.setCellWidget(row, 1, select_container)

        visible_container = QtWidgets.QWidget()
        visible_layout = QtWidgets.QHBoxLayout()
        visible_layout.setContentsMargins(0, 0, 0, 0)
        visible_layout.addStretch(1)
        visible_layout.addWidget(checkbox)
        visible_layout.addStretch(1)
        visible_container.setLayout(visible_layout)
        self._lp_list.setCellWidget(row, 2, visible_container)

        dirty_label = QtWidgets.QLabel()
        dirty_label.setAlignment(QtCore.Qt.AlignCenter)
        dirty_container = QtWidgets.QWidget()
        dirty_layout = QtWidgets.QHBoxLayout()
        dirty_layout.setContentsMargins(6, 0, 6, 0)
        dirty_layout.addStretch(1)
        dirty_layout.addWidget(dirty_label)
        dirty_layout.addStretch(1)
        dirty_container.setLayout(dirty_layout)
        self._lp_list.setCellWidget(row, 3, dirty_container)

        self._lp_list.setRowHeight(row, name_container.sizeHint().height())
        self._lp_checkboxes[name] = checkbox
        self._lp_name_cells[name] = name_container
        self._lp_name_labels[name] = name_label
        self._lp_dirty_labels[name] = dirty_label
        if color:
            self._update_lp_name_color(name, color)
        self._update_lp_dirty_indicator(name)

    def _sync_replay_lp_targets(
        self, available_files: list[str], enabled: bool
    ) -> None:
        current = self._current_replay_lp_target()
        active_line = self.preview_api.active_lp_line()
        with QtCore.QSignalBlocker(self._replay_lp_combo):
            self._replay_lp_combo.clear()
            self._replay_lp_combo.addItem("Select LP line", None)
            for name in available_files:
                self._replay_lp_combo.addItem(name, name)
            target = current if current in available_files else active_line
            if target in available_files:
                index = self._replay_lp_combo.findData(target)
                if index >= 0:
                    self._replay_lp_combo.setCurrentIndex(index)
            else:
                self._replay_lp_combo.setCurrentIndex(0)
        self._replay_lp_combo.setEnabled(enabled and bool(available_files))
        self._update_replay_lp_controls()

    def _toggle_boundaries(self, enabled: bool) -> None:
        self.preview_api.set_show_boundaries(enabled)

    def _toggle_section_dividers(self, enabled: bool) -> None:
        self.preview_api.set_show_section_dividers(enabled)

    def _toggle_zoom_points(self, enabled: bool) -> None:
        self.preview_api.set_show_zoom_points(enabled)

    def _toggle_flag_drawing(self, enabled: bool) -> None:
        text = "Stop Drawing Flags" if enabled else "Draw Flag"
        self._flag_draw_button.setText(text)
        self.preview_api.set_flag_drawing_enabled(enabled)

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

        self._ai_gradient_button.setText("Show AI Speed Gradient")
        self._ai_acceleration_button.setText("Show AI Acceleration Gradient")
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

    def _update_lp_name_color(self, name: str, color: str) -> None:
        label = self._lp_name_labels.get(name)
        container = self._lp_name_cells.get(name)
        if label is None or container is None:
            return
        qcolor = QtGui.QColor(color)
        if not qcolor.isValid():
            return
        label.setStyleSheet(self._lp_color_style(qcolor))
        container.setStyleSheet("")

    def _update_lp_dirty_indicator(self, name: str) -> None:
        label = self._lp_dirty_labels.get(name)
        if label is None:
            return
        dirty = self.preview_api.lp_line_dirty(name)
        label.setText("Unsaved changes" if dirty else "")
        self._update_dirty_tab_labels()

    def _update_all_lp_dirty_indicators(self) -> None:
        for name in self._lp_dirty_labels:
            self._update_lp_dirty_indicator(name)

    @staticmethod
    def _lp_color_style(color: QtGui.QColor) -> str:
        luminance = (
            0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()
        ) / 255.0
        if luminance > 0.6:
            return (
                f"color: {color.name()}; background-color: #424242;"
                " padding: 1px 4px; border-radius: 2px;"
            )
        return f"color: {color.name()};"

    def _apply_saved_lp_colors(self) -> None:
        colors = self.app_state.load_lp_colors()
        defaults = {
            name: LP_COLORS[index % len(LP_COLORS)]
            for index, name in enumerate(LP_FILE_NAMES)
        }
        merged = {}
        missing_defaults = False
        for name, default_color in defaults.items():
            stored = colors.get(name)
            if stored:
                merged[name] = stored
            else:
                merged[name] = default_color
                missing_defaults = True
        for name, color in colors.items():
            if name not in merged:
                merged[name] = color
        if missing_defaults:
            self.app_state.save_lp_colors(merged)
        for name, color in merged.items():
            self.preview_api.set_lp_color(name, color)

    def _apply_saved_pit_colors(self) -> None:
        stored_dlong, stored_dlat = self.app_state.load_pit_colors()
        default_dlong = dict(PIT_DLONG_LINE_COLORS)
        default_dlat = dict(PIT_DLAT_LINE_COLORS)
        merged_dlong: dict[int, str] = {}
        merged_dlat: dict[int, str] = {}
        missing_defaults = False

        for index, default_color in default_dlong.items():
            stored = stored_dlong.get(index)
            normalized = self._normalize_pit_color(stored)
            if normalized:
                merged_dlong[index] = normalized
            else:
                merged_dlong[index] = default_color
                missing_defaults = True

        for index, default_color in default_dlat.items():
            stored = stored_dlat.get(index)
            normalized = self._normalize_pit_color(stored)
            if normalized:
                merged_dlat[index] = normalized
            else:
                merged_dlat[index] = default_color
                missing_defaults = True

        for index, color in stored_dlong.items():
            if index in merged_dlong:
                continue
            normalized = self._normalize_pit_color(color)
            if normalized:
                merged_dlong[index] = normalized

        for index, color in stored_dlat.items():
            if index in merged_dlat:
                continue
            normalized = self._normalize_pit_color(color)
            if normalized:
                merged_dlat[index] = normalized

        PIT_DLONG_LINE_COLORS.clear()
        PIT_DLONG_LINE_COLORS.update(merged_dlong)
        PIT_DLAT_LINE_COLORS.clear()
        PIT_DLAT_LINE_COLORS.update(merged_dlat)

        if missing_defaults:
            self.app_state.save_pit_colors(merged_dlong, merged_dlat)

    @staticmethod
    def _normalize_pit_color(color: str | None) -> str | None:
        if not color:
            return None
        candidate = color.strip()
        if not candidate:
            return None
        if QtGui.QColor(candidate).isValid():
            return candidate
        hex_value = candidate[1:] if candidate.startswith("#") else candidate
        if len(hex_value) != 8 or any(
            ch not in "0123456789abcdefABCDEF" for ch in hex_value
        ):
            return None
        argb = f"#{hex_value[6:8]}{hex_value[:6]}"
        if QtGui.QColor(argb).isValid():
            return argb
        return None

    def _handle_lp_radio_clicked(self, button: QtWidgets.QAbstractButton) -> None:
        name = button.property("lp-name")
        if isinstance(name, str):
            if name != "center-line":
                checkbox = self._lp_checkboxes.get(name)
                if checkbox is not None and not checkbox.isChecked():
                    checkbox.setChecked(True)
            self.preview_api.set_active_lp_line(name)

    def _set_active_lp_line_in_ui(self, name: str) -> None:
        self.preview_api.set_active_lp_line(name)
        for button in self._lp_button_group.buttons():
            if button.property("lp-name") == name:
                with QtCore.QSignalBlocker(button):
                    button.setChecked(True)
                break

    def _update_lp_speed_graph(
        self, lp_name: str | None, records: list[LpPoint]
    ) -> None:
        if not lp_name or lp_name == "center-line":
            self._lp_speed_graph.set_records([])
            return
        self._lp_speed_graph.set_records(records)

    def _update_lp_records_table(self, name: str | None = None) -> None:
        lp_name = name or self.preview_api.active_lp_line()
        records = self.preview_api.ai_line_records(lp_name)
        label = "LP records"
        if lp_name and lp_name != "center-line":
            label = f"LP records: {lp_name}"
        self._lp_records_label.setText(label)
        self._lp_records_model.set_records(records, lp_name)
        self._update_lp_speed_graph(lp_name, records)
        self._update_save_lp_button_state(lp_name)
        self._update_import_lp_csv_button_state(lp_name)
        self._update_export_lp_csv_button_state(lp_name)
        self._update_export_all_lp_csv_button_state()
        self._update_recalculate_lateral_speed_button_state(lp_name)
        self._update_generate_lp_button_state(lp_name)
        selection_model = self._lp_records_table.selectionModel()
        if selection_model is not None:
            selection_model.clearSelection()
        self.preview_api.set_selected_lp_record(None, None)
        self._set_lp_shortcut_active(False)
        self._update_lp_shortcut_button_state()
        self._update_selected_lp_index_label(None)
        self._lp_speed_graph.set_selected_index(None)
        if lp_name and lp_name != "center-line" and records:
            self._select_lp_record_row(0)

    def _handle_ai_line_loaded(self, name: str) -> None:
        if name == self.preview_api.active_lp_line():
            self._update_lp_records_table(name)
        self._update_save_lp_button_state(self.preview_api.active_lp_line())
        self._update_import_lp_csv_button_state(self.preview_api.active_lp_line())
        self._update_export_lp_csv_button_state(
            self.preview_api.active_lp_line()
        )
        self._update_export_all_lp_csv_button_state()
        self._update_recalculate_lateral_speed_button_state(
            self.preview_api.active_lp_line()
        )
        self._update_generate_lp_button_state(self.preview_api.active_lp_line())

    def _handle_lp_record_selected(self) -> None:
        selection = self._lp_records_table.selectionModel()
        if selection is None:
            self._update_selected_lp_index_label(None)
            self._lp_speed_graph.set_selected_index(None)
            return
        rows = selection.selectedRows()
        if not rows:
            self.preview_api.set_selected_lp_record(None, None)
            self._set_lp_shortcut_active(False)
            self._update_lp_shortcut_button_state()
            self._update_selected_lp_index_label(None)
            self._lp_speed_graph.set_selected_index(None)
            return
        row = rows[0].row()
        lp_name = self.preview_api.active_lp_line()
        if not lp_name or lp_name == "center-line":
            self.preview_api.set_selected_lp_record(None, None)
            self._set_lp_shortcut_active(False)
            self._update_lp_shortcut_button_state()
            self._update_selected_lp_index_label(None)
            self._lp_speed_graph.set_selected_index(None)
            return
        self.preview_api.set_selected_lp_record(lp_name, row)
        self._update_lp_shortcut_button_state()
        self._update_selected_lp_index_label(row)
        self._lp_speed_graph.set_selected_index(row)

    def _handle_lp_shortcut_activation(self) -> None:
        if not self._lp_tab_active():
            self._set_lp_shortcut_active(False)
            return
        if self._current_lp_selection() is None:
            self._set_lp_shortcut_active(False)
            return
        self._set_lp_shortcut_active(True)

    def _handle_lp_shortcut_toggled(self, active: bool) -> None:
        if not self._lp_tab_active():
            self._set_lp_shortcut_active(False)
            return
        if active and self._current_lp_selection() is None:
            self._set_lp_shortcut_active(False)
            return
        self._set_lp_shortcut_active(active)

    def _set_lp_shortcut_active(self, active: bool) -> None:
        if self.preview_api.lp_shortcut_active() == active:
            return
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

    def _sync_lp_table_selection(self) -> None:
        selection = self.preview_api.selected_lp_record()
        if selection is None:
            self._lp_records_table.clearSelection()
            self._update_selected_lp_index_label(None)
            self._lp_speed_graph.set_selected_index(None)
            return
        lp_name, row = selection
        if lp_name != self.preview_api.active_lp_line():
            return
        self._select_lp_record_row(row)

    def _refresh_lp_record_row(self, row: int) -> None:
        if row < 0 or row >= self._lp_records_model.rowCount():
            return
        self._lp_records_model.refresh_row(row)
        start = self._lp_records_model.index(row, 0)
        end = self._lp_records_model.index(row, self._lp_records_model.columnCount() - 1)
        self._lp_records_model.dataChanged.emit(
            start, end, [QtCore.Qt.DisplayRole, QtCore.Qt.EditRole]
        )

    def _handle_lp_data_changed(self, lp_name: str) -> None:
        self._update_lp_dirty_indicator(lp_name)
        records = self.preview_api.ai_line_records(lp_name)
        self._update_lp_speed_graph(lp_name, records)
        self._sync_lp_speed_graph_selection()

    def _update_selected_lp_index_label(self, row: int | None) -> None:
        self.visualization_widget.update()

    def _sync_lp_speed_graph_selection(self) -> None:
        current = self._current_lp_selection()
        if current is None:
            self._lp_speed_graph.set_selected_index(None)
            return
        _, row = current
        self._lp_speed_graph.set_selected_index(row)

    def _handle_lp_record_edited(self, row: int) -> None:
        lp_name = self.preview_api.active_lp_line()
        if not lp_name or lp_name == "center-line":
            return
        self._handle_lp_data_changed(lp_name)

    def _handle_save_lp_line(self) -> None:
        if (
            QtWidgets.QMessageBox.question(
                self,
                "Save Selected LP",
                "Save the selected LP line to disk?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Cancel,
            )
            != QtWidgets.QMessageBox.Yes
        ):
            return
        success, message = self.preview_api.save_active_lp_line()
        title = "Save Selected LP"
        if success:
            QtWidgets.QMessageBox.information(self, title, message)
        else:
            QtWidgets.QMessageBox.warning(self, title, message)
        self._update_lp_dirty_indicator(self.preview_api.active_lp_line())

    def _handle_save_all_lp_lines(self) -> None:
        if (
            QtWidgets.QMessageBox.question(
                self,
                "Save All LPs",
                "Save all LP lines to disk?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.Cancel,
                QtWidgets.QMessageBox.Cancel,
            )
            != QtWidgets.QMessageBox.Yes
        ):
            return
        success, message = self.preview_api.save_all_lp_lines()
        title = "Save All LPs"
        if success:
            QtWidgets.QMessageBox.information(self, title, message)
        else:
            QtWidgets.QMessageBox.warning(self, title, message)
        self._update_all_lp_dirty_indicators()

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

    def _handle_export_all_lp_csv(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Export All LPs to CSV",
        )
        if not path:
            return
        success, message = self.preview_api.export_all_lp_csvs(Path(path))
        title = "Export All LPs to CSV"
        if success:
            QtWidgets.QMessageBox.information(self, title, message)
        else:
            QtWidgets.QMessageBox.warning(self, title, message)

    def _handle_import_lp_csv(self) -> None:
        lp_name = self.preview_api.active_lp_line()
        if not lp_name or lp_name == "center-line":
            QtWidgets.QMessageBox.warning(
                self, "Import LP CSV", "Select a valid LP line to replace."
            )
            return
        suggested = f"{lp_name}.csv"
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Import LP CSV",
            suggested,
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return
        success, message = self.preview_api.import_active_lp_csv(Path(path))
        title = "Import LP CSV"
        if success:
            self._update_lp_records_table(lp_name)
            self.visualization_widget.update()
            self._update_lp_dirty_indicator(lp_name)
            QtWidgets.QMessageBox.information(self, title, message)
        else:
            QtWidgets.QMessageBox.warning(self, title, message)

    def _handle_generate_lp_line(self) -> None:
        lp_name = self.preview_api.active_lp_line()
        if not lp_name or lp_name == "center-line":
            QtWidgets.QMessageBox.warning(
                self, "Generate LP Line", "Select a valid LP line to replace."
            )
            return
        if self.preview_api.trk is None:
            QtWidgets.QMessageBox.warning(
                self, "Generate LP Line", "Load a track before generating an LP line."
            )
            return
        records = self.preview_api.ai_line_records(lp_name)
        default_speed = 100.0
        default_dlat = 0
        current = self._current_lp_selection()
        if current and current[0] == lp_name:
            record = records[current[1]]
            default_speed = record.speed_mph
            default_dlat = int(round(record.dlat))
        elif records:
            default_speed = records[0].speed_mph
            default_dlat = int(round(records[0].dlat))

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Generate LP Line")
        form_layout = QtWidgets.QFormLayout()
        speed_input = QtWidgets.QDoubleSpinBox(dialog)
        speed_input.setRange(0.0, 1000.0)
        speed_input.setDecimals(2)
        speed_input.setSingleStep(1.0)
        speed_input.setValue(default_speed)
        speed_input.setSuffix(" mph")
        dlat_input = QtWidgets.QSpinBox(dialog)
        dlat_input.setRange(-2_147_483_647, 2_147_483_647)
        dlat_input.setSingleStep(500)
        dlat_input.setValue(default_dlat)
        form_layout.addRow("Speed", speed_input)
        form_layout.addRow("DLAT", dlat_input)
        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(form_layout)
        layout.addWidget(button_box)
        dialog.setLayout(layout)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        success, message = self.preview_api.generate_lp_line(
            lp_name, speed_input.value(), dlat_input.value()
        )
        title = "Generate LP Line"
        if success:
            checkbox = self._lp_checkboxes.get(lp_name)
            if checkbox is not None and not checkbox.isChecked():
                with QtCore.QSignalBlocker(checkbox):
                    checkbox.setChecked(True)
                selected = set(self.preview_api.visible_lp_files())
                selected.add(lp_name)
                self.controller.set_visible_lp_files(sorted(selected))
            self._update_lp_records_table(lp_name)
            self.visualization_widget.update()
            self._update_lp_dirty_indicator(lp_name)
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
        self._save_all_lp_button.setEnabled(
            self.preview_api.trk is not None
            and bool(self.preview_api.available_lp_files())
        )

    def _update_import_lp_csv_button_state(self, lp_name: str | None = None) -> None:
        name = lp_name or self.preview_api.active_lp_line()
        enabled = (
            bool(name)
            and name != "center-line"
            and self.preview_api.trk is not None
        )
        self._import_lp_csv_button.setEnabled(enabled)

    def _update_export_lp_csv_button_state(self, lp_name: str | None = None) -> None:
        name = lp_name or self.preview_api.active_lp_line()
        enabled = (
            bool(name)
            and name != "center-line"
            and bool(self.preview_api.ai_line_records(name))
        )
        self._export_lp_csv_button.setEnabled(enabled)

    def _update_export_all_lp_csv_button_state(self) -> None:
        enabled = bool(self.preview_api.available_lp_files()) and bool(
            self.preview_api.trk
        )
        self._export_all_lp_csv_button.setEnabled(enabled)

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

    def _update_generate_lp_button_state(self, lp_name: str | None = None) -> None:
        name = lp_name or self.preview_api.active_lp_line()
        enabled = (
            bool(name)
            and name != "center-line"
            and self.preview_api.trk is not None
        )
        self._generate_lp_button.setEnabled(enabled)

    def _handle_tv_mode_selection_changed(self, mode_count: int) -> None:
        self.preview_api.set_tv_mode_count(mode_count)
        self._mark_camera_dirty()

    def _handle_tv_mode_view_changed(self, index: int) -> None:
        self.preview_api.set_current_tv_mode_index(index)

    def _handle_show_current_tv_only_changed(self, enabled: bool) -> None:
        self.preview_api.set_show_cameras_current_tv_only(enabled)

    def _handle_recalculate_lateral_speed(self) -> None:
        lp_name = self.preview_api.active_lp_line()
        if not lp_name or lp_name == "center-line":
            return
        if self._lp_records_model.recalculate_lateral_speeds():
            self._handle_lp_data_changed(lp_name)
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
        self._mark_camera_dirty()

    def _handle_camera_position_updated(
        self, index: int, x: Optional[int], y: Optional[int], z: Optional[int]
    ) -> None:
        self.preview_api.update_camera_position(index, x, y, z)
        self._mark_camera_dirty()

    def _handle_type6_parameters_changed(self) -> None:
        self.visualization_widget.update()
        self._mark_camera_dirty()

    def _handle_type7_parameters_changed(self) -> None:
        self.visualization_widget.update()
        self._mark_camera_dirty()

    def _handle_camera_assignment_changed(self) -> None:
        self._mark_camera_dirty()
