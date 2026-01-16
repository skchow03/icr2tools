"""LP tab builder for the track viewer."""
from __future__ import annotations

from PyQt5 import QtCore, QtWidgets

from track_viewer.model.lp_records_model import LpRecordsModel
from track_viewer.widget.tabs.ai_controls import AiControlsWidget


class LpTabBuilder:
    """Builds the LP tab UI and wires signals."""

    def __init__(self, window: QtWidgets.QWidget) -> None:
        self._window = window

    def build(self) -> QtWidgets.QWidget:
        window = self._window
        window._lp_list = QtWidgets.QTableWidget(0, 4)
        window._lp_list.setHorizontalHeaderLabels(
            ["LP name", "Edit", "Visible", "Unsaved changes"]
        )
        window._lp_list.setSelectionMode(
            QtWidgets.QAbstractItemView.NoSelection
        )
        window._lp_list.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers
        )
        window._lp_list.setAlternatingRowColors(True)
        window._lp_list.setShowGrid(False)
        window._lp_list.verticalHeader().setVisible(False)
        window._lp_list.verticalHeader().setDefaultSectionSize(28)
        header = window._lp_list.horizontalHeader()
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeToContents
        )
        header.setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeToContents
        )
        header.setSectionResizeMode(
            3, QtWidgets.QHeaderView.ResizeToContents
        )
        window._lp_button_group = QtWidgets.QButtonGroup(window)
        window._lp_button_group.setExclusive(True)
        window._lp_button_group.buttonClicked.connect(
            window._handle_lp_radio_clicked
        )
        window._lp_checkboxes = {}
        window._lp_name_cells = {}
        window._lp_name_labels = {}
        window._lp_dirty_labels = {}
        window._lp_records_label = QtWidgets.QLabel("LP records")
        window._lp_records_label.setStyleSheet("font-weight: bold")
        window._recalculate_lateral_speed_button = QtWidgets.QPushButton(
            "Recalculate Lateral Speed"
        )
        window._recalculate_lateral_speed_button.setEnabled(False)
        window._recalculate_lateral_speed_button.clicked.connect(
            window._handle_recalculate_lateral_speed
        )
        window._lp_dlat_step = QtWidgets.QSpinBox()
        window._lp_dlat_step.setRange(1, 1_000_000)
        window._lp_dlat_step.setSingleStep(500)
        window._lp_dlat_step.setValue(6000)
        window._lp_dlat_step.setSuffix(" DLAT")
        window._lp_dlat_step.setToolTip(
            "Arrow key step size for adjusting selected LP DLAT values."
        )
        window._lp_dlat_step.valueChanged.connect(
            window._handle_lp_dlat_step_changed
        )
        window._lp_shortcut_button = QtWidgets.QPushButton(
            "Enable LP arrow-key editing"
        )
        window._lp_shortcut_button.setCheckable(True)
        window._lp_shortcut_button.setEnabled(False)
        window._lp_shortcut_button.toggled.connect(
            window._handle_lp_shortcut_toggled
        )
        window._lp_records_model = LpRecordsModel(
            window.preview_api.lp_session(),
            window.preview_api.apply_lp_changes,
            window,
        )
        window._lp_records_table = QtWidgets.QTableView()
        window._lp_records_table.setModel(window._lp_records_model)
        window._lp_records_table.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
        )
        window._lp_records_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows
        )
        window._lp_records_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        window._lp_records_table.setAlternatingRowColors(True)
        if hasattr(window._lp_records_table, "setUniformRowHeights"):
            window._lp_records_table.setUniformRowHeights(True)
        header = window._lp_records_table.horizontalHeader()

        # Allow multi-line headers
        header.setTextElideMode(QtCore.Qt.ElideNone)
        header.setDefaultAlignment(
            QtCore.Qt.AlignCenter | QtCore.Qt.AlignVCenter
        )
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)

        # Force header to be tall enough for wrapping
        header.setMinimumHeight(56)

        # This is REQUIRED even though it looks unrelated
        window._lp_records_table.setWordWrap(True)

        window._lp_records_table.verticalHeader().setVisible(False)
        selection_model = window._lp_records_table.selectionModel()
        if selection_model is not None:
            selection_model.selectionChanged.connect(
                lambda *_: window._handle_lp_record_selected()
            )
        window._lp_records_model.recordEdited.connect(
            window._handle_lp_record_edited
        )

        lp_sidebar = QtWidgets.QFrame()
        lp_sidebar.setFrameShape(QtWidgets.QFrame.StyledPanel)
        left_layout = QtWidgets.QVBoxLayout()
        left_layout.setSpacing(8)
        lp_label = QtWidgets.QLabel("AI and center lines")
        lp_label.setStyleSheet("font-weight: bold")
        left_layout.addWidget(lp_label)
        lp_list_header = QtWidgets.QLabel(
            "Radio selects the active LP (center line is view-only). "
            "Checkbox toggles visibility."
        )
        lp_list_header.setWordWrap(True)
        left_layout.addWidget(lp_list_header)
        left_layout.addWidget(window._lp_list)
        view_options_label = QtWidgets.QLabel("View Options")
        view_options_label.setStyleSheet("font-weight: bold")
        left_layout.addWidget(view_options_label)
        left_layout.addWidget(AiControlsWidget(window))
        lp_records_header = QtWidgets.QHBoxLayout()
        lp_records_header.addWidget(window._lp_records_label)
        lp_records_header.addStretch(1)
        left_layout.addLayout(lp_records_header)
        dlat_step_layout = QtWidgets.QHBoxLayout()
        dlat_step_layout.addWidget(window._lp_shortcut_button)
        dlat_step_layout.addStretch(1)
        dlat_step_layout.addWidget(QtWidgets.QLabel("DLAT step"))
        dlat_step_layout.addWidget(window._lp_dlat_step)
        left_layout.addLayout(dlat_step_layout)
        generation_tools_label = QtWidgets.QLabel("Generation Tools")
        generation_tools_label.setStyleSheet("font-weight: bold")
        left_layout.addWidget(generation_tools_label)
        generation_tools_layout = QtWidgets.QHBoxLayout()
        generation_tools_layout.addWidget(window._generate_lp_button)
        generation_tools_layout.addWidget(
            window._recalculate_lateral_speed_button
        )
        left_layout.addLayout(generation_tools_layout)
        io_label = QtWidgets.QLabel("Input/Output")
        io_label.setStyleSheet("font-weight: bold")
        left_layout.addWidget(io_label)
        io_save_layout = QtWidgets.QHBoxLayout()
        io_save_layout.addWidget(window._save_lp_button)
        io_save_layout.addWidget(window._save_all_lp_button)
        left_layout.addLayout(io_save_layout)
        io_csv_layout = QtWidgets.QHBoxLayout()
        io_csv_layout.addWidget(window._export_lp_csv_button)
        io_csv_layout.addWidget(window._import_lp_csv_button)
        left_layout.addLayout(io_csv_layout)
        left_layout.addWidget(window._export_all_lp_csv_button)
        window._lp_records_table.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding,
            QtWidgets.QSizePolicy.Expanding,
        )
        left_layout.addWidget(window._lp_records_table, 1)
        lp_sidebar.setLayout(left_layout)
        return lp_sidebar
