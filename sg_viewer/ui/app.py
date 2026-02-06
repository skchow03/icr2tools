from __future__ import annotations

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
    units_from_500ths,
    units_to_500ths,
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
        self._updating_xsect_table = False
        self._measurement_unit_data = "feet"

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
        self._right_sidebar_tabs = QtWidgets.QTabWidget()
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
        self._radii_button = QtWidgets.QCheckBox("Show Radii")
        self._radii_button.setChecked(True)
        self._axes_button = QtWidgets.QCheckBox("Show Axes")
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
        self._section_table_action: QtWidgets.QAction | None = None
        self._heading_table_action: QtWidgets.QAction | None = None
        self._xsect_table_action: QtWidgets.QAction | None = None
        self._profile_widget = ElevationProfileWidget()
        self._xsect_elevation_widget = XsectElevationWidget()
        self._xsect_combo = QtWidgets.QComboBox()
        self._xsect_combo.setEnabled(False)
        self._copy_xsect_button = QtWidgets.QPushButton("Copy X-Section to All")
        self._copy_xsect_button.setEnabled(False)
        self._track_stats_label = QtWidgets.QLabel("Track Length: –")
        self._section_index_label = QtWidgets.QLabel("Current Section: –")
        self._section_start_dlong_label = QtWidgets.QLabel("Starting DLONG: –")
        self._section_end_dlong_label = QtWidgets.QLabel("Ending DLONG: –")
        self._previous_label = QtWidgets.QLabel("Previous Section: –")
        self._next_label = QtWidgets.QLabel("Next Section: –")
        self._section_length_label = QtWidgets.QLabel("Section Length: –")
        self._radius_label = QtWidgets.QLabel("Radius: –")
        self._measurement_units_combo = QtWidgets.QComboBox()
        self._measurement_units_combo.addItem("Feet", "feet")
        self._measurement_units_combo.addItem("Meter", "meter")
        self._measurement_units_combo.addItem("Inch", "inch")
        self._measurement_units_combo.addItem("500ths", "500ths")
        self._measurement_units_combo.setCurrentIndex(0)
        self._measurement_units_combo.currentIndexChanged.connect(
            self._on_measurement_units_changed
        )
        self._fsect_table = QtWidgets.QTableWidget(0, 4)
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
        self._xsect_elevation_table = QtWidgets.QTableWidget(0, 3)
        self.update_xsect_table_headers()
        self._xsect_elevation_table.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.SelectedClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
        )
        self._xsect_elevation_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self._xsect_elevation_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows
        )
        self._xsect_elevation_table.verticalHeader().setVisible(False)
        self._xsect_elevation_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeToContents
        )
        self._xsect_elevation_table.horizontalHeader().setStretchLastSection(False)
        self._xsect_elevation_table.setSizeAdjustPolicy(
            QtWidgets.QAbstractScrollArea.AdjustToContents
        )
        self._xsect_elevation_table.setSizePolicy(
            QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Preferred
        )
        self._xsect_elevation_table.setMinimumHeight(140)
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
        self._altitude_min_spin.setSuffix(" ft")
        self._altitude_max_spin.setSuffix(" ft")
        self._altitude_set_range_button = QtWidgets.QPushButton("Set Range...")
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
        self._grade_set_range_button = QtWidgets.QPushButton("Set Range...")

        navigation_layout = QtWidgets.QHBoxLayout()
        #navigation_layout.addWidget(self._new_track_button)
        navigation_layout.addWidget(self._prev_button)
        navigation_layout.addWidget(self._next_button)
        navigation_layout.addWidget(self._new_straight_button)
        navigation_layout.addWidget(self._new_curve_button)
        navigation_layout.addWidget(self._split_section_button)
        navigation_layout.addWidget(self._delete_section_button)
        navigation_layout.addWidget(self._set_start_finish_button)
        elevation_layout = QtWidgets.QFormLayout()
        altitude_container = QtWidgets.QWidget()
        altitude_layout = QtWidgets.QHBoxLayout()
        altitude_layout.setContentsMargins(0, 0, 0, 0)
        altitude_layout.addWidget(self._altitude_slider, stretch=1)
        altitude_layout.addWidget(self._altitude_value_label)
        altitude_layout.addWidget(self._altitude_set_range_button)
        altitude_container.setLayout(altitude_layout)
        elevation_layout.addRow("Altitude (xsect):", altitude_container)
        grade_container = QtWidgets.QWidget()
        grade_layout = QtWidgets.QHBoxLayout()
        grade_layout.setContentsMargins(0, 0, 0, 0)
        grade_layout.addWidget(self._grade_slider, stretch=1)
        grade_layout.addWidget(self._grade_value_label)
        grade_layout.addWidget(self._grade_set_range_button)
        grade_container.setLayout(grade_layout)
        elevation_layout.addRow("Grade (xsect):", grade_container)
        altitude_grade_sidebar = QtWidgets.QWidget()
        altitude_grade_sidebar_layout = QtWidgets.QVBoxLayout()
        altitude_grade_sidebar_layout.addLayout(elevation_layout)
        altitude_grade_sidebar_layout.addWidget(QtWidgets.QLabel("X-Section Elevations"))
        altitude_grade_sidebar_layout.addWidget(self._xsect_elevation_table)
        altitude_profile_controls = QtWidgets.QHBoxLayout()
        altitude_profile_controls.addWidget(QtWidgets.QLabel("Elevation X-Section:"))
        altitude_profile_controls.addWidget(self._xsect_combo)
        altitude_profile_controls.addWidget(self._copy_xsect_button)
        altitude_profile_controls.addWidget(self._xsect_dlat_line_checkbox)
        altitude_grade_sidebar_layout.addLayout(altitude_profile_controls)
        altitude_grade_sidebar_layout.addWidget(self._profile_widget, stretch=2)
        altitude_grade_sidebar_layout.addWidget(
            QtWidgets.QLabel("Section X-Section Elevation")
        )
        altitude_grade_sidebar_layout.addWidget(self._xsect_elevation_widget, stretch=1)
        altitude_grade_sidebar_layout.addStretch()
        altitude_grade_sidebar.setLayout(altitude_grade_sidebar_layout)

        fsect_sidebar = QtWidgets.QWidget()
        fsect_sidebar_layout = QtWidgets.QVBoxLayout()
        fsect_sidebar_layout.addWidget(self._sg_fsects_checkbox)
        fsect_sidebar_layout.addWidget(self._refresh_fsects_button)
        fsect_sidebar_layout.addWidget(self._copy_fsects_prev_button)
        fsect_sidebar_layout.addWidget(self._copy_fsects_next_button)
        fsect_sidebar_layout.addWidget(self._add_fsect_button)
        fsect_sidebar_layout.addWidget(self._delete_fsect_button)
        fsect_sidebar_layout.addWidget(QtWidgets.QLabel("Fsects"))
        fsect_sidebar_layout.addWidget(self._fsect_table)
        fsect_sidebar_layout.addWidget(QtWidgets.QLabel("Fsect Diagram"))
        fsect_sidebar_layout.addWidget(self._fsect_diagram)
        fsect_sidebar_layout.addStretch()
        fsect_sidebar.setLayout(fsect_sidebar_layout)

        view_options_sidebar = QtWidgets.QWidget()
        view_options_layout = QtWidgets.QVBoxLayout()
        view_options_layout.addWidget(self._radii_button)
        view_options_layout.addWidget(self._axes_button)
        unit_layout = QtWidgets.QHBoxLayout()
        unit_layout.addWidget(QtWidgets.QLabel("Unit of Measurement:"))
        unit_layout.addWidget(self._measurement_units_combo)
        view_options_layout.addLayout(unit_layout)
        view_options_layout.addStretch()
        view_options_sidebar.setLayout(view_options_layout)

        self._right_sidebar_tabs.addTab(altitude_grade_sidebar, "Altitude/Grade")
        self._right_sidebar_tabs.addTab(fsect_sidebar, "Fsects")
        self._right_sidebar_tabs.addTab(view_options_sidebar, "View Options")
        # Avoid locking the splitter to the tabs' initial size hint (which can become
        # very wide due to table content) so users can shrink the right sidebar.
        self._right_sidebar_tabs.setMinimumWidth(260)
        self._right_sidebar_tabs.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred,
            QtWidgets.QSizePolicy.Expanding,
        )

        preview_column = QtWidgets.QWidget()
        preview_column_layout = QtWidgets.QVBoxLayout()
        preview_column_layout.addLayout(navigation_layout)
        preview_column_layout.addWidget(self._preview, stretch=5)
        selection_summary_group = QtWidgets.QGroupBox("Track / Section")
        selection_summary_layout = QtWidgets.QVBoxLayout()
        selection_summary_layout.addWidget(self._track_stats_label)
        selection_summary_layout.addWidget(self._section_index_label)
        selection_summary_layout.addWidget(self._section_start_dlong_label)
        selection_summary_layout.addWidget(self._section_end_dlong_label)
        selection_summary_layout.addWidget(self._previous_label)
        selection_summary_layout.addWidget(self._next_label)
        selection_summary_layout.addWidget(self._section_length_label)
        selection_summary_layout.addWidget(self._radius_label)
        selection_summary_group.setLayout(selection_summary_layout)
        preview_column_layout.addWidget(selection_summary_group)
        preview_column.setLayout(preview_column_layout)

        container = QtWidgets.QWidget()
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(preview_column)
        splitter.addWidget(self._right_sidebar_tabs)
        splitter.setStretchFactor(0, 1)
        splitter.setCollapsible(1, False)
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
    def radii_button(self) -> QtWidgets.QCheckBox:
        return self._radii_button

    @property
    def axes_button(self) -> QtWidgets.QCheckBox:
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
    def xsect_elevation_table(self) -> QtWidgets.QTableWidget:
        return self._xsect_elevation_table

    def set_section_table_action(self, action: QtWidgets.QAction) -> None:
        self._section_table_action = action

    def set_heading_table_action(self, action: QtWidgets.QAction) -> None:
        self._heading_table_action = action

    def set_xsect_table_action(self, action: QtWidgets.QAction) -> None:
        self._xsect_table_action = action

    def set_table_actions_enabled(self, enabled: bool) -> None:
        if self._section_table_action is not None:
            self._section_table_action.setEnabled(enabled)
        if self._heading_table_action is not None:
            self._heading_table_action.setEnabled(enabled)
        if self._xsect_table_action is not None:
            self._xsect_table_action.setEnabled(enabled)

    @property
    def measurement_units_combo(self) -> QtWidgets.QComboBox:
        return self._measurement_units_combo

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

    @property
    def altitude_set_range_button(self) -> QtWidgets.QPushButton:
        return self._altitude_set_range_button

    @property
    def grade_set_range_button(self) -> QtWidgets.QPushButton:
        return self._grade_set_range_button

    @property
    def is_updating_xsect_table(self) -> bool:
        return self._updating_xsect_table

    def show_status_message(self, message: str) -> None:
        self._preview.set_status_text(message)

    def update_xsect_elevation_table(
        self,
        altitudes: list[int | None],
        grades: list[int | None],
        selected_index: int | None,
        *,
        enabled: bool,
    ) -> None:
        self._updating_xsect_table = True
        self._xsect_elevation_table.blockSignals(True)
        try:
            row_count = min(len(altitudes), len(grades))
            self._xsect_elevation_table.setRowCount(row_count)
            for row in range(row_count):
                xsect_item = QtWidgets.QTableWidgetItem(str(row))
                xsect_item.setFlags(
                    QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled
                )
                altitude_value = altitudes[row]
                altitude_text = (
                    self._format_xsect_altitude(altitude_value)
                    if altitude_value is not None
                    else ""
                )
                altitude_item = QtWidgets.QTableWidgetItem(altitude_text)
                altitude_item.setTextAlignment(
                    QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
                )
                grade_value = grades[row]
                grade_text = f"{grade_value}" if grade_value is not None else ""
                grade_item = QtWidgets.QTableWidgetItem(grade_text)
                grade_item.setTextAlignment(
                    QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
                )
                self._xsect_elevation_table.setItem(row, 0, xsect_item)
                self._xsect_elevation_table.setItem(row, 1, altitude_item)
                self._xsect_elevation_table.setItem(row, 2, grade_item)
            if (
                selected_index is not None
                and 0 <= selected_index < self._xsect_elevation_table.rowCount()
            ):
                self._xsect_elevation_table.setCurrentCell(selected_index, 0)
            self._xsect_elevation_table.resizeColumnsToContents()
            self._xsect_elevation_table.setEnabled(enabled)
        finally:
            self._xsect_elevation_table.blockSignals(False)
            self._updating_xsect_table = False

    def update_track_length_label(self, text: str) -> None:
        self._track_stats_label.setText(text)

    def format_length(self, value: float | int | None) -> str:
        if value is None:
            return "–"
        display = units_from_500ths(value, self._current_measurement_unit())
        decimals = self._measurement_unit_decimals(self._current_measurement_unit())
        unit = self._measurement_unit_label(self._current_measurement_unit())
        if decimals == 0:
            return f"{int(round(display))} {unit}"
        return f"{display:.{decimals}f} {unit}"

    def format_length_with_secondary(self, value: float | int | None) -> str:
        primary = self.format_length(value)
        if value is None:
            return primary

        unit = self._current_measurement_unit()
        feet_value = units_from_500ths(value, "feet")
        if unit == "feet":
            miles = feet_value / 5280.0
            return f"{primary} ({miles:.3f} miles)"
        if unit == "meter":
            kilometers = feet_value * 0.3048 / 1000.0
            return f"{primary} ({kilometers:.3f} km)"
        return primary

    def update_elevation_inputs(
        self, altitude: int | None, grade: int | None, enabled: bool
    ) -> None:
        self._altitude_slider.blockSignals(True)
        self._grade_slider.blockSignals(True)
        altitude_value = altitude if altitude is not None else 0
        altitude_feet = feet_from_500ths(altitude_value)
        self._altitude_slider.setValue(feet_to_slider_units(altitude_feet))
        self._altitude_value_label.setText(
            self._format_altitude_for_units(altitude_value)
        )
        grade_value = grade if grade is not None else 0
        self._grade_slider.setValue(grade_value)
        self._grade_value_label.setText(str(grade_value))
        self._altitude_slider.setEnabled(enabled)
        self._grade_slider.setEnabled(enabled)
        self._altitude_slider.blockSignals(False)
        self._grade_slider.blockSignals(False)

    def _current_measurement_unit(self) -> str:
        return str(self._measurement_units_combo.currentData())

    @staticmethod
    def _measurement_unit_label(unit: str) -> str:
        return {"feet": "ft", "meter": "m", "inch": "in", "500ths": "500ths"}.get(unit, "500ths")

    @staticmethod
    def _measurement_unit_decimals(unit: str) -> int:
        return {"feet": 1, "meter": 3, "inch": 1, "500ths": 0}.get(unit, 0)

    @staticmethod
    def _measurement_unit_step(unit: str) -> float:
        return {"feet": 0.1, "meter": 0.05, "inch": 1.0, "500ths": 50.0}.get(unit, 50.0)

    def update_xsect_table_headers(self) -> None:
        unit_label = self._xsect_altitude_units_label()
        self._xsect_elevation_table.setHorizontalHeaderLabels(
            ["Xsect", f"Altitude ({unit_label})", "Grade"]
        )

    def _xsect_altitude_units_label(self) -> str:
        return self._measurement_unit_label(self._current_measurement_unit())

    def xsect_altitude_to_display_units(self, value: int) -> float:
        return units_from_500ths(value, self._current_measurement_unit())

    def xsect_altitude_from_display_units(self, value: float) -> int:
        return units_to_500ths(value, self._current_measurement_unit())

    def _format_xsect_altitude(self, value: int) -> str:
        display_value = self.xsect_altitude_to_display_units(value)
        decimals = self._measurement_unit_decimals(self._current_measurement_unit())
        if decimals == 0:
            return f"{int(round(display_value))}"
        return f"{display_value:.{decimals}f}"

    def update_grade_display(self, value: int) -> None:
        self._grade_value_label.setText(str(value))

    def update_altitude_display(self, value: int) -> None:
        altitude_feet = feet_from_slider_units(value)
        altitude = units_to_500ths(altitude_feet, "feet")
        self._altitude_value_label.setText(self._format_altitude_for_units(altitude))

    def update_selection_sidebar(self, selection: SectionSelection | None) -> None:
        if selection is None:
            self._selected_section_index = None
            self._section_index_label.setText("Current Section: –")
            self._section_start_dlong_label.setText("Starting DLONG: –")
            self._section_end_dlong_label.setText("Ending DLONG: –")
            self._radius_label.setText("Radius: –")
            self._previous_label.setText("Previous Section: –")
            self._next_label.setText("Next Section: –")
            self._section_length_label.setText("Section Length: –")
            self._profile_widget.set_selected_range(None)
            self._update_fsect_table(None)
            return

        self._selected_section_index = selection.index
        self._section_index_label.setText(f"Current Section: {selection.index}")
        self._section_start_dlong_label.setText(
            f"Starting DLONG: {self.format_length(selection.start_dlong)}"
        )
        self._section_end_dlong_label.setText(
            f"Ending DLONG: {self.format_length(selection.end_dlong)}"
        )
        self._section_length_label.setText(
            f"Section Length: {self.format_length_with_secondary(selection.length)}"
        )

        radius_value = selection.sg_radius
        if radius_value is None:
            radius_value = selection.radius
        self._radius_label.setText(f"Radius: {self.format_length(radius_value)}")
        self._previous_label.setText(self._format_section_link("Previous", selection.previous_id))
        self._next_label.setText(self._format_section_link("Next", selection.next_id))

        selected_range = self._preview.get_section_range(selection.index)
        self._profile_widget.set_selected_range(selected_range)
        self._update_fsect_table(selection.index)

    @staticmethod
    def _format_section_link(prefix: str, section_id: int) -> str:
        connection = "Not connected" if section_id == -1 else f"{section_id}"
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
            self._fsect_table.setCellWidget(row_index, 3, combo)
        if not fsects:
            self._fsect_table.setRowCount(0)
        self._updating_fsect_table = False
        self._fsect_table.resizeColumnsToContents()
        prev_fsects = (
            self._preview.get_section_fsects(section_index - 1)
            if section_index is not None
            else []
        )
        next_fsects = (
            self._preview.get_section_fsects(section_index + 1)
            if section_index is not None
            else []
        )
        self._fsect_diagram.set_fsects(
            section_index,
            fsects,
            prev_fsects=prev_fsects,
            next_fsects=next_fsects,
        )

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

    def _on_measurement_units_changed(self) -> None:
        previous_unit = self._measurement_unit_data
        self._measurement_unit_data = str(self._measurement_units_combo.currentData())
        self._sync_altitude_range_spin_units(previous_unit)
        self.update_xsect_table_headers()
        self._update_fsect_table_headers()
        self._update_fsect_table(self._selected_section_index)

    def _update_fsect_table_headers(self) -> None:
        unit_label = self._fsect_dlat_units_label()
        self._fsect_table.setHorizontalHeaderLabels(
            [
                "Index",
                f"Start DLAT ({unit_label})",
                f"End DLAT ({unit_label})",
                "Type Selection",
            ]
        )

    def _fsect_dlat_units_label(self) -> str:
        return self._measurement_unit_label(self._current_measurement_unit())

    def _fsect_dlat_to_display_units(self, value: float) -> float:
        return units_from_500ths(value, self._current_measurement_unit())

    def _fsect_dlat_from_display_units(self, value: float) -> float:
        return float(units_to_500ths(value, self._current_measurement_unit()))

    def _format_fsect_dlat(self, value: float) -> str:
        display_value = self._fsect_dlat_to_display_units(value)
        decimals = self._measurement_unit_decimals(self._current_measurement_unit())
        if decimals == 0:
            return f"{int(round(display_value))}"
        return f"{display_value:.{decimals}f}".rstrip("0").rstrip(".")

    def altitude_display_to_feet(self, value: float) -> float:
        altitude_500ths = units_to_500ths(value, self._current_measurement_unit())
        return feet_from_500ths(altitude_500ths)

    def feet_to_altitude_display(self, value_feet: float) -> float:
        altitude_500ths = units_to_500ths(value_feet, "feet")
        return units_from_500ths(altitude_500ths, self._current_measurement_unit())

    def altitude_display_step(self) -> float:
        return self._measurement_unit_step(self._current_measurement_unit())

    def _format_altitude_for_units(self, altitude_500ths: int) -> str:
        unit = self._current_measurement_unit()
        value = units_from_500ths(altitude_500ths, unit)
        decimals = self._measurement_unit_decimals(unit)
        if decimals == 0:
            return f"{int(round(value))}"
        return f"{value:.{decimals}f}"

    def _sync_altitude_range_spin_units(self, previous_unit: str) -> None:
        current_unit = self._current_measurement_unit()

        current_min_500ths = units_to_500ths(self._altitude_min_spin.value(), previous_unit)
        current_max_500ths = units_to_500ths(self._altitude_max_spin.value(), previous_unit)

        current_min_display = units_from_500ths(current_min_500ths, current_unit)
        current_max_display = units_from_500ths(current_max_500ths, current_unit)

        spin_decimals = self._measurement_unit_decimals(current_unit)
        spin_step = self._measurement_unit_step(current_unit)
        spin_min = units_from_500ths(SGDocument.ELEVATION_MIN, current_unit)
        spin_max = units_from_500ths(SGDocument.ELEVATION_MAX, current_unit)
        suffix = f" {self._measurement_unit_label(current_unit)}"

        for spin in (self._altitude_min_spin, self._altitude_max_spin):
            spin.blockSignals(True)
            spin.setDecimals(spin_decimals)
            spin.setSingleStep(spin_step)
            spin.setSuffix(suffix)
            spin.blockSignals(False)

        self._altitude_min_spin.setRange(spin_min, spin_max - spin_step)
        self._altitude_max_spin.setRange(spin_min + spin_step, spin_max)
        self._altitude_min_spin.setValue(min(max(current_min_display, spin_min), spin_max - spin_step))
        self._altitude_max_spin.setValue(max(min(current_max_display, spin_max), spin_min + spin_step))

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
