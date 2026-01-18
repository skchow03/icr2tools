from __future__ import annotations

from pathlib import Path
from typing import List

from PyQt5 import QtCore, QtWidgets

from sg_viewer.preview.context import PreviewContext
from sg_viewer.ui.elevation_profile import ElevationProfileWidget
from sg_viewer.ui.features_preview_widget import FeaturesPreviewWidget
from sg_viewer.ui.preview_widget import SGPreviewWidget
from sg_viewer.models.selection import SectionSelection
from sg_viewer.ui.viewer_controller import SGViewerController
from icr2_core.trk.trk_utils import ground_type_name
from icr2_core.trk.utils import sg_ground_to_trk


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

        self._preview: PreviewContext = SGPreviewWidget(
            show_status=self.show_status_message
        )
        self._features_preview = FeaturesPreviewWidget()
        self._current_selection: SectionSelection | None = None
        self._sidebar = QtWidgets.QWidget()
        self._features_sidebar = QtWidgets.QWidget()
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
        self._section_table_button = QtWidgets.QPushButton("Section Table")
        self._section_table_button.setEnabled(False)
        self._heading_table_button = QtWidgets.QPushButton("Heading Table")
        self._heading_table_button.setEnabled(False)
        self._profile_widget = ElevationProfileWidget()
        self._xsect_combo = QtWidgets.QComboBox()
        self._xsect_combo.setEnabled(False)
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
        self._start_point_label = QtWidgets.QLabel("Start Point: –")
        self._end_point_label = QtWidgets.QLabel("End Point: –")
        self._features_section_combo = QtWidgets.QComboBox()
        self._features_section_combo.setEnabled(False)
        self._features_prev_button = QtWidgets.QPushButton("Previous")
        self._features_next_button = QtWidgets.QPushButton("Next")
        self._features_prev_button.setEnabled(False)
        self._features_next_button.setEnabled(False)
        self._features_fsect_table = QtWidgets.QTableWidget(10, 4)
        self._features_fsect_table.setHorizontalHeaderLabels(
            ["Surface/Boundary", "Type", "Start DLAT", "End DLAT"]
        )
        self._features_fsect_table.verticalHeader().setVisible(False)
        self._features_fsect_table.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.SelectedClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
        )
        self._features_fsect_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self._features_fsect_table.setFocusPolicy(QtCore.Qt.StrongFocus)
        self._features_fsect_table.setMinimumWidth(440)
        header = self._features_fsect_table.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        header.setStretchLastSection(True)
        self._features_fsect_table.itemChanged.connect(
            self._on_features_fsect_item_changed
        )
        self._features_fsect_rows: list[dict[str, int]] = []
        self._updating_features_fsect_table = False

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
        sidebar_layout.addWidget(self._start_point_label)
        sidebar_layout.addWidget(self._end_point_label)
        sidebar_layout.addStretch()
        self._sidebar.setLayout(sidebar_layout)

        features_sidebar_layout = QtWidgets.QVBoxLayout()
        features_sidebar_layout.addWidget(QtWidgets.QLabel("Section"))
        features_sidebar_layout.addWidget(self._features_section_combo)
        features_nav_layout = QtWidgets.QHBoxLayout()
        features_nav_layout.addWidget(self._features_prev_button)
        features_nav_layout.addWidget(self._features_next_button)
        features_sidebar_layout.addLayout(features_nav_layout)
        features_sidebar_layout.addWidget(QtWidgets.QLabel("Fsections"))
        features_sidebar_layout.addWidget(self._features_fsect_table)
        features_sidebar_layout.addStretch()
        self._features_sidebar.setLayout(features_sidebar_layout)
        self._features_sidebar.setMinimumWidth(460)

        preview_column = QtWidgets.QWidget()
        preview_column_layout = QtWidgets.QVBoxLayout()
        preview_column_layout.addLayout(navigation_layout)
        preview_column_layout.addWidget(self._preview, stretch=5)

        profile_controls = QtWidgets.QHBoxLayout()
        profile_controls.addWidget(QtWidgets.QLabel("Elevation X-Section:"))
        profile_controls.addWidget(self._xsect_combo)
        preview_column_layout.addLayout(profile_controls)
        preview_column_layout.addWidget(self._profile_widget, stretch=2)
        preview_column.setLayout(preview_column_layout)

        geometry_container = QtWidgets.QWidget()
        geometry_layout = QtWidgets.QHBoxLayout()
        geometry_layout.addWidget(preview_column, stretch=1)
        geometry_layout.addWidget(self._sidebar)
        geometry_container.setLayout(geometry_layout)

        features_container = QtWidgets.QWidget()
        features_layout = QtWidgets.QHBoxLayout()
        features_preview_column = QtWidgets.QWidget()
        features_preview_layout = QtWidgets.QVBoxLayout()
        features_preview_layout.addWidget(self._features_preview, stretch=3)
        features_preview_column.setLayout(features_preview_layout)
        features_layout.addWidget(features_preview_column, stretch=1)
        features_layout.addWidget(self._features_sidebar)
        features_container.setLayout(features_layout)

        self._tabs = QtWidgets.QTabWidget()
        self._geometry_tab_index = self._tabs.addTab(geometry_container, "Geometry")
        self._features_tab_index = self._tabs.addTab(features_container, "Features")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        self.setCentralWidget(self._tabs)

        self.controller = SGViewerController(self)
        self.refresh_features_preview()

    @property
    def preview(self) -> PreviewContext:
        return self._preview

    @property
    def features_preview(self) -> FeaturesPreviewWidget:
        return self._features_preview

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

    @property
    def features_section_combo(self) -> QtWidgets.QComboBox:
        return self._features_section_combo

    @property
    def features_prev_button(self) -> QtWidgets.QPushButton:
        return self._features_prev_button

    @property
    def features_next_button(self) -> QtWidgets.QPushButton:
        return self._features_next_button

    def refresh_features_preview(self) -> None:
        trk, cline, sampled_centerline, sampled_bounds = (
            self._preview.get_surface_preview_data()
        )
        self._features_preview.set_surface_data(
            trk, cline, sampled_centerline, sampled_bounds
        )
        self._features_preview.set_section_selection(self._current_selection)
        self.refresh_features_sidebar()

    def refresh_features_sidebar(self) -> None:
        sections, _ = self._preview.get_section_set()
        self._features_section_combo.blockSignals(True)
        self._features_section_combo.clear()
        for index, section in enumerate(sections):
            label = f"Section {index}: {section.type_name.title()}"
            self._features_section_combo.addItem(label, index)
        has_sections = bool(sections)
        self._features_section_combo.setEnabled(has_sections)
        self._features_prev_button.setEnabled(has_sections)
        self._features_next_button.setEnabled(has_sections)
        self._features_section_combo.blockSignals(False)

        if self._current_selection is not None:
            combo_index = self._features_section_combo.findData(
                self._current_selection.index
            )
            if combo_index != -1:
                self._features_section_combo.blockSignals(True)
                self._features_section_combo.setCurrentIndex(combo_index)
                self._features_section_combo.blockSignals(False)
        else:
            self._features_section_combo.blockSignals(True)
            self._features_section_combo.setCurrentIndex(-1)
            self._features_section_combo.blockSignals(False)
        self._update_features_fsect_table(self._current_selection)

    def _on_tab_changed(self, index: int) -> None:
        if index == self._features_tab_index:
            self.refresh_features_preview()

    def show_status_message(self, message: str) -> None:
        self._preview.set_status_text(message)

    def update_scale_label(self, scale: float | None) -> None:
        if scale is None or scale <= 0:
            self._scale_label.setText("Scale: –")
            return

        self._scale_label.setText(f"Scale: 1px = {1 / scale:.1f} 500ths")

    def update_track_length_label(self, text: str) -> None:
        self._track_length_label.setText(text)

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

        if selection is None:
            self._current_selection = None
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
            self._start_point_label.setText("Start Point: –")
            self._end_point_label.setText("End Point: –")
            self._profile_widget.set_selected_range(None)
            self._features_preview.set_section_selection(None)
            self._update_features_selection(None)
            return

        self._current_selection = selection
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

        self._start_point_label.setText(
            f"Start Point: {_fmt_point(selection.start_point)}"
        )
        self._end_point_label.setText(f"End Point: {_fmt_point(selection.end_point)}")

        selected_range = self._preview.get_section_range(selection.index)
        self._profile_widget.set_selected_range(selected_range)
        self._features_preview.set_section_selection(selection)
        self._update_features_selection(selection)

    @staticmethod
    def _format_section_link(prefix: str, section_id: int) -> str:
        connection = "Not connected" if section_id == -1 else str(section_id)
        return f"{prefix} Section: {connection}"

    def _update_features_selection(self, selection: SectionSelection | None) -> None:
        if selection is None:
            self._features_section_combo.blockSignals(True)
            self._features_section_combo.setCurrentIndex(-1)
            self._features_section_combo.blockSignals(False)
            self._update_features_fsect_table(None)
            return

        combo_index = self._features_section_combo.findData(selection.index)
        if combo_index != -1:
            self._features_section_combo.blockSignals(True)
            self._features_section_combo.setCurrentIndex(combo_index)
            self._features_section_combo.blockSignals(False)
        self._update_features_fsect_table(selection)

    def _update_features_fsect_table(self, selection: SectionSelection | None) -> None:
        placeholder = "—"
        self._updating_features_fsect_table = True
        self._features_fsect_table.blockSignals(True)
        self._features_fsect_rows = []
        for row in range(10):
            for col in range(4):
                item = QtWidgets.QTableWidgetItem(placeholder)
                item.setTextAlignment(QtCore.Qt.AlignCenter)
                item.setFlags(QtCore.Qt.ItemIsEnabled)
                self._features_fsect_table.setItem(row, col, item)

        sgfile = self._preview.sgfile
        if sgfile is None or selection is None:
            self._features_fsect_table.blockSignals(False)
            self._updating_features_fsect_table = False
            return

        if selection.index < 0 or selection.index >= len(sgfile.sects):
            self._features_fsect_table.blockSignals(False)
            self._updating_features_fsect_table = False
            return

        section = sgfile.sects[selection.index]
        fsections = []
        for index in range(section.num_fsects):
            ftype1 = section.ftype1[index]
            ftype2 = section.ftype2[index]
            fstart = section.fstart[index]
            fend = section.fend[index]
            sort_key = (min(fstart, fend), max(fstart, fend), index)
            fsections.append((sort_key, ftype1, ftype2, fstart, fend, index))

        fsections.sort(key=lambda item: item[0])

        for row, (_, ftype1, ftype2, fstart, fend, fsect_index) in enumerate(
            fsections[:10]
        ):
            is_surface = ftype1 in {0, 1, 2, 3, 4, 5, 6}
            kind = "Surface" if is_surface else "Boundary"
            type_name = self._format_fsect_type(ftype1, ftype2)
            values = [kind, type_name, str(fstart), str(fend)]
            self._features_fsect_rows.append(
                {"index": fsect_index, "start": int(fstart), "end": int(fend)}
            )
            for col, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                item.setTextAlignment(QtCore.Qt.AlignCenter)
                item.setData(QtCore.Qt.UserRole, fsect_index)
                if col in {2, 3}:
                    item.setFlags(
                        QtCore.Qt.ItemIsSelectable
                        | QtCore.Qt.ItemIsEnabled
                        | QtCore.Qt.ItemIsEditable
                    )
                    item.setData(QtCore.Qt.UserRole + 1, value)
                else:
                    item.setFlags(QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled)
                self._features_fsect_table.setItem(row, col, item)
        self._features_fsect_table.blockSignals(False)
        self._updating_features_fsect_table = False

    def _format_fsect_type(self, ftype1: int, ftype2: int) -> str:
        if ftype1 in {0, 1, 2, 3, 4, 5, 6}:
            trk_type = sg_ground_to_trk(ftype1)
            surface_name = ground_type_name(trk_type) if trk_type is not None else None
            return surface_name or f"Surface {ftype1}"

        wall_label = "Wall" if ftype1 == 7 else "Armco" if ftype1 == 8 else f"Boundary {ftype1}"
        fence_label = (
            "Fence"
            if ftype2 in {2, 6, 10, 14}
            else "No fence"
            if ftype2 in {0, 4, 8, 12}
            else f"Fence {ftype2}"
        )
        return f"{wall_label} / {fence_label}"

    def _on_features_fsect_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        if self._updating_features_fsect_table:
            return

        row = item.row()
        column = item.column()
        if column not in {2, 3}:
            return

        if row >= len(self._features_fsect_rows):
            return

        fsect_info = self._features_fsect_rows[row]
        fsect_index = fsect_info["index"]
        previous_text = item.data(QtCore.Qt.UserRole + 1)
        try:
            new_value = int(item.text())
        except (TypeError, ValueError):
            self._restore_fsect_cell(item, previous_text)
            self.show_status_message("DLAT values must be integers.")
            return

        prev_value = None
        next_value = None
        field = "start" if column == 2 else "end"
        if row > 0:
            prev_value = self._features_fsect_rows[row - 1][field]
        if row + 1 < len(self._features_fsect_rows):
            next_value = self._features_fsect_rows[row + 1][field]

        if prev_value is not None and new_value < prev_value:
            self._restore_fsect_cell(item, previous_text)
            self.show_status_message("DLAT value must be >= previous fsection.")
            return

        if next_value is not None and new_value > next_value:
            self._restore_fsect_cell(item, previous_text)
            self.show_status_message("DLAT value must be <= next fsection.")
            return

        selection = self._current_selection
        if selection is None:
            self._restore_fsect_cell(item, previous_text)
            return

        updated = self._preview.update_fsection_dlat(
            selection.index,
            fsect_index,
            start_dlat=new_value if column == 2 else None,
            end_dlat=new_value if column == 3 else None,
        )
        if not updated:
            self._restore_fsect_cell(item, previous_text)
            return

        item.setData(QtCore.Qt.UserRole + 1, str(new_value))
        self.refresh_features_preview()

    def _restore_fsect_cell(
        self, item: QtWidgets.QTableWidgetItem, previous_text: str | None
    ) -> None:
        if previous_text is None:
            previous_text = "—"
        self._updating_features_fsect_table = True
        self._features_fsect_table.blockSignals(True)
        item.setText(previous_text)
        self._features_fsect_table.blockSignals(False)
        self._updating_features_fsect_table = False
    
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
