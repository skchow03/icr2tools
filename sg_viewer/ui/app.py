from __future__ import annotations

import math
from typing import List

from PyQt5 import QtCore, QtWidgets

from sg_viewer.model.sg_document import SGDocument
from sg_viewer.rendering.fsection_style_map import FENCE_TYPE2
from sg_viewer.preview.context import PreviewContext
from sg_viewer.ui.altitude_units import (
    DEFAULT_ALTITUDE_MAX_FEET,
    DEFAULT_ALTITUDE_MIN_FEET,
    feet_from_500ths,
    feet_from_slider_units,
    feet_to_slider_units,
)
from sg_viewer.ui.elevation_profile import ElevationProfileWidget
from sg_viewer.ui.fsect_diagram_widget import FsectDiagramWidget
from sg_viewer.ui.xsect_elevation import XsectElevationWidget
from sg_viewer.ui.preview_widget_qt import PreviewWidgetQt
from sg_viewer.models.selection import SectionSelection
from sg_viewer.ui.viewer_controller import SGViewerController


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
        self._selected_section_index: int | None = None
        self._updating_fsect_table = False

        shortcut_labels = {
            "new_straight": "Ctrl+Alt+S",
            "new_curve": "Ctrl+Alt+C",
            "split_section": "Ctrl+Alt+P",
            "delete_section": "Ctrl+Alt+D",
            "set_start_finish": "Ctrl+Alt+F",
        }

        def _set_button_shortcut(
            button: QtWidgets.QPushButton, label: str, shortcut: str
        ) -> None:
            button.setText(label)
            button.setToolTip(f"{label} ({shortcut})")
            button.setShortcut(shortcut)

        self._preview: PreviewContext = PreviewWidgetQt(
            show_status=self.show_status_message
        )
        self._sidebar = QtWidgets.QWidget()
        self._fsect_sidebar = QtWidgets.QWidget()
        #self._new_track_button = QtWidgets.QPushButton("New Track")
        self._prev_button = QtWidgets.QPushButton("Previous Section")
        self._next_button = QtWidgets.QPushButton("Next Section")
        self._new_straight_button = QtWidgets.QPushButton("New Straight")
        self._new_straight_button.setCheckable(True)
        self._new_straight_button.setEnabled(False)
        _set_button_shortcut(
            self._new_straight_button, "New Straight", shortcut_labels["new_straight"]
        )
        self._new_curve_button = QtWidgets.QPushButton("New Curve")
        self._new_curve_button.setCheckable(True)
        self._new_curve_button.setEnabled(False)
        _set_button_shortcut(
            self._new_curve_button, "New Curve", shortcut_labels["new_curve"]
        )
        self._split_section_button = QtWidgets.QPushButton("Split")
        self._split_section_button.setCheckable(True)
        self._split_section_button.setEnabled(False)
        _set_button_shortcut(
            self._split_section_button, "Split", shortcut_labels["split_section"]
        )
        self._delete_section_button = QtWidgets.QPushButton("Delete Section")
        self._delete_section_button.setCheckable(True)
        self._delete_section_button.setEnabled(False)
        _set_button_shortcut(
            self._delete_section_button,
            "Delete Section",
            shortcut_labels["delete_section"],
        )
        self._set_start_finish_button = QtWidgets.QPushButton("Set Start/Finish")
        self._set_start_finish_button.setEnabled(False)
        _set_button_shortcut(
            self._set_start_finish_button,
            "Set Start/Finish",
            shortcut_labels["set_start_finish"],
        )
        self._radii_button = QtWidgets.QPushButton("Radii")
        self._radii_button.setCheckable(True)
        self._radii_button.setChecked(True)
        self._axes_button = QtWidgets.QPushButton("Axes")
        self._axes_button.setCheckable(True)
        self._axes_button.setChecked(False)
        self._sg_fsects_checkbox = QtWidgets.QCheckBox("Show SG Fsects (preview)")
        self._sg_fsects_checkbox.setChecked(False)
        self._xsect_dlat_line_checkbox = QtWidgets.QCheckBox(
            "Show X-Section DLAT Line"
        )
        self._xsect_dlat_line_checkbox.setChecked(False)
        self._refresh_fsects_button = QtWidgets.QPushButton("Refresh Fsects Preview")
        self._refresh_fsects_button.setEnabled(False)
        self._copy_fsects_prev_button = QtWidgets.QPushButton(
            "Copy Fsects to Previous"
        )
        self._copy_fsects_prev_button.setEnabled(False)
        self._copy_fsects_next_button = QtWidgets.QPushButton("Copy Fsects to Next")
        self._copy_fsects_next_button.setEnabled(False)
        self._add_fsect_button = QtWidgets.QPushButton("Add Fsect Below")
        self._add_fsect_button.setEnabled(False)
        self._delete_fsect_button = QtWidgets.QPushButton("Delete Fsect")
        self._delete_fsect_button.setEnabled(False)
        self._section_table_button = QtWidgets.QPushButton("Section Table")
        self._section_table_button.setEnabled(False)
        self._heading_table_button = QtWidgets.QPushButton("Heading Table")
        self._heading_table_button.setEnabled(False)
        self._xsect_table_button = QtWidgets.QPushButton("X-Section Table")
        self._xsect_table_button.setEnabled(False)
        self._profile_widget = ElevationProfileWidget()
        self._xsect_elevation_widget = XsectElevationWidget()
        self._xsect_combo = QtWidgets.QComboBox()
        self._xsect_combo.setEnabled(False)
        self._copy_xsect_button = QtWidgets.QPushButton("Copy X-Section to All")
        self._copy_xsect_button.setEnabled(False)
        self._elevation_samples_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._elevation_samples_slider.setRange(10, 32)
        self._elevation_samples_slider.setSingleStep(1)
        self._elevation_samples_slider.setPageStep(2)
        self._elevation_samples_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self._elevation_samples_slider.setTickInterval(2)
        self._elevation_samples_slider.setValue(10)
        self._elevation_samples_slider.setToolTip(
            "Number of elevation samples per track section."
        )
        self._elevation_samples_value_label = QtWidgets.QLabel("10")
        self._elevation_samples_value_label.setMinimumWidth(24)
        self._elevation_samples_value_label.setAlignment(
            QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
        )
        self._scale_label = QtWidgets.QLabel("Scale: –")
        self._track_length_label = QtWidgets.QLabel("Track length: –")
        self._section_label = QtWidgets.QLabel("Section: None")
        self._type_label = QtWidgets.QLabel("Type: –")
        self._dlong_label = QtWidgets.QLabel("DLONG: –")
        self._length_label = QtWidgets.QLabel("Length: –")
        self._center_label = QtWidgets.QLabel("Center: –")
        self._radius_label = QtWidgets.QLabel("Radius: –")
        self._sang_label = QtWidgets.QLabel("Sang: –")
        self._eang_label = QtWidgets.QLabel("Eang: –")
        self._previous_label = QtWidgets.QLabel("Previous Section: –")
        self._next_label = QtWidgets.QLabel("Next Section: –")
        self._start_heading_label = QtWidgets.QLabel("Start Heading (SG): –")
        self._end_heading_label = QtWidgets.QLabel("End Heading (SG): –")
        self._start_compass_heading_label = QtWidgets.QLabel("Start Heading (Compass): –")
        self._end_compass_heading_label = QtWidgets.QLabel("End Heading (Compass): –")
        self._start_point_label = QtWidgets.QLabel("Start Point: –")
        self._end_point_label = QtWidgets.QLabel("End Point: –")
        self._fsect_dlat_units_combo = QtWidgets.QComboBox()
        self._fsect_dlat_units_combo.addItem("Feet", "feet")
        self._fsect_dlat_units_combo.addItem("500ths", "500ths")
        self._fsect_dlat_units_combo.setCurrentIndex(0)
        self._fsect_dlat_units_combo.currentIndexChanged.connect(
            self._on_fsect_dlat_units_changed
        )
        self._fsect_table = QtWidgets.QTableWidget(0, 5)
        self._update_fsect_table_headers()
        self._fsect_table.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.SelectedClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
        )
        self._fsect_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self._fsect_table.verticalHeader().setVisible(False)
        self._fsect_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeToContents
        )
        self._fsect_table.horizontalHeader().setStretchLastSection(True)
        self._fsect_table.setSizeAdjustPolicy(
            QtWidgets.QAbstractScrollArea.AdjustToContents
        )
        self._fsect_table.setMinimumHeight(160)
        self._fsect_table.cellChanged.connect(self._on_fsect_cell_changed)
        self._fsect_diagram = FsectDiagramWidget(
            on_dlat_changed=self._on_fsect_diagram_dlat_changed
        )
        self._altitude_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        min_altitude_feet = feet_from_500ths(SGDocument.ELEVATION_MIN)
        max_altitude_feet = feet_from_500ths(SGDocument.ELEVATION_MAX)
        self._altitude_slider.setRange(
            feet_to_slider_units(DEFAULT_ALTITUDE_MIN_FEET),
            feet_to_slider_units(DEFAULT_ALTITUDE_MAX_FEET),
        )
        self._altitude_slider.setSingleStep(1)
        self._altitude_slider.setPageStep(10)
        self._altitude_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self._altitude_slider.setTickInterval(10)
        self._altitude_slider.setEnabled(False)
        self._altitude_value_label = QtWidgets.QLabel("0.0")
        self._altitude_value_label.setMinimumWidth(50)
        self._altitude_value_label.setAlignment(
            QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
        )
        self._altitude_min_spin = QtWidgets.QDoubleSpinBox()
        self._altitude_min_spin.setRange(
            min_altitude_feet, max_altitude_feet - 0.1
        )
        self._altitude_min_spin.setDecimals(1)
        self._altitude_min_spin.setSingleStep(0.1)
        self._altitude_min_spin.setValue(DEFAULT_ALTITUDE_MIN_FEET)
        self._altitude_min_spin.setKeyboardTracking(False)
        self._altitude_max_spin = QtWidgets.QDoubleSpinBox()
        self._altitude_max_spin.setRange(
            min_altitude_feet + 0.1, max_altitude_feet
        )
        self._altitude_max_spin.setDecimals(1)
        self._altitude_max_spin.setSingleStep(0.1)
        self._altitude_max_spin.setValue(DEFAULT_ALTITUDE_MAX_FEET)
        self._altitude_max_spin.setKeyboardTracking(False)
        self._grade_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._grade_slider.setRange(-1000, 1000)
        self._grade_slider.setSingleStep(1)
        self._grade_slider.setPageStep(10)
        self._grade_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self._grade_slider.setTickInterval(250)
        self._grade_slider.setEnabled(False)
        self._grade_value_label = QtWidgets.QLabel("0")
        self._grade_value_label.setMinimumWidth(40)
        self._grade_value_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)

        sidebar_layout = QtWidgets.QVBoxLayout()
        navigation_layout = QtWidgets.QHBoxLayout()
        #navigation_layout.addWidget(self._new_track_button)
        navigation_layout.addWidget(self._prev_button)
        navigation_layout.addWidget(self._next_button)
        navigation_layout.addWidget(self._new_straight_button)
        navigation_layout.addWidget(self._new_curve_button)
        navigation_layout.addWidget(self._split_section_button)
        navigation_layout.addWidget(self._delete_section_button)
        navigation_layout.addWidget(self._set_start_finish_button)
        sidebar_layout.addWidget(self._radii_button)
        sidebar_layout.addWidget(self._axes_button)
        sidebar_layout.addWidget(self._section_table_button)
        sidebar_layout.addWidget(self._heading_table_button)
        sidebar_layout.addWidget(self._xsect_table_button)
        sidebar_layout.addWidget(QtWidgets.QLabel("Selection"))
        sidebar_layout.addWidget(self._scale_label)
        sidebar_layout.addWidget(self._track_length_label)
        sidebar_layout.addWidget(self._section_label)
        sidebar_layout.addWidget(self._type_label)
        sidebar_layout.addWidget(self._dlong_label)
        sidebar_layout.addWidget(self._length_label)
        sidebar_layout.addWidget(self._center_label)
        sidebar_layout.addWidget(self._radius_label)
        sidebar_layout.addWidget(self._sang_label)
        sidebar_layout.addWidget(self._eang_label)
        sidebar_layout.addWidget(self._previous_label)
        sidebar_layout.addWidget(self._next_label)
        sidebar_layout.addWidget(self._start_heading_label)
        sidebar_layout.addWidget(self._end_heading_label)
        sidebar_layout.addWidget(self._start_compass_heading_label)
        sidebar_layout.addWidget(self._end_compass_heading_label)
        sidebar_layout.addWidget(self._start_point_label)
        sidebar_layout.addWidget(self._end_point_label)
        elevation_layout = QtWidgets.QFormLayout()
        altitude_container = QtWidgets.QWidget()
        altitude_layout = QtWidgets.QHBoxLayout()
        altitude_layout.setContentsMargins(0, 0, 0, 0)
        altitude_layout.addWidget(self._altitude_slider, stretch=1)
        altitude_layout.addWidget(self._altitude_value_label)
        altitude_container.setLayout(altitude_layout)
        elevation_layout.addRow("Altitude (xsect):", altitude_container)
        altitude_range_container = QtWidgets.QWidget()
        altitude_range_layout = QtWidgets.QHBoxLayout()
        altitude_range_layout.setContentsMargins(0, 0, 0, 0)
        altitude_range_layout.addWidget(self._altitude_min_spin)
        altitude_range_layout.addWidget(QtWidgets.QLabel("to"))
        altitude_range_layout.addWidget(self._altitude_max_spin)
        altitude_range_container.setLayout(altitude_range_layout)
        elevation_layout.addRow("Altitude range:", altitude_range_container)
        grade_container = QtWidgets.QWidget()
        grade_layout = QtWidgets.QHBoxLayout()
        grade_layout.setContentsMargins(0, 0, 0, 0)
        grade_layout.addWidget(self._grade_slider, stretch=1)
        grade_layout.addWidget(self._grade_value_label)
        grade_container.setLayout(grade_layout)
        elevation_layout.addRow("Grade (xsect):", grade_container)
        sidebar_layout.addLayout(elevation_layout)
        sidebar_layout.addStretch()
        self._sidebar.setLayout(sidebar_layout)

        fsect_sidebar_layout = QtWidgets.QVBoxLayout()
        fsect_sidebar_layout.addWidget(self._sg_fsects_checkbox)
        fsect_sidebar_layout.addWidget(self._refresh_fsects_button)
        fsect_sidebar_layout.addWidget(self._copy_fsects_prev_button)
        fsect_sidebar_layout.addWidget(self._copy_fsects_next_button)
        fsect_sidebar_layout.addWidget(self._add_fsect_button)
        fsect_sidebar_layout.addWidget(self._delete_fsect_button)
        fsect_sidebar_layout.addWidget(QtWidgets.QLabel("Fsects"))
        fsect_units_layout = QtWidgets.QHBoxLayout()
        fsect_units_layout.addWidget(QtWidgets.QLabel("DLAT units:"))
        fsect_units_layout.addWidget(self._fsect_dlat_units_combo)
        fsect_units_layout.addStretch()
        fsect_sidebar_layout.addLayout(fsect_units_layout)
        fsect_sidebar_layout.addWidget(self._fsect_table)
        fsect_sidebar_layout.addWidget(QtWidgets.QLabel("Fsect Diagram"))
        fsect_sidebar_layout.addWidget(self._fsect_diagram)
        fsect_sidebar_layout.addStretch()
        self._fsect_sidebar.setLayout(fsect_sidebar_layout)

        preview_column = QtWidgets.QWidget()
        preview_column_layout = QtWidgets.QVBoxLayout()
        preview_column_layout.addLayout(navigation_layout)
        preview_column_layout.addWidget(self._preview, stretch=5)

        profile_controls = QtWidgets.QHBoxLayout()
        profile_controls.addWidget(QtWidgets.QLabel("Elevation X-Section:"))
        profile_controls.addWidget(self._xsect_combo)
        profile_controls.addWidget(self._copy_xsect_button)
        profile_controls.addWidget(self._xsect_dlat_line_checkbox)
        profile_controls.addWidget(QtWidgets.QLabel("Samples/Section:"))
        profile_controls.addWidget(self._elevation_samples_slider, stretch=1)
        profile_controls.addWidget(self._elevation_samples_value_label)
        preview_column_layout.addLayout(profile_controls)
        preview_column_layout.addWidget(self._profile_widget, stretch=2)
        preview_column_layout.addWidget(QtWidgets.QLabel("Section X-Section Elevation"))
        preview_column_layout.addWidget(self._xsect_elevation_widget, stretch=1)
        preview_column.setLayout(preview_column_layout)

        container = QtWidgets.QWidget()
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(self._sidebar)
        splitter.addWidget(preview_column)
        splitter.addWidget(self._fsect_sidebar)
        splitter.setStretchFactor(1, 1)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(2, False)
        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(splitter)
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.controller = SGViewerController(self)

    @property
    def preview(self) -> PreviewContext:
        return self._preview

    @property
    def prev_button(self) -> QtWidgets.QPushButton:
        return self._prev_button

    @property
    def next_button(self) -> QtWidgets.QPushButton:
        return self._next_button

    # @property
    # def new_track_button(self) -> QtWidgets.QPushButton:
    #     return self._new_track_button

    @property
    def new_straight_button(self) -> QtWidgets.QPushButton:
        return self._new_straight_button

    @property
    def new_curve_button(self) -> QtWidgets.QPushButton:
        return self._new_curve_button

    @property
    def split_section_button(self) -> QtWidgets.QPushButton:
        return self._split_section_button

    @property
    def delete_section_button(self) -> QtWidgets.QPushButton:
        return self._delete_section_button

    @property
    def set_start_finish_button(self) -> QtWidgets.QPushButton:
        return self._set_start_finish_button

    @property
    def radii_button(self) -> QtWidgets.QPushButton:
        return self._radii_button

    @property
    def axes_button(self) -> QtWidgets.QPushButton:
        return self._axes_button

    @property
    def sg_fsects_checkbox(self) -> QtWidgets.QCheckBox:
        return self._sg_fsects_checkbox

    @property
    def xsect_dlat_line_checkbox(self) -> QtWidgets.QCheckBox:
        return self._xsect_dlat_line_checkbox

    @property
    def refresh_fsects_button(self) -> QtWidgets.QPushButton:
        return self._refresh_fsects_button

    @property
    def copy_fsects_prev_button(self) -> QtWidgets.QPushButton:
        return self._copy_fsects_prev_button

    @property
    def copy_fsects_next_button(self) -> QtWidgets.QPushButton:
        return self._copy_fsects_next_button

    @property
    def add_fsect_button(self) -> QtWidgets.QPushButton:
        return self._add_fsect_button

    @property
    def delete_fsect_button(self) -> QtWidgets.QPushButton:
        return self._delete_fsect_button

    @property
    def fsect_table(self) -> QtWidgets.QTableWidget:
        return self._fsect_table

    @property
    def section_table_button(self) -> QtWidgets.QPushButton:
        return self._section_table_button

    @property
    def heading_table_button(self) -> QtWidgets.QPushButton:
        return self._heading_table_button

    @property
    def xsect_table_button(self) -> QtWidgets.QPushButton:
        return self._xsect_table_button

    @property
    def profile_widget(self) -> ElevationProfileWidget:
        return self._profile_widget

    @property
    def xsect_elevation_widget(self) -> XsectElevationWidget:
        return self._xsect_elevation_widget

    @property
    def xsect_combo(self) -> QtWidgets.QComboBox:
        return self._xsect_combo

    @property
    def copy_xsect_button(self) -> QtWidgets.QPushButton:
        return self._copy_xsect_button

    @property
    def elevation_samples_slider(self) -> QtWidgets.QSlider:
        return self._elevation_samples_slider

    @property
    def altitude_slider(self) -> QtWidgets.QSlider:
        return self._altitude_slider

    @property
    def altitude_min_spin(self) -> QtWidgets.QDoubleSpinBox:
        return self._altitude_min_spin

    @property
    def altitude_max_spin(self) -> QtWidgets.QDoubleSpinBox:
        return self._altitude_max_spin

    @property
    def grade_spin(self) -> QtWidgets.QSlider:
        return self._grade_slider

    def show_status_message(self, message: str) -> None:
        self._preview.set_status_text(message)

    def update_scale_label(self, scale: float | None) -> None:
        if scale is None or scale <= 0:
            self._scale_label.setText("Scale: –")
            return

        self._scale_label.setText(f"Scale: 1px = {1 / scale:.1f} 500ths")

    def update_track_length_label(self, text: str) -> None:
        self._track_length_label.setText(text)

    def update_elevation_inputs(
        self, altitude: int | None, grade: int | None, enabled: bool
    ) -> None:
        self._altitude_slider.blockSignals(True)
        self._grade_slider.blockSignals(True)
        altitude_value = altitude if altitude is not None else 0
        altitude_feet = feet_from_500ths(altitude_value)
        self._altitude_slider.setValue(feet_to_slider_units(altitude_feet))
        self._altitude_value_label.setText(f"{altitude_feet:.1f}")
        grade_value = grade if grade is not None else 0
        self._grade_slider.setValue(grade_value)
        self._grade_value_label.setText(str(grade_value))
        self._altitude_slider.setEnabled(enabled)
        self._grade_slider.setEnabled(enabled)
        self._altitude_slider.blockSignals(False)
        self._grade_slider.blockSignals(False)

    def update_grade_display(self, value: int) -> None:
        self._grade_value_label.setText(str(value))

    def update_altitude_display(self, value: int) -> None:
        altitude_feet = feet_from_slider_units(value)
        self._altitude_value_label.setText(f"{altitude_feet:.1f}")

    def update_elevation_samples_display(self, value: int) -> None:
        self._elevation_samples_value_label.setText(str(value))

    def update_selection_sidebar(self, selection: SectionSelection | None) -> None:
        def _fmt_int(value: float | int | None) -> str:
            if value is None:
                return "–"
            return f"{int(round(value))}"

        def _fmt_point(point: tuple[float, float] | None) -> str:
            if point is None:
                return "–"
            return f"({_fmt_int(point[0])}, {_fmt_int(point[1])})"

        def _fmt_heading(heading: tuple[int, int] | None) -> str:
            if heading is None:
                return "–"
            return f"({_fmt_int(heading[0])}, {_fmt_int(heading[1])})"

        def _fmt_compass_heading(heading: tuple[float, float] | None) -> str:
            if heading is None:
                return "–"
            hx, hy = heading
            length = math.hypot(hx, hy)
            if length <= 0:
                return "–"
            angle_deg = math.degrees(math.atan2(hy, hx))
            compass_deg = (90.0 - angle_deg) % 360.0
            return f"{compass_deg:.1f}°"

        if selection is None:
            self._selected_section_index = None
            self._section_label.setText("Section: None")
            self._type_label.setText("Type: –")
            self._dlong_label.setText("DLONG: –")
            self._length_label.setText("Length: –")
            self._center_label.setText("Center: –")
            self._radius_label.setText("Radius: –")
            self._sang_label.setText("Sang: –")
            self._eang_label.setText("Eang: –")
            self._previous_label.setText("Previous Section: –")
            self._next_label.setText("Next Section: –")
            self._start_heading_label.setText("Start Heading (SG): –")
            self._end_heading_label.setText("End Heading (SG): –")
            self._start_compass_heading_label.setText("Start Heading (Compass): –")
            self._end_compass_heading_label.setText("End Heading (Compass): –")
            self._start_point_label.setText("Start Point: –")
            self._end_point_label.setText("End Point: –")
            self._profile_widget.set_selected_range(None)
            self._update_fsect_table(None)
            return

        self._selected_section_index = selection.index
        self._section_label.setText(f"Section: {selection.index}")
        self._type_label.setText(f"Type: {selection.type_name}")
        self._dlong_label.setText(
            f"DLONG: {_fmt_int(selection.start_dlong)} → {_fmt_int(selection.end_dlong)}"
        )
        self._length_label.setText(f"Length: {_fmt_int(selection.length)}")

        self._center_label.setText(f"Center: {_fmt_point(selection.center)}")

        radius_value = selection.sg_radius
        if radius_value is None:
            radius_value = selection.radius
        self._radius_label.setText(f"Radius: {_fmt_int(radius_value)}")
        self._sang_label.setText(
            f"Sang: ({_fmt_int(selection.sg_sang1)}, {_fmt_int(selection.sg_sang2)})"
        )
        self._eang_label.setText(
            f"Eang: ({_fmt_int(selection.sg_eang1)}, {_fmt_int(selection.sg_eang2)})"
        )

        self._previous_label.setText(self._format_section_link("Previous", selection.previous_id))
        self._next_label.setText(self._format_section_link("Next", selection.next_id))

        self._start_heading_label.setText(
            f"Start Heading (SG): {_fmt_heading(selection.sg_start_heading)}"
        )

        self._end_heading_label.setText(
            f"End Heading (SG): {_fmt_heading(selection.sg_end_heading)}"
        )

        self._start_compass_heading_label.setText(
            f"Start Heading (Compass): {_fmt_compass_heading(selection.start_heading)}"
        )
        self._end_compass_heading_label.setText(
            f"End Heading (Compass): {_fmt_compass_heading(selection.end_heading)}"
        )

        self._start_point_label.setText(
            f"Start Point: {_fmt_point(selection.start_point)}"
        )
        self._end_point_label.setText(f"End Point: {_fmt_point(selection.end_point)}")

        selected_range = self._preview.get_section_range(selection.index)
        self._profile_widget.set_selected_range(selected_range)
        self._update_fsect_table(selection.index)

    @staticmethod
    def _format_section_link(prefix: str, section_id: int) -> str:
        connection = "Not connected" if section_id == -1 else str(section_id)
        return f"{prefix} Section: {connection}"

    def _update_fsect_table(self, section_index: int | None) -> None:
        fsects = self._preview.get_section_fsects(section_index)
        self._updating_fsect_table = True
        self._fsect_table.setRowCount(len(fsects))
        for row_index, fsect in enumerate(fsects):
            start_item = QtWidgets.QTableWidgetItem(
                self._format_fsect_dlat(fsect.start_dlat)
            )
            end_item = QtWidgets.QTableWidgetItem(
                self._format_fsect_dlat(fsect.end_dlat)
            )
            type_item = QtWidgets.QTableWidgetItem(
                self._fsect_type_description(fsect.surface_type, fsect.type2)
            )
            for editable_item in (start_item, end_item):
                editable_item.setFlags(
                    editable_item.flags()
                    | QtCore.Qt.ItemIsEditable
                    | QtCore.Qt.ItemIsSelectable
                )
            self._fsect_table.setItem(
                row_index, 0, QtWidgets.QTableWidgetItem(str(row_index))
            )
            self._fsect_table.setItem(row_index, 1, start_item)
            self._fsect_table.setItem(row_index, 2, end_item)
            self._fsect_table.setItem(row_index, 3, type_item)
            combo = QtWidgets.QComboBox()
            for label, surface_type, type2 in self._fsect_type_options():
                combo.addItem(label, (surface_type, type2))
            combo.setCurrentIndex(
                self._fsect_type_index(fsect.surface_type, fsect.type2)
            )
            combo.currentIndexChanged.connect(
                lambda _idx, row=row_index, widget=combo: self._on_fsect_type_changed(
                    row, widget
                )
            )
            self._fsect_table.setCellWidget(row_index, 4, combo)
        if not fsects:
            self._fsect_table.setRowCount(0)
        self._updating_fsect_table = False
        self._fsect_table.resizeColumnsToContents()
        self._fsect_diagram.set_fsects(section_index, fsects)

    def _on_fsect_cell_changed(self, row_index: int, column_index: int) -> None:
        if self._updating_fsect_table:
            return
        if column_index not in (1, 2):
            return
        section_index = self._selected_section_index
        if section_index is None:
            return
        fsects = self._preview.get_section_fsects(section_index)
        if row_index < 0 or row_index >= len(fsects):
            return
        item = self._fsect_table.item(row_index, column_index)
        if item is None:
            return
        text = item.text().strip()
        try:
            new_value = float(text)
        except ValueError:
            self._reset_fsect_dlat_cell(row_index, column_index, fsects[row_index])
            return
        new_value = self._fsect_dlat_from_display_units(new_value)
        if column_index == 1:
            self._preview.update_fsection_dlat(
                section_index, row_index, start_dlat=new_value
            )
        else:
            self._preview.update_fsection_dlat(
                section_index, row_index, end_dlat=new_value
            )
        self._update_fsect_table(section_index)

    def _reset_fsect_dlat_cell(
        self,
        row_index: int,
        column_index: int,
        fsect,
    ) -> None:
        value = fsect.start_dlat if column_index == 1 else fsect.end_dlat
        item = self._fsect_table.item(row_index, column_index)
        if item is None:
            return
        self._updating_fsect_table = True
        item.setText(self._format_fsect_dlat(value))
        self._updating_fsect_table = False

    def _on_fsect_dlat_units_changed(self) -> None:
        self._update_fsect_table_headers()
        self._update_fsect_table(self._selected_section_index)

    def _update_fsect_table_headers(self) -> None:
        unit_label = self._fsect_dlat_units_label()
        self._fsect_table.setHorizontalHeaderLabels(
            [
                "Index",
                f"Start DLAT ({unit_label})",
                f"End DLAT ({unit_label})",
                "Type Description",
                "Type Selection",
            ]
        )

    def _fsect_dlat_units_label(self) -> str:
        unit = self._fsect_dlat_units_combo.currentData()
        return "ft" if unit == "feet" else "500ths"

    def _fsect_dlat_to_display_units(self, value: float) -> float:
        if self._fsect_dlat_units_combo.currentData() == "feet":
            return value / 6000.0
        return value

    def _fsect_dlat_from_display_units(self, value: float) -> float:
        if self._fsect_dlat_units_combo.currentData() == "feet":
            return value * 6000.0
        return value

    def _format_fsect_dlat(self, value: float) -> str:
        display_value = self._fsect_dlat_to_display_units(value)
        if self._fsect_dlat_units_combo.currentData() == "feet":
            return f"{display_value:.3f}".rstrip("0").rstrip(".")
        return f"{int(round(display_value))}"

    def _on_fsect_type_changed(
        self, row_index: int, widget: QtWidgets.QComboBox
    ) -> None:
        if self._updating_fsect_table:
            return
        section_index = self._selected_section_index
        if section_index is None:
            return
        selection = widget.currentData()
        if selection is None:
            return
        surface_type, type2 = selection
        type_item = self._fsect_table.item(row_index, 3)
        if type_item is not None:
            type_item.setText(self._fsect_type_description(surface_type, type2))
        self._preview.update_fsection_type(
            section_index,
            row_index,
            surface_type=surface_type,
            type2=type2,
        )

    def _on_fsect_diagram_dlat_changed(
        self, section_index: int, row_index: int, endpoint: str, new_dlat: float
    ) -> None:
        if endpoint == "start":
            self._preview.update_fsection_dlat(
                section_index, row_index, start_dlat=new_dlat
            )
        else:
            self._preview.update_fsection_dlat(
                section_index, row_index, end_dlat=new_dlat
            )
        self._update_fsect_table(section_index)

    @staticmethod
    def _fsect_type_options() -> list[tuple[str, int, int]]:
        fence_type = min(FENCE_TYPE2) if FENCE_TYPE2 else 0
        return [
            ("Grass", 0, 0),
            ("Dry grass", 1, 0),
            ("Dirt", 2, 0),
            ("Sand", 3, 0),
            ("Concrete", 4, 0),
            ("Asphalt", 5, 0),
            ("Paint (Curbing)", 6, 0),
            ("Wall", 7, 0),
            ("Wall (Fence)", 7, fence_type),
            ("Armco", 8, 0),
            ("Armco (Fence)", 8, fence_type),
        ]

    @staticmethod
    def _fsect_type_index(surface_type: int, type2: int) -> int:
        is_fence = surface_type in {7, 8} and type2 in FENCE_TYPE2
        options = SGViewerWindow._fsect_type_options()
        for index, (_label, option_surface, option_type2) in enumerate(options):
            option_fence = (
                option_surface in {7, 8} and option_type2 in FENCE_TYPE2
            )
            if option_surface == surface_type and option_fence == is_fence:
                return index
        return 0

    @staticmethod
    def _fsect_type_description(surface_type: int, type2: int) -> str:
        ground_map = {
            0: "Grass",
            1: "Dry grass",
            2: "Dirt",
            3: "Sand",
            4: "Concrete",
            5: "Asphalt",
            6: "Paint (Curbing)",
        }
        if surface_type in ground_map:
            return ground_map[surface_type]
        if surface_type in {7, 8}:
            base = "Wall" if surface_type == 7 else "Armco"
            if type2 in FENCE_TYPE2:
                return f"{base} (Fence)"
            return base
        return "Unknown"

    def update_window_title(
        self,
        *,
        path: Path | None,
        is_dirty: bool,
        is_untitled: bool = False,
    ) -> None:
        if is_untitled:
            name = "Untitled"
        elif path is not None:
            name = path.name
        else:
            self.setWindowTitle("SG Viewer")
            return

        dirty_marker = "*" if is_dirty else ""
        self.setWindowTitle(f"{name}{dirty_marker} — SG Viewer")
