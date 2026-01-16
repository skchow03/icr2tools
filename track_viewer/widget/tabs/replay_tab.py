"""Replay tab builder for the track viewer."""
from __future__ import annotations

from PyQt5 import QtWidgets



class ReplayTabBuilder:
    """Builds the replay tab UI and wires signals."""

    def __init__(self, window: QtWidgets.QWidget) -> None:
        self._window = window

    def build(self) -> QtWidgets.QWidget:
        window = self._window
        window._replay_list = QtWidgets.QListWidget()
        window._replay_list.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        window._replay_list.setAlternatingRowColors(True)
        window._replay_list.currentRowChanged.connect(
            window._handle_replay_selected
        )
        window._replay_car_combo = QtWidgets.QComboBox()
        window._replay_car_combo.setEnabled(False)
        window._replay_car_combo.currentIndexChanged.connect(
            window._handle_replay_car_selected
        )
        window._replay_laps_table = QtWidgets.QTableWidget(0, 5)
        window._replay_laps_table.setHorizontalHeaderLabels(
            ["Use", "Lap", "Status", "Frames", "Time"]
        )
        window._replay_laps_table.setEditTriggers(
            QtWidgets.QAbstractItemView.NoEditTriggers
        )
        window._replay_laps_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows
        )
        window._replay_laps_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        window._replay_laps_table.setAlternatingRowColors(True)
        window._replay_laps_table.currentCellChanged.connect(
            window._handle_replay_lap_selected
        )
        window._replay_laps_table.verticalHeader().setVisible(False)
        replay_header = window._replay_laps_table.horizontalHeader()
        replay_header.setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeToContents
        )
        replay_header.setStretchLastSection(True)
        window._replay_lap_button_group = QtWidgets.QButtonGroup(window)
        window._replay_lap_button_group.setExclusive(True)
        window._replay_lap_button_group.buttonToggled.connect(
            window._handle_replay_lap_radio_toggled
        )
        window._replay_selected_lap_for_generation = None
        window._replay_lp_combo = QtWidgets.QComboBox()
        window._replay_lp_combo.setEnabled(False)
        window._replay_lp_combo.currentIndexChanged.connect(
            window._handle_replay_lp_target_changed
        )
        window._replay_generate_lp_button = QtWidgets.QPushButton(
            "Generate LP from Replay"
        )
        window._replay_generate_lp_button.setEnabled(False)
        window._replay_generate_lp_button.clicked.connect(
            window._handle_generate_replay_lp
        )
        window._replay_copy_speeds_button = QtWidgets.QPushButton(
            "Copy Only Speeds to Selected LP"
        )
        window._replay_copy_speeds_button.setEnabled(False)
        window._replay_copy_speeds_button.clicked.connect(
            window._handle_copy_replay_speeds
        )
        window._replay_status_label = QtWidgets.QLabel(
            "Select a track to view replay laps."
        )
        window._replay_status_label.setWordWrap(True)
        window._current_replay = None
        window._current_replay_path = None

        replay_sidebar = QtWidgets.QFrame()
        replay_sidebar.setFrameShape(QtWidgets.QFrame.StyledPanel)
        replay_layout = QtWidgets.QVBoxLayout()
        replay_layout.setSpacing(8)
        replay_title = QtWidgets.QLabel("Replays")
        replay_title.setStyleSheet("font-weight: bold")
        replay_layout.addWidget(replay_title)
        replay_layout.addWidget(window._replay_status_label)
        replay_layout.addWidget(QtWidgets.QLabel("Replay files"))
        replay_layout.addWidget(window._replay_list, stretch=1)
        replay_layout.addWidget(QtWidgets.QLabel("Car"))
        replay_layout.addWidget(window._replay_car_combo)
        replay_layout.addWidget(QtWidgets.QLabel("Lap list"))
        replay_layout.addWidget(window._replay_laps_table, stretch=2)
        replay_layout.addWidget(QtWidgets.QLabel("LP target"))
        replay_layout.addWidget(window._replay_lp_combo)
        replay_layout.addWidget(window._replay_generate_lp_button)
        replay_layout.addWidget(window._replay_copy_speeds_button)
        replay_sidebar.setLayout(replay_layout)
        return replay_sidebar
