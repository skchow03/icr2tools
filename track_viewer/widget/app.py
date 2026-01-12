"""Simple Qt application shell for the standalone track viewer."""
from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import List, Optional, Sequence

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.cam.helpers import CameraPosition
from icr2_core.lp.loader import papy_speed_to_mph
from icr2_core.trk.trk_utils import ground_type_name
from track_viewer.controllers.camera_actions import CameraActions
from track_viewer.model.camera_models import CameraViewListing
from track_viewer.sidebar.coordinate_sidebar import CoordinateSidebar
from track_viewer.sidebar.coordinate_sidebar_vm import CoordinateSidebarViewModel
from track_viewer.services.io_service import TrackIOService, TrackTxtMetadata, TrackTxtResult
from track_viewer.sidebar.pit_editor import PitParametersEditor
from track_viewer.model.pit_models import (
    PIT_DLAT_LINE_COLORS,
    PIT_DLONG_LINE_COLORS,
    PitParameters,
)
from track_viewer.ai.ai_line_service import LpPoint
from track_viewer.widget.track_preview_widget import TrackPreviewWidget
from track_viewer.common.version import __version__
from track_viewer.controllers.window_controller import WindowController
from track_viewer import config as viewer_config
from track_viewer.common.preview_constants import LP_COLORS, LP_FILE_NAMES


class TrackViewerApp(QtWidgets.QApplication):
    """Thin wrapper that stores shared state for the viewer."""

    def __init__(self, argv: List[str], main_script_path: Optional[Path] = None):
        surface_format = QtGui.QSurfaceFormat()
        surface_format.setSamples(4)
        QtGui.QSurfaceFormat.setDefaultFormat(surface_format)
        super().__init__(argv)
        self.setQuitOnLastWindowClosed(True)

        self._main_script_path = main_script_path
        self.installation_path = viewer_config.load_installation_path(
            self._main_script_path
        )
        self.tracks: List[str] = []
        self.window: Optional["TrackViewerWindow"] = None

    def load_lp_colors(self) -> dict[str, str]:
        return viewer_config.load_lp_colors(self._main_script_path)

    def save_lp_colors(self, lp_colors: dict[str, str]) -> None:
        viewer_config.save_lp_colors(lp_colors, self._main_script_path)

    def load_pit_colors(self) -> tuple[dict[int, str], dict[int, str]]:
        return viewer_config.load_pit_colors(self._main_script_path)

    def save_pit_colors(
        self, dlong_colors: dict[int, str], dlat_colors: dict[int, str]
    ) -> None:
        viewer_config.save_pit_colors(dlong_colors, dlat_colors, self._main_script_path)

    def set_installation_path(self, path: Optional[Path]) -> None:
        self.installation_path = path
        if path is None:
            return
        viewer_config.save_installation_path(path, self._main_script_path)

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


class TrkSectionsModel(QtCore.QAbstractTableModel):
    """Table model for TRK section geometry."""

    _BASE_HEADERS = [
        "Section",
        "Type",
        "Start DLONG",
        "Length",
    ]

    def __init__(self, parent: QtCore.QObject | None = None) -> None:
        super().__init__(parent)
        self._sections: list[object] = []
        self._headers: list[str] = list(self._BASE_HEADERS)
        self._max_bounds = 0
        self._max_surfaces = 0

    def rowCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._sections)

    def columnCount(self, parent: QtCore.QModelIndex = QtCore.QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._headers)

    def data(
        self, index: QtCore.QModelIndex, role: int = QtCore.Qt.DisplayRole
    ) -> object | None:
        if not index.isValid():
            return None
        row = index.row()
        if row < 0 or row >= len(self._sections):
            return None
        section = self._sections[row]
        column = index.column()
        if role == QtCore.Qt.TextAlignmentRole:
            if column == 1:
                return QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter
            return QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
        if role != QtCore.Qt.DisplayRole:
            return None
        if column == 0:
            return str(row)
        if column == 1:
            if section.type == 1:
                return "Straight"
            if section.type == 2:
                return "Curve"
            return f"Type {section.type}"
        if column == 2:
            return str(section.start_dlong)
        if column == 3:
            return str(section.length)
        boundary_base = len(self._BASE_HEADERS)
        surface_base = boundary_base + self._max_bounds * 2
        if boundary_base <= column < surface_base:
            bound_index = (column - boundary_base) // 2
            if bound_index >= len(section.bound_dlat_start):
                return ""
            if (column - boundary_base) % 2 == 0:
                return str(section.bound_dlat_start[bound_index])
            return str(section.bound_dlat_end[bound_index])
        if column >= surface_base:
            surface_index = (column - surface_base) // 3
            if surface_index >= len(section.ground_dlat_start):
                return ""
            offset = (column - surface_base) % 3
            if offset == 0:
                return str(section.ground_dlat_start[surface_index])
            if offset == 1:
                return str(section.ground_dlat_end[surface_index])
            ground_type = section.ground_type[surface_index]
            name = ground_type_name(ground_type)
            return name or str(ground_type)
        return None

    def flags(self, index: QtCore.QModelIndex) -> QtCore.Qt.ItemFlags:
        if not index.isValid():
            return QtCore.Qt.NoItemFlags
        return QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable

    def headerData(
        self,
        section: int,
        orientation: QtCore.Qt.Orientation,
        role: int = QtCore.Qt.DisplayRole,
    ) -> object | None:
        if role != QtCore.Qt.DisplayRole:
            return None
        if orientation == QtCore.Qt.Horizontal:
            if 0 <= section < len(self._headers):
                return self._headers[section]
            return None
        return str(section)

    def set_sections(self, sections: list[object]) -> None:
        self.beginResetModel()
        self._sections = list(sections)
        self._max_bounds = max(
            (len(sect.bound_dlat_start) for sect in sections), default=0
        )
        self._max_surfaces = max(
            (len(sect.ground_dlat_start) for sect in sections), default=0
        )
        self._headers = list(self._BASE_HEADERS)
        for bound_index in range(self._max_bounds):
            label = bound_index + 1
            self._headers.append(f"Boundary {label} Start DLAT")
            self._headers.append(f"Boundary {label} End DLAT")
        for surface_index in range(self._max_surfaces):
            label = surface_index + 1
            self._headers.append(f"Surface {label} Start DLAT")
            self._headers.append(f"Surface {label} End DLAT")
            self._headers.append(f"Surface {label} Type")
        self.endResetModel()


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

        self._lp_list = QtWidgets.QTableWidget(0, 3)
        self._lp_list.setHorizontalHeaderLabels(["LP name", "Select", "Visible"])
        self._lp_list.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self._lp_list.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._lp_list.setAlternatingRowColors(True)
        self._lp_list.setShowGrid(False)
        self._lp_list.verticalHeader().setVisible(False)
        self._lp_list.verticalHeader().setDefaultSectionSize(28)
        header = self._lp_list.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self._lp_button_group = QtWidgets.QButtonGroup(self)
        self._lp_button_group.setExclusive(True)
        self._lp_button_group.buttonClicked.connect(self._handle_lp_radio_clicked)
        self._lp_checkboxes: dict[str, QtWidgets.QCheckBox] = {}
        self._lp_name_cells: dict[str, QtWidgets.QWidget] = {}
        self._lp_name_labels: dict[str, QtWidgets.QLabel] = {}
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
        self.preview_api.set_lp_dlat_step(self._lp_dlat_step.value())
        self._apply_saved_lp_colors()
        self._apply_saved_pit_colors()
        self._lp_shortcut_active = False
        self._sidebar_vm = CoordinateSidebarViewModel()
        self._sidebar = CoordinateSidebar(self._sidebar_vm)
        self._pit_lane_count_combo = QtWidgets.QComboBox()
        self._pit_lane_count_combo.addItem("1 pit lane", 1)
        self._pit_lane_count_combo.addItem("2 pit lanes", 2)
        self._pit_lane_count_combo.setCurrentIndex(0)
        self._pit_lane_count_combo.currentIndexChanged.connect(
            self._handle_pit_lane_count_changed
        )
        self._pit_tabs = QtWidgets.QTabWidget()
        self._pit_editors = [PitParametersEditor(), PitParametersEditor()]
        self._pit_tabs.addTab(self._pit_editors[0], "PIT")
        self._pit_tabs.currentChanged.connect(self._handle_pit_tab_changed)
        self._pit_status_label = QtWidgets.QLabel(
            "Select a track to edit pit parameters."
        )
        self._pit_status_label.setWordWrap(True)
        self._track_txt_status_label = QtWidgets.QLabel(
            "Select a track to edit track.txt parameters."
        )
        self._track_txt_status_label.setWordWrap(True)
        self._track_txt_tire_status_label = QtWidgets.QLabel(
            "Select a track to edit track.txt parameters."
        )
        self._track_txt_tire_status_label.setWordWrap(True)
        self._track_txt_weather_status_label = QtWidgets.QLabel(
            "Select a track to edit track.txt parameters."
        )
        self._track_txt_weather_status_label.setWordWrap(True)
        self._trk_status_label = QtWidgets.QLabel(
            "Select a track to view TRK sections."
        )
        self._trk_status_label.setWordWrap(True)
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
        self._wind_dir_field = self._create_int_field("–")
        self._wind_var_field = self._create_int_field("–")
        self._wind_speed_field = self._create_int_field("–")
        self._wind_speed_var_field = self._create_int_field("–")
        self._wind_heading_adjust_field = self._create_int_field("–")
        self._wind2_dir_field = self._create_int_field("–")
        self._wind2_var_field = self._create_int_field("–")
        self._wind2_speed_field = self._create_int_field("–")
        self._wind2_speed_var_field = self._create_int_field("–")
        self._wind2_heading_adjust_field = self._create_int_field("–")
        self._rain_level_field = self._create_int_field("–")
        self._rain_variation_field = self._create_int_field("–")
        self._blap_field = self._create_int_field("–")
        self._rels_field = self._create_int_field("–")
        self._theat_fields = [self._create_int_field("–") for _ in range(8)]
        self._tcff_fields = [self._create_int_field("–") for _ in range(8)]
        self._tcfr_fields = [self._create_int_field("–") for _ in range(8)]
        self._tires_fields = [self._create_int_field("–") for _ in range(7)]
        self._tire2_fields = [self._create_int_field("–") for _ in range(7)]
        self._sctns_fields = [self._create_int_field("–") for _ in range(3)]
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
        for index, editor in enumerate(self._pit_editors):
            editor.parametersChanged.connect(
                partial(self._handle_pit_params_changed, index)
            )
            editor.pitVisibilityChanged.connect(
                partial(self._handle_pit_visibility_changed, index)
            )
            editor.pitStallCenterVisibilityChanged.connect(
                partial(self._handle_pit_stall_center_visibility_changed, index)
            )
            editor.pitWallVisibilityChanged.connect(
                partial(self._handle_pit_wall_visibility_changed, index)
            )
            editor.pitStallCarsVisibilityChanged.connect(
                partial(self._handle_pit_stall_cars_visibility_changed, index)
            )
        self._pit_save_button = QtWidgets.QPushButton("Save PIT")
        self._pit_save_button.setEnabled(False)
        self._pit_save_button.clicked.connect(self._handle_save_pit_params)
        self._track_txt_save_button = QtWidgets.QPushButton("Save Track TXT")
        self._track_txt_save_button.setEnabled(False)
        self._track_txt_save_button.clicked.connect(self._handle_save_track_txt)
        self._track_txt_tire_save_button = QtWidgets.QPushButton(
            "Save Track TXT"
        )
        self._track_txt_tire_save_button.setEnabled(False)
        self._track_txt_tire_save_button.clicked.connect(
            self._handle_save_track_txt
        )
        self._track_txt_weather_save_button = QtWidgets.QPushButton(
            "Save Track TXT"
        )
        self._track_txt_weather_save_button.setEnabled(False)
        self._track_txt_weather_save_button.clicked.connect(
            self._handle_save_track_txt
        )
        self._add_type6_camera_button = QtWidgets.QPushButton("Add Panning Camera")
        self._add_type2_camera_button = QtWidgets.QPushButton(
            "Add Alternate Panning Camera"
        )
        self._add_type7_camera_button = QtWidgets.QPushButton("Add Fixed Camera")
        self._boundary_button = QtWidgets.QPushButton("Hide Boundaries")
        self._boundary_button.setCheckable(True)
        self._boundary_button.setChecked(True)
        self._boundary_button.toggled.connect(self._toggle_boundaries)
        self._toggle_boundaries(self._boundary_button.isChecked())
        self._section_divider_button = QtWidgets.QPushButton("Show Section Dividers")
        self._section_divider_button.setCheckable(True)
        self._section_divider_button.toggled.connect(self._toggle_section_dividers)
        self._toggle_section_dividers(self._section_divider_button.isChecked())

        self._weather_compass_group = QtWidgets.QButtonGroup(self)
        self._weather_compass_wind_button = QtWidgets.QRadioButton("WIND")
        self._weather_compass_wind2_button = QtWidgets.QRadioButton("WIND2")
        self._weather_compass_group.addButton(self._weather_compass_wind_button)
        self._weather_compass_group.addButton(self._weather_compass_wind2_button)
        self._weather_compass_wind_button.setChecked(True)
        self._weather_compass_wind_button.toggled.connect(
            lambda checked: self._handle_weather_compass_source_changed(
                "wind", checked
            )
        )
        self._weather_compass_wind2_button.toggled.connect(
            lambda checked: self._handle_weather_compass_source_changed(
                "wind2", checked
            )
        )
        self._wind_heading_adjust_field.textChanged.connect(
            lambda text: self._handle_weather_heading_adjust_changed("wind", text)
        )
        self._wind2_heading_adjust_field.textChanged.connect(
            lambda text: self._handle_weather_heading_adjust_changed("wind2", text)
        )
        self._wind_dir_field.textChanged.connect(
            lambda text: self._handle_weather_direction_changed("wind", text)
        )
        self._wind_var_field.textChanged.connect(
            lambda text: self._handle_weather_variation_changed("wind", text)
        )
        self._wind2_dir_field.textChanged.connect(
            lambda text: self._handle_weather_direction_changed("wind2", text)
        )
        self._wind2_var_field.textChanged.connect(
            lambda text: self._handle_weather_variation_changed("wind2", text)
        )

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
        self._generate_lp_button = QtWidgets.QPushButton("Generate LP Line")
        self._generate_lp_button.setEnabled(False)

        self._trk_gaps_button = QtWidgets.QPushButton("Run TRK Gaps")
        self._trk_gaps_button.setEnabled(False)

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
        left_layout.addWidget(self._generate_lp_button)
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
        self.visualization_widget.weatherCompassHeadingAdjustChanged.connect(
            self._handle_weather_compass_heading_adjust_changed
        )
        self.visualization_widget.weatherCompassWindDirectionChanged.connect(
            self._handle_weather_compass_wind_direction_changed
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
        self._sidebar.tvModeViewChanged.connect(
            self._handle_tv_mode_view_changed
        )
        self._sidebar.showCurrentTvOnlyChanged.connect(
            self._handle_show_current_tv_only_changed
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
        self._add_type2_camera_button.clicked.connect(
            self.camera_actions.add_type2_camera
        )
        self._add_type7_camera_button.clicked.connect(
            self.camera_actions.add_type7_camera
        )
        self._save_cameras_button.clicked.connect(self.camera_actions.save_cameras)
        self._save_lp_button.clicked.connect(self._handle_save_lp_line)
        self._export_lp_csv_button.clicked.connect(self._handle_export_lp_csv)
        self._generate_lp_button.clicked.connect(self._handle_generate_lp_line)
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
        controls.addWidget(self._flag_draw_button)
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
        view_settings_layout.addWidget(self._zoom_points_button)
        view_settings_widget = QtWidgets.QWidget()
        view_settings_widget.setLayout(view_settings_layout)
        right_sidebar_layout.addWidget(view_settings_widget)
        right_sidebar_layout.addWidget(self._sidebar)
        right_sidebar_layout.addWidget(self._sidebar.type7_details)
        right_sidebar_layout.addWidget(self._sidebar.type6_editor)
        type_button_layout = QtWidgets.QHBoxLayout()
        type_button_layout.addWidget(self._add_type6_camera_button)
        type_button_layout.addWidget(self._add_type2_camera_button)
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
        pit_lane_layout = QtWidgets.QHBoxLayout()
        pit_lane_layout.addWidget(QtWidgets.QLabel("Pit lanes"))
        pit_lane_layout.addWidget(self._pit_lane_count_combo)
        pit_lane_layout.addStretch(1)
        pit_layout.addLayout(pit_lane_layout)
        pit_layout.addWidget(self._pit_tabs)
        pit_layout.addStretch(1)
        pit_layout.addWidget(self._pit_save_button)
        pit_sidebar.setLayout(pit_layout)
        pit_scroll = QtWidgets.QScrollArea()
        pit_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        pit_scroll.setWidgetResizable(True)
        pit_scroll.setWidget(pit_sidebar)
        self._pit_tab = pit_scroll

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
        track_name_layout = QtWidgets.QHBoxLayout()
        track_name_layout.setContentsMargins(0, 0, 0, 0)
        track_name_layout.addWidget(QtWidgets.QLabel("Track name (TNAME)"))
        track_name_layout.addWidget(self._track_name_field)
        track_name_layout.addWidget(QtWidgets.QLabel("Short name (SNAME)"))
        track_name_layout.addWidget(self._track_short_name_field)
        track_name_widget = QtWidgets.QWidget()
        track_name_widget.setLayout(track_name_layout)
        track_txt_form.addRow(track_name_widget)
        track_location_layout = QtWidgets.QHBoxLayout()
        track_location_layout.setContentsMargins(0, 0, 0, 0)
        track_location_layout.addWidget(QtWidgets.QLabel("City (CITYN)"))
        track_location_layout.addWidget(self._track_city_field)
        track_location_layout.addWidget(QtWidgets.QLabel("Country (COUNT)"))
        track_location_layout.addWidget(self._track_country_field)
        track_location_widget = QtWidgets.QWidget()
        track_location_widget.setLayout(track_location_layout)
        track_txt_form.addRow(track_location_widget)
        spdwy_layout = QtWidgets.QHBoxLayout()
        spdwy_layout.setContentsMargins(0, 0, 0, 0)
        spdwy_layout.addWidget(QtWidgets.QLabel("Start"))
        spdwy_layout.addWidget(self._track_pit_window_start_field)
        spdwy_layout.addWidget(QtWidgets.QLabel("End"))
        spdwy_layout.addWidget(self._track_pit_window_end_field)
        spdwy_widget = QtWidgets.QWidget()
        spdwy_widget.setLayout(spdwy_layout)
        track_txt_form.addRow("Pit window (SPDWY)", spdwy_widget)
        track_length_layout = QtWidgets.QHBoxLayout()
        track_length_layout.setContentsMargins(0, 0, 0, 0)
        track_length_layout.addWidget(QtWidgets.QLabel("Length (LENGT)"))
        track_length_layout.addWidget(self._track_length_field)
        track_length_layout.addWidget(QtWidgets.QLabel("Laps (LAPS)"))
        track_length_layout.addWidget(self._track_laps_field)
        track_length_widget = QtWidgets.QWidget()
        track_length_widget.setLayout(track_length_layout)
        track_txt_form.addRow(track_length_widget)
        track_txt_form.addRow("Full name (FNAME)", self._track_full_name_field)
        cars_layout = QtWidgets.QHBoxLayout()
        cars_layout.setContentsMargins(0, 0, 0, 0)
        cars_layout.addWidget(QtWidgets.QLabel("Unknown"))
        cars_layout.addWidget(self._cars_min_field)
        cars_layout.addWidget(QtWidgets.QLabel("Cars"))
        cars_layout.addWidget(self._cars_max_field)
        cars_widget = QtWidgets.QWidget()
        cars_widget.setLayout(cars_layout)
        track_txt_form.addRow("Cars (CARS)", cars_widget)
        track_txt_form.addRow("Pole lap (BLAP)", self._blap_field)
        track_txt_form.addRow("Relative strength (RELS)", self._rels_field)
        track_txt_form.addRow(
            "Sections (SCTNS)", self._build_number_row(self._sctns_fields)
        )
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
        track_txt_scroll = QtWidgets.QScrollArea()
        track_txt_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        track_txt_scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarAlwaysOff
        )
        track_txt_scroll.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarAsNeeded
        )
        track_txt_scroll.setWidgetResizable(True)
        track_txt_scroll.setWidget(track_txt_sidebar)

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

        tire_txt_sidebar = QtWidgets.QFrame()
        tire_txt_sidebar.setFrameShape(QtWidgets.QFrame.StyledPanel)
        tire_txt_layout = QtWidgets.QVBoxLayout()
        tire_txt_layout.setSpacing(8)
        tire_txt_title = QtWidgets.QLabel("Tire TXT parameters")
        tire_txt_title.setStyleSheet("font-weight: bold")
        tire_txt_layout.addWidget(tire_txt_title)
        tire_txt_layout.addWidget(self._track_txt_tire_status_label)
        tire_txt_form = QtWidgets.QFormLayout()
        tire_txt_form.setLabelAlignment(QtCore.Qt.AlignLeft)
        tire_txt_form.setFormAlignment(QtCore.Qt.AlignTop)
        tire_txt_form.addRow(QtWidgets.QLabel("Tire heat (THEAT)"))
        tire_txt_form.addRow(self._build_compound_grid(self._theat_fields))
        tire_txt_form.addRow(
            QtWidgets.QLabel("Tire compound friction front (TCFF)")
        )
        tire_txt_form.addRow(self._build_compound_grid(self._tcff_fields))
        tire_txt_form.addRow(
            QtWidgets.QLabel("Tire compound friction rear (TCFR)")
        )
        tire_txt_form.addRow(self._build_compound_grid(self._tcfr_fields))
        tire_txt_form.addRow(QtWidgets.QLabel("Goodyear tires (TIRES)"))
        tire_txt_form.addRow(
            self._build_number_row(self._tires_fields, show_labels=False)
        )
        tire_txt_form.addRow(QtWidgets.QLabel("Firestone tires (TIRE2)"))
        tire_txt_form.addRow(
            self._build_number_row(self._tire2_fields, show_labels=False)
        )
        tire_txt_layout.addLayout(tire_txt_form)
        tire_txt_layout.addStretch(1)
        tire_txt_layout.addWidget(self._track_txt_tire_save_button)
        tire_txt_sidebar.setLayout(tire_txt_layout)
        tire_txt_scroll = QtWidgets.QScrollArea()
        tire_txt_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        tire_txt_scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarAlwaysOff
        )
        tire_txt_scroll.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        tire_txt_scroll.setWidgetResizable(True)
        tire_txt_scroll.setWidget(tire_txt_sidebar)

        weather_txt_sidebar = QtWidgets.QFrame()
        weather_txt_sidebar.setFrameShape(QtWidgets.QFrame.StyledPanel)
        weather_txt_layout = QtWidgets.QVBoxLayout()
        weather_txt_layout.setSpacing(8)
        weather_txt_title = QtWidgets.QLabel("Weather TXT parameters")
        weather_txt_title.setStyleSheet("font-weight: bold")
        weather_txt_layout.addWidget(weather_txt_title)
        weather_txt_layout.addWidget(self._track_txt_weather_status_label)
        compass_source_layout = QtWidgets.QHBoxLayout()
        compass_source_layout.setContentsMargins(0, 0, 0, 0)
        compass_source_layout.addWidget(QtWidgets.QLabel("Compass source"))
        compass_source_layout.addWidget(self._weather_compass_wind_button)
        compass_source_layout.addWidget(self._weather_compass_wind2_button)
        compass_source_layout.addStretch(1)
        compass_source_widget = QtWidgets.QWidget()
        compass_source_widget.setLayout(compass_source_layout)
        weather_txt_layout.addWidget(compass_source_widget)
        weather_txt_form = QtWidgets.QFormLayout()
        weather_txt_form.setLabelAlignment(QtCore.Qt.AlignLeft)
        weather_txt_form.setFormAlignment(QtCore.Qt.AlignTop)
        temp_layout = QtWidgets.QHBoxLayout()
        temp_layout.setContentsMargins(0, 0, 0, 0)
        temp_layout.addWidget(QtWidgets.QLabel("Average"))
        temp_layout.addWidget(self._temp_avg_field)
        temp_layout.addWidget(QtWidgets.QLabel("Deviation"))
        temp_layout.addWidget(self._temp_dev_field)
        temp_widget = QtWidgets.QWidget()
        temp_widget.setLayout(temp_layout)
        weather_txt_form.addRow("Temperature (TEMP)", temp_widget)
        temp2_layout = QtWidgets.QHBoxLayout()
        temp2_layout.setContentsMargins(0, 0, 0, 0)
        temp2_layout.addWidget(QtWidgets.QLabel("Average"))
        temp2_layout.addWidget(self._temp2_avg_field)
        temp2_layout.addWidget(QtWidgets.QLabel("Deviation"))
        temp2_layout.addWidget(self._temp2_dev_field)
        temp2_widget = QtWidgets.QWidget()
        temp2_widget.setLayout(temp2_layout)
        weather_txt_form.addRow("Temperature 2 (TEMP2)", temp2_widget)
        wind_layout = QtWidgets.QGridLayout()
        wind_layout.setContentsMargins(0, 0, 0, 0)
        wind_layout.setHorizontalSpacing(6)
        wind_layout.addWidget(QtWidgets.QLabel("Direction"), 0, 0)
        wind_layout.addWidget(self._wind_dir_field, 0, 1)
        wind_layout.addWidget(QtWidgets.QLabel("Variation"), 0, 2)
        wind_layout.addWidget(self._wind_var_field, 0, 3)
        wind_layout.addWidget(QtWidgets.QLabel("Speed (0.1 mph)"), 1, 0)
        wind_layout.addWidget(self._wind_speed_field, 1, 1)
        wind_layout.addWidget(QtWidgets.QLabel("Speed variation"), 1, 2)
        wind_layout.addWidget(self._wind_speed_var_field, 1, 3)
        wind_layout.addWidget(QtWidgets.QLabel("Heading adjust"), 2, 0)
        wind_layout.addWidget(self._wind_heading_adjust_field, 2, 1)
        wind_widget = QtWidgets.QWidget()
        wind_widget.setLayout(wind_layout)
        weather_txt_form.addRow(QtWidgets.QLabel("Wind (WIND)"))
        weather_txt_form.addRow(wind_widget)
        wind2_layout = QtWidgets.QGridLayout()
        wind2_layout.setContentsMargins(0, 0, 0, 0)
        wind2_layout.setHorizontalSpacing(6)
        wind2_layout.addWidget(QtWidgets.QLabel("Direction"), 0, 0)
        wind2_layout.addWidget(self._wind2_dir_field, 0, 1)
        wind2_layout.addWidget(QtWidgets.QLabel("Variation"), 0, 2)
        wind2_layout.addWidget(self._wind2_var_field, 0, 3)
        wind2_layout.addWidget(QtWidgets.QLabel("Speed (0.1 mph)"), 1, 0)
        wind2_layout.addWidget(self._wind2_speed_field, 1, 1)
        wind2_layout.addWidget(QtWidgets.QLabel("Speed variation"), 1, 2)
        wind2_layout.addWidget(self._wind2_speed_var_field, 1, 3)
        wind2_layout.addWidget(QtWidgets.QLabel("Heading adjust"), 2, 0)
        wind2_layout.addWidget(self._wind2_heading_adjust_field, 2, 1)
        wind2_widget = QtWidgets.QWidget()
        wind2_widget.setLayout(wind2_layout)
        weather_txt_form.addRow(QtWidgets.QLabel("Wind 2 (WIND2)"))
        weather_txt_form.addRow(wind2_widget)
        rain_layout = QtWidgets.QHBoxLayout()
        rain_layout.setContentsMargins(0, 0, 0, 0)
        rain_layout.addWidget(QtWidgets.QLabel("Parameter 1"))
        rain_layout.addWidget(self._rain_level_field)
        rain_layout.addWidget(QtWidgets.QLabel("Parameter 2"))
        rain_layout.addWidget(self._rain_variation_field)
        rain_widget = QtWidgets.QWidget()
        rain_widget.setLayout(rain_layout)
        weather_txt_form.addRow(QtWidgets.QLabel("Rain (RAIN)"))
        weather_txt_form.addRow(rain_widget)
        weather_txt_layout.addLayout(weather_txt_form)
        weather_txt_layout.addStretch(1)
        weather_txt_layout.addWidget(self._track_txt_weather_save_button)
        weather_txt_sidebar.setLayout(weather_txt_layout)
        weather_txt_scroll = QtWidgets.QScrollArea()
        weather_txt_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        weather_txt_scroll.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarAlwaysOff
        )
        weather_txt_scroll.setVerticalScrollBarPolicy(
            QtCore.Qt.ScrollBarAsNeeded
        )
        weather_txt_scroll.setWidgetResizable(True)
        weather_txt_scroll.setWidget(weather_txt_sidebar)

        tabs = QtWidgets.QTabWidget()
        self._tabs = tabs
        tabs.addTab(
            lp_sidebar,
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
            pit_scroll,
            self.style().standardIcon(QtWidgets.QStyle.SP_DialogApplyButton),
            "Pit",
        )
        tabs.addTab(
            track_txt_scroll,
            self.style().standardIcon(QtWidgets.QStyle.SP_DirHomeIcon),
            "Track",
        )
        tabs.addTab(
            trk_scroll,
            self.style().standardIcon(QtWidgets.QStyle.SP_FileIcon),
            "TRK",
        )
        self._weather_tab = weather_txt_scroll
        tabs.addTab(
            weather_txt_scroll,
            self.style().standardIcon(QtWidgets.QStyle.SP_BrowserReload),
            "Weather",
        )
        tabs.addTab(
            tire_txt_scroll,
            self.style().standardIcon(QtWidgets.QStyle.SP_DriveHDIcon),
            "Tires",
        )

        body = QtWidgets.QSplitter()
        body.setOrientation(QtCore.Qt.Horizontal)
        tabs.currentChanged.connect(self._handle_tab_changed)
        body.addWidget(tabs)
        body.addWidget(self.visualization_widget)
        body.setSizes([260, 640])
        layout.addWidget(body, stretch=1)

        wrapper = QtWidgets.QWidget()
        wrapper.setLayout(layout)
        self.setCentralWidget(wrapper)

        self._handle_tab_changed(self._tabs.currentIndex())
        QtWidgets.QApplication.instance().installEventFilter(self)

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

    def _set_track_txt_field(
        self, field: QtWidgets.QLineEdit, value: str | None
    ) -> None:
        if value is not None:
            field.setText(value)
        else:
            field.clear()

    def _set_track_txt_sequence(
        self, fields: Sequence[QtWidgets.QLineEdit], values: Sequence[int] | None
    ) -> None:
        for index, field in enumerate(fields):
            if values is not None and index < len(values):
                field.setText(str(values[index]))
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
            self._wind_dir_field,
            self._wind_var_field,
            self._wind_speed_field,
            self._wind_speed_var_field,
            self._wind_heading_adjust_field,
            self._wind2_dir_field,
            self._wind2_var_field,
            self._wind2_speed_field,
            self._wind2_speed_var_field,
            self._wind2_heading_adjust_field,
            self._rain_level_field,
            self._rain_variation_field,
            self._blap_field,
            self._rels_field,
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
        for field in (
            *self._theat_fields,
            *self._tcff_fields,
            *self._tcfr_fields,
            *self._tires_fields,
            *self._tire2_fields,
            *self._sctns_fields,
        ):
            field.clear()
        self._set_qual_mode(None)
        self._set_track_type(None)
        self._sync_weather_compass_from_fields()

    def _update_track_txt_fields(self, result: TrackTxtResult) -> None:
        if not result.exists:
            status_text = f"No {result.txt_path.name} found."
        else:
            status_text = f"Loaded {result.txt_path.name}."
        self._track_txt_status_label.setText(status_text)
        self._track_txt_tire_status_label.setText(status_text)
        self._track_txt_weather_status_label.setText(status_text)
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
        wind_values = (
            metadata.wind_dir,
            metadata.wind_var,
            metadata.wind_speed,
            metadata.wind_speed_var,
            metadata.wind_heading_adjust,
        )
        wind_text = [
            str(value) if value is not None else None for value in wind_values
        ]
        self._set_track_txt_field(self._wind_dir_field, wind_text[0])
        self._set_track_txt_field(self._wind_var_field, wind_text[1])
        self._set_track_txt_field(self._wind_speed_field, wind_text[2])
        self._set_track_txt_field(self._wind_speed_var_field, wind_text[3])
        self._set_track_txt_field(self._wind_heading_adjust_field, wind_text[4])
        wind2_values = (
            metadata.wind2_dir,
            metadata.wind2_var,
            metadata.wind2_speed,
            metadata.wind2_speed_var,
            metadata.wind2_heading_adjust,
        )
        wind2_text = [
            str(value) if value is not None else None for value in wind2_values
        ]
        self._set_track_txt_field(self._wind2_dir_field, wind2_text[0])
        self._set_track_txt_field(self._wind2_var_field, wind2_text[1])
        self._set_track_txt_field(self._wind2_speed_field, wind2_text[2])
        self._set_track_txt_field(self._wind2_speed_var_field, wind2_text[3])
        self._set_track_txt_field(
            self._wind2_heading_adjust_field, wind2_text[4]
        )
        rain_level = (
            str(metadata.rain_level) if metadata.rain_level is not None else None
        )
        rain_variation = (
            str(metadata.rain_variation)
            if metadata.rain_variation is not None
            else None
        )
        self._set_track_txt_field(self._rain_level_field, rain_level)
        self._set_track_txt_field(self._rain_variation_field, rain_variation)
        blap = str(metadata.blap) if metadata.blap is not None else None
        self._set_track_txt_field(self._blap_field, blap)
        rels = str(metadata.rels) if metadata.rels is not None else None
        self._set_track_txt_field(self._rels_field, rels)
        self._set_track_txt_sequence(self._theat_fields, metadata.theat)
        self._set_track_txt_sequence(self._tcff_fields, metadata.tcff)
        self._set_track_txt_sequence(self._tcfr_fields, metadata.tcfr)
        self._set_track_txt_sequence(self._tires_fields, metadata.tires)
        self._set_track_txt_sequence(self._tire2_fields, metadata.tire2)
        self._set_track_txt_sequence(self._sctns_fields, metadata.sctns)
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
        self._sync_weather_compass_from_fields()

    def _sync_weather_compass_from_fields(self) -> None:
        self.preview_api.set_weather_heading_adjust(
            "wind", self._parse_optional_int(self._wind_heading_adjust_field.text())
        )
        self.preview_api.set_weather_heading_adjust(
            "wind2",
            self._parse_optional_int(self._wind2_heading_adjust_field.text()),
        )
        self.preview_api.set_weather_wind_direction(
            "wind", self._parse_optional_int(self._wind_dir_field.text())
        )
        self.preview_api.set_weather_wind_variation(
            "wind", self._parse_optional_int(self._wind_var_field.text())
        )
        self.preview_api.set_weather_wind_direction(
            "wind2", self._parse_optional_int(self._wind2_dir_field.text())
        )
        self.preview_api.set_weather_wind_variation(
            "wind2", self._parse_optional_int(self._wind2_var_field.text())
        )

    def _handle_weather_compass_source_changed(
        self, source: str, checked: bool
    ) -> None:
        if not checked:
            return
        self.preview_api.set_weather_compass_source(source)
        self.visualization_widget.update()

    def _handle_weather_heading_adjust_changed(
        self, source: str, text: str
    ) -> None:
        self.preview_api.set_weather_heading_adjust(
            source, self._parse_optional_int(text)
        )

    def _handle_weather_direction_changed(self, source: str, text: str) -> None:
        self.preview_api.set_weather_wind_direction(
            source, self._parse_optional_int(text)
        )

    def _handle_weather_variation_changed(self, source: str, text: str) -> None:
        self.preview_api.set_weather_wind_variation(
            source, self._parse_optional_int(text)
        )

    def _handle_weather_compass_heading_adjust_changed(
        self, source: str, value: int
    ) -> None:
        field = (
            self._wind2_heading_adjust_field
            if source == "wind2"
            else self._wind_heading_adjust_field
        )
        with QtCore.QSignalBlocker(field):
            field.setText(str(value))

    def _handle_weather_compass_wind_direction_changed(
        self, source: str, value: int
    ) -> None:
        field = self._wind2_dir_field if source == "wind2" else self._wind_dir_field
        with QtCore.QSignalBlocker(field):
            field.setText(str(value))

    def _handle_tab_changed(self, index: int) -> None:
        widget = self._tabs.widget(index)
        self.preview_api.set_show_weather_compass(widget is self._weather_tab)
        show_cameras = widget is self._camera_tab
        self.preview_api.set_show_cameras(show_cameras)
        self.preview_api.set_camera_selection_enabled(show_cameras)
        self._sync_pit_preview_for_tab()

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

    def _load_track_txt_data(self, folder: Path | None) -> None:
        self._current_track_folder = folder if isinstance(folder, Path) else None
        if self._current_track_folder is None:
            self._track_txt_result = None
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
            return

        result = self._io_service.load_track_txt(self._current_track_folder)
        self._track_txt_result = result
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

    def _load_trk_data(self) -> None:
        trk = self.preview_api.trk
        if trk is None:
            self._trk_status_label.setText("Select a track to view TRK sections.")
            self._trk_sections_model.set_sections([])
            return
        sections = trk.sects or []
        self._trk_status_label.setText(f"Loaded {len(sections)} sections.")
        self._trk_sections_model.set_sections(sections)

    def _handle_save_pit_params(self) -> None:
        if self._current_track_folder is None:
            QtWidgets.QMessageBox.warning(
                self, "Save PIT", "No track is currently loaded."
            )
            return
        pit_params = self._pit_editors[0].parameters()
        if pit_params is None:
            QtWidgets.QMessageBox.warning(
                self, "Save PIT", "No PIT parameters are available to save."
            )
            return
        pit2_params = None
        if self._pit_lane_count() == 2:
            pit2_params = self._pit_editors[1].parameters()
            if pit2_params is None:
                QtWidgets.QMessageBox.warning(
                    self, "Save PIT", "No PIT2 parameters are available to save."
                )
                return
        lines = self._track_txt_result.lines if self._track_txt_result else []
        message = self._io_service.save_track_txt(
            self._current_track_folder, pit_params, pit2_params, None, lines
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
        pit_params = self._pit_editors[0].parameters()
        pit2_params = (
            self._pit_editors[1].parameters()
            if self._pit_lane_count() == 2
            else None
        )
        lines = self._track_txt_result.lines if self._track_txt_result else []
        message = self._io_service.save_track_txt(
            self._current_track_folder,
            pit_params,
            pit2_params,
            metadata,
            lines,
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
        metadata.wind_dir = self._parse_optional_int(self._wind_dir_field.text())
        metadata.wind_var = self._parse_optional_int(self._wind_var_field.text())
        metadata.wind_speed = self._parse_optional_int(self._wind_speed_field.text())
        metadata.wind_speed_var = self._parse_optional_int(
            self._wind_speed_var_field.text()
        )
        metadata.wind_heading_adjust = self._parse_optional_int(
            self._wind_heading_adjust_field.text()
        )
        metadata.wind2_dir = self._parse_optional_int(self._wind2_dir_field.text())
        metadata.wind2_var = self._parse_optional_int(self._wind2_var_field.text())
        metadata.wind2_speed = self._parse_optional_int(self._wind2_speed_field.text())
        metadata.wind2_speed_var = self._parse_optional_int(
            self._wind2_speed_var_field.text()
        )
        metadata.wind2_heading_adjust = self._parse_optional_int(
            self._wind2_heading_adjust_field.text()
        )
        metadata.rain_level = self._parse_optional_int(self._rain_level_field.text())
        metadata.rain_variation = self._parse_optional_int(
            self._rain_variation_field.text()
        )
        metadata.blap = self._parse_optional_int(self._blap_field.text())
        metadata.rels = self._parse_optional_int(self._rels_field.text())
        metadata.theat = self._collect_int_sequence(self._theat_fields)
        metadata.tcff = self._collect_int_sequence(self._tcff_fields)
        metadata.tcfr = self._collect_int_sequence(self._tcfr_fields)
        metadata.tires = self._collect_int_sequence(self._tires_fields)
        metadata.tire2 = self._collect_int_sequence(self._tire2_fields)
        metadata.sctns = self._collect_int_sequence(self._sctns_fields)
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

    def _collect_int_sequence(
        self, fields: Sequence[QtWidgets.QLineEdit]
    ) -> list[int] | None:
        parsed_values: list[int | None] = [
            self._parse_optional_int(field.text()) for field in fields
        ]
        if all(value is None for value in parsed_values):
            return None
        if any(value is None for value in parsed_values):
            return None
        return [value for value in parsed_values if value is not None]

    def _handle_pit_lane_count_changed(self, _index: int) -> None:
        count = self._pit_lane_count()
        self._update_pit_tabs(count)
        if count == 1:
            self._pit_tabs.setCurrentIndex(0)
        self._apply_active_pit_editor_to_preview()

    def _handle_pit_tab_changed(self, _index: int) -> None:
        self._apply_active_pit_editor_to_preview()

    def _handle_pit_params_changed(self, lane_index: int) -> None:
        if lane_index != self._active_pit_lane_index():
            return
        self.preview_api.set_pit_parameters(
            self._pit_editors[lane_index].parameters()
        )

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
            self._lp_name_cells = {}
            self._lp_name_labels = {}
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
        self._update_generate_lp_button_state(active_line)

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

        self._lp_list.setRowHeight(row, name_container.sizeHint().height())
        self._lp_checkboxes[name] = checkbox
        self._lp_name_cells[name] = name_container
        self._lp_name_labels[name] = name_label
        if color:
            self._update_lp_name_color(name, color)

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
        self._update_generate_lp_button_state(lp_name)
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
        self._update_generate_lp_button_state(self.preview_api.active_lp_line())

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

    def _update_generate_lp_button_state(self, lp_name: str | None = None) -> None:
        name = lp_name or self.preview_api.active_lp_line()
        enabled = (
            bool(name)
            and name != "center-line"
            and self.preview_api.trk is not None
        )
        self._generate_lp_button.setEnabled(enabled)

    def _handle_lp_speed_unit_toggled(self, enabled: bool) -> None:
        self._lp_records_model.set_speed_raw_visible(enabled)
        text = "Show Speed MPH" if enabled else "Show Speed 500ths per frame"
        self._lp_speed_unit_button.setText(text)

    def _handle_tv_mode_selection_changed(self, mode_count: int) -> None:
        self.preview_api.set_tv_mode_count(mode_count)

    def _handle_tv_mode_view_changed(self, index: int) -> None:
        self.preview_api.set_current_tv_mode_index(index)

    def _handle_show_current_tv_only_changed(self, enabled: bool) -> None:
        self.preview_api.set_show_cameras_current_tv_only(enabled)

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
