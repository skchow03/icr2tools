from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from PyQt5 import QtCore, QtWidgets

from sg_viewer.preview.context import PreviewContext
from sg_viewer.ui.elevation_profile import ElevationProfileWidget
from sg_viewer.ui.features_preview_widget import FeaturesPreviewWidget
from sg_viewer.ui.section_surface_widget import SectionSurfaceWidget
from sg_viewer.ui.preview_widget import SGPreviewWidget
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
        self._section_surface_preview = SectionSurfaceWidget()
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
        self._features_section_label = QtWidgets.QLabel("Selected Section: –")
        self._features_section_combo = QtWidgets.QComboBox()
        self._features_prev_button = QtWidgets.QPushButton("Previous")
        self._features_next_button = QtWidgets.QPushButton("Next")
        self._features_fsect_table = QtWidgets.QTableWidget(10, 4)
        self._features_fsect_table.setHorizontalHeaderLabels(
            ["Type", "Description", "Start DLAT", "End DLAT"]
        )
        self._features_fsect_table.verticalHeader().setVisible(True)
        self._features_fsect_table.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
            | QtWidgets.QAbstractItemView.SelectedClicked
        )
        self._features_fsect_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self._features_fsect_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectItems
        )
        self._features_fsect_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.Stretch
        )
        self._features_fsect_table.setHorizontalScrollBarPolicy(
            QtCore.Qt.ScrollBarAlwaysOff
        )
        self._features_fsect_table.itemChanged.connect(
            self._on_features_fsect_item_changed
        )
        self._features_section_combo.setEnabled(False)
        self._features_prev_button.setEnabled(False)
        self._features_next_button.setEnabled(False)
        self._is_updating_fsect_table = False

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

        features_sidebar_layout = QtWidgets.QVBoxLayout()
        features_section_controls = QtWidgets.QHBoxLayout()
        features_section_controls.addWidget(QtWidgets.QLabel("Jump to section:"))
        features_section_controls.addWidget(self._features_section_combo)
        features_nav_controls = QtWidgets.QHBoxLayout()
        features_nav_controls.addWidget(self._features_prev_button)
        features_nav_controls.addWidget(self._features_next_button)
        features_sidebar_layout.addWidget(QtWidgets.QLabel("Surface/Boundary Fsects"))
        features_sidebar_layout.addWidget(self._features_section_label)
        features_sidebar_layout.addLayout(features_section_controls)
        features_sidebar_layout.addLayout(features_nav_controls)
        features_sidebar_layout.addWidget(self._features_fsect_table)
        features_sidebar_layout.addStretch()
        self._features_sidebar.setLayout(features_sidebar_layout)

        features_container = QtWidgets.QWidget()
        features_layout = QtWidgets.QHBoxLayout()
        features_preview_column = QtWidgets.QWidget()
        features_preview_layout = QtWidgets.QVBoxLayout()
        features_preview_layout.addWidget(self._features_preview, stretch=3)
        features_preview_layout.addWidget(self._section_surface_preview, stretch=1)
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
    def features_section_combo(self) -> QtWidgets.QComboBox:
        return self._features_section_combo

    @property
    def features_prev_button(self) -> QtWidgets.QPushButton:
        return self._features_prev_button

    @property
    def features_next_button(self) -> QtWidgets.QPushButton:
        return self._features_next_button

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

    def refresh_features_preview(self) -> None:
        trk, cline, sampled_centerline, sampled_bounds = (
            self._preview.get_surface_preview_data()
        )
        self._features_preview.set_surface_data(
            trk, cline, sampled_centerline, sampled_bounds
        )
        self.refresh_feature_section_choices()
        self.update_section_surface_preview(self._current_selection)

    def update_section_surface_preview(
        self, selection: SectionSelection | None
    ) -> None:
        trk, _, _, _ = self._preview.get_surface_preview_data()
        self._section_surface_preview.set_section_data(trk, selection)

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
            self.update_section_surface_preview(None)
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
        self.update_section_surface_preview(selection)

    @staticmethod
    def _format_section_link(prefix: str, section_id: int) -> str:
        connection = "Not connected" if section_id == -1 else str(section_id)
        return f"{prefix} Section: {connection}"

    def refresh_feature_section_choices(self) -> None:
        sections, _ = self._preview.get_section_set()
        self._features_section_combo.blockSignals(True)
        self._features_section_combo.clear()
        for idx, section in enumerate(sections):
            self._features_section_combo.addItem(f"Section {idx} ({section.type_name})", idx)
        has_sections = bool(sections)
        self._features_section_combo.setEnabled(has_sections)
        self._features_prev_button.setEnabled(has_sections)
        self._features_next_button.setEnabled(has_sections)
        if self._current_selection and 0 <= self._current_selection.index < len(sections):
            self._features_section_combo.setCurrentIndex(self._current_selection.index)
        else:
            self._features_section_combo.setCurrentIndex(-1)
        self._features_section_combo.blockSignals(False)

    def update_features_sidebar(self, selection: SectionSelection | None) -> None:
        trk, _, _, _ = self._preview.get_surface_preview_data()
        self.refresh_feature_section_choices()
        if selection is None or trk is None:
            self._features_section_label.setText("Selected Section: –")
            self._fill_features_fsect_table([])
            return

        self._features_section_label.setText(f"Selected Section: {selection.index}")
        self._fill_features_fsect_table(
            self._build_fsect_rows(trk, selection.index)
        )

    @dataclass(frozen=True)
    class _FsectRow:
        fsect_type: str
        description: str
        start: str
        end: str
        kind: str
        index: int
        section_index: int
        start_value: Optional[float]

    def _build_fsect_rows(
        self, trk: object, section_index: int
    ) -> list[_FsectRow]:
        if not hasattr(trk, "sects") or section_index < 0:
            return []
        if section_index >= len(trk.sects):
            return []
        sect = trk.sects[section_index]
        rows: list[SGViewerWindow._FsectRow] = []

        def _format_value(value: object) -> str:
            if value is None or value == "–":
                return "–"
            try:
                return f"{int(round(float(value)))}"
            except (TypeError, ValueError):
                return str(value)

        def _parse_value(value: object) -> Optional[float]:
            if value is None or value == "–":
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        def _append_row(
            kind: str,
            idx: int,
            start: object,
            end: object,
            fsect_type: str,
            description: str,
        ) -> None:
            rows.append(
                SGViewerWindow._FsectRow(
                    fsect_type=fsect_type,
                    description=description,
                    start=_format_value(start),
                    end=_format_value(end),
                    kind=kind,
                    index=idx,
                    section_index=section_index,
                    start_value=_parse_value(start),
                )
            )

        for idx in range(getattr(sect, "ground_fsects", 0)):
            ground_type = sect.ground_type[idx] if idx < len(sect.ground_type) else "–"
            start = sect.ground_dlat_start[idx] if idx < len(sect.ground_dlat_start) else "–"
            end = sect.ground_dlat_end[idx] if idx < len(sect.ground_dlat_end) else "–"
            _append_row("surface", idx, start, end, "Surface", str(ground_type))
        for idx in range(getattr(sect, "num_bounds", 0)):
            bound_type = sect.bound_type[idx] if idx < len(sect.bound_type) else "–"
            start = sect.bound_dlat_start[idx] if idx < len(sect.bound_dlat_start) else "–"
            end = sect.bound_dlat_end[idx] if idx < len(sect.bound_dlat_end) else "–"
            _append_row("boundary", idx, start, end, "Wall", str(bound_type))

        rows.sort(
            key=lambda row: (row.start_value is None, -(row.start_value or 0.0))
        )
        return rows[:10]

    def _fill_features_fsect_table(
        self, rows: list[_FsectRow]
    ) -> None:
        self._is_updating_fsect_table = True
        try:
            for row_index in range(10):
                if row_index < len(rows):
                    row = rows[row_index]
                    values = (row.fsect_type, row.description, row.start, row.end)
                    metadata = {
                        "kind": row.kind,
                        "index": row.index,
                        "section": row.section_index,
                    }
                else:
                    values = ("–", "–", "–", "–")
                    metadata = None
                for col_index, value in enumerate(values):
                    item = QtWidgets.QTableWidgetItem(value)
                    if metadata is not None:
                        item.setData(QtCore.Qt.UserRole, metadata)
                    if metadata is None or col_index in (0, 1):
                        item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                    self._features_fsect_table.setItem(row_index, col_index, item)
        finally:
            self._is_updating_fsect_table = False

    def _on_features_fsect_item_changed(
        self, item: QtWidgets.QTableWidgetItem
    ) -> None:
        if self._is_updating_fsect_table:
            return
        if item is None or item.column() in (0, 1):
            return
        metadata = item.data(QtCore.Qt.UserRole)
        if not metadata:
            return

        start_item = self._features_fsect_table.item(item.row(), 2)
        end_item = self._features_fsect_table.item(item.row(), 3)
        if start_item is None or end_item is None:
            return

        start_value = self._parse_fsect_value(start_item.text())
        end_value = self._parse_fsect_value(end_item.text())
        if start_value is None or end_value is None:
            self.show_status_message("Fsect values must be numeric.")
            self._restore_fsect_row(metadata)
            return

        updated = self._preview.update_fsect_dlat(
            metadata["section"],
            metadata["kind"],
            metadata["index"],
            start_value,
            end_value,
        )
        if not updated:
            self.show_status_message("Unable to update fsect values.")
            self._restore_fsect_row(metadata)
            return

        self.refresh_features_preview()
        if self._current_selection is not None:
            self.update_features_sidebar(self._current_selection)

    def _parse_fsect_value(self, value: str) -> Optional[int]:
        text = value.strip()
        if not text:
            return None
        try:
            return int(round(float(text)))
        except ValueError:
            return None

    def _restore_fsect_row(self, metadata: dict) -> None:
        values = self._lookup_fsect_values(
            metadata["section"], metadata["kind"], metadata["index"]
        )
        if values is None:
            return
        self._is_updating_fsect_table = True
        try:
            for row in range(self._features_fsect_table.rowCount()):
                item = self._features_fsect_table.item(row, 2)
                if item is None:
                    continue
                row_meta = item.data(QtCore.Qt.UserRole)
                if row_meta != metadata:
                    continue
                start_item = self._features_fsect_table.item(row, 2)
                end_item = self._features_fsect_table.item(row, 3)
                if start_item is not None:
                    start_item.setText(str(values[0]))
                if end_item is not None:
                    end_item.setText(str(values[1]))
                break
        finally:
            self._is_updating_fsect_table = False

    def _lookup_fsect_values(
        self, section_index: int, kind: str, fsect_index: int
    ) -> Optional[tuple[int, int]]:
        trk, _, _, _ = self._preview.get_surface_preview_data()
        if trk is None or section_index < 0 or section_index >= len(trk.sects):
            return None
        sect = trk.sects[section_index]
        if kind == "surface":
            if fsect_index >= len(sect.ground_dlat_start):
                return None
            return (
                int(sect.ground_dlat_start[fsect_index]),
                int(sect.ground_dlat_end[fsect_index]),
            )
        if kind == "boundary":
            if fsect_index >= len(sect.bound_dlat_start):
                return None
            return (
                int(sect.bound_dlat_start[fsect_index]),
                int(sect.bound_dlat_end[fsect_index]),
            )
        return None
    
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
