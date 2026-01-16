"""Pit tab builder for the track viewer."""
from __future__ import annotations

from functools import partial

from PyQt5 import QtWidgets

from track_viewer.sidebar.pit_editor import PitParametersEditor


class PitTabBuilder:
    """Builds the pit tab UI and wires signals."""

    def __init__(self, window: QtWidgets.QWidget) -> None:
        self._window = window

    def build(self) -> QtWidgets.QWidget:
        window = self._window
        window._pit_lane_count_combo = QtWidgets.QComboBox()
        window._pit_lane_count_combo.addItem("1 pit lane", 1)
        window._pit_lane_count_combo.addItem("2 pit lanes", 2)
        window._pit_lane_count_combo.setCurrentIndex(0)
        window._pit_lane_count_combo.currentIndexChanged.connect(
            window._handle_pit_lane_count_changed
        )
        window._pit_tabs = QtWidgets.QTabWidget()
        window._pit_editors = [PitParametersEditor(), PitParametersEditor()]
        window._pit_tabs.addTab(window._pit_editors[0], "PIT")
        window._pit_tabs.currentChanged.connect(
            window._handle_pit_tab_changed
        )
        window._pit_status_label = QtWidgets.QLabel(
            "Select a track to edit pit parameters."
        )
        window._pit_status_label.setWordWrap(True)
        for index, editor in enumerate(window._pit_editors):
            editor.parametersChanged.connect(
                partial(window._handle_pit_params_changed, index)
            )
            editor.pitVisibilityChanged.connect(
                partial(window._handle_pit_visibility_changed, index)
            )
            editor.pitStallCenterVisibilityChanged.connect(
                partial(
                    window._handle_pit_stall_center_visibility_changed, index
                )
            )
            editor.pitWallVisibilityChanged.connect(
                partial(window._handle_pit_wall_visibility_changed, index)
            )
            editor.pitStallCarsVisibilityChanged.connect(
                partial(window._handle_pit_stall_cars_visibility_changed, index)
            )
        window._pit_save_button = QtWidgets.QPushButton("Save PIT")
        window._pit_save_button.setEnabled(False)
        window._pit_save_button.clicked.connect(
            window._handle_save_pit_params
        )

        pit_sidebar = QtWidgets.QFrame()
        pit_sidebar.setFrameShape(QtWidgets.QFrame.StyledPanel)
        pit_layout = QtWidgets.QVBoxLayout()
        pit_layout.setSpacing(8)
        pit_title = QtWidgets.QLabel("PIT parameters")
        pit_title.setStyleSheet("font-weight: bold")
        pit_layout.addWidget(pit_title)
        pit_layout.addWidget(window._pit_status_label)
        pit_lane_layout = QtWidgets.QHBoxLayout()
        pit_lane_layout.addWidget(QtWidgets.QLabel("Pit lanes"))
        pit_lane_layout.addWidget(window._pit_lane_count_combo)
        pit_lane_layout.addStretch(1)
        pit_layout.addLayout(pit_lane_layout)
        pit_layout.addWidget(window._pit_tabs)
        pit_layout.addStretch(1)
        pit_layout.addWidget(window._pit_save_button)
        pit_sidebar.setLayout(pit_layout)
        pit_scroll = QtWidgets.QScrollArea()
        pit_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        pit_scroll.setWidgetResizable(True)
        pit_scroll.setWidget(pit_sidebar)
        return pit_scroll
