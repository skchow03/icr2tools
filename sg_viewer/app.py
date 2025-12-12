from __future__ import annotations

from typing import List

from PyQt5 import QtWidgets

from sg_viewer.elevation_profile import ElevationProfileWidget
from sg_viewer.preview_widget import SGPreviewWidget
from sg_viewer.selection import SectionSelection
from sg_viewer.viewer_controller import SGViewerController


class SGViewerApp(QtWidgets.QApplication):
    """Thin application wrapper for the SG viewer."""

    def __init__(self, argv: List[str]):
        super().__init__(argv)
        self.setQuitOnLastWindowClosed(True)
        self.window: SGViewerWindow | None = None


class SGViewerWindow(QtWidgets.QMainWindow):
    """Single-window utility that previews SG centrelines."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SG Viewer")
        self.resize(960, 720)

        self._preview = SGPreviewWidget()
        self._sidebar = QtWidgets.QWidget()
        self._prev_button = QtWidgets.QPushButton("Previous Section")
        self._next_button = QtWidgets.QPushButton("Next Section")
        self._new_straight_button = QtWidgets.QPushButton("New Straight")
        self._new_straight_button.setEnabled(False)
        self._radii_button = QtWidgets.QPushButton("Radii")
        self._radii_button.setCheckable(True)
        self._radii_button.setChecked(True)
        self._section_table_button = QtWidgets.QPushButton("Section Table")
        self._section_table_button.setEnabled(False)
        self._heading_table_button = QtWidgets.QPushButton("Heading Table")
        self._heading_table_button.setEnabled(False)
        self._profile_widget = ElevationProfileWidget()
        self._xsect_combo = QtWidgets.QComboBox()
        self._xsect_combo.setEnabled(False)
        self._section_label = QtWidgets.QLabel("Section: None")
        self._type_label = QtWidgets.QLabel("Type: –")
        self._dlong_label = QtWidgets.QLabel("DLONG: –")
        self._length_label = QtWidgets.QLabel("Length: –")
        self._center_label = QtWidgets.QLabel("Center: –")
        self._radius_label = QtWidgets.QLabel("Radius: –")
        self._previous_label = QtWidgets.QLabel("Previous Section: –")
        self._next_label = QtWidgets.QLabel("Next Section: –")
        self._start_heading_label = QtWidgets.QLabel("Start Heading: –")
        self._end_heading_label = QtWidgets.QLabel("End Heading: –")
        self._start_point_label = QtWidgets.QLabel("Start Point: –")
        self._end_point_label = QtWidgets.QLabel("End Point: –")

        sidebar_layout = QtWidgets.QVBoxLayout()
        navigation_layout = QtWidgets.QHBoxLayout()
        navigation_layout.addWidget(self._prev_button)
        navigation_layout.addWidget(self._next_button)
        navigation_layout.addWidget(self._new_straight_button)
        sidebar_layout.addLayout(navigation_layout)
        sidebar_layout.addWidget(self._radii_button)
        sidebar_layout.addWidget(self._section_table_button)
        sidebar_layout.addWidget(self._heading_table_button)
        sidebar_layout.addWidget(QtWidgets.QLabel("Selection"))
        sidebar_layout.addWidget(self._section_label)
        sidebar_layout.addWidget(self._type_label)
        sidebar_layout.addWidget(self._dlong_label)
        sidebar_layout.addWidget(self._length_label)
        sidebar_layout.addWidget(self._center_label)
        sidebar_layout.addWidget(self._radius_label)
        sidebar_layout.addWidget(self._previous_label)
        sidebar_layout.addWidget(self._next_label)
        sidebar_layout.addWidget(self._start_heading_label)
        sidebar_layout.addWidget(self._end_heading_label)
        sidebar_layout.addWidget(self._start_point_label)
        sidebar_layout.addWidget(self._end_point_label)
        sidebar_layout.addStretch()
        self._sidebar.setLayout(sidebar_layout)

        preview_column = QtWidgets.QWidget()
        preview_column_layout = QtWidgets.QVBoxLayout()
        preview_column_layout.addWidget(self._preview, stretch=5)

        profile_controls = QtWidgets.QHBoxLayout()
        profile_controls.addWidget(QtWidgets.QLabel("Elevation X-Section:"))
        profile_controls.addWidget(self._xsect_combo)
        preview_column_layout.addLayout(profile_controls)
        preview_column_layout.addWidget(self._profile_widget, stretch=2)
        preview_column.setLayout(preview_column_layout)

        container = QtWidgets.QWidget()
        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(preview_column, stretch=1)
        layout.addWidget(self._sidebar)
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.controller = SGViewerController(self)

    @property
    def preview(self) -> SGPreviewWidget:
        return self._preview

    @property
    def prev_button(self) -> QtWidgets.QPushButton:
        return self._prev_button

    @property
    def next_button(self) -> QtWidgets.QPushButton:
        return self._next_button

    @property
    def new_straight_button(self) -> QtWidgets.QPushButton:
        return self._new_straight_button

    @property
    def radii_button(self) -> QtWidgets.QPushButton:
        return self._radii_button

    @property
    def section_table_button(self) -> QtWidgets.QPushButton:
        return self._section_table_button

    @property
    def heading_table_button(self) -> QtWidgets.QPushButton:
        return self._heading_table_button

    @property
    def profile_widget(self) -> ElevationProfileWidget:
        return self._profile_widget

    @property
    def xsect_combo(self) -> QtWidgets.QComboBox:
        return self._xsect_combo

    def update_selection_sidebar(self, selection: SectionSelection | None) -> None:
        if selection is None:
            self._section_label.setText("Section: None")
            self._type_label.setText("Type: –")
            self._dlong_label.setText("DLONG: –")
            self._length_label.setText("Length: –")
            self._center_label.setText("Center: –")
            self._radius_label.setText("Radius: –")
            self._previous_label.setText("Previous Section: –")
            self._next_label.setText("Next Section: –")
            self._start_heading_label.setText("Start Heading: –")
            self._end_heading_label.setText("End Heading: –")
            self._start_point_label.setText("Start Point: –")
            self._end_point_label.setText("End Point: –")
            self._profile_widget.set_selected_range(None)
            return

        self._section_label.setText(f"Section: {selection.index}")
        self._type_label.setText(f"Type: {selection.type_name}")
        self._dlong_label.setText(
            f"DLONG: {selection.start_dlong:.0f} → {selection.end_dlong:.0f}"
        )
        self._length_label.setText(f"Length: {selection.length:.3f}")
        if selection.center is not None and selection.radius is not None:
            cx, cy = selection.center
            self._center_label.setText(f"Center: ({cx:.1f}, {cy:.1f})")
            self._radius_label.setText(f"Radius: {selection.radius:.1f}")
        else:
            self._center_label.setText("Center: –")
            self._radius_label.setText("Radius: –")

        self._previous_label.setText(self._format_section_link("Previous", selection.previous_id))
        self._next_label.setText(self._format_section_link("Next", selection.next_id))

        if selection.start_heading is not None:
            sx, sy = selection.start_heading
            self._start_heading_label.setText(
                f"Start Heading: ({sx:.5f}, {sy:.5f})"
            )
        else:
            self._start_heading_label.setText("Start Heading: –")

        if selection.end_heading is not None:
            ex, ey = selection.end_heading
            self._end_heading_label.setText(f"End Heading: ({ex:.5f}, {ey:.5f})")
        else:
            self._end_heading_label.setText("End Heading: –")

        if selection.start_point is not None:
            sx, sy = selection.start_point
            self._start_point_label.setText(f"Start Point: ({sx:.1f}, {sy:.1f})")
        else:
            self._start_point_label.setText("Start Point: –")

        if selection.end_point is not None:
            ex, ey = selection.end_point
            self._end_point_label.setText(f"End Point: ({ex:.1f}, {ey:.1f})")
        else:
            self._end_point_label.setText("End Point: –")

        selected_range = self._preview.get_section_range(selection.index)
        self._profile_widget.set_selected_range(selected_range)

    @staticmethod
    def _format_section_link(prefix: str, section_id: int) -> str:
        connection = "Not connected" if section_id == -1 else str(section_id)
        return f"{prefix} Section: {connection}"
