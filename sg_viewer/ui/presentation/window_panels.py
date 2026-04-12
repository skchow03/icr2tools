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
    edit_xsect_list_button: QtWidgets.QPushButton,
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
    layout.addWidget(edit_xsect_list_button)
    controls = QtWidgets.QHBoxLayout()
    controls.addWidget(QtWidgets.QLabel("Track Elevation Profile:"))
    controls.addWidget(xsect_combo)
    controls.addWidget(copy_xsect_button)
    layout.addLayout(controls)
    layout.addWidget(profile_widget, stretch=2)
    layout.addWidget(QtWidgets.QLabel("Lateral Section Elevation Profile"))
    layout.addWidget(xsect_elevation_widget, stretch=1)
    layout.addStretch()
    widget.setLayout(layout)
    return ElevationPanel(widget=widget, layout=layout)


def create_stats_sidebar_panel(*labels: QtWidgets.QLabel) -> StatsSidebarPanel:
    widget = QtWidgets.QGroupBox("Track / Section")
    layout = QtWidgets.QVBoxLayout()
    layout.setContentsMargins(8, 10, 8, 8)
    layout.setSpacing(8)

    sections_layout = QtWidgets.QGridLayout()
    sections_layout.setContentsMargins(0, 0, 0, 0)
    sections_layout.setHorizontalSpacing(10)
    sections_layout.setVerticalSpacing(8)

    grouped_indices: list[tuple[str, tuple[int, ...]]] = [
        ("Track", (0,)),
        ("Current Section", (1, 2, 3, 6, 14)),
        ("Connections", (4, 5, 9, 10)),
        ("Section Metadata", (7, 8, 11, 12, 13)),
        ("Boundaries (Walls)", (15, 16)),
    ]

    for panel_index, (title, indices) in enumerate(grouped_indices):
        group_box = QtWidgets.QGroupBox(title)
        group_layout = QtWidgets.QVBoxLayout()
        group_layout.setContentsMargins(8, 8, 8, 8)
        group_layout.setSpacing(4)
        for index in indices:
            if index < len(labels):
                label = labels[index]
                label.setWordWrap(True)
                group_layout.addWidget(label)
        group_box.setLayout(group_layout)
        sections_layout.addWidget(group_box, panel_index // 2, panel_index % 2)

    layout.addLayout(sections_layout)
    widget.setLayout(layout)
    return StatsSidebarPanel(widget=widget, layout=layout)
