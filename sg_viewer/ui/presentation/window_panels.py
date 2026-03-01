from __future__ import annotations

from dataclasses import dataclass

from PyQt5 import QtWidgets


@dataclass
class ToolbarNavigationPanel:
    widget: QtWidgets.QWidget
    layout: QtWidgets.QHBoxLayout


@dataclass
class FsectPanel:
    widget: QtWidgets.QWidget
    layout: QtWidgets.QVBoxLayout


@dataclass
class ElevationPanel:
    widget: QtWidgets.QWidget
    layout: QtWidgets.QVBoxLayout


@dataclass
class StatsSidebarPanel:
    widget: QtWidgets.QGroupBox
    layout: QtWidgets.QVBoxLayout


def create_toolbar_navigation_panel(*buttons: QtWidgets.QWidget) -> ToolbarNavigationPanel:
    layout = QtWidgets.QHBoxLayout()
    for button in buttons:
        layout.addWidget(button)
    widget = QtWidgets.QWidget()
    widget.setLayout(layout)
    return ToolbarNavigationPanel(widget=widget, layout=layout)


def create_fsect_panel(
    *,
    live_preview_checkbox: QtWidgets.QCheckBox,
    copy_prev_button: QtWidgets.QPushButton,
    copy_next_button: QtWidgets.QPushButton,
    add_button: QtWidgets.QPushButton,
    delete_button: QtWidgets.QPushButton,
    move_up_button: QtWidgets.QPushButton,
    move_down_button: QtWidgets.QPushButton,
    table: QtWidgets.QTableWidget,
    diagram: QtWidgets.QWidget,
) -> FsectPanel:
    widget = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout()
    options = QtWidgets.QHBoxLayout()
    options.addWidget(live_preview_checkbox)
    layout.addLayout(options)
    layout.addWidget(copy_prev_button)
    layout.addWidget(copy_next_button)
    layout.addWidget(add_button)
    layout.addWidget(delete_button)
    layout.addWidget(move_up_button)
    layout.addWidget(move_down_button)
    layout.addWidget(QtWidgets.QLabel("Fsects"))
    layout.addWidget(table)
    layout.addWidget(QtWidgets.QLabel("Fsect Diagram"))
    layout.addWidget(diagram)
    layout.addStretch()
    widget.setLayout(layout)
    return FsectPanel(widget=widget, layout=layout)


def create_elevation_panel(
    *,
    elevation_layout: QtWidgets.QFormLayout,
    xsect_table: QtWidgets.QTableWidget,
    xsect_combo: QtWidgets.QComboBox,
    copy_xsect_button: QtWidgets.QPushButton,
    profile_widget: QtWidgets.QWidget,
    xsect_elevation_widget: QtWidgets.QWidget,
) -> ElevationPanel:
    widget = QtWidgets.QWidget()
    layout = QtWidgets.QVBoxLayout()
    layout.addLayout(elevation_layout)
    layout.addWidget(QtWidgets.QLabel("X-Section Elevations"))
    layout.addWidget(xsect_table)
    controls = QtWidgets.QHBoxLayout()
    controls.addWidget(QtWidgets.QLabel("Elevation X-Section:"))
    controls.addWidget(xsect_combo)
    controls.addWidget(copy_xsect_button)
    layout.addLayout(controls)
    layout.addWidget(profile_widget, stretch=2)
    layout.addWidget(QtWidgets.QLabel("Section X-Section Elevation"))
    layout.addWidget(xsect_elevation_widget, stretch=1)
    layout.addStretch()
    widget.setLayout(layout)
    return ElevationPanel(widget=widget, layout=layout)


def create_stats_sidebar_panel(*labels: QtWidgets.QLabel) -> StatsSidebarPanel:
    widget = QtWidgets.QGroupBox("Track / Section")
    layout = QtWidgets.QVBoxLayout()
    for label in labels:
        layout.addWidget(label)
    widget.setLayout(layout)
    return StatsSidebarPanel(widget=widget, layout=layout)
