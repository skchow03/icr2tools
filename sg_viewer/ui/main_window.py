from __future__ import annotations

from pathlib import Path
import math

from PyQt5 import QtCore, QtGui, QtWidgets
from icr2_core.sg_elevation import sg_xsect_altitude_grade_at
from track_viewer.geometry import project_point_to_centerline

from sg_viewer.model.sg_document import SGDocument
from sg_viewer.sg_create_marquee_messages import random_marquee_message
from sg_viewer.model.dlong_mapping import dlong_to_section_position
from sg_viewer.preview_runtime.preview_runtime_api import ViewerRuntimeApi
from sg_viewer.preview.context import PreviewContext
from sg_viewer.ui.color_utils import parse_hex_color
from sg_viewer.ui.palette_dialog import PaletteColorDialog
from sg_viewer.ui.fsection_type_utils import (
    fsect_type_description,
    fsect_type_index,
    fsect_type_options,
)
from sg_viewer.ui.window_title import build_window_title
from sg_viewer.ui.models.tsd_lines_model import TSD_COMMAND_CHOICES
from sg_viewer.rendering.fsection_style_map import resolve_fsection_style
from sg_viewer.services import sg_rendering
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
from sg_viewer.model.selection import SectionSelection
from sg_viewer.ui.presentation.fsect_table_presenter import (
    boundary_numbers_for_fsects,
    format_fsect_delta,
    set_fsect_delta_cell_text,
)
from sg_viewer.ui.presentation.units_presenter import (
    altitude_display_to_feet,
    feet_to_altitude_display,
    format_altitude_for_units,
    format_fsect_dlat,
    format_length,
    format_length_with_secondary,
    format_xsect_altitude,
    fsect_dlat_from_display_units,
    fsect_dlat_to_display_units,
    fsect_dlat_units_label,
    measurement_unit_decimals,
    measurement_unit_label,
    measurement_unit_step,
    xsect_altitude_from_display_units,
    xsect_altitude_to_display_units,
)
from sg_viewer.ui.presentation.window_panels import (
    create_elevation_panel,
    create_fsect_panel,
    create_toolbar_navigation_panel,
)
from sg_viewer.ui.tabs.tso_visibility_tab import TSOVisibilityTab

MARQUEE_STATUS_INTERVAL_MS = 20


class WorkflowTabButton(QtWidgets.QPushButton):
    """Push button whose requested enabled state is gated by a workflow tab."""

    def __init__(self, text: str = "", parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(text, parent)
        self._requested_enabled = True
        self._workflow_tab_active = False
        self.setVisible(False)

    def setEnabled(self, enabled: bool) -> None:  # noqa: N802 - Qt API override
        self._requested_enabled = enabled
        super().setEnabled(enabled and self._workflow_tab_active)

    def set_workflow_tab_active(self, active: bool) -> None:
        self._workflow_tab_active = active
        self.setVisible(active)
        super().setEnabled(self._requested_enabled and active)

    def requested_enabled(self) -> bool:
        return self._requested_enabled


class GeometryTabButton(WorkflowTabButton):
    """Push button whose requested enabled state is gated by the Geometry tab."""

    def set_geometry_tab_active(self, active: bool) -> None:
        self.set_workflow_tab_active(active)


class ElevationTabButton(WorkflowTabButton):
    """Push button whose requested enabled state is gated by the Elevation tab."""

    def set_elevation_tab_active(self, active: bool) -> None:
        self.set_workflow_tab_active(active)


class TsdCommandDelegate(QtWidgets.QStyledItemDelegate):
    """Combo-box editor for TSD line command cells."""

    def createEditor(
        self,
        parent: QtWidgets.QWidget,
        option: QtWidgets.QStyleOptionViewItem,
        index: QtCore.QModelIndex,
    ) -> QtWidgets.QWidget | None:
        if index.column() != 0:
            return super().createEditor(parent, option, index)
        combo = QtWidgets.QComboBox(parent)
        combo.addItems(TSD_COMMAND_CHOICES)
        return combo

    def setEditorData(
        self, editor: QtWidgets.QWidget, index: QtCore.QModelIndex
    ) -> None:
        if isinstance(editor, QtWidgets.QComboBox):
            current = str(index.data(QtCore.Qt.EditRole) or TSD_COMMAND_CHOICES[0])
            editor.setCurrentText(
                current if current in TSD_COMMAND_CHOICES else TSD_COMMAND_CHOICES[0]
            )
            return
        super().setEditorData(editor, index)

    def setModelData(
        self,
        editor: QtWidgets.QWidget,
        model: QtCore.QAbstractItemModel,
        index: QtCore.QModelIndex,
    ) -> None:
        if isinstance(editor, QtWidgets.QComboBox):
            model.setData(index, editor.currentText(), QtCore.Qt.EditRole)
            return
        super().setModelData(editor, model, index)


class MarqueeStatusLabel(QtWidgets.QLabel):
    """Status label that paints marquee text at a pixel offset for smooth motion."""

    def __init__(self) -> None:
        super().__init__()
        self._marquee_text = ""
        self._marquee_offset_px = 0

    def set_marquee_text(self, text: str, offset_px: int) -> None:
        self._marquee_text = text
        self._marquee_offset_px = max(0, offset_px)
        self.setText(text)
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        if not self._marquee_text:
            super().paintEvent(event)
            return

        painter = QtGui.QPainter(self)
        painter.setFont(self.font())
        painter.setPen(self.palette().color(QtGui.QPalette.WindowText))
        text_rect = self.contentsRect()
        text_rect.translate(-self._marquee_offset_px, 0)
        painter.drawText(
            text_rect,
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter,
            self._marquee_text,
        )


class SGViewerWindow(QtWidgets.QMainWindow):
    """Single-window utility that previews SG centrelines."""

    fsectDiagramDlatChangeRequested = QtCore.pyqtSignal(
        int, int, str, float, bool, bool
    )
    fsectDiagramDragRefreshRequested = QtCore.pyqtSignal()
    fsectDiagramDragCommitRequested = QtCore.pyqtSignal(int, int, str, float)
    generateElevationChangeApplied = QtCore.pyqtSignal()

    def __init__(self, *, wire_features: bool = True) -> None:
        super().__init__()
        self.setWindowTitle("SG CREATE")
        self.resize(960, 720)
        self.controller = None
        self._selected_section_index: int | None = None
        self._section_subindex_metadata: dict[int, tuple[int, ...]] = {}
        self._updating_fsect_table = False
        self._updating_xsect_table = False
        self._measurement_unit_data = "feet"
        self._fsect_drag_active = False
        self._fsect_drag_dirty = False
        self._fsect_drag_timer = QtCore.QTimer(self)
        self._fsect_drag_timer.setSingleShot(True)
        self._fsect_drag_timer.setInterval(50)
        self._fsect_drag_timer.timeout.connect(self._on_fsect_drag_timer)
        self._fsect_table_commit_timer = QtCore.QTimer(self)
        self._fsect_table_commit_timer.setSingleShot(True)
        self._fsect_table_commit_timer.setInterval(150)
        self._fsect_table_commit_timer.timeout.connect(
            self._on_fsect_table_commit_timer
        )
        self._fsect_table_commit_needs_normalization = False
        # Cache of adjusted section ranges indexed by section. Rebuilt when SG geometry or
        # elevation/grade data changes, because those values feed intent-length conversion.
        self._adjusted_section_ranges_cache: tuple[tuple[int, int, int], ...] | None = (
            None
        )
        self._query_track_mode_active = False
        self._query_track_info_frozen = False
        self._query_track_result: dict[str, object] | None = None
        self._ruler_mode_active = False
        self._ruler_start_point: tuple[float, float] | None = None
        self._ruler_end_point: tuple[float, float] | None = None
        self._ruler_frozen = False
        self._ruler_notch_interval_500ths: float | None = None
        self._sunny_palette_colors: list[QtGui.QColor] | None = None
        self._updating_land_polygon_color_cells = False
        self._marquee_status_label = MarqueeStatusLabel()
        self._marquee_status_label.setTextInteractionFlags(QtCore.Qt.NoTextInteraction)
        self._marquee_status_label.setAlignment(
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter
        )
        self._marquee_status_label.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred
        )
        self._marquee_status_label.setMinimumWidth(200)
        self._marquee_status_text = ""
        self._marquee_status_offset = 0
        self._marquee_status_offset_px = 0
        self._marquee_last_message = ""
        self._marquee_entry_gap_spaces = 80
        self._studio_chatter_enabled = True
        self._marquee_status_timer = QtCore.QTimer(self)
        self._marquee_status_timer.setInterval(MARQUEE_STATUS_INTERVAL_MS)
        self._marquee_status_timer.timeout.connect(self._advance_marquee_status)

        shortcut_labels = {
            "previous_section": "Ctrl+PgUp",
            "next_section": "Ctrl+PgDown",
            "new_straight": "Ctrl+Alt+S",
            "new_curve": "Ctrl+Alt+C",
            "split_section": "Ctrl+Alt+P",
            "move_section": "Ctrl+Alt+M",
            "delete_section": "Ctrl+Alt+D",
            "set_start_finish": "Ctrl+Alt+F",
        }

        def _set_button_shortcut(
            button: QtWidgets.QPushButton, label: str, shortcut: str
        ) -> None:
            button.setText(label)
            button.setToolTip(f"{label} ({shortcut})")

        self._preview: PreviewWidgetQt = PreviewWidgetQt(
            show_status=self.show_status_message
        )
        self._runtime_api = ViewerRuntimeApi(preview_context=self._preview)
        self._right_sidebar_tabs = QtWidgets.QTabWidget()
        self._right_sidebar_tabs.currentChanged.connect(self._on_workflow_tab_changed)
        self._current_section_banner = QtWidgets.QLabel(
            "Currently selected section: – (Adjusted DLONG –)"
        )
        self._current_section_banner.setWordWrap(True)
        self._current_section_banner.setAlignment(
            QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter
        )
        self._current_section_banner.setStyleSheet(
            "font-weight: 700; padding: 6px 8px; "
            "border: 1px solid palette(mid); border-radius: 4px; "
            "background: palette(alternate-base);"
        )
        self._sidebar_feature_tabs: dict[str, QtWidgets.QTabWidget] = {}
        self._sidebar_feature_tab_widgets: dict[str, QtWidgets.QWidget] = {}
        self._dirty_sidebar_features: set[str] = set()
        self._feature_to_workflow_tab: dict[str, str] = {
            "Geometry": "Geometry",
            "Elevation": "Elevation",
            "Elevation/Grade": "Elevation",
            "Features": "Surface",
            "Fsects": "Surface",
            "Walls": "Surface",
            "Track Surface Markings": "Surface",
            "TSD": "Surface",
            "Objects": "Objects",
            "TSO Visibility": "Objects",
            "Draw land objects": "Objects",
            ".3D file": "Files",
        }
        self._sidebar_tab_base_labels: dict[str, str] = {
            "Elevation": "Elevation",
            "Elevation/Grade": "Elevation",
            "Features": "Features",
            "Fsects": "Features",
            "Walls": "Walls",
            "Track Surface Markings": "Surface Detail",
            "TSD": "Surface Detail",
            "Objects": "Objects",
            "TSO Visibility": "TSO Visibility",
            "Draw land objects": "Draw land objects",
            ".3D file": ".3D file",
            "Geometry": "Geometry",
        }
        self._view_options_dialog: QtWidgets.QDialog | None = None
        self._mrk_add_entry_button = QtWidgets.QPushButton("Add MRK Entry")
        self._mrk_delete_entry_button = QtWidgets.QPushButton("Delete MRK Entry")
        self._mrk_move_up_button = QtWidgets.QPushButton("Move Up")
        self._mrk_move_down_button = QtWidgets.QPushButton("Move Down")
        self._mrk_sort_by_section_button = QtWidgets.QPushButton("Sort by Section")
        self._mrk_sort_by_boundary_button = QtWidgets.QPushButton("Sort by Boundary")
        self._mrk_textures_button = QtWidgets.QPushButton("Manage textures...")
        self._mrk_texture_pattern_show_colors_checkbox = QtWidgets.QCheckBox(
            "Show texture color boxes"
        )
        self._mrk_texture_pattern_show_colors_checkbox.setChecked(True)
        self._mrk_generate_file_button = QtWidgets.QPushButton("Generate .MRK file")
        self._mrk_export_locations_button = QtWidgets.QPushButton(
            "Set export locations..."
        )
        self._mrk_save_button = QtWidgets.QPushButton("Export MRK entries")
        self._mrk_load_button = QtWidgets.QPushButton("Import MRK entries")
        self._generate_pitwall_button = QtWidgets.QPushButton("Generate pitwall.txt")
        self._generate_pitwall_button.setEnabled(False)
        self._manual_wall_height_overrides_button = QtWidgets.QPushButton(
            "Manual Wall Height overrides"
        )
        self._manual_wall_height_overrides_button.setEnabled(False)
        self._pitwall_wall_height_spin = QtWidgets.QDoubleSpinBox()
        self._pitwall_armco_height_spin = QtWidgets.QDoubleSpinBox()
        self._pitwall_length_multiplier_spin = QtWidgets.QDoubleSpinBox()
        self._wall_defaults_override_count = 0
        self._wall_defaults_summary_label = QtWidgets.QLabel()
        self._wall_defaults_edit_button = QtWidgets.QPushButton("Edit defaults…")
        self._tsd_add_line_button = QtWidgets.QPushButton("Add TSD line")
        self._tsd_delete_line_button = QtWidgets.QPushButton("Delete TSD line")
        self._tsd_move_line_up_button = QtWidgets.QPushButton("Move Up")
        self._tsd_move_line_down_button = QtWidgets.QPushButton("Move Down")
        self._tsd_save_file_button = QtWidgets.QPushButton("Save .TSD")
        self._tsd_generate_file_button = QtWidgets.QPushButton("Save As .TSD")
        self._tsd_load_file_button = QtWidgets.QPushButton("Load .TSD file")
        self._tsd_remove_file_button = QtWidgets.QPushButton(
            "Remove .TSD file from project"
        )
        self._tsd_remove_file_button.setEnabled(False)
        self._centerline_nodes_checkbox = QtWidgets.QCheckBox("Centerline + nodes")
        self._centerline_nodes_checkbox.setChecked(True)
        self._tsd_add_object_button = QtWidgets.QPushButton("Add TSD Object")
        self._tsd_duplicate_object_button = QtWidgets.QPushButton(
            "Duplicate TSD Object"
        )
        self._tsd_move_object_up_button = QtWidgets.QPushButton("Move Up")
        self._tsd_move_object_down_button = QtWidgets.QPushButton("Move Down")
        self._tsd_remove_selected_object_button = QtWidgets.QPushButton(
            "Remove Selected TSD Object"
        )
        self._tsd_export_objects_button = QtWidgets.QPushButton(
            "Export object .TSD files"
        )
        self._tsd_skid_marks_button = QtWidgets.QPushButton("Skid Marks...")
        self._tsd_objects_table = QtWidgets.QTableWidget(0, 5)
        self._tsd_objects_table.setHorizontalHeaderLabels(
            [
                "Name",
                "Type",
                "Starting DLONG",
                "Ending DLONG",
                "Attributes",
            ]
        )
        self._tsd_objects_table.horizontalHeader().setStretchLastSection(True)
        self._tsd_objects_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows
        )
        self._tsd_objects_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self._tso_add_button = QtWidgets.QPushButton("Add TSO")
        self._tso_add_button.setCheckable(True)
        self._tso_stamp_button = QtWidgets.QPushButton("Stamp")
        self._tso_stamp_button.setCheckable(True)
        self._tso_box_select_button = QtWidgets.QPushButton("Box Select")
        self._tso_box_select_button.setCheckable(True)
        self._tso_delete_button = QtWidgets.QPushButton("Delete TSO")
        self._tso_move_up_button = QtWidgets.QPushButton("Move Up")
        self._tso_move_down_button = QtWidgets.QPushButton("Move Down")
        self._tso_import_from_3d_button = QtWidgets.QPushButton(
            "Import TSOs from .3D file"
        )
        self._tso_delete_all_button = QtWidgets.QPushButton("Delete All TSOs")
        self._tso_modify_elevations_button = QtWidgets.QPushButton(
            "Modify elevations..."
        )
        self._tso_generate_file_button = QtWidgets.QPushButton(
            "Generate objects.txt file"
        )
        self._tso_write_to_3d_file_button = QtWidgets.QPushButton(
            "Write to .3D file (in place)"
        )
        self._tso_export_locations_button = QtWidgets.QPushButton(
            "Set export locations..."
        )
        self._land_objects_table = QtWidgets.QTableWidget(0, 2)
        self._land_object_name_edit = QtWidgets.QLineEdit()
        self._land_object_name_edit.setPlaceholderText("Object name")
        self._land_save_object_button = QtWidgets.QPushButton("Save Object")
        self._land_add_object_button = QtWidgets.QPushButton("Add Object")
        self._land_export_object_button = QtWidgets.QPushButton("Export Object to .3D")
        self._land_saved_objects: list[dict[str, object]] = []
        self._land_objects_table.setHorizontalHeaderLabels(["Name", "Notes"])
        self._land_objects_table.horizontalHeader().setStretchLastSection(True)
        self._land_objects_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows
        )
        self._land_objects_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self._land_points_table = QtWidgets.QTableWidget(0, 5)
        self._land_points_table.setHorizontalHeaderLabels(["#", "X", "Y", "Z", ""])
        self._land_points_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeToContents
        )
        self._land_points_table.horizontalHeader().setStretchLastSection(False)
        self._land_points_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows
        )
        self._land_points_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self._land_points_table.verticalHeader().setVisible(False)
        self._land_polygons_table = QtWidgets.QTableWidget(0, 4)
        self._land_polygons_table.setHorizontalHeaderLabels(
            ["Polygon points", "Color", "Mode", "Height"]
        )
        self._land_polygons_table.horizontalHeader().setStretchLastSection(True)
        self._land_polygons_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows
        )
        self._land_polygons_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self._land_polygons_table.setToolTip(
            "Double-click a Color cell to choose a SUNNY.PCX palette color."
        )
        self._land_add_polygon_button = QtWidgets.QPushButton("Add Polygon")
        self._land_delete_polygon_button = QtWidgets.QPushButton("Delete Polygon")
        self._land_move_polygon_up_button = QtWidgets.QPushButton("Move Up")
        self._land_move_polygon_down_button = QtWidgets.QPushButton("Move Down")
        self._land_add_point_button = QtWidgets.QPushButton("Add Point")
        self._land_add_point_button.setCheckable(True)
        self._land_edit_point_button = QtWidgets.QPushButton("Edit Point")
        self._land_edit_point_button.setCheckable(True)
        self._land_polygon_fill_checkbox = QtWidgets.QCheckBox("Fill polygons")
        self._land_polygon_fill_checkbox.setChecked(True)
        self._dragging_land_point_row: int | None = None
        self._three_d_file_selected_path_label = QtWidgets.QLabel(
            "Selected .3D file: none"
        )
        self._three_d_file_selected_path_label.setWordWrap(True)
        self._three_d_file_select_button = QtWidgets.QPushButton(
            "Select track .3D file..."
        )
        self._files_copy_template_button = QtWidgets.QPushButton(
            "Copy template files to project folder..."
        )
        self._files_create_run_bat_button = QtWidgets.QPushButton(
            "Create run .bat file..."
        )
        self._files_create_mrk_button = QtWidgets.QPushButton(
            "Create empty .mrk file"
        )
        self._three_d_set_export_locations_button = QtWidgets.QPushButton(
            "Set export locations..."
        )
        self._three_d_file_catalog_inspector_button = QtWidgets.QPushButton(
            "Open catalog inspector (read-only)"
        )
        self._three_d_show_section_entries_button = QtWidgets.QPushButton(
            "Show .3D entries for selected SG section"
        )
        self._three_d_show_section_object_lists_button = QtWidgets.QPushButton(
            "Show ObjectLists referenced by selected section"
        )
        self._three_d_show_section_tsos_button = QtWidgets.QPushButton(
            "Show TSOs used by selected section"
        )
        self._three_d_preview_object_list_changes_button = QtWidgets.QPushButton(
            "Preview ObjectList changes for selected section"
        )
        self._three_d_apply_object_list_changes_button = QtWidgets.QPushButton(
            "Apply ObjectList changes for selected section"
        )
        self._three_d_apply_tso_definitions_button = QtWidgets.QPushButton(
            "Apply selected TSO definitions"
        )
        self._three_d_apply_face_materials_button = QtWidgets.QPushButton(
            "Replace materials in selected FACE spans"
        )
        self._three_d_file_inspect_button = QtWidgets.QPushButton(
            "Inspect see-through candidates"
        )
        self._three_d_file_fix_copy_button = QtWidgets.QPushButton(
            "Fix see-through (save as copy)"
        )
        self._three_d_file_fix_in_place_button = QtWidgets.QPushButton(
            "Fix see-through (in place)"
        )
        self._three_d_file_colors_path_label = QtWidgets.QLabel(
            "Color mappings: defaults"
        )
        self._three_d_file_colors_path_label.setWordWrap(True)
        self._three_d_file_select_colors_button = QtWidgets.QPushButton(
            "Edit color mappings..."
        )
        self._three_d_file_apply_colors_button = QtWidgets.QPushButton(
            "Apply color replacements"
        )
        self._three_d_workflow_tso_checkbox = QtWidgets.QCheckBox()
        self._three_d_workflow_object_lists_checkbox = QtWidgets.QCheckBox()
        self._three_d_workflow_detail_lists_checkbox = QtWidgets.QCheckBox()
        self._three_d_workflow_see_through_checkbox = QtWidgets.QCheckBox()
        self._three_d_workflow_colors_checkbox = QtWidgets.QCheckBox()
        for checkbox in (
            self._three_d_workflow_tso_checkbox,
            self._three_d_workflow_object_lists_checkbox,
            self._three_d_workflow_detail_lists_checkbox,
            self._three_d_workflow_see_through_checkbox,
            self._three_d_workflow_colors_checkbox,
        ):
            checkbox.setChecked(True)
        self._three_d_apply_selected_workflow_button = QtWidgets.QPushButton(
            "Apply Selected to .3D"
        )
        self._three_d_workflow_save_tso_button = QtWidgets.QPushButton(
            "Save TSOs to .3D file"
        )
        self._three_d_workflow_save_object_lists_button = QtWidgets.QPushButton(
            "Save ObjectLists"
        )
        self._three_d_workflow_save_detail_lists_button = QtWidgets.QPushButton(
            "Save DetailLists"
        )
        self._three_d_apply_all_workflow_button = QtWidgets.QPushButton(
            "Apply all to .3D"
        )
        self._tso_table = QtWidgets.QTableWidget(0, 6)
        self._tso_table.setHorizontalHeaderLabels(
            [
                "Name",
                "Filename",
                "X (500ths)",
                "Y (500ths)",
                "Z (500ths)",
                "Attributes",
            ]
        )
        self._tso_table.horizontalHeader().setStretchLastSection(True)
        self._tso_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._tso_table.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._tso_table.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
        )
        self._tsd_files_combo = QtWidgets.QComboBox()
        self._tsd_files_combo.setEnabled(False)
        self._tsd_files_combo.setToolTip("Select a loaded TSD file to edit.")
        self._tsd_lines_table = QtWidgets.QTableView()
        self._tsd_command_delegate = TsdCommandDelegate(self._tsd_lines_table)
        self._tsd_lines_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeToContents
        )
        self._tsd_lines_table.horizontalHeader().setStretchLastSection(True)
        self._tsd_lines_table.horizontalHeader().setDefaultAlignment(
            QtCore.Qt.Alignment(QtCore.Qt.AlignCenter | QtCore.Qt.TextWordWrap)
        )
        self._tsd_lines_table.horizontalHeader().setMinimumSectionSize(56)
        self._tsd_lines_table.setItemDelegateForColumn(0, self._tsd_command_delegate)
        self._tsd_lines_table.viewport().installEventFilter(self)
        self._tsd_lines_table.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )
        self._tsd_lines_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows
        )
        self._tsd_lines_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self._tsd_lines_table.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
        )
        self._mrk_entries_table = QtWidgets.QTableWidget(0, 7)
        self._mrk_entries_table.setHorizontalHeaderLabels(
            [
                "Track Section",
                "Boundary",
                "Starting Wall",
                "Wall Count",
                "Side",
                "Texture Pattern",
                "Description",
            ]
        )
        self._mrk_entries_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeToContents
        )
        self._mrk_entries_table.horizontalHeader().setStretchLastSection(True)
        self._mrk_entries_table.setSelectionBehavior(
            QtWidgets.QAbstractItemView.SelectRows
        )
        self._mrk_entries_table.setSelectionMode(
            QtWidgets.QAbstractItemView.SingleSelection
        )
        self._mrk_entries_table.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
        )
        # self._new_track_button = QtWidgets.QPushButton("New Track")
        self._prev_button = QtWidgets.QPushButton("Previous Section")
        self._next_button = QtWidgets.QPushButton("Next Section")
        _set_button_shortcut(
            self._prev_button,
            "Previous Section",
            shortcut_labels["previous_section"],
        )
        _set_button_shortcut(
            self._next_button,
            "Next Section",
            shortcut_labels["next_section"],
        )
        self._new_straight_button = GeometryTabButton("New Straight")
        self._new_straight_button.setCheckable(True)
        self._new_straight_button.setEnabled(False)
        _set_button_shortcut(
            self._new_straight_button, "New Straight", shortcut_labels["new_straight"]
        )
        self._new_curve_button = GeometryTabButton("New Curve")
        self._new_curve_button.setCheckable(True)
        self._new_curve_button.setEnabled(False)
        _set_button_shortcut(
            self._new_curve_button, "New Curve", shortcut_labels["new_curve"]
        )
        self._split_section_button = GeometryTabButton("Split")
        self._split_section_button.setCheckable(True)
        self._split_section_button.setEnabled(False)
        _set_button_shortcut(
            self._split_section_button, "Split", shortcut_labels["split_section"]
        )
        self._move_section_button = GeometryTabButton("Move Section")
        self._move_section_button.setCheckable(True)
        self._move_section_button.setChecked(False)
        self._move_section_button.setEnabled(False)
        _set_button_shortcut(
            self._move_section_button,
            "Move Section",
            shortcut_labels["move_section"],
        )
        self._delete_section_button = GeometryTabButton("Delete Section")
        self._delete_section_button.setCheckable(True)
        self._delete_section_button.setEnabled(False)
        _set_button_shortcut(
            self._delete_section_button,
            "Delete Section",
            shortcut_labels["delete_section"],
        )
        self._set_start_finish_button = GeometryTabButton("Set Start/Finish")
        self._set_start_finish_button.setEnabled(False)
        _set_button_shortcut(
            self._set_start_finish_button,
            "Set Start/Finish",
            shortcut_labels["set_start_finish"],
        )
        self._query_track_button = QtWidgets.QPushButton("Inspect Track")
        self._query_track_button.setCheckable(True)
        self._query_track_button.setEnabled(False)
        self._ruler_button = QtWidgets.QPushButton("Ruler")
        self._ruler_button.setEnabled(False)
        self._ruler_notch_panel = QtWidgets.QFrame()
        self._ruler_notch_panel.setObjectName("rulerNotchPanel")
        self._ruler_notch_panel.setStyleSheet(
            "QFrame#rulerNotchPanel { background: rgba(0, 0, 0, 170); "
            "border: 1px solid rgba(255, 255, 255, 110); border-radius: 4px; }"
        )
        ruler_notch_layout = QtWidgets.QHBoxLayout()
        ruler_notch_layout.setContentsMargins(6, 4, 6, 4)
        ruler_notch_layout.setSpacing(4)
        self._ruler_notch_label = QtWidgets.QLabel("Notches every")
        self._ruler_notch_label.setStyleSheet("color: white;")
        self._ruler_notch_spin = QtWidgets.QDoubleSpinBox()
        self._ruler_notch_spin.setRange(0.0, 100000000.0)
        self._ruler_notch_spin.setDecimals(1)
        self._ruler_notch_spin.setValue(100.0)
        self._ruler_notch_spin.setMinimumWidth(92)
        self._ruler_notch_spin.setSpecialValueText("Off")
        self._ruler_notch_spin.setToolTip(
            "Distance between ruler notches in the current measurement unit. Set to 0 to hide notches."
        )
        ruler_notch_layout.addWidget(self._ruler_notch_label)
        ruler_notch_layout.addWidget(self._ruler_notch_spin)
        self._ruler_notch_panel.setLayout(ruler_notch_layout)
        self._ruler_notch_panel.setVisible(False)
        self._radii_button = QtWidgets.QCheckBox("Show Radii")
        self._radii_button.setChecked(True)
        self._axes_button = QtWidgets.QCheckBox("Show Axes")
        self._axes_button.setChecked(False)
        self._crosshair_button = QtWidgets.QCheckBox("Show Crosshair")
        self._crosshair_button.setChecked(False)
        self._background_image_checkbox = QtWidgets.QCheckBox("BG image")
        self._background_image_checkbox.setChecked(True)
        self._land_objects_overlay_checkbox = QtWidgets.QCheckBox("Land objects")
        self._land_objects_overlay_checkbox.setChecked(True)
        self._land_objects_overlay_checkbox.setToolTip(
            "Show placed trackside land objects."
        )
        self._trackside_objects_overlay_checkbox = QtWidgets.QCheckBox("TSOs")
        self._trackside_objects_overlay_checkbox.setChecked(False)
        self._trackside_objects_overlay_checkbox.setToolTip(
            "Show trackside object instances."
        )
        self._background_brightness_spin = QtWidgets.QSpinBox()
        self._background_brightness_spin.setRange(-100, 100)
        self._background_brightness_spin.setValue(0)
        self._background_brightness_spin.setSingleStep(1)
        self._background_brightness_spin.setMinimumWidth(72)
        self._background_brightness_spin.setToolTip(
            "Adjust background image brightness from -100 to 100."
        )
        self._track_opacity_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._track_opacity_slider.setRange(0, 100)
        self._track_opacity_slider.setValue(100)
        self._track_opacity_slider.setSingleStep(1)
        self._track_opacity_slider.setPageStep(10)
        self._track_opacity_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self._track_opacity_slider.setTickInterval(25)
        self._track_opacity_slider.setMinimumWidth(180)
        self._track_opacity_slider.setToolTip("Adjust track opacity from 0% to 100%.")
        self._track_opacity_button = QtWidgets.QToolButton()
        self._track_opacity_button.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self._track_opacity_button.setMinimumWidth(84)
        self._track_opacity_button.setToolTip("Open track opacity slider.")
        self._track_opacity_menu = QtWidgets.QMenu(self._track_opacity_button)
        self._track_opacity_panel = QtWidgets.QWidget(self._track_opacity_menu)
        track_opacity_layout = QtWidgets.QVBoxLayout(self._track_opacity_panel)
        track_opacity_layout.setContentsMargins(10, 8, 10, 8)
        track_opacity_layout.setSpacing(6)
        self._track_opacity_value_label = QtWidgets.QLabel()
        self._track_opacity_value_label.setAlignment(QtCore.Qt.AlignCenter)
        track_opacity_layout.addWidget(self._track_opacity_value_label)
        track_opacity_layout.addWidget(self._track_opacity_slider)
        track_opacity_action = QtWidgets.QWidgetAction(self._track_opacity_menu)
        track_opacity_action.setDefaultWidget(self._track_opacity_panel)
        self._track_opacity_menu.addAction(track_opacity_action)
        self._track_opacity_button.setMenu(self._track_opacity_menu)
        self._track_opacity_slider.valueChanged.connect(
            self._update_track_opacity_selector_label
        )
        self._update_track_opacity_selector_label(self._track_opacity_slider.value())
        self._sg_fsects_checkbox = QtWidgets.QCheckBox("F-sections")
        self._sg_fsects_checkbox.setChecked(False)
        self._xsect_dlat_line_checkbox = QtWidgets.QCheckBox("X-sect DLAT")
        self._xsect_dlat_line_checkbox.setChecked(False)
        self._copy_fsects_prev_button = QtWidgets.QPushButton(
            "Copy Fsects to Previous Section"
        )
        self._copy_fsects_prev_button.setEnabled(False)
        self._copy_fsects_next_button = QtWidgets.QPushButton(
            "Copy Fsects to Next Section"
        )
        self._copy_fsects_next_button.setEnabled(False)
        self._add_fsect_button = QtWidgets.QPushButton("Insert New Fsect")
        self._add_fsect_button.setEnabled(False)
        self._delete_fsect_button = QtWidgets.QPushButton("Delete Fsect")
        self._delete_fsect_button.setEnabled(False)
        self._move_fsect_up_button = QtWidgets.QPushButton("Move Fsect Right")
        self._move_fsect_up_button.setEnabled(False)
        self._move_fsect_down_button = QtWidgets.QPushButton("Move Fsect Left")
        self._move_fsect_down_button.setEnabled(False)
        self._swap_fsect_types_button = QtWidgets.QPushButton(
            "Swap Type Across All Sections…"
        )
        self._swap_fsect_types_button.setEnabled(False)
        self._section_table_action: QtWidgets.QAction | None = None
        self._heading_table_action: QtWidgets.QAction | None = None
        self._xsect_table_action: QtWidgets.QAction | None = None
        self._profile_widget = ElevationProfileWidget()
        self._xsect_elevation_widget = XsectElevationWidget()
        self._xsect_combo = QtWidgets.QComboBox()
        self._xsect_combo.setEnabled(False)
        self._edit_xsect_list_button = ElevationTabButton("Edit Xsect data...")
        self._edit_xsect_list_button.setEnabled(False)
        self._copy_xsect_button = ElevationTabButton("Copy Xsect")
        self._copy_xsect_button.setToolTip(
            "Copy selected Xsect data to other sections."
        )
        self._copy_xsect_button.setEnabled(False)
        self._generate_elevation_change_button = ElevationTabButton("Generate Change")
        self._generate_elevation_change_button.setToolTip(
            "Generate an elevation change for the selected Xsect."
        )
        self._generate_elevation_change_button.setEnabled(False)
        self._raise_lower_elevations_button = ElevationTabButton("Raise/Lower")
        self._raise_lower_elevations_button.setToolTip("Raise or lower all elevations.")
        self._raise_lower_elevations_button.setEnabled(False)
        self._flatten_elevations_button = ElevationTabButton("Flatten")
        self._flatten_elevations_button.setToolTip(
            "Flatten all elevations and grade values."
        )
        self._flatten_elevations_button.setEnabled(False)
        self._generate_elevation_change_dialog: QtWidgets.QDialog | None = None
        self._elevation_summary_label = QtWidgets.QLabel(
            "Select a section and xsect to inspect elevation data."
        )
        self._elevation_summary_label.setWordWrap(True)
        self._elevation_summary_label.setTextInteractionFlags(
            QtCore.Qt.TextSelectableByMouse
        )
        self._track_stats_label = QtWidgets.QLabel("Track Length: –")
        self._section_summary_title_label = QtWidgets.QLabel("No section selected")
        self._section_summary_title_label.setStyleSheet(
            "font-weight: bold; font-size: 14px;"
        )
        self._section_summary_detail_label = QtWidgets.QLabel(
            "Select a section to inspect geometry, connections, and metadata."
        )
        self._section_summary_detail_label.setWordWrap(True)
        self._section_health_labels: dict[
            str, tuple[QtWidgets.QLabel, QtWidgets.QLabel]
        ] = {}
        self._section_geometry_labels: dict[str, QtWidgets.QLabel] = {}
        self._section_connection_labels: dict[str, QtWidgets.QLabel] = {}
        self._section_boundary_labels: dict[str, QtWidgets.QLabel] = {}
        self._section_subsection_labels: dict[str, QtWidgets.QLabel] = {}
        self._section_context_labels: dict[str, QtWidgets.QLabel] = {}
        self._section_view_labels: dict[str, QtWidgets.QLabel] = {}
        self._section_advanced_labels: dict[str, QtWidgets.QLabel] = {}
        self._run_full_integrity_check_button = QtWidgets.QPushButton(
            "Run Full Integrity Check…"
        )
        self._section_split_action_button = QtWidgets.QPushButton("Split")
        self._section_delete_action_button = QtWidgets.QPushButton("Delete Section")
        self._section_set_start_finish_action_button = QtWidgets.QPushButton(
            "Set Start/Finish"
        )
        self._section_split_action_button.clicked.connect(
            self._split_section_button.click
        )
        self._section_delete_action_button.clicked.connect(
            self._delete_section_button.click
        )
        self._section_set_start_finish_action_button.clicked.connect(
            self._set_start_finish_button.click
        )
        self._section_index_label = QtWidgets.QLabel("Current Section: –")
        self._section_start_dlong_label = QtWidgets.QLabel("Starting DLONG: –")
        self._section_end_dlong_label = QtWidgets.QLabel("Ending DLONG: –")
        self._previous_label = QtWidgets.QLabel("Previous Section: –")
        self._next_label = QtWidgets.QLabel("Next Section: –")
        self._section_length_label = QtWidgets.QLabel("Section Length: –")
        self._section_subindex_count_label = QtWidgets.QLabel(
            "Section SubIndexes (.3d): –"
        )
        self._section_subindex_starts_label = QtWidgets.QLabel(
            "SubIndex Start DLONGs (.3d): –"
        )
        self._previous_section_length_label = QtWidgets.QLabel(
            "Previous Section Length: –"
        )
        self._next_section_length_label = QtWidgets.QLabel("Next Section Length: –")
        self._adjusted_section_start_dlong_label = QtWidgets.QLabel(
            "Adjusted Starting DLONG: –"
        )
        self._adjusted_section_end_dlong_label = QtWidgets.QLabel(
            "Adjusted Ending DLONG: –"
        )
        self._adjusted_section_length_label = QtWidgets.QLabel(
            "Adjusted Section Length: –"
        )
        self._radius_label = QtWidgets.QLabel("Radius: –")
        self._section_boundary_dlats_label = QtWidgets.QLabel("Boundary DLATs: –")
        self._section_boundary_dlats_label.setWordWrap(True)
        self._query_track_info_label = QtWidgets.QLabel("")
        self._query_track_info_label.setWordWrap(True)
        self._zoom_factor_label = QtWidgets.QLabel("Zoom Factor: –")
        self._zoom_factor_label.setWordWrap(True)
        self._measurement_units_combo = QtWidgets.QComboBox()
        self._measurement_units_combo.addItem("Feet", "feet")
        self._measurement_units_combo.addItem("Meter", "meter")
        self._measurement_units_combo.addItem("Inch", "inch")
        self._measurement_units_combo.addItem("500ths", "500ths")
        self._measurement_units_combo.setCurrentIndex(0)
        self._measurement_units_combo.currentIndexChanged.connect(
            self._on_measurement_units_changed
        )
        self._view_preset_combo = QtWidgets.QComboBox()
        for preset in ("Geometry", "Construction", "Objects", "Debug"):
            self._view_preset_combo.addItem(preset)
        self._xsect_dlat_line_checkbox.setToolTip(
            "Show cross-section lateral offset reference line."
        )
        self._sg_fsects_checkbox.setToolTip("Show generated/preview f-section spans.")
        self._background_image_checkbox.setToolTip("Show calibrated background image.")
        self._centerline_nodes_checkbox.setToolTip(
            "Show centerline and endpoint nodes in the track diagram. "
            "This overlay is required in Geometry, Elevation, and Surface/Features."
        )
        self._quick_display_toolbar = self._build_viewport_toolbar()
        self.update_visual_intensity_controls()
        self.update_mouse_usage_text()
        self._preview_color_controls: dict[
            str, tuple[QtWidgets.QLineEdit, QtWidgets.QPushButton]
        ] = {}
        self._preview_color_labels = {
            "background": "Background",
            "centerline_unselected": "Centerline (Not Selected)",
            "centerline_selected": "Centerline (Selected)",
            "centerline_long_curve": "Centerline (Curve > 120° Arc)",
            "nodes_connected": "Nodes (Connected)",
            "nodes_disconnected": "Nodes (Disconnected)",
            "radii_unselected": "Radii (Not Selected)",
            "radii_selected": "Radii (Selected)",
            "xsect_dlat_line": "X-Section DLAT Line",
            "tso_box_default": "TSO Boxes (Default)",
            "tso_box_selected": "TSO Boxes (Selected)",
            "tso_box_highlighted": "TSO Boxes (TSO Visibility Highlight)",
            "tso_pivot": "TSO Pivot Dot",
            "fsect_0": "Fsect: Grass",
            "fsect_1": "Fsect: Dry grass",
            "fsect_2": "Fsect: Dirt",
            "fsect_3": "Fsect: Sand",
            "fsect_4": "Fsect: Concrete",
            "fsect_5": "Fsect: Asphalt",
            "fsect_6": "Fsect: Paint",
            "fsect_7": "Fsect: Wall",
            "fsect_8": "Fsect: Armco",
        }
        self._fsect_table = QtWidgets.QTableWidget(5, 0)
        self._update_fsect_table_headers()
        self._fsect_table.setEditTriggers(
            QtWidgets.QAbstractItemView.DoubleClicked
            | QtWidgets.QAbstractItemView.SelectedClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
        )
        self._fsect_table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._fsect_table.verticalHeader().setVisible(True)
        self._fsect_table.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeToContents
        )
        self._fsect_table.horizontalHeader().setStretchLastSection(False)
        self._fsect_table.setSizeAdjustPolicy(
            QtWidgets.QAbstractScrollArea.AdjustToContents
        )
        self._fsect_table.setMinimumHeight(160)
        self._fsect_table.cellChanged.connect(self._on_fsect_cell_changed)
        self._fsect_table.currentCellChanged.connect(
            self._on_fsect_current_cell_changed
        )
        self._fsect_diagram = FsectDiagramWidget(
            on_dlat_changed=self._on_fsect_diagram_dlat_changed,
            on_drag_started=self._on_fsect_diagram_drag_started,
            on_drag_ended=self._on_fsect_diagram_drag_ended,
        )
        self._xsect_elevation_table = QtWidgets.QTableWidget(0, 4)
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
        self._altitude_slider = QtWidgets.QSlider(QtCore.Qt.Vertical)
        min_altitude_feet = feet_from_500ths(SGDocument.ELEVATION_MIN)
        max_altitude_feet = feet_from_500ths(SGDocument.ELEVATION_MAX)
        self._altitude_slider.setRange(
            feet_to_slider_units(DEFAULT_ALTITUDE_MIN_FEET),
            feet_to_slider_units(DEFAULT_ALTITUDE_MAX_FEET),
        )
        self._altitude_slider.setSingleStep(1)
        self._altitude_slider.setPageStep(10)
        self._altitude_slider.setTickPosition(QtWidgets.QSlider.TicksRight)
        self._altitude_slider.setTickInterval(10)
        self._altitude_slider.setEnabled(False)
        self._altitude_value_label = QtWidgets.QLabel("0.0")
        self._altitude_value_label.setMinimumWidth(50)
        self._altitude_value_label.setAlignment(
            QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
        )
        self._altitude_min_spin = QtWidgets.QDoubleSpinBox()
        self._altitude_min_spin.setRange(min_altitude_feet, max_altitude_feet - 0.1)
        self._altitude_min_spin.setDecimals(1)
        self._altitude_min_spin.setSingleStep(0.1)
        self._altitude_min_spin.setValue(DEFAULT_ALTITUDE_MIN_FEET)
        self._altitude_min_spin.setKeyboardTracking(False)
        self._altitude_max_spin = QtWidgets.QDoubleSpinBox()
        self._altitude_max_spin.setRange(min_altitude_feet + 0.1, max_altitude_feet)
        self._altitude_max_spin.setDecimals(1)
        self._altitude_max_spin.setSingleStep(0.1)
        self._altitude_max_spin.setValue(DEFAULT_ALTITUDE_MAX_FEET)
        self._altitude_max_spin.setKeyboardTracking(False)
        self._altitude_min_spin.setSuffix(" ft")
        self._altitude_max_spin.setSuffix(" ft")
        self._altitude_set_range_button = QtWidgets.QPushButton(
            "Set elevation slider range..."
        )
        self._grade_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._grade_slider.setRange(-1000, 1000)
        self._grade_slider.setSingleStep(1)
        self._grade_slider.setPageStep(10)
        self._grade_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self._grade_slider.setTickInterval(250)
        self._grade_slider.setEnabled(False)
        self._grade_value_label = QtWidgets.QLabel("0")
        self._grade_value_label.setMinimumWidth(40)
        self._grade_value_label.setAlignment(
            QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
        )
        self._grade_set_range_button = QtWidgets.QPushButton(
            "Set grade slider range..."
        )

        toolbar_panel = create_toolbar_navigation_panel(
            self._prev_button,
            self._next_button,
            self._query_track_button,
            self._ruler_button,
        )
        elevation_layout = QtWidgets.QFormLayout()
        altitude_container = QtWidgets.QWidget()
        altitude_layout = QtWidgets.QVBoxLayout()
        altitude_layout.setContentsMargins(0, 0, 0, 0)
        altitude_layout.addWidget(QtWidgets.QLabel("Elevation (xsect)"))
        altitude_layout.addWidget(self._altitude_slider, stretch=1)
        altitude_layout.addWidget(self._altitude_value_label)
        altitude_container.setLayout(altitude_layout)
        grade_container = QtWidgets.QWidget()
        grade_layout = QtWidgets.QHBoxLayout()
        grade_layout.setContentsMargins(0, 0, 0, 0)
        grade_layout.addWidget(QtWidgets.QLabel("Grade (xsect):"))
        grade_layout.addWidget(self._grade_slider, stretch=1)
        grade_layout.addWidget(self._grade_value_label)
        grade_layout.addWidget(self._grade_set_range_button)
        grade_container.setLayout(grade_layout)
        elevation_panel = create_elevation_panel(
            elevation_layout=elevation_layout,
            xsect_table=self._xsect_elevation_table,
            xsect_combo=self._xsect_combo,
            profile_widget=self._profile_widget,
            altitude_control=altitude_container,
            altitude_set_range_button=self._altitude_set_range_button,
            grade_control=grade_container,
            xsect_elevation_widget=self._xsect_elevation_widget,
            elevation_summary_label=self._elevation_summary_label,
        )

        fsect_panel = create_fsect_panel(
            copy_prev_button=self._copy_fsects_prev_button,
            copy_next_button=self._copy_fsects_next_button,
            add_button=self._add_fsect_button,
            delete_button=self._delete_fsect_button,
            move_up_button=self._move_fsect_up_button,
            move_down_button=self._move_fsect_down_button,
            swap_types_button=self._swap_fsect_types_button,
            table=self._fsect_table,
            diagram=self._fsect_diagram,
        )

        def _build_color_control_row(
            label: str,
            key: str,
            *,
            tooltip: str | None = None,
        ) -> tuple[str, QtWidgets.QWidget]:
            row = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout()
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.setSpacing(8)
            hex_edit = QtWidgets.QLineEdit()
            hex_edit.setPlaceholderText("#RRGGBB")
            hex_edit.setClearButtonEnabled(True)
            if tooltip:
                hex_edit.setToolTip(tooltip)
            color_swatch = QtWidgets.QPushButton("…")
            color_swatch.setFixedWidth(34)
            color_swatch.setToolTip("Pick color")
            color_swatch.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
            row_layout.addWidget(hex_edit, stretch=1)
            row_layout.addWidget(color_swatch)
            row.setLayout(row_layout)
            self._preview_color_controls[key] = (hex_edit, color_swatch)
            return label, row

        def _build_color_group(
            title: str,
            entries: list[tuple[str, str, str | None]],
        ) -> QtWidgets.QGroupBox:
            group = QtWidgets.QGroupBox(title)
            form = QtWidgets.QFormLayout()
            form.setLabelAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            form.setFormAlignment(QtCore.Qt.AlignTop)
            form.setHorizontalSpacing(12)
            form.setVerticalSpacing(10)
            for label, key, tooltip in entries:
                row_label, row_widget = _build_color_control_row(
                    label,
                    key,
                    tooltip=tooltip,
                )
                form.addRow(row_label + ":", row_widget)
            group.setLayout(form)
            return group

        view_options_scroll = QtWidgets.QScrollArea()
        view_options_scroll.setWidgetResizable(True)
        view_options_scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        view_options_sidebar = QtWidgets.QWidget()
        view_options_layout = QtWidgets.QVBoxLayout()
        view_options_layout.setContentsMargins(12, 12, 12, 12)
        view_options_layout.setSpacing(12)

        general_group = QtWidgets.QGroupBox("General")
        general_layout = QtWidgets.QVBoxLayout()
        general_layout.setSpacing(10)
        general_layout.addWidget(self._background_image_checkbox)
        toggles_layout = QtWidgets.QGridLayout()
        toggles_layout.setHorizontalSpacing(12)
        toggles_layout.setVerticalSpacing(8)
        toggles_layout.addWidget(self._radii_button, 0, 0)
        toggles_layout.addWidget(self._axes_button, 0, 1)
        toggles_layout.addWidget(self._crosshair_button, 1, 0)
        general_layout.addLayout(toggles_layout)
        general_group.setLayout(general_layout)
        view_options_layout.addWidget(general_group)

        view_options_layout.addWidget(
            _build_color_group(
                "Track Preview Colors",
                [
                    ("Background", "background", None),
                    ("Centerline (Not Selected)", "centerline_unselected", None),
                    ("Centerline (Selected)", "centerline_selected", None),
                    ("Centerline (Curve > 120° Arc)", "centerline_long_curve", None),
                    ("Nodes (Connected)", "nodes_connected", None),
                    ("Nodes (Disconnected)", "nodes_disconnected", None),
                    ("Radii (Not Selected)", "radii_unselected", None),
                    ("Radii (Selected)", "radii_selected", None),
                    ("X-Section DLAT Line", "xsect_dlat_line", None),
                ],
            )
        )
        view_options_layout.addWidget(
            _build_color_group(
                "Trackside Object Colors",
                [
                    (
                        "TSO Boxes (Default)",
                        "tso_box_default",
                        "Standard TSO bounding box color.",
                    ),
                    (
                        "TSO Boxes (Selected)",
                        "tso_box_selected",
                        "Used for selected TSO bounding boxes.",
                    ),
                    (
                        "TSO Boxes (TSO Visibility Highlight)",
                        "tso_box_highlighted",
                        "Used when a TSO is highlighted from the TSO Visibility tab.",
                    ),
                    (
                        "TSO Pivot Dot",
                        "tso_pivot",
                        "Used for the pivot point marker on selected TSOs.",
                    ),
                ],
            )
        )
        view_options_layout.addWidget(
            _build_color_group(
                "Fsect Surface Colors",
                [
                    ("Fsect: Grass", "fsect_0", None),
                    ("Fsect: Dry grass", "fsect_1", None),
                    ("Fsect: Dirt", "fsect_2", None),
                    ("Fsect: Sand", "fsect_3", None),
                    ("Fsect: Concrete", "fsect_4", None),
                    ("Fsect: Asphalt", "fsect_5", None),
                    ("Fsect: Paint", "fsect_6", None),
                    ("Fsect: Wall", "fsect_7", None),
                    ("Fsect: Armco", "fsect_8", None),
                ],
            )
        )
        view_options_layout.addStretch()
        view_options_sidebar.setLayout(view_options_layout)
        view_options_scroll.setWidget(view_options_sidebar)

        self._view_options_dialog = QtWidgets.QDialog(self)
        self._view_options_dialog.setWindowTitle("View Options")
        self._view_options_dialog.setModal(False)
        view_options_dialog_layout = QtWidgets.QVBoxLayout()
        header = QtWidgets.QLabel(
            "Fine-tune what the preview shows and how the track, TSOs, and surfaces are colored."
        )
        header.setWordWrap(True)
        view_options_dialog_layout.addWidget(header)
        view_options_dialog_layout.addWidget(view_options_scroll)
        self._view_options_dialog.setLayout(view_options_dialog_layout)
        self._view_options_dialog.resize(480, 640)

        self._lazy_sidebar_placeholders: dict[str, QtWidgets.QWidget] = {}
        self._lazy_sidebar_tabs: dict[str, QtWidgets.QTabWidget] = {}
        self._surface_sidebar_built = False
        self._objects_sidebar_built = False
        self._files_sidebar_built = False

        preview_column = QtWidgets.QWidget()
        preview_column_layout = QtWidgets.QVBoxLayout()
        preview_column_layout.addWidget(toolbar_panel.widget)
        preview_column_layout.addWidget(self._quick_display_toolbar)
        self._geometry_viewport_toolbar = self._create_tab_button_panel(
            None, self._geometry_tab_buttons()
        )
        self._geometry_viewport_toolbar.setVisible(False)
        preview_column_layout.addWidget(self._geometry_viewport_toolbar)
        self._preview_stack = QtWidgets.QWidget()
        preview_stack_layout = QtWidgets.QGridLayout()
        preview_stack_layout.setContentsMargins(0, 0, 0, 0)
        preview_stack_layout.addWidget(self._preview, 0, 0)
        preview_stack_layout.addWidget(
            self._ruler_notch_panel,
            0,
            0,
            QtCore.Qt.AlignTop | QtCore.Qt.AlignRight,
        )
        self._preview_stack.setLayout(preview_stack_layout)
        preview_column_layout.addWidget(self._preview_stack, stretch=5)
        stats_panel = self._create_section_inspector_panel()
        self._stats_sidebar_panel = stats_panel
        self._build_grouped_sidebar_tabs(
            section_widget=stats_panel,
            elevation_widget=elevation_panel.widget,
            fsect_widget=fsect_panel.widget,
        )
        self._update_geometry_tab_button_state()
        right_sidebar = QtWidgets.QWidget()
        right_sidebar_layout = QtWidgets.QVBoxLayout()
        right_sidebar_layout.setContentsMargins(0, 0, 0, 0)
        right_sidebar_layout.setSpacing(6)
        right_sidebar_header = QtWidgets.QWidget()
        right_sidebar_header_layout = QtWidgets.QHBoxLayout(right_sidebar_header)
        right_sidebar_header_layout.setContentsMargins(0, 0, 0, 0)
        right_sidebar_header_layout.setSpacing(8)
        right_sidebar_header_layout.addWidget(self._current_section_banner, stretch=1)
        right_sidebar_header_layout.addWidget(QtWidgets.QLabel("Units:"))
        right_sidebar_header_layout.addWidget(self._measurement_units_combo)
        right_sidebar_layout.addWidget(right_sidebar_header)
        right_sidebar_layout.addWidget(self._right_sidebar_tabs, stretch=1)
        right_sidebar.setLayout(right_sidebar_layout)
        self._right_sidebar_container = right_sidebar
        # Keep the right sidebar width fixed so window resizing only grows/shrinks
        # the track-diagram side of the window.
        sidebar_width = max(320, right_sidebar.sizeHint().width())
        right_sidebar.setFixedWidth(sidebar_width)
        right_sidebar.setSizePolicy(
            QtWidgets.QSizePolicy.Fixed,
            QtWidgets.QSizePolicy.Expanding,
        )
        preview_column.setLayout(preview_column_layout)

        container = QtWidgets.QWidget()
        splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        splitter.addWidget(preview_column)
        splitter.addWidget(right_sidebar)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        splitter.setCollapsible(1, False)
        layout = QtWidgets.QHBoxLayout()
        layout.addWidget(splitter)
        container.setLayout(layout)
        self.setCentralWidget(container)
        self._setup_marquee_status_bar()

        if wire_features:
            from sg_viewer.ui.app_bootstrap import wire_window_features

            wire_window_features(self)
        self._preview.pointerMoved.connect(self._on_preview_pointer_moved)
        self._preview.pointerLeft.connect(self._on_preview_pointer_left)
        self._preview.pointerClicked.connect(self._on_preview_pointer_clicked)
        self._preview.pointerReleased.connect(self._on_preview_pointer_released)
        self._preview.pointerDragMoved.connect(self._on_preview_pointer_drag_moved)
        self._preview.scaleChanged.connect(self._on_preview_scale_changed)
        self._preview.sectionsChanged.connect(
            lambda: self.update_visual_intensity_controls()
        )
        self._query_track_button.toggled.connect(self._on_query_track_toggled)
        self._ruler_button.clicked.connect(self._on_ruler_button_clicked)
        self._ruler_notch_spin.valueChanged.connect(
            self._on_ruler_notch_interval_changed
        )
        self._view_preset_combo.currentTextChanged.connect(self._on_view_preset_changed)
        self._background_image_checkbox.toggled.connect(
            lambda _checked: self.update_visual_intensity_controls()
        )
        self._query_track_freeze_shortcut = QtWidgets.QShortcut(
            QtGui.QKeySequence(QtCore.Qt.Key_Space),
            self,
        )
        self._query_track_freeze_shortcut.setContext(
            QtCore.Qt.WidgetWithChildrenShortcut
        )
        self._query_track_freeze_shortcut.activated.connect(
            self._toggle_query_track_info_freeze
        )

    def _setup_marquee_status_bar(self) -> None:
        status_bar = self.statusBar()
        status_bar.setSizeGripEnabled(False)
        status_bar.addPermanentWidget(self._marquee_status_label, 1)
        self._queue_next_marquee_status_message()
        self._marquee_status_timer.start()

    @property
    def studio_chatter_enabled(self) -> bool:
        return self._studio_chatter_enabled

    def set_studio_chatter_enabled(self, enabled: bool) -> None:
        self._studio_chatter_enabled = enabled
        self._marquee_status_label.setVisible(enabled)
        if enabled:
            if not self._marquee_status_text:
                self._queue_next_marquee_status_message()
            if not self._marquee_status_timer.isActive():
                self._marquee_status_timer.start()
            return
        self._marquee_status_timer.stop()
        self._marquee_status_label.set_marquee_text("", 0)

    def _marquee_spaces_for_width(self, width_px: int) -> str:
        space_width = max(
            1, self._marquee_status_label.fontMetrics().horizontalAdvance(" ")
        )
        return " " * max(1, math.ceil(width_px / space_width))

    def _marquee_message_gap(self) -> str:
        return " " * self._marquee_entry_gap_spaces

    def _next_marquee_status_message(self) -> str:
        message = random_marquee_message()
        if self._marquee_last_message:
            for _attempt in range(5):
                if message != self._marquee_last_message:
                    break
                message = random_marquee_message()
        self._marquee_last_message = message
        return message

    def _append_next_marquee_status_message(self) -> None:
        self._marquee_status_text += (
            f"{self._next_marquee_status_message()}{self._marquee_message_gap()}"
        )

    def _queue_next_marquee_status_message(self) -> None:
        entry_padding = self._marquee_spaces_for_width(
            self._marquee_status_label.width()
        )
        self._marquee_status_text = entry_padding
        self._marquee_status_offset = 0
        self._marquee_status_offset_px = 0
        self._append_next_marquee_status_message()

    def _remaining_marquee_width(self) -> int:
        return self._marquee_status_label.fontMetrics().horizontalAdvance(
            self._marquee_status_text[self._marquee_status_offset :]
        )

    def _advance_marquee_status(self) -> None:
        if not self._marquee_status_text:
            self._queue_next_marquee_status_message()
        if self._marquee_status_offset >= len(self._marquee_status_text):
            self._queue_next_marquee_status_message()

        gap_width = self._marquee_status_label.fontMetrics().horizontalAdvance(
            self._marquee_message_gap()
        )
        if (
            self._remaining_marquee_width()
            <= self._marquee_status_label.width() + gap_width
        ):
            self._append_next_marquee_status_message()

        visible_text = self._marquee_status_text[self._marquee_status_offset :]
        self._marquee_status_label.set_marquee_text(
            visible_text, self._marquee_status_offset_px
        )
        self._marquee_status_offset_px += 1
        self._advance_marquee_character_offset()
        self._discard_scrolled_marquee_text()

    def _advance_marquee_character_offset(self) -> None:
        while self._marquee_status_offset < len(self._marquee_status_text):
            current_character = self._marquee_status_text[self._marquee_status_offset]
            character_width = max(
                1,
                self._marquee_status_label.fontMetrics().horizontalAdvance(
                    current_character
                ),
            )
            if self._marquee_status_offset_px < character_width:
                return
            self._marquee_status_offset_px -= character_width
            self._marquee_status_offset += 1

    def _discard_scrolled_marquee_text(self) -> None:
        if self._marquee_status_offset <= 0:
            return
        self._marquee_status_text = self._marquee_status_text[
            self._marquee_status_offset :
        ]
        self._marquee_status_offset = 0

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        if self.controller is not None and hasattr(self.controller, "confirm_close"):
            if not self.controller.confirm_close():
                event.ignore()
                return
        super().closeEvent(event)

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
    def move_section_button(self) -> QtWidgets.QPushButton:
        return self._move_section_button

    @property
    def delete_section_button(self) -> QtWidgets.QPushButton:
        return self._delete_section_button

    @property
    def set_start_finish_button(self) -> QtWidgets.QPushButton:
        return self._set_start_finish_button

    @property
    def query_track_button(self) -> QtWidgets.QPushButton:
        return self._query_track_button

    @property
    def run_full_integrity_check_button(self) -> QtWidgets.QPushButton:
        return self._run_full_integrity_check_button

    @property
    def ruler_button(self) -> QtWidgets.QPushButton:
        return self._ruler_button

    @property
    def radii_button(self) -> QtWidgets.QCheckBox:
        return self._radii_button

    @property
    def axes_button(self) -> QtWidgets.QCheckBox:
        return self._axes_button

    @property
    def crosshair_button(self) -> QtWidgets.QCheckBox:
        return self._crosshair_button

    @property
    def background_image_checkbox(self) -> QtWidgets.QCheckBox:
        return self._background_image_checkbox

    @property
    def land_objects_overlay_checkbox(self) -> QtWidgets.QCheckBox:
        return self._land_objects_overlay_checkbox

    @property
    def trackside_objects_overlay_checkbox(self) -> QtWidgets.QCheckBox:
        return self._trackside_objects_overlay_checkbox

    @property
    def background_brightness_spin(self) -> QtWidgets.QSpinBox:
        return self._background_brightness_spin

    @property
    def track_opacity_spin(self) -> QtWidgets.QSlider:
        return self._track_opacity_slider

    @property
    def track_opacity_button(self) -> QtWidgets.QToolButton:
        return self._track_opacity_button

    @property
    def sg_fsects_checkbox(self) -> QtWidgets.QCheckBox:
        return self._sg_fsects_checkbox

    @property
    def xsect_dlat_line_checkbox(self) -> QtWidgets.QCheckBox:
        return self._xsect_dlat_line_checkbox

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
    def move_fsect_up_button(self) -> QtWidgets.QPushButton:
        return self._move_fsect_up_button

    @property
    def move_fsect_down_button(self) -> QtWidgets.QPushButton:
        return self._move_fsect_down_button

    @property
    def swap_fsect_types_button(self) -> QtWidgets.QPushButton:
        return self._swap_fsect_types_button

    @property
    def fsect_table(self) -> QtWidgets.QTableWidget:
        return self._fsect_table

    @property
    def xsect_elevation_table(self) -> QtWidgets.QTableWidget:
        return self._xsect_elevation_table

    @property
    def right_sidebar_tabs(self) -> QtWidgets.QTabWidget:
        return self._right_sidebar_tabs

    def active_sidebar_tab_name(self) -> str:
        current_index = self._right_sidebar_tabs.currentIndex()
        if current_index < 0:
            return ""
        active_widget = self._right_sidebar_tabs.widget(current_index)
        if isinstance(active_widget, QtWidgets.QTabWidget):
            child_index = active_widget.currentIndex()
            if child_index >= 0:
                return active_widget.tabText(child_index).rstrip("*")
        return self._right_sidebar_tabs.tabText(current_index).rstrip("*")

    def _create_section_inspector_panel(self) -> QtWidgets.QWidget:
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        content = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(content)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        layout.addWidget(self._section_summary_title_label)
        layout.addWidget(self._section_summary_detail_label)

        def group(title: str) -> QtWidgets.QFormLayout:
            box = QtWidgets.QGroupBox(title)
            form = QtWidgets.QFormLayout(box)
            form.setContentsMargins(8, 8, 8, 8)
            form.setSpacing(4)
            form.setLabelAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
            layout.addWidget(box)
            return form

        def two_column_group(title: str) -> QtWidgets.QGridLayout:
            box = QtWidgets.QGroupBox(title)
            grid = QtWidgets.QGridLayout(box)
            grid.setContentsMargins(8, 8, 8, 8)
            grid.setHorizontalSpacing(12)
            grid.setVerticalSpacing(4)
            layout.addWidget(box)
            return grid

        health = two_column_group("Section Health")
        health_items = (
            ("selected", "Selected section"),
            ("length", "Length"),
            ("previous", "Previous connection"),
            ("next", "Next connection"),
            ("start_tangency", "Start tangency"),
            ("end_tangency", "End tangency"),
            ("radius", "Curve radius"),
            ("boundaries", "Boundaries"),
            ("fsects", "Fsects"),
            ("dlong", "DLONG range"),
            ("adjusted", "Adjusted DLONGs"),
        )
        for index, (key, label) in enumerate(health_items):
            grid_row = index // 2
            grid_column = (index % 2) * 2
            name = QtWidgets.QLabel(label)
            name.setStyleSheet("font-weight: bold;")
            status = QtWidgets.QLabel("Unknown")
            detail = QtWidgets.QLabel("–")
            detail.setWordWrap(True)
            row = QtWidgets.QWidget()
            row_layout = QtWidgets.QHBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            row_layout.addWidget(status)
            row_layout.addWidget(detail, stretch=1)
            health.addWidget(name, grid_row, grid_column)
            health.addWidget(row, grid_row, grid_column + 1)
            self._section_health_labels[key] = (status, detail)
        health.addWidget(
            self._run_full_integrity_check_button, (len(health_items) + 1) // 2, 0, 1, 4
        )
        health.setColumnStretch(1, 1)
        health.setColumnStretch(3, 1)

        for title, labels, store in (
            (
                "Geometry",
                (
                    "Type",
                    "Start DLONG",
                    "End DLONG",
                    "Length",
                    "Radius",
                    "Start point",
                    "End point",
                    "Start heading",
                    "End heading",
                    "Curve center",
                    "Curve arc/sweep",
                    "Adjusted start",
                    "Adjusted end",
                    "Adjusted length",
                ),
                self._section_geometry_labels,
            ),
            (
                "Connections",
                (
                    "Previous",
                    "Next",
                    "Previous length",
                    "Next length",
                    "Previous status",
                    "Next status",
                    "Gap to previous",
                    "Gap to next",
                    "Heading mismatch previous",
                    "Heading mismatch next",
                ),
                self._section_connection_labels,
            ),
            (
                "Boundaries / Walls",
                ("Summary", "B0", "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9"),
                self._section_boundary_labels,
            ),
            (
                "Subsections / .3D",
                (
                    "Count",
                    "Starts",
                    "Adjusted start",
                    "Adjusted end",
                    "Adjusted length",
                ),
                self._section_subsection_labels,
            ),
            (
                "Track Context",
                ("Track length", "Miles", "Section position", "Lap percentage"),
                self._section_context_labels,
            ),
            ("View", ("Zoom", "Units"), self._section_view_labels),
            (
                "Advanced / Raw SG Values",
                (
                    "Raw section id",
                    "Raw previous id",
                    "Raw next id",
                    "SG radius",
                    "SG angles",
                    "Subindex starts",
                ),
                self._section_advanced_labels,
            ),
        ):
            grid = two_column_group(title)
            for index, label in enumerate(labels):
                row = index // 2
                column = (index % 2) * 2
                name = QtWidgets.QLabel(label)
                name.setStyleSheet("font-weight: bold;")
                value = QtWidgets.QLabel("–")
                value.setWordWrap(True)
                grid.addWidget(name, row, column)
                grid.addWidget(value, row, column + 1)
                store[label] = value
            grid.setColumnStretch(1, 1)
            grid.setColumnStretch(3, 1)

        self._section_split_action_button.hide()
        self._section_delete_action_button.hide()
        self._section_set_start_finish_action_button.hide()
        layout.addStretch(1)
        scroll.setWidget(content)
        return scroll

    def _set_section_value(
        self, store: dict[str, QtWidgets.QLabel], key: str, value: str
    ) -> None:
        if key in store:
            store[key].setText(value)

    def _set_section_health(self, key: str, status: str, detail: str = "–") -> None:
        labels = self._section_health_labels.get(key)
        if labels is None:
            return
        status_label, detail_label = labels
        status_label.setText(status)
        detail_label.setText(detail)

    def _format_point(self, point: tuple[float, float] | None) -> str:
        if point is None:
            return "–"
        return f"X {self.format_length(point[0])}, Y {self.format_length(point[1])}"

    def _format_heading(self, heading: tuple[float, float] | None) -> str:
        if heading is None:
            return "–"
        return f"({heading[0]:.4f}, {heading[1]:.4f})"

    def _create_tab_button_panel(
        self,
        title: str | None,
        buttons: tuple[QtWidgets.QPushButton, ...],
    ) -> QtWidgets.QFrame:
        panel = QtWidgets.QFrame()
        panel.setFrameShape(QtWidgets.QFrame.StyledPanel)
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        if title:
            title_label = QtWidgets.QLabel(title)
            title_label.setStyleSheet("font-weight: bold;")
            layout.addWidget(title_label)

        button_row = QtWidgets.QHBoxLayout()
        button_row.setContentsMargins(0, 0, 0, 0)
        button_row.setSpacing(6)
        for button in buttons:
            button.setSizePolicy(
                QtWidgets.QSizePolicy.Minimum, QtWidgets.QSizePolicy.Fixed
            )
            button_row.addWidget(button)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        return panel

    def _create_tab_with_button_panel(
        self,
        *,
        title: str | None,
        buttons: tuple[QtWidgets.QPushButton, ...],
        content: QtWidgets.QWidget,
        panel_position: str = "top",
    ) -> QtWidgets.QWidget:
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        button_panel = self._create_tab_button_panel(title, buttons)
        if panel_position == "bottom":
            layout.addWidget(content, stretch=1)
            layout.addWidget(button_panel)
        else:
            layout.addWidget(button_panel)
            layout.addWidget(content, stretch=1)
        return widget

    def _ensure_surface_sidebar_built(self) -> None:
        if self._surface_sidebar_built:
            return
        self._mrk_sidebar = QtWidgets.QWidget()
        mrk_layout = QtWidgets.QVBoxLayout()
        wall_defaults_row = QtWidgets.QFrame()
        wall_defaults_row.setObjectName("wallDefaultsSummaryRow")
        wall_defaults_row.setFrameShape(QtWidgets.QFrame.StyledPanel)
        wall_defaults_layout = QtWidgets.QHBoxLayout()
        wall_defaults_layout.setContentsMargins(6, 3, 6, 3)
        wall_defaults_layout.setSpacing(6)
        wall_defaults_title = QtWidgets.QLabel("Wall defaults:")
        wall_defaults_title.setStyleSheet("font-weight: bold")
        wall_defaults_layout.addWidget(wall_defaults_title)
        wall_defaults_layout.addWidget(self._wall_defaults_summary_label, 1)
        wall_defaults_layout.addWidget(self._wall_defaults_edit_button)
        wall_defaults_row.setLayout(wall_defaults_layout)
        mrk_layout.addWidget(wall_defaults_row)

        mrk_file_group = QtWidgets.QGroupBox("File")
        mrk_file_layout = QtWidgets.QGridLayout()
        mrk_file_layout.setHorizontalSpacing(8)
        mrk_file_layout.setVerticalSpacing(6)
        mrk_file_layout.addWidget(self._generate_pitwall_button, 0, 0)
        mrk_file_layout.addWidget(self._mrk_generate_file_button, 0, 1)
        mrk_file_layout.addWidget(self._mrk_export_locations_button, 0, 2)
        mrk_file_group.setLayout(mrk_file_layout)

        mrk_buttons = QtWidgets.QGridLayout()
        mrk_buttons.setHorizontalSpacing(8)
        mrk_buttons.setVerticalSpacing(6)
        mrk_buttons.addWidget(self._mrk_add_entry_button, 0, 0)
        mrk_buttons.addWidget(self._mrk_delete_entry_button, 0, 1)
        mrk_buttons.addWidget(self._mrk_move_up_button, 0, 2)
        mrk_buttons.addWidget(self._mrk_move_down_button, 0, 3)
        mrk_buttons.addWidget(self._mrk_sort_by_section_button, 1, 0)
        mrk_buttons.addWidget(self._mrk_sort_by_boundary_button, 1, 1)
        mrk_buttons.addWidget(self._mrk_textures_button, 1, 2)
        mrk_layout.addLayout(mrk_buttons)
        mrk_layout.addWidget(self._mrk_texture_pattern_show_colors_checkbox)
        mrk_layout.addWidget(self._mrk_entries_table)
        mrk_layout.addWidget(mrk_file_group)
        mrk_layout.setStretchFactor(self._mrk_entries_table, 1)
        self._mrk_sidebar.setLayout(mrk_layout)

        self._sync_pitwall_height_spin_units(previous_unit="500ths")
        self._pitwall_wall_height_spin.setValue(
            self._fsect_dlat_to_display_units(21000.0)
        )
        self._pitwall_armco_height_spin.setValue(
            self._fsect_dlat_to_display_units(18000.0)
        )
        self._pitwall_length_multiplier_spin.setDecimals(2)
        self._pitwall_length_multiplier_spin.setRange(0.1, 1000.0)
        self._pitwall_length_multiplier_spin.setSingleStep(0.1)
        self._pitwall_length_multiplier_spin.setValue(4.0)
        self._pitwall_wall_height_spin.valueChanged.connect(
            self._refresh_wall_defaults_summary
        )
        self._pitwall_armco_height_spin.valueChanged.connect(
            self._refresh_wall_defaults_summary
        )
        self._pitwall_length_multiplier_spin.valueChanged.connect(
            self._refresh_wall_defaults_summary
        )
        self._wall_defaults_edit_button.clicked.connect(self._edit_wall_defaults)
        self._refresh_wall_defaults_summary()

        self._tsd_sidebar = QtWidgets.QWidget()
        tsd_layout = QtWidgets.QVBoxLayout()
        tsd_lines_group = QtWidgets.QGroupBox("TSD Lines")
        tsd_lines_layout = QtWidgets.QVBoxLayout()
        tsd_file_row = QtWidgets.QHBoxLayout()
        tsd_file_row.addWidget(QtWidgets.QLabel("Loaded TSD file:"))
        tsd_file_row.addWidget(self._tsd_files_combo)
        tsd_file_row.addWidget(self._tsd_save_file_button)
        tsd_file_row.addWidget(self._tsd_generate_file_button)
        tsd_file_row.addWidget(self._tsd_load_file_button)
        tsd_file_row.addWidget(self._tsd_remove_file_button)
        tsd_lines_layout.addLayout(tsd_file_row)
        tsd_buttons = QtWidgets.QHBoxLayout()
        tsd_buttons.addWidget(self._tsd_add_line_button)
        tsd_buttons.addWidget(self._tsd_delete_line_button)
        tsd_buttons.addWidget(self._tsd_move_line_up_button)
        tsd_buttons.addWidget(self._tsd_move_line_down_button)
        tsd_lines_layout.addLayout(tsd_buttons)
        tsd_lines_layout.addWidget(self._tsd_lines_table, 1)
        tsd_lines_group.setLayout(tsd_lines_layout)
        tsd_lines_group.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding
        )
        tsd_layout.addWidget(tsd_lines_group, 1)
        tsd_objects_group = QtWidgets.QGroupBox("TSD Objects")
        tsd_objects_layout = QtWidgets.QVBoxLayout()
        tsd_objects_layout.addWidget(
            QtWidgets.QLabel(
                "Create higher-level patterns that generate multiple TSD lines."
            )
        )
        tsd_object_buttons = QtWidgets.QGridLayout()
        tsd_object_buttons.addWidget(self._tsd_add_object_button, 0, 0)
        tsd_object_buttons.addWidget(self._tsd_duplicate_object_button, 0, 1)
        tsd_object_buttons.addWidget(self._tsd_remove_selected_object_button, 0, 2)
        tsd_object_buttons.addWidget(self._tsd_move_object_up_button, 1, 0)
        tsd_object_buttons.addWidget(self._tsd_move_object_down_button, 1, 1)
        tsd_object_buttons.addWidget(self._tsd_export_objects_button, 1, 2)
        tsd_object_buttons.addWidget(self._tsd_skid_marks_button, 1, 3)
        tsd_objects_layout.addLayout(tsd_object_buttons)
        tsd_objects_layout.addWidget(self._tsd_objects_table)
        tsd_objects_group.setLayout(tsd_objects_layout)
        tsd_layout.addWidget(tsd_objects_group)

        self._tsd_add_line_button.setToolTip("Add a new TSD line row.")
        self._tsd_delete_line_button.setToolTip("Delete the selected TSD line row.")
        self._tsd_move_line_up_button.setToolTip(
            "Move the selected TSD line up one row."
        )
        self._tsd_move_line_down_button.setToolTip(
            "Move the selected TSD line down one row."
        )
        self._tsd_save_file_button.setToolTip(
            "Save current TSD lines to the selected loaded .TSD file."
        )
        self._tsd_generate_file_button.setToolTip(
            "Choose a file path and save current TSD lines as a .TSD file."
        )
        self._tsd_load_file_button.setToolTip(
            "Load a .TSD file and add it to the loaded list."
        )
        self._tsd_remove_file_button.setToolTip(
            "Remove selected .TSD file(s) from this project without deleting files from disk."
        )
        self._tsd_add_object_button.setToolTip("Create a new TSD object pattern.")
        self._tsd_duplicate_object_button.setToolTip(
            "Duplicate the selected TSD object below it."
        )
        self._tsd_remove_selected_object_button.setToolTip(
            "Remove the selected TSD object."
        )
        self._tsd_move_object_up_button.setToolTip(
            "Move the selected TSD object up one row."
        )
        self._tsd_move_object_down_button.setToolTip(
            "Move the selected TSD object down one row."
        )
        self._tsd_export_objects_button.setToolTip(
            "Export all TSD objects as .TSD files."
        )
        self._tsd_skid_marks_button.setToolTip("Open the skid-mark randomizer dialog.")
        self._tsd_sidebar.setLayout(tsd_layout)

        self._surface_sidebar_built = True

    def _ensure_objects_sidebar_built(self) -> None:
        if self._objects_sidebar_built:
            return
        self._tso_sidebar = QtWidgets.QWidget()
        tso_layout = QtWidgets.QVBoxLayout()
        tso_info = QtWidgets.QLabel(
            "Trackside objects (TSOs) are exported to objects.txt entries named __TSOn.\n"
            "Position values use 500ths and rotations use tenths of angles."
        )
        tso_info.setWordWrap(True)
        tso_layout.addWidget(tso_info)
        tso_buttons = QtWidgets.QGridLayout()
        tso_buttons.addWidget(self._tso_add_button, 0, 0)
        tso_buttons.addWidget(self._tso_stamp_button, 0, 1)
        tso_buttons.addWidget(self._tso_box_select_button, 0, 2)
        tso_buttons.addWidget(self._tso_delete_button, 0, 3)
        tso_buttons.addWidget(self._tso_move_up_button, 0, 4)
        tso_buttons.addWidget(self._tso_move_down_button, 0, 5)
        tso_layout.addLayout(tso_buttons)
        tso_layout.addWidget(self._tso_table)
        tso_advanced_group = QtWidgets.QGroupBox("Advanced")
        tso_advanced_layout = QtWidgets.QHBoxLayout()
        tso_advanced_layout.addWidget(self._tso_delete_all_button)
        tso_advanced_layout.addWidget(self._tso_modify_elevations_button)
        tso_advanced_layout.addStretch(1)
        tso_advanced_group.setLayout(tso_advanced_layout)
        tso_layout.addWidget(tso_advanced_group)
        tso_files_group = QtWidgets.QGroupBox("Files")
        tso_files_layout = QtWidgets.QGridLayout()
        tso_files_layout.setHorizontalSpacing(8)
        tso_files_layout.setVerticalSpacing(6)
        tso_files_layout.addWidget(self._tso_import_from_3d_button, 0, 0)
        tso_files_layout.addWidget(self._tso_generate_file_button, 0, 1)
        tso_files_layout.addWidget(self._tso_write_to_3d_file_button, 0, 2)
        tso_files_layout.addWidget(self._tso_export_locations_button, 1, 0, 1, 3)
        tso_files_group.setLayout(tso_files_layout)
        tso_layout.addWidget(tso_files_group)
        self._tso_sidebar.setLayout(tso_layout)
        self._tso_import_from_3d_button.setToolTip(
            "Import TSOs from an existing .3D file and replace all current TSOs."
        )
        self._tso_delete_all_button.setToolTip(
            "Delete every TSO from the current project."
        )
        self._tso_visibility_sidebar = TSOVisibilityTab()
        self._land_objects_sidebar = QtWidgets.QWidget()
        land_layout = QtWidgets.QVBoxLayout()
        land_layout.addWidget(QtWidgets.QLabel("Land objects:"))
        land_object_header = QtWidgets.QHBoxLayout()
        land_object_header.addWidget(self._land_object_name_edit, 1)
        land_object_header.addWidget(self._land_add_object_button)
        land_object_header.addWidget(self._land_save_object_button)
        land_object_header.addWidget(self._land_export_object_button)
        land_layout.addLayout(land_object_header)
        land_layout.addWidget(self._land_objects_table)
        land_layout.addWidget(QtWidgets.QLabel("Points"))
        land_point_buttons = QtWidgets.QHBoxLayout()
        land_point_buttons.addWidget(self._land_add_point_button)
        land_point_buttons.addWidget(self._land_edit_point_button)
        land_layout.addLayout(land_point_buttons)
        land_layout.addWidget(self._land_points_table)
        land_layout.addWidget(QtWidgets.QLabel("Polygons"))
        land_polygon_buttons = QtWidgets.QHBoxLayout()
        land_polygon_buttons.addWidget(self._land_add_polygon_button)
        land_polygon_buttons.addWidget(self._land_delete_polygon_button)
        land_polygon_buttons.addWidget(self._land_move_polygon_up_button)
        land_polygon_buttons.addWidget(self._land_move_polygon_down_button)
        land_layout.addLayout(land_polygon_buttons)
        land_layout.addWidget(self._land_polygon_fill_checkbox)
        land_layout.addWidget(self._land_polygons_table)
        self._land_objects_sidebar.setLayout(land_layout)
        self._land_add_polygon_button.setToolTip(
            "Add a polygon row. Enter point numbers separated by commas (example: 0, 1, 2, 3)."
        )
        self._land_delete_polygon_button.setToolTip("Delete the selected polygon row.")
        self._land_move_polygon_up_button.setToolTip(
            "Move the selected polygon row up one position."
        )
        self._land_move_polygon_down_button.setToolTip(
            "Move the selected polygon row down one position."
        )
        self._land_add_polygon_button.clicked.connect(self._add_land_polygon_row)
        self._land_delete_polygon_button.clicked.connect(
            self._delete_selected_land_polygon_row
        )
        self._land_move_polygon_up_button.clicked.connect(
            lambda: self._move_selected_land_polygon_row(-1)
        )
        self._land_move_polygon_down_button.clicked.connect(
            lambda: self._move_selected_land_polygon_row(1)
        )
        self._land_add_point_button.toggled.connect(
            lambda checked: self._on_land_point_mode_toggled("add", checked)
        )
        self._land_edit_point_button.toggled.connect(
            lambda checked: self._on_land_point_mode_toggled("edit", checked)
        )
        self._land_points_table.itemChanged.connect(
            self._on_land_points_table_item_changed
        )
        self._land_save_object_button.clicked.connect(self._save_current_land_object)
        self._land_add_object_button.clicked.connect(self._add_land_object)
        self._land_export_object_button.clicked.connect(
            self._export_selected_land_object_to_3d
        )
        self._land_objects_table.itemSelectionChanged.connect(
            self._load_selected_land_object
        )
        self._land_objects_table.itemChanged.connect(
            self._on_land_objects_table_item_changed
        )
        self._land_object_name_edit.textChanged.connect(
            self._persist_selected_land_object
        )
        self._update_land_object_edit_controls()
        self._land_polygons_table.itemChanged.connect(
            self._on_land_polygons_table_item_changed
        )
        self._land_polygons_table.itemDoubleClicked.connect(
            self._on_land_polygons_table_item_double_clicked
        )
        self._land_polygon_fill_checkbox.toggled.connect(
            lambda _checked: self._sync_land_polygons_overlay()
        )
        self._objects_sidebar_built = True

    def _ensure_files_sidebar_built(self) -> None:
        if self._files_sidebar_built:
            return
        self._three_d_file_sidebar = QtWidgets.QWidget()
        three_d_layout = QtWidgets.QVBoxLayout()
        three_d_intro = QtWidgets.QLabel(
            "Use this tab to choose the project .3D file, then run tools that inspect/fix "
            "see-through elevations and replace color definitions.\n"
            "The selected paths are saved with the project."
        )
        three_d_intro.setWordWrap(True)
        three_d_layout.addWidget(three_d_intro)

        track_group = QtWidgets.QGroupBox("1) Export locations")
        track_group_layout = QtWidgets.QVBoxLayout()
        track_group_layout.addWidget(self._three_d_file_selected_path_label)
        track_group_buttons = QtWidgets.QHBoxLayout()
        track_group_buttons.addWidget(self._three_d_set_export_locations_button)
        track_group_buttons.addWidget(self._three_d_file_select_button)
        track_group_layout.addLayout(track_group_buttons)
        track_group.setLayout(track_group_layout)
        three_d_layout.addWidget(track_group)

        project_files_group = QtWidgets.QGroupBox("2) Project files")
        project_files_layout = QtWidgets.QVBoxLayout()
        project_files_note = QtWidgets.QLabel(
            "Copy reusable template files into the project folder, or generate "
            "a build batch file for the current SG track."
        )
        project_files_note.setWordWrap(True)
        project_files_layout.addWidget(project_files_note)
        project_files_layout.addWidget(self._files_copy_template_button)
        project_files_layout.addWidget(self._files_create_run_bat_button)
        project_files_layout.addWidget(self._files_create_mrk_button)
        project_files_group.setLayout(project_files_layout)
        three_d_layout.addWidget(project_files_group)

        workflow_group = QtWidgets.QGroupBox("3) Standard workflow")
        workflow_layout = QtWidgets.QVBoxLayout()
        workflow_note = QtWidgets.QLabel(
            "Select the updates to run, or apply the complete standard .3D workflow."
        )
        workflow_note.setWordWrap(True)
        workflow_layout.addWidget(workflow_note)
        workflow_grid = QtWidgets.QGridLayout()
        workflow_rows = (
            (self._three_d_workflow_tso_checkbox, self._three_d_workflow_save_tso_button),
            (
                self._three_d_workflow_object_lists_checkbox,
                self._three_d_workflow_save_object_lists_button,
            ),
            (
                self._three_d_workflow_detail_lists_checkbox,
                self._three_d_workflow_save_detail_lists_button,
            ),
            (
                self._three_d_workflow_see_through_checkbox,
                self._three_d_file_fix_in_place_button,
            ),
            (
                self._three_d_workflow_colors_checkbox,
                self._three_d_file_apply_colors_button,
            ),
        )
        workflow_labels = (
            "Save TSOs to .3D file",
            "Save ObjectLists",
            "Save DetailLists",
            "Fix see-through (in place)",
            "Apply color replacements",
        )
        for row, ((checkbox, button), label) in enumerate(
            zip(workflow_rows, workflow_labels)
        ):
            checkbox.setToolTip(
                f"Include '{label}' when applying selected workflow steps."
            )
            button.setText(label)
            workflow_grid.addWidget(checkbox, row, 0)
            workflow_grid.addWidget(button, row, 1)
        workflow_layout.addLayout(workflow_grid)
        workflow_buttons = QtWidgets.QHBoxLayout()
        workflow_buttons.addWidget(self._three_d_apply_selected_workflow_button)
        workflow_buttons.addWidget(self._three_d_apply_all_workflow_button)
        workflow_layout.addLayout(workflow_buttons)
        workflow_group.setLayout(workflow_layout)
        three_d_layout.addWidget(workflow_group)

        other_group = QtWidgets.QGroupBox("4) Other tools")
        other_layout = QtWidgets.QVBoxLayout()
        other_layout.addWidget(self._three_d_file_catalog_inspector_button)
        other_layout.addWidget(self._three_d_show_section_entries_button)
        other_layout.addWidget(self._three_d_show_section_object_lists_button)
        other_layout.addWidget(self._three_d_show_section_tsos_button)
        other_layout.addWidget(self._three_d_preview_object_list_changes_button)
        other_layout.addWidget(self._three_d_file_inspect_button)
        other_layout.addWidget(self._three_d_file_fix_copy_button)
        other_layout.addWidget(self._three_d_apply_face_materials_button)
        other_layout.addWidget(self._three_d_file_colors_path_label)
        other_layout.addWidget(self._three_d_file_select_colors_button)
        other_group.setLayout(other_layout)
        three_d_layout.addWidget(other_group)
        three_d_layout.addStretch(1)
        self._three_d_file_sidebar.setLayout(three_d_layout)

        self._files_sidebar_built = True

    def _geometry_tab_buttons(self) -> tuple[GeometryTabButton, ...]:
        return (
            self._new_straight_button,
            self._new_curve_button,
            self._split_section_button,
            self._move_section_button,
            self._delete_section_button,
            self._set_start_finish_button,
        )

    def _elevation_toolbar_buttons(self) -> tuple[QtWidgets.QPushButton, ...]:
        return (
            self._edit_xsect_list_button,
            self._copy_xsect_button,
            self._generate_elevation_change_button,
            self._flatten_elevations_button,
            self._raise_lower_elevations_button,
        )

    def _on_workflow_tab_changed(self, _index: int) -> None:
        current_index = self._right_sidebar_tabs.currentIndex()
        workflow_label = (
            self._right_sidebar_tabs.tabText(current_index).rstrip("*")
            if current_index >= 0
            else ""
        )
        if workflow_label == "Surface":
            self._ensure_surface_sidebar_built()
            self._populate_lazy_workflow_tab(
                "Surface",
                (
                    (self._fsect_widget, "Features"),
                    (self._mrk_sidebar, "Walls"),
                    (self._tsd_sidebar, "Track Surface Markings"),
                ),
            )
            controller = getattr(self, "controller", None)
            if controller is not None:
                controller.ensure_surface_sidebar_signals_connected()
        elif workflow_label == "Objects":
            self._ensure_objects_sidebar_built()
            self._populate_lazy_workflow_tab(
                "Objects",
                (
                    (self._tso_sidebar, "Objects"),
                    (self._tso_visibility_sidebar, "TSO Visibility"),
                    (self._land_objects_sidebar, "Draw land objects"),
                ),
            )
            controller = getattr(self, "controller", None)
            if controller is not None:
                controller.ensure_objects_sidebar_signals_connected()
        elif workflow_label == "Files":
            self._ensure_files_sidebar_built()
            self._populate_lazy_workflow_tab(
                "Files",
                ((self._three_d_file_sidebar, ".3D file"),),
            )
            controller = getattr(self, "controller", None)
            if controller is not None:
                controller.ensure_files_sidebar_signals_connected()
        self._update_geometry_tab_button_state()
        self._sync_land_vertex_points_overlay()
        self.update_mouse_usage_text()

    def _on_sidebar_feature_tab_changed(self) -> None:
        self._sync_land_vertex_points_overlay()
        self.update_mouse_usage_text()

    def _update_geometry_tab_button_state(self) -> None:
        current_index = self._right_sidebar_tabs.currentIndex()
        current_tab = (
            self._right_sidebar_tabs.tabText(current_index).rstrip("*")
            if current_index >= 0
            else ""
        )
        geometry_active = current_tab == "Geometry"
        elevation_active = current_tab == "Elevation"
        for button in self._geometry_tab_buttons():
            button.set_geometry_tab_active(geometry_active)
        for button in self._elevation_toolbar_buttons():
            button.set_elevation_tab_active(elevation_active)
        geometry_toolbar = getattr(self, "_geometry_viewport_toolbar", None)
        if geometry_toolbar is not None:
            geometry_toolbar.setVisible(geometry_active)
        self._preview.set_centerline_editing_enabled(geometry_active)
        self._preview.set_section_drag_enabled(
            geometry_active and self._move_section_button.isChecked()
        )
        if not geometry_active:
            self._cancel_geometry_edit_modes()
        controller = getattr(self, "controller", None)
        if controller is not None and hasattr(
            controller, "_sync_section_editing_menu_actions"
        ):
            controller._sync_section_editing_menu_actions()

    def _cancel_geometry_edit_modes(self) -> None:
        self._preview.cancel_creation()
        self._preview.cancel_split_section()
        for button in (
            self._new_straight_button,
            self._new_curve_button,
            self._split_section_button,
            self._move_section_button,
            self._delete_section_button,
        ):
            if button.isCheckable() and button.isChecked():
                button.blockSignals(True)
                button.setChecked(False)
                button.blockSignals(False)
        self._preview.set_section_drag_enabled(False)

    def _build_grouped_sidebar_tabs(
        self,
        *,
        section_widget: QtWidgets.QWidget,
        elevation_widget: QtWidgets.QWidget,
        fsect_widget: QtWidgets.QWidget,
    ) -> None:
        self._fsect_widget = fsect_widget

        self._right_sidebar_tabs.addTab(section_widget, "Geometry")
        self._sidebar_feature_tab_widgets["Geometry"] = section_widget

        elevation_tab_widget = self._create_tab_with_button_panel(
            title=None,
            buttons=self._elevation_toolbar_buttons(),
            content=elevation_widget,
            panel_position="bottom",
        )
        self._right_sidebar_tabs.addTab(elevation_tab_widget, "Elevation")
        self._sidebar_feature_tab_widgets["Elevation"] = elevation_widget

        for workflow_label in ("Surface", "Objects", "Files"):
            tab_widget = QtWidgets.QTabWidget()
            tab_widget.currentChanged.connect(
                lambda _index: self._on_sidebar_feature_tab_changed()
            )
            placeholder = self._create_lazy_sidebar_placeholder(workflow_label)
            tab_widget.addTab(placeholder, workflow_label)
            self._right_sidebar_tabs.addTab(tab_widget, workflow_label)
            self._lazy_sidebar_tabs[workflow_label] = tab_widget
            self._lazy_sidebar_placeholders[workflow_label] = placeholder

    def _create_lazy_sidebar_placeholder(self, workflow_label: str) -> QtWidgets.QWidget:
        placeholder = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(placeholder)
        layout.addStretch(1)
        message = QtWidgets.QLabel(f"{workflow_label} tools load when this tab is opened.")
        message.setAlignment(QtCore.Qt.AlignCenter)
        message.setWordWrap(True)
        layout.addWidget(message)
        layout.addStretch(1)
        return placeholder

    def _populate_lazy_workflow_tab(
        self,
        workflow_label: str,
        panels: tuple[tuple[QtWidgets.QWidget, str], ...],
    ) -> None:
        tab_widget = self._lazy_sidebar_tabs[workflow_label]
        placeholder = self._lazy_sidebar_placeholders.get(workflow_label)
        if placeholder is not None:
            index = tab_widget.indexOf(placeholder)
            if index >= 0:
                tab_widget.removeTab(index)
            placeholder.deleteLater()
            del self._lazy_sidebar_placeholders[workflow_label]
        for panel_widget, feature_label in panels:
            if tab_widget.indexOf(panel_widget) >= 0:
                continue
            display_label = (
                "Surface Detail"
                if feature_label == "Track Surface Markings"
                else feature_label
            )
            tab_widget.addTab(panel_widget, display_label)
            self._sidebar_feature_tabs[feature_label] = tab_widget
            self._sidebar_feature_tab_widgets[feature_label] = panel_widget
            if feature_label == "Features":
                self._sidebar_feature_tabs["Fsects"] = tab_widget
                self._sidebar_feature_tab_widgets["Fsects"] = panel_widget
            elif feature_label == "Track Surface Markings":
                self._sidebar_feature_tabs["TSD"] = tab_widget
                self._sidebar_feature_tab_widgets["TSD"] = panel_widget

    def _build_viewport_toolbar(self) -> QtWidgets.QFrame:
        """Build the compact viewport display/options toolbar above the preview."""
        toolbar = QtWidgets.QFrame()
        toolbar.setFrameShape(QtWidgets.QFrame.StyledPanel)
        toolbar.setFrameShadow(QtWidgets.QFrame.Raised)
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)
        layout.addWidget(self._ruler_button)
        layout.addSpacing(14)
        layout.addWidget(QtWidgets.QLabel("Overlays:"))
        layout.addWidget(self._centerline_nodes_checkbox)
        layout.addWidget(self._xsect_dlat_line_checkbox)
        layout.addWidget(self._sg_fsects_checkbox)
        layout.addWidget(self._land_objects_overlay_checkbox)
        layout.addWidget(self._trackside_objects_overlay_checkbox)
        layout.addWidget(self._background_image_checkbox)
        layout.addSpacing(8)
        layout.addStretch(1)
        layout.addWidget(QtWidgets.QLabel("Background brightness:"))
        layout.addWidget(self._background_brightness_spin)
        layout.addSpacing(8)
        layout.addWidget(QtWidgets.QLabel("Track opacity:"))
        layout.addWidget(self._track_opacity_button)
        toolbar.setLayout(layout)
        return toolbar

    def update_visual_intensity_controls(self) -> None:
        has_background = bool(self._preview.has_background_image())
        background_active = (
            has_background and self._background_image_checkbox.isChecked()
        )
        for widget in (self._background_brightness_spin,):
            widget.setEnabled(background_active)
        has_track = bool(self._preview.section_manager.sections)
        for widget in (self._track_opacity_button, self._track_opacity_slider):
            widget.setEnabled(has_track)

    def _update_track_opacity_selector_label(self, value: int) -> None:
        text = f"{max(0, min(100, int(value)))}%"
        self._track_opacity_button.setText(text)
        self._track_opacity_value_label.setText(f"Track opacity: {text}")

    def _on_view_preset_changed(self, preset: str) -> None:
        if preset == "Geometry":
            self._sg_fsects_checkbox.setChecked(False)
            self._xsect_dlat_line_checkbox.setChecked(False)
            self._land_objects_overlay_checkbox.setChecked(False)
            self._trackside_objects_overlay_checkbox.setChecked(False)
            self._background_image_checkbox.setChecked(False)
        elif preset == "Construction":
            self._sg_fsects_checkbox.setChecked(True)
            self._xsect_dlat_line_checkbox.setChecked(True)
        elif preset == "Objects":
            self._land_objects_overlay_checkbox.setChecked(True)
            self._trackside_objects_overlay_checkbox.setChecked(True)
        elif preset == "Debug":
            self._sg_fsects_checkbox.setChecked(True)
            self._xsect_dlat_line_checkbox.setChecked(True)
            self._land_objects_overlay_checkbox.setChecked(True)
            self._trackside_objects_overlay_checkbox.setChecked(True)
            if self._preview.has_background_image():
                self._background_image_checkbox.setChecked(True)
        self.update_visual_intensity_controls()

    def update_mouse_usage_text(self) -> None:
        """Refresh the viewport mouse help for the active tab/mode."""
        if self._ruler_mode_active:
            usage_text = (
                "Left click: set ruler start/end points • "
                "Mouse move: preview ruler after start point • "
                "Mouse wheel: zoom at cursor"
            )
        elif self._delete_section_button.isChecked():
            usage_text = (
                "Left click section: delete section • Mouse wheel: zoom at cursor"
            )
        elif self._split_section_button.isChecked():
            usage_text = (
                "Mouse move: choose split location • "
                "Left click highlighted section: split section • "
                "Mouse wheel: zoom at cursor"
            )
        elif (
            self._new_straight_button.isChecked() or self._new_curve_button.isChecked()
        ):
            usage_text = (
                "Left click: place/connect new section endpoints • "
                "Mouse move: preview new section • "
                "Mouse wheel: zoom at cursor"
            )
        elif self._tso_box_select_button.isChecked():
            usage_text = (
                "Left drag: box select trackside objects • "
                "Right drag TSO: move selected object • "
                "Mouse wheel: zoom at cursor"
            )
        else:
            tab_name = self.active_sidebar_tab_name()
            usage_by_tab = {
                "Elevation": (
                    "Left click: select section/xsect marker • "
                    "Left drag node directly, or drag section only when Move is active; "
                    "drag empty space to pan • "
                    "Right click node: disconnect • "
                    "Mouse wheel: zoom at cursor"
                ),
                "Features": (
                    "Left click viewport: select section • "
                    "Select/edit fsect rows in the fsect table or diagram • "
                    "Left drag node directly, or drag section only when Move is active; "
                    "drag empty space to pan • "
                    "Right click node: disconnect • "
                    "Mouse wheel: zoom at cursor"
                ),
                "Walls": (
                    "Left click: select wall/section • "
                    "Left drag: pan view • "
                    "Right click node: disconnect • "
                    "Mouse wheel: zoom at cursor"
                ),
                "Track Surface Markings": (
                    "Select TSD rows in the TSD table; selecting a row centers the viewport on it • "
                    "Left drag: pan view • "
                    "Mouse wheel: zoom at cursor"
                ),
                "Objects": (
                    "Left click: select TSO or place TSO when Add/Stamp is active • "
                    "Right drag selected TSO: move object • "
                    "Left drag: pan view • "
                    "Mouse wheel: zoom at cursor"
                ),
                "TSO Visibility": (
                    "Left click: select/highlight visible TSO • "
                    "Left drag: pan view • "
                    "Mouse wheel: zoom at cursor"
                ),
                "Draw land objects": (
                    "Left click: add land point • "
                    "Left drag land point: move point • "
                    "Left drag empty space: pan view • "
                    "Mouse wheel: zoom at cursor"
                ),
                ".3D file": (
                    "Left click: select section/object in viewport • "
                    "Left drag: pan view • "
                    "Mouse wheel: zoom at cursor"
                ),
            }
            usage_text = usage_by_tab.get(
                tab_name,
                "Left click: select • Left drag: pan view • Mouse wheel: zoom at cursor",
            )
        default_hint = "Mouse: left click selects · left drag pans · wheel zooms"
        self._preview.set_status_text(
            default_hint
            if usage_text
            == "Left click: select • Left drag: pan view • Mouse wheel: zoom at cursor"
            else usage_text
        )

    def show_view_options_dialog(self) -> None:
        if self._view_options_dialog is None:
            return
        self._view_options_dialog.show()
        self._view_options_dialog.raise_()
        self._view_options_dialog.activateWindow()

    @property
    def mrk_add_entry_button(self) -> QtWidgets.QPushButton:
        return self._mrk_add_entry_button

    @property
    def mrk_delete_entry_button(self) -> QtWidgets.QPushButton:
        return self._mrk_delete_entry_button

    @property
    def mrk_move_up_button(self) -> QtWidgets.QPushButton:
        return self._mrk_move_up_button

    @property
    def mrk_move_down_button(self) -> QtWidgets.QPushButton:
        return self._mrk_move_down_button

    @property
    def mrk_sort_by_section_button(self) -> QtWidgets.QPushButton:
        return self._mrk_sort_by_section_button

    @property
    def mrk_sort_by_boundary_button(self) -> QtWidgets.QPushButton:
        return self._mrk_sort_by_boundary_button

    @property
    def mrk_textures_button(self) -> QtWidgets.QPushButton:
        return self._mrk_textures_button

    @property
    def mrk_generate_file_button(self) -> QtWidgets.QPushButton:
        return self._mrk_generate_file_button

    @property
    def mrk_texture_pattern_show_colors_checkbox(self) -> QtWidgets.QCheckBox:
        return self._mrk_texture_pattern_show_colors_checkbox

    @property
    def mrk_entries_table(self) -> QtWidgets.QTableWidget:
        return self._mrk_entries_table

    @property
    def mrk_export_locations_button(self) -> QtWidgets.QPushButton:
        return self._mrk_export_locations_button

    @property
    def mrk_save_button(self) -> QtWidgets.QPushButton:
        return self._mrk_save_button

    @property
    def mrk_load_button(self) -> QtWidgets.QPushButton:
        return self._mrk_load_button

    @property
    def wall_defaults_edit_button(self) -> QtWidgets.QPushButton:
        return self._wall_defaults_edit_button

    @property
    def wall_defaults_summary_label(self) -> QtWidgets.QLabel:
        return self._wall_defaults_summary_label

    def set_wall_defaults_override_count(self, count: int) -> None:
        self._wall_defaults_override_count = max(0, int(count))
        self._refresh_wall_defaults_summary()

    def _refresh_wall_defaults_summary(self) -> None:
        self._wall_defaults_summary_label.setText(
            "Wall {wall} | Armco {armco} | Ratio {ratio:.2f} | "
            "Overrides: {overrides}".format(
                wall=self.pitwall_wall_height_500ths(),
                armco=self.pitwall_armco_height_500ths(),
                ratio=self.pitwall_length_multiplier(),
                overrides=self._wall_defaults_override_count,
            )
        )

    def _edit_wall_defaults(self) -> None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Edit wall defaults")
        layout = QtWidgets.QVBoxLayout(dialog)
        form = QtWidgets.QFormLayout()

        wall_spin = QtWidgets.QDoubleSpinBox(dialog)
        armco_spin = QtWidgets.QDoubleSpinBox(dialog)
        current_unit = self._current_measurement_unit()
        decimals = self._measurement_unit_decimals(current_unit)
        step = self._measurement_unit_step(current_unit)
        suffix = f" {self._measurement_unit_label(current_unit)}"
        maximum = units_from_500ths(999999999, current_unit)
        for spin, source in (
            (wall_spin, self._pitwall_wall_height_spin),
            (armco_spin, self._pitwall_armco_height_spin),
        ):
            spin.setDecimals(decimals)
            spin.setSingleStep(step)
            spin.setRange(0.0, maximum)
            spin.setSuffix(suffix)
            spin.setValue(source.value())

        ratio_spin = QtWidgets.QDoubleSpinBox(dialog)
        ratio_spin.setDecimals(2)
        ratio_spin.setRange(0.1, 1000.0)
        ratio_spin.setSingleStep(0.1)
        ratio_spin.setValue(self._pitwall_length_multiplier_spin.value())

        form.addRow("Wall height:", wall_spin)
        form.addRow("Armco height:", armco_spin)
        form.addRow("Wall length-to-height ratio:", ratio_spin)
        layout.addLayout(form)

        overrides_button = QtWidgets.QPushButton(
            "Manual wall height overrides…", dialog
        )
        overrides_button.setEnabled(
            self._manual_wall_height_overrides_button.isEnabled()
        )
        overrides_button.clicked.connect(
            self._manual_wall_height_overrides_button.click
        )
        layout.addWidget(overrides_button)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        self._pitwall_wall_height_spin.setValue(wall_spin.value())
        self._pitwall_armco_height_spin.setValue(armco_spin.value())
        self._pitwall_length_multiplier_spin.setValue(ratio_spin.value())
        self._refresh_wall_defaults_summary()

    @property
    def generate_pitwall_button(self) -> QtWidgets.QPushButton:
        return self._generate_pitwall_button

    @property
    def manual_wall_height_overrides_button(self) -> QtWidgets.QPushButton:
        return self._manual_wall_height_overrides_button

    @property
    def pitwall_wall_height_spin(self) -> QtWidgets.QDoubleSpinBox:
        return self._pitwall_wall_height_spin

    @property
    def pitwall_armco_height_spin(self) -> QtWidgets.QDoubleSpinBox:
        return self._pitwall_armco_height_spin

    @property
    def pitwall_length_multiplier_spin(self) -> QtWidgets.QDoubleSpinBox:
        return self._pitwall_length_multiplier_spin

    def pitwall_length_multiplier(self) -> float:
        return float(self._pitwall_length_multiplier_spin.value())

    def pitwall_wall_height_500ths(self) -> int:
        return int(
            round(
                units_to_500ths(
                    self._pitwall_wall_height_spin.value(),
                    self._current_measurement_unit(),
                )
            )
        )

    def pitwall_armco_height_500ths(self) -> int:
        return int(
            round(
                units_to_500ths(
                    self._pitwall_armco_height_spin.value(),
                    self._current_measurement_unit(),
                )
            )
        )

    @property
    def tsd_add_line_button(self) -> QtWidgets.QPushButton:
        return self._tsd_add_line_button

    @property
    def tsd_delete_line_button(self) -> QtWidgets.QPushButton:
        return self._tsd_delete_line_button

    @property
    def tsd_generate_file_button(self) -> QtWidgets.QPushButton:
        return self._tsd_generate_file_button

    @property
    def tsd_save_file_button(self) -> QtWidgets.QPushButton:
        return self._tsd_save_file_button

    @property
    def tsd_load_file_button(self) -> QtWidgets.QPushButton:
        return self._tsd_load_file_button

    @property
    def tsd_remove_file_button(self) -> QtWidgets.QPushButton:
        return self._tsd_remove_file_button

    @property
    def tsd_move_line_up_button(self) -> QtWidgets.QPushButton:
        return self._tsd_move_line_up_button

    @property
    def tsd_move_line_down_button(self) -> QtWidgets.QPushButton:
        return self._tsd_move_line_down_button

    @property
    def tsd_lines_table(self) -> QtWidgets.QTableView:
        return self._tsd_lines_table

    @property
    def tsd_files_combo(self) -> QtWidgets.QComboBox:
        return self._tsd_files_combo

    @property
    def tsd_add_object_button(self) -> QtWidgets.QPushButton:
        return self._tsd_add_object_button

    @property
    def tsd_remove_selected_object_button(self) -> QtWidgets.QPushButton:
        return self._tsd_remove_selected_object_button

    @property
    def tsd_duplicate_object_button(self) -> QtWidgets.QPushButton:
        return self._tsd_duplicate_object_button

    @property
    def tsd_move_object_up_button(self) -> QtWidgets.QPushButton:
        return self._tsd_move_object_up_button

    @property
    def tsd_move_object_down_button(self) -> QtWidgets.QPushButton:
        return self._tsd_move_object_down_button

    @property
    def tsd_export_objects_button(self) -> QtWidgets.QPushButton:
        return self._tsd_export_objects_button

    @property
    def tsd_objects_table(self) -> QtWidgets.QTableWidget:
        return self._tsd_objects_table

    @property
    def tsd_skid_marks_button(self) -> QtWidgets.QPushButton:
        return self._tsd_skid_marks_button

    @property
    def centerline_nodes_checkbox(self) -> QtWidgets.QCheckBox:
        return self._centerline_nodes_checkbox

    @property
    def tso_add_button(self) -> QtWidgets.QPushButton:
        return self._tso_add_button

    @property
    def tso_delete_button(self) -> QtWidgets.QPushButton:
        return self._tso_delete_button

    @property
    def tso_stamp_button(self) -> QtWidgets.QPushButton:
        return self._tso_stamp_button

    @property
    def selected_section_index(self) -> int | None:
        return self._selected_section_index

    @property
    def tso_box_select_button(self) -> QtWidgets.QPushButton:
        return self._tso_box_select_button

    @property
    def tso_move_up_button(self) -> QtWidgets.QPushButton:
        return self._tso_move_up_button

    @property
    def tso_move_down_button(self) -> QtWidgets.QPushButton:
        return self._tso_move_down_button

    @property
    def tso_generate_file_button(self) -> QtWidgets.QPushButton:
        return self._tso_generate_file_button

    @property
    def tso_export_locations_button(self) -> QtWidgets.QPushButton:
        return self._tso_export_locations_button

    @property
    def tso_write_to_3d_file_button(self) -> QtWidgets.QPushButton:
        return self._tso_write_to_3d_file_button

    @property
    def tso_modify_elevations_button(self) -> QtWidgets.QPushButton:
        return self._tso_modify_elevations_button

    @property
    def tso_import_from_3d_button(self) -> QtWidgets.QPushButton:
        return self._tso_import_from_3d_button

    @property
    def tso_delete_all_button(self) -> QtWidgets.QPushButton:
        return self._tso_delete_all_button

    @property
    def tso_table(self) -> QtWidgets.QTableWidget:
        return self._tso_table

    @property
    def tso_visibility_sidebar(self) -> TSOVisibilityTab:
        return self._tso_visibility_sidebar

    @property
    def three_d_file_select_button(self) -> QtWidgets.QPushButton:
        return self._three_d_file_select_button

    @property
    def files_copy_template_button(self) -> QtWidgets.QPushButton:
        return self._files_copy_template_button

    @property
    def files_create_run_bat_button(self) -> QtWidgets.QPushButton:
        return self._files_create_run_bat_button

    @property
    def files_create_mrk_button(self) -> QtWidgets.QPushButton:
        return self._files_create_mrk_button

    @property
    def three_d_set_export_locations_button(self) -> QtWidgets.QPushButton:
        return self._three_d_set_export_locations_button

    @property
    def three_d_file_catalog_inspector_button(self) -> QtWidgets.QPushButton:
        return self._three_d_file_catalog_inspector_button

    @property
    def three_d_show_section_entries_button(self) -> QtWidgets.QPushButton:
        return self._three_d_show_section_entries_button

    @property
    def three_d_show_section_object_lists_button(self) -> QtWidgets.QPushButton:
        return self._three_d_show_section_object_lists_button

    @property
    def three_d_show_section_tsos_button(self) -> QtWidgets.QPushButton:
        return self._three_d_show_section_tsos_button

    @property
    def three_d_preview_object_list_changes_button(self) -> QtWidgets.QPushButton:
        return self._three_d_preview_object_list_changes_button

    @property
    def three_d_apply_object_list_changes_button(self) -> QtWidgets.QPushButton:
        return self._three_d_apply_object_list_changes_button

    @property
    def three_d_apply_tso_definitions_button(self) -> QtWidgets.QPushButton:
        return self._three_d_apply_tso_definitions_button

    @property
    def three_d_apply_face_materials_button(self) -> QtWidgets.QPushButton:
        return self._three_d_apply_face_materials_button

    @property
    def three_d_file_inspect_button(self) -> QtWidgets.QPushButton:
        return self._three_d_file_inspect_button

    @property
    def three_d_file_fix_copy_button(self) -> QtWidgets.QPushButton:
        return self._three_d_file_fix_copy_button

    @property
    def three_d_file_fix_in_place_button(self) -> QtWidgets.QPushButton:
        return self._three_d_file_fix_in_place_button

    @property
    def three_d_file_select_colors_button(self) -> QtWidgets.QPushButton:
        return self._three_d_file_select_colors_button

    @property
    def three_d_file_apply_colors_button(self) -> QtWidgets.QPushButton:
        return self._three_d_file_apply_colors_button

    @property
    def three_d_workflow_save_tso_button(self) -> QtWidgets.QPushButton:
        return self._three_d_workflow_save_tso_button

    @property
    def three_d_workflow_save_object_lists_button(self) -> QtWidgets.QPushButton:
        return self._three_d_workflow_save_object_lists_button

    @property
    def three_d_workflow_save_detail_lists_button(self) -> QtWidgets.QPushButton:
        return self._three_d_workflow_save_detail_lists_button

    @property
    def three_d_apply_selected_workflow_button(self) -> QtWidgets.QPushButton:
        return self._three_d_apply_selected_workflow_button

    @property
    def three_d_apply_all_workflow_button(self) -> QtWidgets.QPushButton:
        return self._three_d_apply_all_workflow_button

    def selected_three_d_workflow_steps(self) -> tuple[str, ...]:
        steps: list[str] = []
        if self._three_d_workflow_tso_checkbox.isChecked():
            steps.append("tso")
        if self._three_d_workflow_object_lists_checkbox.isChecked():
            steps.append("object_lists")
        if self._three_d_workflow_detail_lists_checkbox.isChecked():
            steps.append("detail_lists")
        if self._three_d_workflow_see_through_checkbox.isChecked():
            steps.append("see_through")
        if self._three_d_workflow_colors_checkbox.isChecked():
            steps.append("colors")
        return tuple(steps)

    def set_selected_track3d_path_text(self, text: str) -> None:
        self._three_d_file_selected_path_label.setText(f"Selected .3D file: {text}")

    def set_selected_colors_path_text(self, text: str) -> None:
        self._three_d_file_colors_path_label.setText(f"Color mappings: {text}")

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
        self._edit_xsect_list_button.setEnabled(enabled)

    @property
    def preview_color_controls(
        self,
    ) -> dict[str, tuple[QtWidgets.QLineEdit, QtWidgets.QPushButton]]:
        return self._preview_color_controls

    @property
    def measurement_units_combo(self) -> QtWidgets.QComboBox:
        return self._measurement_units_combo

    def fsect_display_unit_label(self) -> str:
        return self._fsect_dlat_units_label()

    def fsect_display_decimals(self) -> int:
        return self._measurement_unit_decimals(self._current_measurement_unit())

    def fsect_display_step(self) -> float:
        return self._measurement_unit_step(self._current_measurement_unit())

    def fsect_dlat_to_display_units(self, value: float) -> float:
        return self._fsect_dlat_to_display_units(value)

    def fsect_dlat_from_display_units(self, value: float) -> float:
        return self._fsect_dlat_from_display_units(value)

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
    def edit_xsect_list_button(self) -> QtWidgets.QPushButton:
        return self._edit_xsect_list_button

    @property
    def copy_xsect_button(self) -> QtWidgets.QPushButton:
        return self._copy_xsect_button

    @property
    def generate_elevation_change_button(self) -> QtWidgets.QPushButton:
        return self._generate_elevation_change_button

    @property
    def raise_lower_elevations_button(self) -> QtWidgets.QPushButton:
        return self._raise_lower_elevations_button

    @property
    def flatten_elevations_button(self) -> QtWidgets.QPushButton:
        return self._flatten_elevations_button

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
        xsect_dlats: list[float | int | None],
        altitudes: list[int | None],
        grades: list[int | None],
        selected_index: int | None,
        *,
        enabled: bool,
    ) -> None:
        self._updating_xsect_table = True
        self._xsect_elevation_table.blockSignals(True)
        try:
            row_count = min(len(xsect_dlats), len(altitudes), len(grades))
            self._xsect_elevation_table.setRowCount(row_count)
            for row in range(row_count):
                xsect_item = QtWidgets.QTableWidgetItem(str(row))
                xsect_item.setFlags(
                    QtCore.Qt.ItemIsSelectable | QtCore.Qt.ItemIsEnabled
                )
                dlat_value = xsect_dlats[row]
                dlat_text = (
                    format_fsect_dlat(dlat_value, unit=self._current_measurement_unit())
                    if dlat_value is not None
                    else ""
                )
                dlat_item = QtWidgets.QTableWidgetItem(dlat_text)
                dlat_item.setTextAlignment(
                    QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter
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
                self._xsect_elevation_table.setItem(row, 1, dlat_item)
                self._xsect_elevation_table.setItem(row, 2, altitude_item)
                self._xsect_elevation_table.setItem(row, 3, grade_item)
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
        return format_length(value, unit=self._current_measurement_unit())

    def format_length_with_secondary(self, value: float | int | None) -> str:
        return format_length_with_secondary(
            value, unit=self._current_measurement_unit()
        )

    def update_elevation_summary(self, text: str) -> None:
        self._elevation_summary_label.setText(text)

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

    def set_altitude_inputs_enabled(self, enabled: bool) -> None:
        self._altitude_slider.setEnabled(enabled)
        self._altitude_set_range_button.setEnabled(enabled)

    def set_grade_inputs_enabled(self, enabled: bool) -> None:
        self._grade_slider.setEnabled(enabled)
        self._grade_set_range_button.setEnabled(enabled)

    def set_altitude_slider_bounds(self, minimum: int, maximum: int) -> None:
        if minimum >= maximum:
            maximum = minimum + 1
        self._altitude_slider.blockSignals(True)
        try:
            self._altitude_slider.setRange(minimum, maximum)
            self._altitude_slider.setValue(
                min(max(self._altitude_slider.value(), minimum), maximum)
            )
        finally:
            self._altitude_slider.blockSignals(False)

    def show_altitude_range_dialog(self) -> bool:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Elevation Profile Range")
        layout = QtWidgets.QFormLayout(dialog)

        unit_label = self._measurement_unit_label(self._current_measurement_unit())

        min_spin = QtWidgets.QDoubleSpinBox(dialog)
        min_spin.setDecimals(self._altitude_min_spin.decimals())
        min_spin.setRange(
            self._altitude_min_spin.minimum(),
            self._altitude_min_spin.maximum(),
        )
        min_spin.setSingleStep(self._altitude_min_spin.singleStep())
        min_spin.setValue(self._altitude_min_spin.value())

        max_spin = QtWidgets.QDoubleSpinBox(dialog)
        max_spin.setDecimals(self._altitude_max_spin.decimals())
        max_spin.setRange(
            self._altitude_max_spin.minimum(),
            self._altitude_max_spin.maximum(),
        )
        max_spin.setSingleStep(self._altitude_max_spin.singleStep())
        max_spin.setValue(self._altitude_max_spin.value())

        layout.addRow(f"Minimum altitude ({unit_label}):", min_spin)
        layout.addRow(f"Maximum altitude ({unit_label}):", max_spin)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal,
            dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return False

        min_value = min_spin.value()
        max_value = max_spin.value()
        if min_value >= max_value:
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid Range",
                "Maximum altitude must be greater than minimum altitude.",
            )
            return False

        self._altitude_min_spin.setValue(min_value)
        self._altitude_max_spin.setValue(max_value)
        return True

    def show_grade_range_dialog(self) -> None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Grade Range")
        layout = QtWidgets.QFormLayout(dialog)

        min_spin = QtWidgets.QSpinBox(dialog)
        min_spin.setRange(-10000, 10000)
        min_spin.setSingleStep(1)
        min_spin.setValue(self._grade_slider.minimum())

        max_spin = QtWidgets.QSpinBox(dialog)
        max_spin.setRange(-10000, 10000)
        max_spin.setSingleStep(1)
        max_spin.setValue(self._grade_slider.maximum())

        layout.addRow("Minimum grade:", min_spin)
        layout.addRow("Maximum grade:", max_spin)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal,
            dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return

        minimum = min_spin.value()
        maximum = max_spin.value()
        if minimum >= maximum:
            QtWidgets.QMessageBox.warning(
                self,
                "Invalid Range",
                "Maximum grade must be greater than minimum grade.",
            )
            return

        self._grade_slider.setRange(minimum, maximum)
        self._grade_slider.setValue(
            min(max(self._grade_slider.value(), minimum), maximum)
        )

    def show_copy_xsect_targets_dialog(
        self,
        *,
        source_xsect_index: int,
        metadata: list[tuple[int, float]],
    ) -> list[int] | None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Copy X-Section data to...")
        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(
            QtWidgets.QLabel(
                f"Copy data from X-section {source_xsect_index} to selected X-sections:"
            )
        )

        list_widget = QtWidgets.QListWidget(dialog)
        unit = self._current_measurement_unit()
        unit_label = self._measurement_unit_label(unit)
        decimals = self._measurement_unit_decimals(unit)
        for idx, dlat in metadata:
            display_dlat = self._fsect_dlat_to_display_units(float(dlat))
            dlat_text = (
                f"{int(round(display_dlat))}"
                if decimals == 0
                else f"{display_dlat:.{decimals}f}".rstrip("0").rstrip(".")
            )
            item = QtWidgets.QListWidgetItem(
                f"X-section {idx} (DLAT {dlat_text} {unit_label})"
            )
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Unchecked)
            if idx == source_xsect_index:
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEnabled)
                item.setForeground(QtGui.QBrush(QtCore.Qt.gray))
            list_widget.addItem(item)
        layout.addWidget(list_widget)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal,
            dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return None

        targets: list[int] = []
        for row in range(list_widget.count()):
            item = list_widget.item(row)
            if item.checkState() == QtCore.Qt.Checked:
                targets.append(metadata[row][0])
        return targets

    def show_raise_lower_elevations_dialog(self) -> None:
        delta, ok = QtWidgets.QInputDialog.getDouble(
            self,
            "Raise/Lower Elevations",
            f"Elevation offset ({self._measurement_unit_label(self._current_measurement_unit())}):",
            0.0,
            -1000000.0,
            1000000.0,
            self._measurement_unit_decimals(self._current_measurement_unit()),
        )
        if not ok:
            return

        delta_500ths = units_to_500ths(delta, self._current_measurement_unit())
        if self._preview.offset_all_elevations(delta_500ths, validate=False):
            self._preview.validate_document()
            self.show_status_message(
                f"Adjusted all elevations by {delta:g} {self._measurement_unit_label(self._current_measurement_unit())}."
            )
        else:
            QtWidgets.QMessageBox.warning(
                self,
                "Raise/Lower Elevations",
                "Unable to update elevations.",
            )

    def show_generate_elevation_change_dialog(self, *, xsect_index: int) -> None:
        sections, _ = self._preview.get_section_set()
        if not sections:
            QtWidgets.QMessageBox.information(
                self,
                "Generate elevation change",
                "There are no track sections available.",
            )
            return

        if self._generate_elevation_change_dialog is not None:
            self._generate_elevation_change_dialog.raise_()
            self._generate_elevation_change_dialog.activateWindow()
            return

        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Generate elevation change")
        dialog.setModal(False)
        dialog.setWindowModality(QtCore.Qt.NonModal)
        layout = QtWidgets.QFormLayout(dialog)

        section_max = len(sections) - 1

        start_section_spin = QtWidgets.QSpinBox(dialog)
        start_section_spin.setRange(0, section_max)
        start_section_spin.setValue(0)

        end_section_spin = QtWidgets.QSpinBox(dialog)
        end_section_spin.setRange(0, section_max)
        end_section_spin.setValue(section_max)

        unit = self._current_measurement_unit()
        unit_label = self._measurement_unit_label(unit)
        decimals = self._measurement_unit_decimals(unit)

        start_elevation_spin = QtWidgets.QDoubleSpinBox(dialog)
        start_elevation_spin.setRange(-1000000.0, 1000000.0)
        start_elevation_spin.setDecimals(decimals)
        start_elevation_spin.setSingleStep(self._measurement_unit_step(unit))
        start_elevation_spin.setValue(0.0)

        end_elevation_spin = QtWidgets.QDoubleSpinBox(dialog)
        end_elevation_spin.setRange(-1000000.0, 1000000.0)
        end_elevation_spin.setDecimals(decimals)
        end_elevation_spin.setSingleStep(self._measurement_unit_step(unit))
        end_elevation_spin.setValue(0.0)

        curve_combo = QtWidgets.QComboBox(dialog)
        curve_combo.addItem("Linear", "linear")
        curve_combo.addItem("Convex", "convex")
        curve_combo.addItem("Concave", "concave")
        curve_combo.addItem("S-curve (flat bottom and top)", "s_curve")

        layout.addRow("Starting track section:", start_section_spin)
        layout.addRow("Ending track section:", end_section_spin)
        layout.addRow(f"Starting elevation ({unit_label}):", start_elevation_spin)
        layout.addRow(f"Ending elevation ({unit_label}):", end_elevation_spin)
        layout.addRow("Curve type:", curve_combo)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            QtCore.Qt.Horizontal,
            dialog,
        )
        buttons.rejected.connect(dialog.close)
        layout.addRow(buttons)

        def _apply_elevation_change() -> None:
            start_section = start_section_spin.value()
            end_section = end_section_spin.value()
            if end_section <= start_section:
                QtWidgets.QMessageBox.warning(
                    self,
                    "Generate elevation change",
                    "Ending section must be greater than starting section.",
                )
                return

            start_elevation = units_to_500ths(start_elevation_spin.value(), unit)
            end_elevation = units_to_500ths(end_elevation_spin.value(), unit)
            curve_type = str(curve_combo.currentData())

            if self._preview.generate_elevation_change(
                start_section_id=start_section,
                end_section_id=end_section,
                xsect_index=xsect_index,
                start_elevation=start_elevation,
                end_elevation=end_elevation,
                curve_type=curve_type,
                validate=False,
            ):
                self._preview.validate_document()
                self.show_status_message(
                    f"Generated {curve_combo.currentText().lower()} elevation change on x-section {xsect_index}."
                )
                self.generateElevationChangeApplied.emit()
                dialog.close()
                return

            QtWidgets.QMessageBox.warning(
                self,
                "Generate elevation change",
                "Unable to generate elevation change for the selected range.",
            )

        def _clear_dialog_ref() -> None:
            self._generate_elevation_change_dialog = None

        buttons.accepted.connect(_apply_elevation_change)
        dialog.finished.connect(_clear_dialog_ref)
        self._generate_elevation_change_dialog = dialog
        dialog.show()

    def show_flatten_all_elevations_and_grade_dialog(self) -> bool:
        elevation, ok = QtWidgets.QInputDialog.getDouble(
            self,
            "Flatten All Elevations + Grade",
            f"Set all elevations to ({self._measurement_unit_label(self._current_measurement_unit())}):",
            0.0,
            -1000000.0,
            1000000.0,
            self._measurement_unit_decimals(self._current_measurement_unit()),
        )
        if not ok:
            return False

        elevation_500ths = units_to_500ths(elevation, self._current_measurement_unit())
        if self._preview.flatten_all_elevations_and_grade(
            elevation_500ths,
            grade=0,
            validate=False,
        ):
            self._preview.validate_document()
            self.show_status_message(
                f"Flattened all elevations to {elevation:g} {self._measurement_unit_label(self._current_measurement_unit())} and set all grades to 0."
            )
            return True

        QtWidgets.QMessageBox.warning(
            self,
            "Flatten All Elevations + Grade",
            "Unable to flatten elevations and grade.",
        )
        return False

    def _current_measurement_unit(self) -> str:
        return str(self._measurement_units_combo.currentData())

    def current_measurement_unit(self) -> str:
        return self._current_measurement_unit()

    @staticmethod
    def _measurement_unit_label(unit: str) -> str:
        return measurement_unit_label(unit)

    @staticmethod
    def _measurement_unit_decimals(unit: str) -> int:
        return measurement_unit_decimals(unit)

    @staticmethod
    def _measurement_unit_step(unit: str) -> float:
        return measurement_unit_step(unit)

    def update_xsect_table_headers(self) -> None:
        unit_label = self._xsect_altitude_units_label()
        self._xsect_elevation_table.setHorizontalHeaderLabels(
            ["Xsect", f"DLAT ({unit_label})", f"Elevation ({unit_label})", "Grade"]
        )

    def _xsect_altitude_units_label(self) -> str:
        return fsect_dlat_units_label(unit=self._current_measurement_unit())

    def xsect_altitude_to_display_units(self, value: int) -> float:
        return xsect_altitude_to_display_units(
            value, unit=self._current_measurement_unit()
        )

    def xsect_altitude_from_display_units(self, value: float) -> int:
        return xsect_altitude_from_display_units(
            value, unit=self._current_measurement_unit()
        )

    def _format_xsect_altitude(self, value: int) -> str:
        return format_xsect_altitude(value, unit=self._current_measurement_unit())

    def xsect_altitude_unit(self) -> str:
        return self._current_measurement_unit()

    def xsect_altitude_unit_label(self) -> str:
        return self._xsect_altitude_units_label()

    def xsect_altitude_display_decimals(self) -> int:
        return self._measurement_unit_decimals(self._current_measurement_unit())

    def update_grade_display(self, value: int) -> None:
        self._grade_value_label.setText(str(value))

    def update_altitude_display(self, value: int) -> None:
        altitude_feet = feet_from_slider_units(value)
        altitude = units_to_500ths(altitude_feet, "feet")
        self._altitude_value_label.setText(self._format_altitude_for_units(altitude))

    def update_selection_sidebar(self, selection: SectionSelection | None) -> None:
        if selection is None:
            self._selected_section_index = None
            self._section_summary_title_label.setText("No section selected")
            self._section_summary_detail_label.setText(
                "Select a section to inspect geometry, connections, and metadata."
            )
            for key in self._section_health_labels:
                self._set_section_health(key, "Unknown", "–")
            for store in (
                self._section_geometry_labels,
                self._section_connection_labels,
                self._section_boundary_labels,
                self._section_subsection_labels,
                self._section_context_labels,
                self._section_view_labels,
                self._section_advanced_labels,
            ):
                for label in store.values():
                    label.setText("–")
            self._set_section_value(
                self._section_view_labels,
                "Units",
                self._measurement_unit_label(self._current_measurement_unit()),
            )
            self._set_section_value(
                self._section_view_labels,
                "Zoom",
                self._zoom_factor_label.text().removeprefix("Zoom Factor: "),
            )
            self._section_split_action_button.setEnabled(False)
            self._section_delete_action_button.setEnabled(False)
            self._section_set_start_finish_action_button.setEnabled(False)
            self._section_index_label.setText("Current Section: –")
            self._update_current_section_banner(None)
            self._section_start_dlong_label.setText("Starting DLONG: –")
            self._section_end_dlong_label.setText("Ending DLONG: –")
            self._radius_label.setText("Radius: –")
            self._previous_label.setText("Previous Section: –")
            self._next_label.setText("Next Section: –")
            self._section_length_label.setText("Section Length: –")
            self._update_section_subindex_labels(None)
            self._previous_section_length_label.setText("Previous Section Length: –")
            self._next_section_length_label.setText("Next Section Length: –")
            self._set_adjusted_dlong_labels(None)
            self._profile_widget.set_selected_range(None)
            self._update_fsect_table(None)
            self._update_boundary_dlat_labels(None)
            return

        self._selected_section_index = selection.index
        radius_value = (
            selection.sg_radius if selection.sg_radius is not None else selection.radius
        )
        type_name = selection.type_name.title() if selection.type_name else "Unknown"
        summary_parts = [
            f"{type_name}",
            f"DLONG {self.format_length(selection.start_dlong)}–{self.format_length(selection.end_dlong)}",
            f"Length {self.format_length_with_secondary(selection.length)}",
        ]
        if radius_value is not None and str(selection.type_name).lower() == "curve":
            summary_parts.append(f"Radius {self.format_length(radius_value)}")
        starts = self._section_subindex_metadata.get(int(selection.index), tuple())
        if starts:
            summary_parts.append(f"{len(starts)} subsections")
        self._section_summary_title_label.setText(f"Section {selection.index}")
        self._section_summary_detail_label.setText(" · ".join(summary_parts))
        self._section_split_action_button.setEnabled(
            self._split_section_button.isEnabled()
        )
        self._section_delete_action_button.setEnabled(
            self._delete_section_button.isEnabled()
        )
        self._section_set_start_finish_action_button.setEnabled(
            self._set_start_finish_button.isEnabled()
        )
        self._section_index_label.setText(f"Current Section: {selection.index}")
        self._update_current_section_banner(selection.index)
        self._section_start_dlong_label.setText(
            f"Starting DLONG: {self.format_length(selection.start_dlong)}"
        )
        self._section_end_dlong_label.setText(
            f"Ending DLONG: {self.format_length(selection.end_dlong)}"
        )
        self._section_length_label.setText(
            f"Section Length: {self.format_length_with_secondary(selection.length)}"
        )
        self._update_section_subindex_labels(selection.index)
        self._previous_section_length_label.setText(
            self._format_section_length("Previous", selection.previous_length)
        )
        self._next_section_length_label.setText(
            self._format_section_length("Next", selection.next_length)
        )
        self._update_adjusted_dlong_labels(selection)

        radius_value = selection.sg_radius
        if radius_value is None:
            radius_value = selection.radius
        self._radius_label.setText(f"Radius: {self.format_length(radius_value)}")
        self._previous_label.setText(
            self._format_section_link("Previous", selection.previous_id)
        )
        self._next_label.setText(self._format_section_link("Next", selection.next_id))

        selected_range = self._preview.get_section_range(selection.index)
        self._profile_widget.set_selected_range(selected_range)
        self._update_fsect_table(selection.index)
        self._update_boundary_dlat_labels(selection.index)
        self._update_section_inspector_details(selection)

    def _update_section_inspector_details(self, selection: SectionSelection) -> None:
        sections, track_length = self._preview.get_section_set()
        total = len(sections)
        adjusted = self._adjusted_section_dlongs(selection.index)
        starts = self._section_subindex_metadata.get(int(selection.index), tuple())
        radius_value = (
            selection.sg_radius if selection.sg_radius is not None else selection.radius
        )
        prev_ok = selection.previous_id != -1 and selection.previous_length is not None
        next_ok = selection.next_id != -1 and selection.next_length is not None

        self._set_section_health("selected", "OK", f"Section {selection.index}")
        self._set_section_health(
            "length",
            "OK" if selection.length > 0 else "Error",
            self.format_length_with_secondary(selection.length),
        )
        self._set_section_health(
            "previous",
            "OK" if prev_ok else "Warning",
            (
                "Not connected"
                if selection.previous_id == -1
                else f"Section {selection.previous_id}"
            ),
        )
        self._set_section_health(
            "next",
            "OK" if next_ok else "Warning",
            (
                "Not connected"
                if selection.next_id == -1
                else f"Section {selection.next_id}"
            ),
        )
        start_status, start_detail = self._section_tangency_status(
            sections, selection, at_start=True
        )
        end_status, end_detail = self._section_tangency_status(
            sections, selection, at_start=False
        )
        self._set_section_health("start_tangency", start_status, start_detail)
        self._set_section_health("end_tangency", end_status, end_detail)
        if str(selection.type_name).lower() == "curve" and radius_value is not None:
            self._set_section_health(
                "radius",
                "Warning" if abs(float(radius_value)) < 1.0 else "OK",
                self.format_length(radius_value),
            )
        else:
            self._set_section_health("radius", "OK", "Not a curve")
        fsects = self._preview.get_section_fsects(selection.index)
        boundary_number_by_row = boundary_numbers_for_fsects(fsects)
        self._set_section_health(
            "boundaries",
            "OK" if boundary_number_by_row else "Unknown",
            (
                "B0/B1 present"
                if len(boundary_number_by_row) >= 2
                else (
                    "Some boundary data present"
                    if boundary_number_by_row
                    else "No boundary data"
                )
            ),
        )
        self._set_section_health(
            "fsects",
            "OK" if fsects else "Unknown",
            f"{len(fsects)} rows" if fsects else "No fsect rows",
        )
        self._set_section_health(
            "dlong",
            "OK" if selection.end_dlong >= selection.start_dlong else "Error",
            f"{self.format_length(selection.start_dlong)}–{self.format_length(selection.end_dlong)}",
        )
        self._set_section_health(
            "adjusted",
            "OK" if adjusted is not None else "Unknown",
            "Available" if adjusted is not None else "Unavailable",
        )

        geom = self._section_geometry_labels
        self._set_section_value(geom, "Type", selection.type_name.title())
        self._set_section_value(
            geom, "Start DLONG", self.format_length(selection.start_dlong)
        )
        self._set_section_value(
            geom, "End DLONG", self.format_length(selection.end_dlong)
        )
        self._set_section_value(
            geom, "Length", self.format_length_with_secondary(selection.length)
        )
        self._set_section_value(
            geom,
            "Radius",
            (
                self.format_length(radius_value)
                if radius_value is not None
                and str(selection.type_name).lower() == "curve"
                else "–"
            ),
        )
        self._set_section_value(
            geom, "Start point", self._format_point(selection.start_point)
        )
        self._set_section_value(
            geom, "End point", self._format_point(selection.end_point)
        )
        self._set_section_value(
            geom,
            "Start heading",
            self._format_heading(selection.start_heading or selection.sg_start_heading),
        )
        self._set_section_value(
            geom,
            "End heading",
            self._format_heading(selection.end_heading or selection.sg_end_heading),
        )
        self._set_section_value(
            geom, "Curve center", self._format_point(selection.center)
        )
        self._set_section_value(
            geom,
            "Curve arc/sweep",
            (
                f"{selection.sg_sang1}/{selection.sg_sang2} → {selection.sg_eang1}/{selection.sg_eang2}"
                if selection.sg_sang1 is not None
                else "–"
            ),
        )
        if adjusted is not None:
            start, end, length = adjusted
            self._set_section_value(geom, "Adjusted start", self.format_length(start))
            self._set_section_value(geom, "Adjusted end", self.format_length(end))
            self._set_section_value(
                geom, "Adjusted length", self.format_length_with_secondary(length)
            )
        conn = self._section_connection_labels
        self._set_section_value(
            conn,
            "Previous",
            (
                "Not connected"
                if selection.previous_id == -1
                else f"Section {selection.previous_id}"
            ),
        )
        self._set_section_value(
            conn,
            "Next",
            (
                "Not connected"
                if selection.next_id == -1
                else f"Section {selection.next_id}"
            ),
        )
        self._set_section_value(
            conn,
            "Previous length",
            (
                self.format_length_with_secondary(selection.previous_length)
                if selection.previous_length is not None
                else "–"
            ),
        )
        self._set_section_value(
            conn,
            "Next length",
            (
                self.format_length_with_secondary(selection.next_length)
                if selection.next_length is not None
                else "–"
            ),
        )
        self._set_section_value(
            conn, "Previous status", "Connected" if prev_ok else "Unknown"
        )
        self._set_section_value(
            conn, "Next status", "Connected" if next_ok else "Unknown"
        )
        previous_gap, previous_heading_mismatch = self._section_connection_metrics(
            sections, selection, at_start=True
        )
        next_gap, next_heading_mismatch = self._section_connection_metrics(
            sections, selection, at_start=False
        )
        self._set_section_value(conn, "Gap to previous", previous_gap)
        self._set_section_value(conn, "Gap to next", next_gap)
        self._set_section_value(
            conn, "Heading mismatch previous", previous_heading_mismatch
        )
        self._set_section_value(conn, "Heading mismatch next", next_heading_mismatch)

        self._set_section_value(
            self._section_boundary_labels,
            "Summary",
            (
                f"{len(boundary_number_by_row)} boundary rows"
                if boundary_number_by_row
                else "No boundary rows"
            ),
        )
        for name in self._section_boundary_labels:
            if name.startswith("B"):
                self._set_section_value(self._section_boundary_labels, name, "–")
        for row_index, boundary_number in sorted(
            boundary_number_by_row.items(), key=lambda item: int(item[1])
        ):
            if f"B{boundary_number}" in self._section_boundary_labels:
                fsect = fsects[row_index]
                self._set_section_value(
                    self._section_boundary_labels,
                    f"B{boundary_number}",
                    f"DLAT start {self._format_fsect_dlat(fsect.start_dlat)}, end {self._format_fsect_dlat(fsect.end_dlat)} {self._fsect_dlat_units_label()}",
                )

        sub = self._section_subsection_labels
        self._set_section_value(sub, "Count", str(len(starts)))
        self._set_section_value(
            sub,
            "Starts",
            ", ".join(self.format_length(v) for v in starts) if starts else "–",
        )
        if adjusted is not None:
            start, end, length = adjusted
            self._set_section_value(sub, "Adjusted start", self.format_length(start))
            self._set_section_value(sub, "Adjusted end", self.format_length(end))
            self._set_section_value(
                sub, "Adjusted length", self.format_length_with_secondary(length)
            )

        ctx = self._section_context_labels
        self._set_section_value(
            ctx,
            "Track length",
            self.format_length(track_length) if track_length else "–",
        )
        self._set_section_value(
            ctx,
            "Miles",
            (
                f"{units_from_500ths(float(track_length), 'feet') / 5280.0:.3f} mi"
                if track_length
                else "–"
            ),
        )
        self._set_section_value(
            ctx,
            "Section position",
            f"{selection.index + 1} of {total}" if total else "–",
        )
        self._set_section_value(
            ctx,
            "Lap percentage",
            (
                f"{selection.start_dlong / track_length * 100:.1f}%–{selection.end_dlong / track_length * 100:.1f}%"
                if track_length
                else "–"
            ),
        )
        self._set_section_value(
            self._section_view_labels,
            "Zoom",
            self._zoom_factor_label.text().removeprefix("Zoom Factor: "),
        )
        self._set_section_value(
            self._section_view_labels,
            "Units",
            self._measurement_unit_label(self._current_measurement_unit()),
        )
        adv = self._section_advanced_labels
        self._set_section_value(adv, "Raw section id", str(selection.index))
        self._set_section_value(adv, "Raw previous id", str(selection.previous_id))
        self._set_section_value(adv, "Raw next id", str(selection.next_id))
        self._set_section_value(
            adv,
            "SG radius",
            str(selection.sg_radius) if selection.sg_radius is not None else "–",
        )
        self._set_section_value(
            adv,
            "SG angles",
            f"{selection.sg_sang1}/{selection.sg_sang2}/{selection.sg_eang1}/{selection.sg_eang2}",
        )
        self._set_section_value(adv, "Subindex starts", repr(starts))

    def set_section_subindex_metadata(
        self, metadata: dict[int, tuple[int, ...]]
    ) -> None:
        self._section_subindex_metadata = dict(metadata)
        if self._selected_section_index is not None:
            self._update_section_subindex_labels(self._selected_section_index)

    def _update_section_subindex_labels(self, section_index: int | None) -> None:
        if section_index is None:
            self._section_subindex_count_label.setText("Section SubIndexes (.3d): –")
            self._section_subindex_starts_label.setText(
                "SubIndex Start DLONGs (.3d): –"
            )
            return

        starts = self._section_subindex_metadata.get(int(section_index), tuple())
        self._section_subindex_count_label.setText(
            f"Section SubIndexes (.3d): {len(starts)}"
        )
        if starts:
            starts_text = ", ".join(self.format_length(value) for value in starts)
        else:
            starts_text = "–"
        self._section_subindex_starts_label.setText(
            f"SubIndex Start DLONGs (.3d): {starts_text}"
        )

    def _format_section_length(self, prefix: str, length: float | None) -> str:
        value = "–" if length is None else self.format_length_with_secondary(length)
        return f"{prefix} Section Length: {value}"

    @staticmethod
    def _format_section_link(prefix: str, section_id: int) -> str:
        connection = "Not connected" if section_id == -1 else f"{section_id}"
        return f"{prefix} Section: {connection}"

    def _update_adjusted_dlong_labels_for_current_selection(self) -> None:
        if self._selected_section_index is None:
            self._set_adjusted_dlong_labels(None)
            return
        self._set_adjusted_dlong_labels(
            self._adjusted_section_dlongs(self._selected_section_index)
        )

    def _update_adjusted_dlong_labels(self, selection: SectionSelection) -> None:
        adjusted = self._adjusted_section_dlongs(selection.index)
        self._set_adjusted_dlong_labels(adjusted)

    def _set_adjusted_dlong_labels(self, adjusted: tuple[int, int, int] | None) -> None:
        if adjusted is None:
            self._adjusted_section_start_dlong_label.setText(
                "Adjusted Starting DLONG: –"
            )
            self._adjusted_section_end_dlong_label.setText("Adjusted Ending DLONG: –")
            self._adjusted_section_length_label.setText("Adjusted Section Length: –")
            self._update_current_section_banner(self._selected_section_index)
            return
        start_dlong, end_dlong, length = adjusted
        self._adjusted_section_start_dlong_label.setText(
            f"Adjusted Starting DLONG: {self.format_length(start_dlong)}"
        )
        self._adjusted_section_end_dlong_label.setText(
            f"Adjusted Ending DLONG: {self.format_length(end_dlong)}"
        )
        self._adjusted_section_length_label.setText(
            f"Adjusted Section Length: {self.format_length_with_secondary(length)}"
        )
        self._update_current_section_banner(self._selected_section_index)

    def _update_current_section_banner(self, section_index: int | None) -> None:
        if section_index is None:
            self._current_section_banner.setText(
                "Currently selected section: – (Adjusted DLONG –)"
            )
            return
        adjusted = self._adjusted_section_dlongs(section_index)
        if adjusted is None:
            adjusted_text = "–"
        else:
            start_dlong, end_dlong, _length = adjusted
            adjusted_text = (
                f"{self.format_length(start_dlong)}–{self.format_length(end_dlong)}"
            )
        self._current_section_banner.setText(
            f"Currently selected section: {section_index} "
            f"(Adjusted DLONG {adjusted_text})"
        )

    def _adjusted_section_dlongs(
        self, section_index: int
    ) -> tuple[int, int, int] | None:
        cache = self._adjusted_section_ranges_cache
        if cache is None:
            cache = self._rebuild_adjusted_section_ranges_cache()
        if cache is None or section_index < 0 or section_index >= len(cache):
            return None
        return cache[section_index]

    def invalidate_adjusted_section_range_cache(self) -> None:
        self._adjusted_section_ranges_cache = None

    def _rebuild_adjusted_section_ranges_cache(
        self,
    ) -> tuple[tuple[int, int, int], ...] | None:
        sgfile = self._preview.sgfile
        if sgfile is None:
            return None
        if sgfile.num_xsects <= 0 or len(sgfile.xsect_dlats) == 0:
            return None

        xsect_pair = self._centerline_xsect_pair(list(sgfile.xsect_dlats))
        if xsect_pair is None:
            return None
        right_idx, left_idx, centerline_pct = xsect_pair

        centerline_altitudes: list[float] = []
        centerline_grades: list[float] = []
        for section in sgfile.sects:
            if right_idx >= len(section.alt) or left_idx >= len(section.alt):
                return None
            if right_idx >= len(section.grade) or left_idx >= len(section.grade):
                return None
            centerline_altitudes.append(
                section.alt[right_idx]
                + centerline_pct * (section.alt[left_idx] - section.alt[right_idx])
            )
            centerline_grades.append(
                section.grade[right_idx]
                + centerline_pct * (section.grade[left_idx] - section.grade[right_idx])
            )

        adjusted_lengths: list[int] = []
        for index, section in enumerate(sgfile.sects):
            previous_index = len(sgfile.sects) - 1 if index == 0 else index - 1
            begin_alt = centerline_altitudes[previous_index]
            end_alt = centerline_altitudes[index]
            section_length = section.length
            if section_length == 0:
                return None
            current_slope = centerline_grades[previous_index] / 8192
            next_slope = centerline_grades[index] / 8192
            grade1 = round(
                (
                    2 * begin_alt / section_length
                    + current_slope
                    + next_slope
                    - 2 * end_alt / section_length
                )
                * section_length
            )
            grade2 = round(
                (
                    3 * end_alt / section_length
                    - 3 * begin_alt / section_length
                    - 2 * current_slope
                    - next_slope
                )
                * section_length
            )
            grade3 = round(current_slope * section_length)
            adjusted_lengths.append(
                round(
                    self._runtime_api.approx_curve_length_intent(
                        grade1,
                        grade2,
                        grade3,
                        centerline_altitudes[index],
                        section_length,
                    )
                )
            )

        adjusted_ranges: list[tuple[int, int, int]] = []
        running_start = 0
        for adjusted_length in adjusted_lengths:
            adjusted_end = running_start + adjusted_length
            adjusted_ranges.append((running_start, adjusted_end, adjusted_length))
            running_start = adjusted_end
        self._adjusted_section_ranges_cache = tuple(adjusted_ranges)
        return self._adjusted_section_ranges_cache

    def adjusted_section_range_500ths(
        self, section_index: int
    ) -> tuple[int, int] | None:
        adjusted = self._adjusted_section_dlongs(section_index)
        if adjusted is None:
            return None
        return adjusted[0], adjusted[1]

    @staticmethod
    def _centerline_xsect_pair(
        xsect_dlats: list[int],
    ) -> tuple[int, int, float] | None:
        if not xsect_dlats:
            return None

        for xsect_index in range(0, len(xsect_dlats) - 1):
            right = xsect_dlats[xsect_index]
            left = xsect_dlats[xsect_index + 1]
            if right < 0 <= left:
                denom = left - right
                centerline_pct = 0.0 if denom == 0 else (-right / denom)
                return xsect_index, xsect_index + 1, centerline_pct

        right_candidates = [idx for idx, value in enumerate(xsect_dlats) if value <= 0]
        left_candidates = [idx for idx, value in enumerate(xsect_dlats) if value >= 0]
        if not right_candidates or not left_candidates:
            closest = min(
                range(len(xsect_dlats)), key=lambda idx: abs(xsect_dlats[idx])
            )
            return closest, closest, 0.0

        right_idx = max(right_candidates, key=lambda idx: xsect_dlats[idx])
        left_idx = min(left_candidates, key=lambda idx: xsect_dlats[idx])
        if right_idx == left_idx:
            return right_idx, left_idx, 0.0
        right = xsect_dlats[right_idx]
        left = xsect_dlats[left_idx]
        denom = left - right
        centerline_pct = 0.0 if denom == 0 else (-right / denom)
        return right_idx, left_idx, centerline_pct

    def _update_fsect_table(self, section_index: int | None) -> None:
        fsects = self._preview.get_section_fsects(section_index)
        self._updating_fsect_table = True
        for table_row in range(self._fsect_table.rowCount()):
            for table_column in range(self._fsect_table.columnCount()):
                self._fsect_table.removeCellWidget(table_row, table_column)
        self._fsect_table.clearContents()
        self._fsect_table.setRowCount(5)
        self._fsect_table.setColumnCount(len(fsects))
        self._update_fsect_table_headers()
        read_only_background = QtGui.QColor(230, 230, 230)
        for column_index in range(len(fsects)):
            fsect_index = self._fsect_model_index_for_column(column_index)
            fsect = fsects[fsect_index]
            next_fsect = (
                fsects[fsect_index + 1] if fsect_index < len(fsects) - 1 else None
            )

            combo = QtWidgets.QComboBox()
            for label, surface_type, type2 in fsect_type_options():
                combo.addItem(label, (surface_type, type2))
            combo.setCurrentIndex(fsect_type_index(fsect.surface_type, fsect.type2))
            self._apply_fsect_type_combo_color(combo)
            combo.currentIndexChanged.connect(
                lambda _idx, index=fsect_index, widget=combo: self._on_fsect_type_changed(
                    index, widget
                )
            )
            self._fsect_table.setCellWidget(0, column_index, combo)

            end_delta_item = QtWidgets.QTableWidgetItem(
                format_fsect_delta(
                    fsects, fsect_index, "end", unit=self._current_measurement_unit()
                )
            )
            end_delta_item.setBackground(read_only_background)
            end_delta_item.setFlags(end_delta_item.flags() & ~QtCore.Qt.ItemIsEditable)

            end_item = QtWidgets.QTableWidgetItem(
                self._format_fsect_dlat(fsect.end_dlat)
            )
            if next_fsect is not None and fsect.end_dlat > next_fsect.end_dlat:
                end_item.setBackground(QtGui.QColor("salmon"))
            end_item.setFlags(
                end_item.flags() | QtCore.Qt.ItemIsEditable | QtCore.Qt.ItemIsSelectable
            )

            start_item = QtWidgets.QTableWidgetItem(
                self._format_fsect_dlat(fsect.start_dlat)
            )
            if next_fsect is not None and fsect.start_dlat > next_fsect.start_dlat:
                start_item.setBackground(QtGui.QColor("salmon"))
            start_item.setFlags(
                start_item.flags()
                | QtCore.Qt.ItemIsEditable
                | QtCore.Qt.ItemIsSelectable
            )

            start_delta_item = QtWidgets.QTableWidgetItem(
                format_fsect_delta(
                    fsects, fsect_index, "start", unit=self._current_measurement_unit()
                )
            )
            start_delta_item.setBackground(read_only_background)
            start_delta_item.setFlags(
                start_delta_item.flags() & ~QtCore.Qt.ItemIsEditable
            )

            self._fsect_table.setItem(1, column_index, end_delta_item)
            self._fsect_table.setItem(2, column_index, end_item)
            self._fsect_table.setItem(3, column_index, start_item)
            self._fsect_table.setItem(4, column_index, start_delta_item)

        self._updating_fsect_table = False
        self._update_fsect_selected_column_header()
        self._fsect_table.resizeColumnsToContents()
        prev_fsects: list[PreviewFSection] = []
        next_fsects: list[PreviewFSection] = []
        if section_index is not None:
            sections, _track_length = self._preview.get_section_set()
            section_count = len(sections)
            if section_count > 0:
                prev_index = (section_index - 1) % section_count
                next_index = (section_index + 1) % section_count
                prev_fsects = self._preview.get_section_fsects(prev_index)
                next_fsects = self._preview.get_section_fsects(next_index)
        self._fsect_diagram.set_fsects(
            section_index,
            fsects,
            prev_fsects=prev_fsects,
            next_fsects=next_fsects,
        )
        self._update_boundary_dlat_labels(section_index)

    def _update_boundary_dlat_labels(self, section_index: int | None) -> None:
        if section_index is None:
            self._section_boundary_dlats_label.setText("Boundary DLATs: –")
            return

        fsects = self._preview.get_section_fsects(section_index)
        boundary_number_by_row = boundary_numbers_for_fsects(fsects)
        if not boundary_number_by_row:
            self._section_boundary_dlats_label.setText("Boundary DLATs: none")
            return

        unit_label = self._fsect_dlat_units_label()
        lines: list[str] = [f"Boundary DLATs ({unit_label}):"]
        for row_index, boundary_number in sorted(
            boundary_number_by_row.items(), key=lambda item: int(item[1])
        ):
            fsect = fsects[row_index]
            lines.append(
                f"B{boundary_number}: Start {self._format_fsect_dlat(fsect.start_dlat)}, End {self._format_fsect_dlat(fsect.end_dlat)}"
            )
        self._section_boundary_dlats_label.setText("\n".join(lines))

    def _on_preview_scale_changed(self, scale: float) -> None:
        _ = scale
        self._refresh_query_track_info_label()
        self._set_section_value(
            self._section_view_labels,
            "Zoom",
            self._zoom_factor_label.text().removeprefix("Zoom Factor: "),
        )

    def _section_connection_metrics(
        self, sections: list, selection: SectionSelection, *, at_start: bool
    ) -> tuple[str, str]:
        neighbor_id = selection.previous_id if at_start else selection.next_id
        if neighbor_id == -1 or neighbor_id < 0 or neighbor_id >= len(sections):
            return "Not connected", "Not connected"

        neighbor = sections[neighbor_id]
        current_point = selection.start_point if at_start else selection.end_point
        neighbor_point = neighbor.end if at_start else neighbor.start
        if current_point is None or neighbor_point is None:
            gap_text = "Point unavailable"
        else:
            gap = math.hypot(
                float(current_point[0]) - float(neighbor_point[0]),
                float(current_point[1]) - float(neighbor_point[1]),
            )
            gap_text = self.format_length_with_secondary(gap)

        current_heading = selection.start_heading if at_start else selection.end_heading
        neighbor_heading = neighbor.end_heading if at_start else neighbor.start_heading
        delta = (
            self._heading_delta_degrees(neighbor_heading, current_heading)
            if current_heading is not None and neighbor_heading is not None
            else None
        )
        heading_text = f"{delta:.2f}°" if delta is not None else "Heading unavailable"
        return gap_text, heading_text

    def _section_tangency_status(
        self, sections: list, selection: SectionSelection, *, at_start: bool
    ) -> tuple[str, str]:
        neighbor_id = selection.previous_id if at_start else selection.next_id
        if neighbor_id == -1 or neighbor_id < 0 or neighbor_id >= len(sections):
            return "Warning", "Not connected"
        current_heading = selection.start_heading if at_start else selection.end_heading
        neighbor = sections[neighbor_id]
        neighbor_heading = neighbor.end_heading if at_start else neighbor.start_heading
        if current_heading is None or neighbor_heading is None:
            return "Unknown", "Heading unavailable"
        delta = self._heading_delta_degrees(neighbor_heading, current_heading)
        if delta is None:
            return "Unknown", "Heading unavailable"
        status = "OK" if delta <= 1.0 else ("Warning" if delta <= 5.0 else "Error")
        return status, f"{delta:.2f}° mismatch vs section {neighbor_id}"

    @staticmethod
    def _heading_delta_degrees(
        heading_a: tuple[float, float], heading_b: tuple[float, float]
    ) -> float | None:
        ax, ay = float(heading_a[0]), float(heading_a[1])
        bx, by = float(heading_b[0]), float(heading_b[1])
        if (ax == 0.0 and ay == 0.0) or (bx == 0.0 and by == 0.0):
            return None
        angle_a = math.degrees(math.atan2(ay, ax))
        angle_b = math.degrees(math.atan2(by, bx))
        delta = (angle_b - angle_a + 180.0) % 360.0 - 180.0
        return abs(delta)

    def _on_query_track_toggled(self, checked: bool) -> None:
        self._query_track_mode_active = bool(checked)
        self._query_track_info_frozen = False
        if not self._query_track_mode_active:
            self._query_track_result = None
            self._preview.set_query_track_hover_point(None)
        else:
            self.show_status_message(
                "Inspect Track active. Press Space to freeze/unfreeze overlay details."
            )
        self._refresh_query_track_info_label()

    def _toggle_query_track_info_freeze(self) -> None:
        if not self._query_track_mode_active:
            return
        self._query_track_info_frozen = not self._query_track_info_frozen
        if self._query_track_info_frozen:
            self.show_status_message(
                "Inspect Track overlay frozen. Press Space again to resume live updates."
            )
        else:
            self.show_status_message("Inspect Track overlay live updates resumed.")
        self._refresh_query_track_info_label()

    def _on_preview_pointer_left(self) -> None:
        if not self._query_track_mode_active or self._query_track_info_frozen:
            pass
        else:
            self._query_track_result = None
            self._preview.set_query_track_hover_point(None)
            self._refresh_query_track_info_label()
        if (
            self._ruler_mode_active
            and self._ruler_start_point is not None
            and not self._ruler_frozen
        ):
            self._update_ruler_overlay(self._ruler_start_point, self._ruler_start_point)

    def _on_preview_pointer_moved(self, point: QtCore.QPointF) -> None:
        if (
            self._ruler_mode_active
            and self._ruler_start_point is not None
            and not self._ruler_frozen
        ):
            track_point = self._track_point_from_preview_position(point)
            if track_point is not None:
                self._update_ruler_overlay(self._ruler_start_point, track_point)
        if not self._query_track_mode_active or self._query_track_info_frozen:
            return

        track_point = self._track_point_from_preview_position(point)
        if track_point is None:
            return

        centerline_index = self._preview.section_manager.centerline_index
        sampled_dlongs = self._preview.section_manager.sampled_dlongs
        sections = self._preview.section_manager.sections
        track_length = float(
            sum(max(0.0, float(section.length)) for section in sections)
        )
        if centerline_index is None or not sampled_dlongs or track_length <= 0.0:
            self._query_track_result = None
            self._preview.set_query_track_hover_point(None)
            self._refresh_query_track_info_label()
            return

        projected_point, projected_dlong, distance_sq = project_point_to_centerline(
            track_point, centerline_index, sampled_dlongs, track_length
        )
        if projected_point is None or projected_dlong is None:
            self._query_track_result = None
            self._preview.set_query_track_hover_point(None)
            self._refresh_query_track_info_label()
            return

        widget_size = self._preview.widget_size()
        transform = self._preview.current_transform(widget_size)
        if transform is None:
            return
        zoom_scale = max(float(transform[0]), 0.0)
        pixel_distance = (distance_sq**0.5) * zoom_scale
        if pixel_distance > 16.0:
            self._query_track_result = None
            self._preview.set_query_track_hover_point(None)
            self._refresh_query_track_info_label()
            return

        mapped = dlong_to_section_position(sections, projected_dlong, track_length)
        if mapped is None:
            self._query_track_result = None
            self._preview.set_query_track_hover_point(None)
            self._refresh_query_track_info_label()
            return

        section_index = int(mapped.section_index)
        progress = max(0.0, min(1.0, float(mapped.fraction)))

        boundary_dlats: list[tuple[str, float, float | None]] = []
        fsects = self._preview.get_section_fsects(section_index)
        boundary_number_by_row = boundary_numbers_for_fsects(fsects)
        for row_index, boundary_number in sorted(
            boundary_number_by_row.items(), key=lambda item: int(item[1])
        ):
            fsect = fsects[row_index]
            dlat = (
                float(fsect.start_dlat)
                + (float(fsect.end_dlat) - float(fsect.start_dlat)) * progress
            )
            elevation = self._sample_elevation_at_dlat(section_index, progress, dlat)
            boundary_dlats.append((f"B{boundary_number}", dlat, elevation))

        adjusted_range = self._adjusted_section_dlongs(section_index)
        adjusted_dlong = None
        if adjusted_range is not None:
            adjusted_start, _adjusted_end, adjusted_length = adjusted_range
            adjusted_dlong = float(adjusted_start) + float(adjusted_length) * progress

        centerline_elevation = self._sample_centerline_elevation(
            section_index, progress
        )

        self._query_track_result = {
            "section_index": section_index,
            "adjusted_dlong": adjusted_dlong,
            "boundary_dlats": tuple(boundary_dlats),
            "centerline_elevation": centerline_elevation,
        }
        self._preview.set_query_track_hover_point(projected_point)
        self._refresh_query_track_info_label()

    def _track_point_from_preview_position(
        self,
        point: QtCore.QPointF,
    ) -> tuple[float, float] | None:
        widget_size = self._preview.widget_size()
        transform = self._preview.current_transform(widget_size)
        if transform is None:
            return None
        return self._preview.map_to_track(
            (float(point.x()), float(point.y())),
            widget_size,
            self._preview.widget_height(),
            transform,
        )

    def _draw_land_objects_tab_active(self) -> bool:
        return self.active_sidebar_tab_name() == "Draw land objects"

    def _append_land_point_from_track(self, track_point: tuple[float, float]) -> None:
        boundary_sample = self._nearest_boundary_sample(track_point)
        z_value = boundary_sample[2] if boundary_sample is not None else None
        row = self._land_points_table.rowCount()
        self._land_points_table.insertRow(row)
        self._land_points_table.setItem(row, 0, QtWidgets.QTableWidgetItem(str(row)))
        self._land_points_table.setItem(
            row, 1, QtWidgets.QTableWidgetItem(f"{float(track_point[0]):.1f}")
        )
        self._land_points_table.setItem(
            row, 2, QtWidgets.QTableWidgetItem(f"{float(track_point[1]):.1f}")
        )
        self._land_points_table.setItem(
            row,
            3,
            QtWidgets.QTableWidgetItem(
                "" if z_value is None else f"{float(z_value):.1f}"
            ),
        )
        delete_button = QtWidgets.QPushButton("Delete")
        delete_button.clicked.connect(
            lambda _checked=False, r=row: self._delete_land_point_row(r)
        )
        self._land_points_table.setCellWidget(row, 4, delete_button)
        self._sync_land_points_overlay()
        self._persist_selected_land_object()

    def _delete_land_point_row(self, row: int) -> None:
        if row < 0 or row >= self._land_points_table.rowCount():
            return
        self._land_points_table.removeRow(row)
        self._renumber_land_points_rows()
        self._sync_land_points_overlay()
        self._persist_selected_land_object()

    def _renumber_land_points_rows(self) -> None:
        for row in range(self._land_points_table.rowCount()):
            self._land_points_table.setItem(
                row, 0, QtWidgets.QTableWidgetItem(str(row))
            )
            widget = self._land_points_table.cellWidget(row, 4)
            if isinstance(widget, QtWidgets.QPushButton):
                try:
                    widget.clicked.disconnect()
                except TypeError:
                    pass
                widget.clicked.connect(
                    lambda _checked=False, r=row: self._delete_land_point_row(r)
                )

    def _sync_land_points_overlay(self) -> None:
        selected_points: list[tuple[float, float]] = []
        for row in range(self._land_points_table.rowCount()):
            x_item = self._land_points_table.item(row, 1)
            y_item = self._land_points_table.item(row, 2)
            if x_item is None or y_item is None:
                continue
            try:
                selected_points.append((float(x_item.text()), float(y_item.text())))
            except ValueError:
                continue
        self._preview.set_land_object_vertex_points_overlay(
            tuple(selected_points) if self._draw_land_objects_tab_active() else ()
        )
        self._sync_all_land_objects_overlay()
        self._sync_land_polygons_overlay()

    def _sync_land_vertex_points_overlay(self) -> None:
        if not self._draw_land_objects_tab_active():
            self._preview.set_land_object_vertex_points_overlay(())
            return
        selected_points: list[tuple[float, float]] = []
        for row in range(self._land_points_table.rowCount()):
            x_item = self._land_points_table.item(row, 1)
            y_item = self._land_points_table.item(row, 2)
            if x_item is None or y_item is None:
                continue
            try:
                selected_points.append((float(x_item.text()), float(y_item.text())))
            except ValueError:
                continue
        self._preview.set_land_object_vertex_points_overlay(tuple(selected_points))

    def _parse_land_object_overlay(self, payload: dict[str, object]) -> tuple[
        list[tuple[float, float]],
        list[tuple[tuple[int, ...], int, bool]],
        list[str],
    ]:
        points: list[tuple[float, float]] = []
        polygons: list[tuple[tuple[int, ...], int, bool]] = []
        errors: list[str] = []
        raw_points = payload.get("points", [])
        if not isinstance(raw_points, list):
            return points, polygons, ["invalid point list"]
        for point_row in raw_points:
            if not (isinstance(point_row, (list, tuple)) and len(point_row) >= 2):
                errors.append("invalid point row")
                continue
            try:
                points.append((float(str(point_row[0])), float(str(point_row[1]))))
            except ValueError:
                errors.append("invalid point coordinates")
        raw_polygons = payload.get("polygons", [])
        if not isinstance(raw_polygons, list):
            return points, polygons, errors + ["invalid polygon list"]
        for polygon_row in raw_polygons:
            if not (isinstance(polygon_row, (list, tuple)) and len(polygon_row) >= 2):
                errors.append("invalid polygon row")
                continue
            try:
                indices = tuple(
                    int(token.strip())
                    for token in str(polygon_row[0]).split(",")
                    if token.strip()
                )
            except ValueError:
                errors.append("invalid polygon point list")
                continue
            mode_text = str(polygon_row[2]).strip() if len(polygon_row) > 2 else "Land"
            is_wall = mode_text.lower() == "wall"
            min_points = 2 if is_wall else 3
            if len(indices) < min_points:
                errors.append("polygon has too few points")
                continue
            if any(index < 0 or index >= len(points) for index in indices):
                errors.append("polygon references a missing point")
                continue
            try:
                color_index = int(str(polygon_row[1]).strip() or "0")
            except ValueError:
                errors.append("invalid polygon color")
                continue
            polygons.append((indices, color_index, is_wall))
        return points, polygons, errors

    def _sync_all_land_objects_overlay(self) -> None:
        all_points: list[tuple[float, float]] = []
        all_polygons: list[tuple[tuple[int, ...], int, bool]] = []
        for payload in self._land_saved_objects:
            if not isinstance(payload, dict):
                continue
            points, polygons, _errors = self._parse_land_object_overlay(payload)
            point_offset = len(all_points)
            all_points.extend(points)
            all_polygons.extend(
                (
                    tuple(point_offset + index for index in indices),
                    color_index,
                    is_wall,
                )
                for indices, color_index, is_wall in polygons
            )
        self._preview.set_land_object_points_overlay(tuple(all_points))
        self._preview.set_land_object_polygons_overlay(tuple(all_polygons))

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if (
            watched is self._tsd_lines_table.viewport()
            and event.type() == QtCore.QEvent.MouseButtonRelease
            and isinstance(event, QtGui.QMouseEvent)
        ):
            index = self._tsd_lines_table.indexAt(event.pos())
            if index.isValid() and index.column() == 1:
                self._choose_tsd_line_color(index.row())
                return True
        return super().eventFilter(watched, event)

    def _choose_tsd_line_color(self, row: int) -> None:
        if row < 0:
            return
        if not self._sunny_palette_colors:
            QtWidgets.QMessageBox.information(
                self,
                "Choose TSD Line Color",
                "Load SUNNY.PCX first from File → Import → Import SUNNY.PCX…",
            )
            return
        model = self._tsd_lines_table.model()
        index = model.index(row, 1)
        try:
            current_index = int(model.data(index, QtCore.Qt.EditRole) or 0)
        except (TypeError, ValueError):
            current_index = 0
        dialog = PaletteColorDialog(
            self._sunny_palette_colors,
            self,
            selection_mode=True,
            initial_index=current_index,
        )
        if (
            dialog.exec_() != QtWidgets.QDialog.Accepted
            or dialog.selected_index is None
        ):
            return
        model.setData(index, int(dialog.selected_index), QtCore.Qt.EditRole)

    def set_sunny_palette_colors(self, palette: list[QtGui.QColor] | None) -> None:
        """Update SUNNY.PCX colors used for land polygon color cells."""
        self._sunny_palette_colors = list(palette) if palette is not None else None
        self._refresh_land_polygon_color_cells()
        model = self._tsd_lines_table.model()
        if hasattr(model, "set_palette_colors"):
            model.set_palette_colors(self._sunny_palette_colors)

    @staticmethod
    def _parse_land_polygon_color_index(text: str) -> int | None:
        try:
            index = int(text.strip())
        except ValueError:
            return None
        return index if 0 <= index <= 255 else None

    def _land_polygon_color_item(self, value: str | int) -> QtWidgets.QTableWidgetItem:
        item = QtWidgets.QTableWidgetItem(str(value))
        item.setTextAlignment(QtCore.Qt.AlignCenter)
        item.setToolTip("Double-click to choose from the SUNNY.PCX palette.")
        return item

    def _refresh_land_polygon_color_cells(self) -> None:
        if self._updating_land_polygon_color_cells:
            return
        self._updating_land_polygon_color_cells = True
        signals_blocked = self._land_polygons_table.blockSignals(True)
        try:
            for row in range(self._land_polygons_table.rowCount()):
                self._update_land_polygon_color_cell(row)
        finally:
            self._land_polygons_table.blockSignals(signals_blocked)
            self._updating_land_polygon_color_cells = False

    def _update_land_polygon_color_cell(self, row: int) -> None:
        item = self._land_polygons_table.item(row, 1)
        if item is None:
            item = self._land_polygon_color_item("0")
            self._land_polygons_table.setItem(row, 1, item)
        index = self._parse_land_polygon_color_index(item.text())
        item.setTextAlignment(QtCore.Qt.AlignCenter)
        item.setToolTip("Double-click to choose from the SUNNY.PCX palette.")
        if index is None:
            item.setBackground(QtGui.QBrush())
            item.setForeground(QtGui.QBrush())
            item.setToolTip(
                "Invalid color index. Enter 0-255 or double-click to choose from the palette."
            )
            return
        if self._sunny_palette_colors and index < len(self._sunny_palette_colors):
            color = QtGui.QColor(self._sunny_palette_colors[index])
            item.setBackground(QtGui.QBrush(color))
            luminance = (
                (0.299 * color.red()) + (0.587 * color.green()) + (0.114 * color.blue())
            )
            text_color = (
                QtGui.QColor("black") if luminance >= 140 else QtGui.QColor("white")
            )
            item.setForeground(QtGui.QBrush(text_color))
            item.setToolTip(
                f"SUNNY.PCX palette index {index}: "
                f"rgb({color.red()}, {color.green()}, {color.blue()}). "
                "Double-click to choose another color."
            )
        else:
            item.setBackground(QtGui.QBrush())
            item.setForeground(QtGui.QBrush())
            item.setToolTip(
                f"SUNNY.PCX palette index {index}. Load SUNNY.PCX, then double-click "
                "to choose from the palette."
            )

    def _on_land_polygons_table_item_double_clicked(
        self, item: QtWidgets.QTableWidgetItem
    ) -> None:
        if item.column() == 1:
            self._choose_land_polygon_color(item.row())

    def _choose_land_polygon_color(self, row: int) -> None:
        if row < 0 or row >= self._land_polygons_table.rowCount():
            return
        if not self._sunny_palette_colors:
            QtWidgets.QMessageBox.information(
                self,
                "Choose Polygon Color",
                "Load SUNNY.PCX first from File → Import → Import SUNNY.PCX…",
            )
            return
        item = self._land_polygons_table.item(row, 1)
        current_index = (
            self._parse_land_polygon_color_index(item.text()) if item is not None else 0
        )
        dialog = PaletteColorDialog(
            self._sunny_palette_colors,
            self,
            selection_mode=True,
            initial_index=current_index,
        )
        if (
            dialog.exec_() != QtWidgets.QDialog.Accepted
            or dialog.selected_index is None
        ):
            return
        if item is None:
            item = self._land_polygon_color_item(dialog.selected_index)
            self._land_polygons_table.setItem(row, 1, item)
        else:
            item.setText(str(dialog.selected_index))
        self._update_land_polygon_color_cell(row)
        self._sync_land_polygons_overlay()
        self._persist_selected_land_object()

    def _sync_land_polygons_overlay(self) -> None:
        polygons: list[tuple[tuple[int, ...], int, bool]] = []
        errors: list[str] = []
        point_count = self._land_points_table.rowCount()
        for row in range(self._land_polygons_table.rowCount()):
            points_item = self._land_polygons_table.item(row, 0)
            if points_item is None:
                continue
            raw_text = points_item.text().strip()
            if not raw_text:
                continue
            try:
                indices = tuple(
                    int(token.strip()) for token in raw_text.split(",") if token.strip()
                )
            except ValueError:
                errors.append(f"row {row + 1}: invalid point list")
                continue
            mode_text = self._land_polygon_mode_text(row)
            min_points = 2 if mode_text == "Wall" else 3
            if len(indices) < min_points:
                errors.append(
                    f"row {row + 1}: {mode_text.lower()} polygon needs at least {min_points} points"
                )
                continue
            invalid_index = next(
                (index for index in indices if index < 0 or index >= point_count), None
            )
            if invalid_index is not None:
                errors.append(f"row {row + 1}: point {invalid_index} does not exist")
                continue
            color_item = self._land_polygons_table.item(row, 1)
            try:
                color_index = (
                    int(color_item.text().strip()) if color_item is not None else 0
                )
            except ValueError:
                errors.append(f"row {row + 1}: invalid color index")
                continue
            is_wall = mode_text.lower() == "wall"
            polygons.append((indices, color_index, is_wall))
        selected_row = self._land_objects_table.currentRow()
        if 0 <= selected_row < len(self._land_saved_objects):
            self._sync_all_land_objects_overlay()
        else:
            self._preview.set_land_object_polygons_overlay(tuple(polygons))
        if errors:
            self.show_status_message(
                "Land polygon preview skipped invalid rows: " + "; ".join(errors[:3])
            )

    def _on_land_points_table_item_changed(
        self, _item: QtWidgets.QTableWidgetItem
    ) -> None:
        self._sync_land_points_overlay()
        self._persist_selected_land_object()

    def _on_land_polygons_table_item_changed(
        self, item: QtWidgets.QTableWidgetItem
    ) -> None:
        if item.column() == 1 and not self._updating_land_polygon_color_cells:
            self._updating_land_polygon_color_cells = True
            signals_blocked = self._land_polygons_table.blockSignals(True)
            try:
                self._update_land_polygon_color_cell(item.row())
            finally:
                self._land_polygons_table.blockSignals(signals_blocked)
                self._updating_land_polygon_color_cells = False
        self._sync_land_polygons_overlay()
        self._persist_selected_land_object()

    def _on_land_objects_table_item_changed(
        self, item: QtWidgets.QTableWidgetItem
    ) -> None:
        if item.column() != 0:
            return
        row = item.row()
        if row < 0 or row >= len(self._land_saved_objects):
            return
        name = item.text().strip()
        self._land_saved_objects[row]["name"] = name
        if row == self._land_objects_table.currentRow():
            self._land_object_name_edit.blockSignals(True)
            self._land_object_name_edit.setText(name)
            self._land_object_name_edit.blockSignals(False)
        self._mark_land_objects_dirty()

    def _add_land_polygon_row(self) -> None:
        row = self._land_polygons_table.rowCount()
        self._land_polygons_table.insertRow(row)
        self._land_polygons_table.setItem(row, 0, QtWidgets.QTableWidgetItem(""))
        self._land_polygons_table.setItem(row, 1, self._land_polygon_color_item("0"))
        self._land_set_polygon_mode_widget(row, "Land")
        self._land_polygons_table.setItem(row, 3, QtWidgets.QTableWidgetItem("0"))
        self._land_polygons_table.setCurrentCell(row, 0)
        self._land_polygons_table.editItem(self._land_polygons_table.item(row, 0))
        self._persist_selected_land_object()

    def _delete_selected_land_polygon_row(self) -> None:
        row = self._land_polygons_table.currentRow()
        if row < 0 or row >= self._land_polygons_table.rowCount():
            return
        self._land_polygons_table.removeRow(row)
        self._sync_land_polygons_overlay()
        self._persist_selected_land_object()

    def _move_selected_land_polygon_row(self, offset: int) -> None:
        row = self._land_polygons_table.currentRow()
        target_row = row + offset
        if (
            row < 0
            or target_row < 0
            or target_row >= self._land_polygons_table.rowCount()
        ):
            return
        current_values = [self._land_polygon_cell_text(row, col) for col in range(4)]
        target_values = [
            self._land_polygon_cell_text(target_row, col) for col in range(4)
        ]
        self._land_polygons_table.blockSignals(True)
        for col in range(4):
            if col == 2:
                self._land_set_polygon_mode_widget(row, target_values[col])
                self._land_set_polygon_mode_widget(target_row, current_values[col])
            else:
                row_item = (
                    self._land_polygon_color_item(target_values[col])
                    if col == 1
                    else QtWidgets.QTableWidgetItem(target_values[col])
                )
                target_item = (
                    self._land_polygon_color_item(current_values[col])
                    if col == 1
                    else QtWidgets.QTableWidgetItem(current_values[col])
                )
                self._land_polygons_table.setItem(row, col, row_item)
                self._land_polygons_table.setItem(target_row, col, target_item)
        self._land_polygons_table.blockSignals(False)
        self._refresh_land_polygon_color_cells()
        self._land_polygons_table.selectRow(target_row)
        self._sync_land_polygons_overlay()
        self._persist_selected_land_object()

    def _collect_current_land_object_payload(self) -> dict[str, object]:
        name = self._land_object_name_edit.text().strip()
        points: list[tuple[str, str, str]] = []
        for row in range(self._land_points_table.rowCount()):
            x_item = self._land_points_table.item(row, 1)
            y_item = self._land_points_table.item(row, 2)
            z_item = self._land_points_table.item(row, 3)
            points.append(
                (
                    "" if x_item is None else x_item.text(),
                    "" if y_item is None else y_item.text(),
                    "" if z_item is None else z_item.text(),
                )
            )
        polygons: list[tuple[str, str, str, str]] = []
        for row in range(self._land_polygons_table.rowCount()):
            points_item = self._land_polygons_table.item(row, 0)
            color_item = self._land_polygons_table.item(row, 1)
            height_item = self._land_polygons_table.item(row, 3)
            polygons.append(
                (
                    "" if points_item is None else points_item.text(),
                    "0" if color_item is None else color_item.text(),
                    self._land_polygon_mode_text(row),
                    "0" if height_item is None else height_item.text(),
                )
            )
        return {"name": name, "points": points, "polygons": polygons}

    def _persist_selected_land_object(self) -> None:
        row = self._land_objects_table.currentRow()
        if row < 0 or row >= len(self._land_saved_objects):
            return
        payload = self._collect_current_land_object_payload()
        self._land_saved_objects[row] = payload
        self._land_objects_table.setItem(
            row, 0, QtWidgets.QTableWidgetItem(str(payload["name"]))
        )
        points = payload["points"] if isinstance(payload.get("points"), list) else []
        polygons = (
            payload["polygons"] if isinstance(payload.get("polygons"), list) else []
        )
        self._land_objects_table.setItem(
            row,
            1,
            QtWidgets.QTableWidgetItem(
                f"{len(points)} points, {len(polygons)} polygons"
            ),
        )
        self._mark_land_objects_dirty()
        self._sync_all_land_objects_overlay()

    def _save_current_land_object(self) -> None:
        name = self._land_object_name_edit.text().strip()
        if not name:
            self.show_status_message("Enter a land object name before saving.")
            return
        payload = self._collect_current_land_object_payload()
        current_row = self._land_objects_table.currentRow()
        if 0 <= current_row < len(self._land_saved_objects):
            self._land_saved_objects[current_row] = payload
            row = current_row
        else:
            self._land_saved_objects.append(payload)
            row = self._land_objects_table.rowCount()
            self._land_objects_table.insertRow(row)
        self._land_objects_table.setItem(row, 0, QtWidgets.QTableWidgetItem(name))
        self._land_objects_table.setItem(
            row,
            1,
            QtWidgets.QTableWidgetItem(
                f"{len(payload['points'])} points, {len(payload['polygons'])} polygons"
            ),
        )
        self._land_objects_table.selectRow(row)
        self._mark_land_objects_dirty()
        self.show_status_message(f"Saved land object '{name}'.")

    def _add_land_object(self) -> None:
        base_name = "Object"
        existing_names = {
            str(entry.get("name", "")).strip()
            for entry in self._land_saved_objects
            if isinstance(entry, dict)
        }
        index = 1
        while f"{base_name} {index}" in existing_names:
            index += 1
        name = f"{base_name} {index}"
        payload = {"name": name, "points": [], "polygons": []}
        self._land_saved_objects.append(payload)
        row = self._land_objects_table.rowCount()
        self._land_objects_table.insertRow(row)
        self._land_objects_table.setItem(row, 0, QtWidgets.QTableWidgetItem(name))
        self._land_objects_table.setItem(
            row, 1, QtWidgets.QTableWidgetItem("0 points, 0 polygons")
        )
        self._land_objects_table.selectRow(row)
        self._load_selected_land_object()
        self._mark_land_objects_dirty()
        self.show_status_message(f"Added land object '{name}'.")

    def _load_selected_land_object(self) -> None:
        row = self._land_objects_table.currentRow()
        if row < 0 or row >= len(self._land_saved_objects):
            self._land_object_name_edit.clear()
            self._land_points_table.setRowCount(0)
            self._land_polygons_table.setRowCount(0)
            self._update_land_object_edit_controls()
            self._sync_land_points_overlay()
            return
        entry = self._land_saved_objects[row]
        points = entry.get("points", [])
        polygons = entry.get("polygons", [])
        self._land_points_table.blockSignals(True)
        self._land_polygons_table.blockSignals(True)
        self._land_points_table.setRowCount(0)
        for point_row, (x_text, y_text, z_text) in enumerate(points):
            self._land_points_table.insertRow(point_row)
            self._land_points_table.setItem(
                point_row, 0, QtWidgets.QTableWidgetItem(str(point_row))
            )
            self._land_points_table.setItem(
                point_row, 1, QtWidgets.QTableWidgetItem(str(x_text))
            )
            self._land_points_table.setItem(
                point_row, 2, QtWidgets.QTableWidgetItem(str(y_text))
            )
            self._land_points_table.setItem(
                point_row, 3, QtWidgets.QTableWidgetItem(str(z_text))
            )
            delete_button = QtWidgets.QPushButton("Delete")
            delete_button.clicked.connect(
                lambda _checked=False, r=point_row: self._delete_land_point_row(r)
            )
            self._land_points_table.setCellWidget(point_row, 4, delete_button)
        self._land_polygons_table.setRowCount(0)
        for polygon_row, polygon_data in enumerate(polygons):
            point_list_text = polygon_data[0] if len(polygon_data) > 0 else ""
            color_text = polygon_data[1] if len(polygon_data) > 1 else "0"
            mode_text = polygon_data[2] if len(polygon_data) > 2 else "Land"
            height_text = polygon_data[3] if len(polygon_data) > 3 else "0"
            self._land_polygons_table.insertRow(polygon_row)
            self._land_polygons_table.setItem(
                polygon_row, 0, QtWidgets.QTableWidgetItem(str(point_list_text))
            )
            self._land_polygons_table.setItem(
                polygon_row, 1, self._land_polygon_color_item(str(color_text))
            )
            self._land_set_polygon_mode_widget(polygon_row, str(mode_text))
            self._land_polygons_table.setItem(
                polygon_row, 3, QtWidgets.QTableWidgetItem(str(height_text))
            )
        self._land_points_table.blockSignals(False)
        self._land_polygons_table.blockSignals(False)
        self._refresh_land_polygon_color_cells()
        self._land_object_name_edit.blockSignals(True)
        self._land_object_name_edit.setText(str(entry.get("name", "")))
        self._land_object_name_edit.blockSignals(False)
        self._update_land_object_edit_controls()
        self._sync_land_points_overlay()

    def _land_polygon_cell_text(self, row: int, col: int) -> str:
        if col == 2:
            return self._land_polygon_mode_text(row)
        item = self._land_polygons_table.item(row, col)
        if item is None:
            return "0" if col in (1, 3) else ("Land" if col == 2 else "")
        return item.text()

    def _land_polygon_mode_text(self, row: int) -> str:
        mode_widget = self._land_polygons_table.cellWidget(row, 2)
        if isinstance(mode_widget, QtWidgets.QComboBox):
            selected = mode_widget.currentText().strip()
            return selected if selected in {"Land", "Wall"} else "Land"
        item = self._land_polygons_table.item(row, 2)
        if item is None:
            return "Land"
        mode = item.text().strip()
        return mode if mode in {"Land", "Wall"} else "Land"

    def _land_set_polygon_mode_widget(self, row: int, mode_text: str) -> None:
        combo = QtWidgets.QComboBox()
        combo.addItems(["Land", "Wall"])
        combo.setCurrentText("Wall" if mode_text.strip().lower() == "wall" else "Land")
        combo.currentTextChanged.connect(self._on_land_polygon_mode_changed)
        self._land_polygons_table.setCellWidget(row, 2, combo)
        self._land_polygons_table.setItem(
            row, 2, QtWidgets.QTableWidgetItem(combo.currentText())
        )

    def _on_land_polygon_mode_changed(self, mode_text: str) -> None:
        combo = self.sender()
        if not isinstance(combo, QtWidgets.QComboBox):
            return
        for row in range(self._land_polygons_table.rowCount()):
            if self._land_polygons_table.cellWidget(row, 2) is combo:
                self._land_polygons_table.setItem(
                    row, 2, QtWidgets.QTableWidgetItem(mode_text)
                )
                break
        self._sync_land_polygons_overlay()
        self._persist_selected_land_object()

    def _update_land_object_edit_controls(self) -> None:
        has_selection = (
            0 <= self._land_objects_table.currentRow() < len(self._land_saved_objects)
        )
        for button in (
            self._land_add_point_button,
            self._land_edit_point_button,
            self._land_add_polygon_button,
            self._land_delete_polygon_button,
            self._land_move_polygon_up_button,
            self._land_move_polygon_down_button,
            self._land_export_object_button,
        ):
            button.setEnabled(has_selection)
        if not has_selection:
            self._land_add_point_button.blockSignals(True)
            self._land_edit_point_button.blockSignals(True)
            self._land_add_point_button.setChecked(False)
            self._land_edit_point_button.setChecked(False)
            self._land_add_point_button.blockSignals(False)
            self._land_edit_point_button.blockSignals(False)

    def serialize_land_objects(self) -> list[dict[str, object]]:
        return [
            dict(entry) for entry in self._land_saved_objects if isinstance(entry, dict)
        ]

    def load_land_objects(self, objects: list[dict[str, object]]) -> None:
        self._land_saved_objects = [
            dict(entry) for entry in objects if isinstance(entry, dict)
        ]
        self._land_objects_table.setRowCount(0)
        for row, entry in enumerate(self._land_saved_objects):
            points = entry.get("points", [])
            polygons = entry.get("polygons", [])
            self._land_objects_table.insertRow(row)
            self._land_objects_table.setItem(
                row, 0, QtWidgets.QTableWidgetItem(str(entry.get("name", "")))
            )
            self._land_objects_table.setItem(
                row,
                1,
                QtWidgets.QTableWidgetItem(
                    f"{len(points)} points, {len(polygons)} polygons"
                ),
            )
        if self._land_saved_objects:
            self._land_objects_table.selectRow(0)
            self._load_selected_land_object()
        else:
            self._land_object_name_edit.clear()
            self._land_points_table.setRowCount(0)
            self._land_polygons_table.setRowCount(0)
            self._sync_land_points_overlay()
            self._update_land_object_edit_controls()

    def _mark_land_objects_dirty(self) -> None:
        if self.controller is not None and hasattr(
            self.controller, "set_land_objects_dirty"
        ):
            self.controller.set_land_objects_dirty(True)

    def _export_selected_land_object_to_3d(self) -> None:
        row = self._land_objects_table.currentRow()
        if row < 0 or row >= len(self._land_saved_objects):
            self.show_status_message("Select a land object to export.")
            return
        payload = self._land_saved_objects[row]
        name = str(payload.get("name", "")).strip() or f"object_{row + 1}"
        points, polygons, error = self._parse_land_object_export_data(payload)
        if error is not None:
            QtWidgets.QMessageBox.warning(self, "Export Object to .3D", error)
            return
        default_path = f"{name.replace(' ', '_')}.3D"
        file_path, _selected_filter = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Export Object to .3D",
            default_path,
            "3D files (*.3D *.3d);;All Files (*)",
        )
        if not file_path:
            return
        export_text = self._build_land_object_3d_text(
            name=name, points=points, polygons=polygons
        )
        try:
            Path(file_path).write_text(export_text, encoding="utf-8")
        except OSError as exc:
            QtWidgets.QMessageBox.warning(
                self, "Export Object to .3D", f"Could not save file:\n{exc}"
            )
            return
        self.show_status_message(f"Exported '{name}' to {file_path}")

    def _parse_land_object_export_data(
        self, payload: dict[str, object]
    ) -> tuple[
        list[tuple[float, float, float]], list[tuple[tuple[int, ...], int]], str | None
    ]:
        raw_points = payload.get("points", [])
        raw_polygons = payload.get("polygons", [])
        if not isinstance(raw_points, list) or not raw_points:
            return [], [], "The selected object has no points."
        if not isinstance(raw_polygons, list) or not raw_polygons:
            return [], [], "The selected object has no polygons."
        points: list[tuple[float, float, float]] = []
        for point_index, point_row in enumerate(raw_points, start=1):
            if not (isinstance(point_row, (list, tuple)) and len(point_row) >= 3):
                return [], [], f"Point row {point_index} is invalid."
            x_text, y_text, z_text = point_row[0], point_row[1], point_row[2]
            try:
                x = float(str(x_text).strip())
                y = float(str(y_text).strip())
                z = float(str(z_text).strip() or "0")
            except ValueError:
                return (
                    [],
                    [],
                    f"Point row {point_index} must contain numeric X, Y, and Z values.",
                )
            points.append((x, y, z))

        polygons: list[tuple[tuple[int, ...], int]] = []
        for polygon_index, polygon_row in enumerate(raw_polygons, start=1):
            if not (isinstance(polygon_row, (list, tuple)) and len(polygon_row) >= 2):
                return [], [], f"Polygon row {polygon_index} is invalid."
            point_list_text, color_text = polygon_row[0], polygon_row[1]
            try:
                indices = tuple(
                    int(chunk.strip())
                    for chunk in str(point_list_text).split(",")
                    if chunk.strip() != ""
                )
            except ValueError:
                return [], [], f"Polygon row {polygon_index} has invalid point indices."
            mode_text = str(polygon_row[2]).strip() if len(polygon_row) > 2 else "Land"
            mode = mode_text.lower()
            if mode not in ("land", "wall"):
                return (
                    [],
                    [],
                    f"Polygon row {polygon_index} has invalid mode '{mode_text}'.",
                )
            min_points = 2 if mode == "wall" else 3
            if len(indices) < min_points:
                return (
                    [],
                    [],
                    f"Polygon row {polygon_index} needs at least {min_points} points.",
                )
            if any(index < 0 or index >= len(points) for index in indices):
                return (
                    [],
                    [],
                    f"Polygon row {polygon_index} references a point outside the valid range.",
                )
            try:
                color = int(str(color_text).strip() or "0")
            except ValueError:
                return (
                    [],
                    [],
                    f"Polygon row {polygon_index} has an invalid color index.",
                )
            height_text = str(polygon_row[3]).strip() if len(polygon_row) > 3 else "0"
            try:
                height = float(height_text or "0")
            except ValueError:
                return [], [], f"Polygon row {polygon_index} has an invalid height."
            if mode == "land":
                if height == 0.0:
                    polygons.append((indices, color))
                    continue
                elevated_index_by_base: dict[int, int] = {}
                for base_index in indices:
                    if base_index not in elevated_index_by_base:
                        x, y, z = points[base_index]
                        points.append((x, y, z + height))
                        elevated_index_by_base[base_index] = len(points) - 1
                polygons.append(
                    (tuple(elevated_index_by_base[index] for index in indices), color)
                )
                continue
            if height <= 0.0:
                return (
                    [],
                    [],
                    f"Polygon row {polygon_index} wall height must be greater than 0.",
                )
            elevated_index_by_base: dict[int, int] = {}
            for base_index in indices:
                if base_index not in elevated_index_by_base:
                    x, y, z = points[base_index]
                    points.append((x, y, z + height))
                    elevated_index_by_base[base_index] = len(points) - 1
            for start, end in zip(indices, indices[1:]):
                polygons.append(
                    (
                        (
                            start,
                            end,
                            elevated_index_by_base[end],
                            elevated_index_by_base[start],
                        ),
                        color,
                    )
                )
        return points, polygons, None

    @staticmethod
    def _build_land_object_3d_text(
        *,
        name: str,
        points: list[tuple[float, float, float]],
        polygons: list[tuple[tuple[int, ...], int]],
    ) -> str:
        lines: list[str] = [
            "3D VERSION 3.0;",
            "% Generated by SG CREATE (land object export)",
            f"% Object name: {name}",
            "",
            "nil: NIL;",
        ]
        for point_index, (x, y, z) in enumerate(points):
            rounded_x = int(round(x))
            rounded_y = int(round(y))
            rounded_z = int(round(z))
            lines.append(f"p{point_index}: [<{rounded_x}, {rounded_y}, {rounded_z}>];")
        lines.append("")
        for poly_index, (indices, color) in enumerate(polygons):
            refs = ", ".join(f"p{point_index}" for point_index in indices)
            lines.append(f"poly{poly_index}: POLY <{color}> {{{refs}}};")
        lines.append("")
        prev_node = "nil"
        for poly_index, (indices, _color) in enumerate(polygons):
            v1, v2, v3 = (f"p{indices[0]}", f"p{indices[1]}", f"p{indices[2]}")
            node_name = f"o{poly_index}"
            lines.append(
                f"{node_name}: BSPF ({v1}, {v2}, {v3}), nil, poly{poly_index}, {prev_node};"
            )
            prev_node = node_name
        last_poly_index = len(polygons) - 1
        last_indices = polygons[last_poly_index][0]
        rv1, rv2, rv3 = (
            f"p{last_indices[0]}",
            f"p{last_indices[1]}",
            f"p{last_indices[2]}",
        )
        lines.append(
            f"root: BSPF ({rv1}, {rv2}, {rv3}), nil, poly{last_poly_index}, {prev_node};"
        )
        return "\n".join(lines)

    def _nearest_boundary_sample(
        self, track_point: tuple[float, float]
    ) -> tuple[int, float, float | None] | None:
        centerline_index = self._preview.section_manager.centerline_index
        sampled_dlongs = self._preview.section_manager.sampled_dlongs
        sections = self._preview.section_manager.sections
        track_length = float(
            sum(max(0.0, float(section.length)) for section in sections)
        )
        if centerline_index is None or not sampled_dlongs or track_length <= 0.0:
            return None
        projected_point, projected_dlong, _distance_sq = project_point_to_centerline(
            track_point, centerline_index, sampled_dlongs, track_length
        )
        if projected_point is None or projected_dlong is None:
            return None
        mapped = dlong_to_section_position(sections, projected_dlong, track_length)
        if mapped is None:
            return None
        section_index = int(mapped.section_index)
        progress = max(0.0, min(1.0, float(mapped.fraction)))
        fsects = self._preview.get_section_fsects(section_index)
        boundary_number_by_row = boundary_numbers_for_fsects(fsects)
        nearest: tuple[int, float, float | None] | None = None
        for row_index, boundary_number in sorted(
            boundary_number_by_row.items(), key=lambda item: int(item[1])
        ):
            fsect = fsects[row_index]
            dlat = (
                float(fsect.start_dlat)
                + (float(fsect.end_dlat) - float(fsect.start_dlat)) * progress
            )
            elevation = self._sample_elevation_at_dlat(section_index, progress, dlat)
            dist = abs(dlat)
            if nearest is None or dist < nearest[1]:
                nearest = (int(boundary_number), dist, elevation)
        return nearest

    def _on_preview_pointer_clicked(self, point: QtCore.QPointF) -> None:
        track_point = self._track_point_from_preview_position(point)
        if track_point is None:
            return
        if self._draw_land_objects_tab_active() and not self._ruler_mode_active:
            if self._land_add_point_button.isChecked():
                self._append_land_point_from_track(track_point)
                return
            if self._land_edit_point_button.isChecked():
                selected_row = self._land_points_table.currentRow()
                if selected_row < 0:
                    self.show_status_message(
                        "Select a point row first, then click to move it."
                    )
                    return
                self._move_land_point_row(selected_row, track_point)
                return
            self._start_land_point_drag(point)
            return
        if not self._ruler_mode_active or self._ruler_frozen:
            return
        if self._ruler_start_point is None:
            self._ruler_start_point = track_point
            self._update_ruler_overlay(track_point, track_point)
            self.show_status_message(
                "Ruler start point set. Move mouse and click again to finish."
            )
            return
        self._update_ruler_overlay(self._ruler_start_point, track_point)
        self._ruler_mode_active = False
        self._ruler_frozen = True
        self._preview.set_track_interaction_enabled(True)
        self._update_ruler_button_state()
        self.show_status_message("Ruler frozen. Click Clear Ruler to remove it.")

    def _on_preview_pointer_drag_moved(self, point: QtCore.QPointF) -> None:
        if (
            self._dragging_land_point_row is None
            or not self._draw_land_objects_tab_active()
        ):
            return
        track_point = self._track_point_from_preview_position(point)
        if track_point is None:
            return
        self._move_land_point_row(self._dragging_land_point_row, track_point)

    def _on_preview_pointer_released(self, _point: QtCore.QPointF) -> None:
        self._dragging_land_point_row = None

    def _start_land_point_drag(self, point: QtCore.QPointF) -> None:
        if (
            self._land_add_point_button.isChecked()
            or self._land_edit_point_button.isChecked()
        ):
            return
        track_point = self._track_point_from_preview_position(point)
        if track_point is None:
            return
        self._dragging_land_point_row = self._nearest_land_point_row(track_point)

    def _nearest_land_point_row(
        self, track_point: tuple[float, float], max_distance: float = 800.0
    ) -> int | None:
        nearest_row: int | None = None
        nearest_distance_sq = max_distance * max_distance
        for row in range(self._land_points_table.rowCount()):
            x_item = self._land_points_table.item(row, 1)
            y_item = self._land_points_table.item(row, 2)
            if x_item is None or y_item is None:
                continue
            try:
                px = float(x_item.text())
                py = float(y_item.text())
            except ValueError:
                continue
            distance_sq = (px - track_point[0]) ** 2 + (py - track_point[1]) ** 2
            if distance_sq <= nearest_distance_sq:
                nearest_distance_sq = distance_sq
                nearest_row = row
        return nearest_row

    def _move_land_point_row(self, row: int, track_point: tuple[float, float]) -> None:
        if row < 0 or row >= self._land_points_table.rowCount():
            return
        self._land_points_table.blockSignals(True)
        self._land_points_table.setItem(
            row, 1, QtWidgets.QTableWidgetItem(f"{float(track_point[0]):.1f}")
        )
        self._land_points_table.setItem(
            row, 2, QtWidgets.QTableWidgetItem(f"{float(track_point[1]):.1f}")
        )
        self._land_points_table.blockSignals(False)
        self._sync_land_points_overlay()

    def _on_land_point_mode_toggled(self, mode: str, checked: bool) -> None:
        if not checked:
            return
        if mode == "add" and self._land_edit_point_button.isChecked():
            self._land_edit_point_button.blockSignals(True)
            self._land_edit_point_button.setChecked(False)
            self._land_edit_point_button.blockSignals(False)
        if mode == "edit" and self._land_add_point_button.isChecked():
            self._land_add_point_button.blockSignals(True)
            self._land_add_point_button.setChecked(False)
            self._land_add_point_button.blockSignals(False)

    def _on_ruler_button_clicked(self) -> None:
        if self._ruler_frozen:
            self._clear_ruler()
            self.show_status_message("Ruler cleared.")
            return
        if self._ruler_mode_active:
            self._ruler_mode_active = False
            self._ruler_start_point = None
            self._ruler_end_point = None
            self._preview.set_track_interaction_enabled(True)
            self._preview.set_ruler_overlay(None, None, "")
            self.show_status_message("Ruler mode cancelled.")
        else:
            self._ruler_mode_active = True
            self._ruler_start_point = None
            self._ruler_end_point = None
            self._preview.set_track_interaction_enabled(False)
            self.show_status_message("Ruler mode active. Click to set start point.")
        self._update_ruler_button_state()
        self.update_mouse_usage_text()

    def _on_ruler_notch_interval_changed(self) -> None:
        self._sync_ruler_notch_interval()
        if self._ruler_start_point is not None and self._ruler_end_point is not None:
            self._update_ruler_overlay(self._ruler_start_point, self._ruler_end_point)

    def _sync_ruler_notch_interval(self) -> None:
        value = float(self._ruler_notch_spin.value())
        unit = self.current_measurement_unit()
        self._ruler_notch_interval_500ths = (
            float(units_to_500ths(value, unit)) if value > 0.0 else None
        )

    def _update_ruler_overlay(
        self,
        start_point: tuple[float, float],
        end_point: tuple[float, float],
    ) -> None:
        self._ruler_start_point = start_point
        self._ruler_end_point = end_point
        dx = float(end_point[0]) - float(start_point[0])
        dy = float(end_point[1]) - float(start_point[1])
        length = (dx * dx + dy * dy) ** 0.5
        self._sync_ruler_notch_interval()
        self._preview.set_ruler_overlay(
            start_point,
            end_point,
            self.format_length(length),
            self._ruler_notch_interval_500ths,
        )

    def _clear_ruler(self) -> None:
        self._ruler_mode_active = False
        self._ruler_start_point = None
        self._ruler_end_point = None
        self._ruler_frozen = False
        self._preview.set_track_interaction_enabled(True)
        self._preview.set_ruler_overlay(None, None, "")
        self._update_ruler_button_state()
        self.update_mouse_usage_text()

    def _update_ruler_button_state(self) -> None:
        ruler_visible = self._ruler_mode_active or self._ruler_frozen
        self._ruler_notch_panel.setVisible(ruler_visible)
        self._ruler_notch_spin.setSuffix(
            f" {measurement_unit_label(self.current_measurement_unit())}"
        )
        self._ruler_notch_spin.setDecimals(
            measurement_unit_decimals(self.current_measurement_unit())
        )
        if self._ruler_frozen:
            self._ruler_button.setText("Clear Ruler")
            return
        self._ruler_button.setText("Ruler")

    def _sample_centerline_elevation(
        self, section_index: int, progress: float
    ) -> float | None:
        return self._sample_elevation_at_dlat(section_index, progress, 0.0)

    def _sample_elevation_at_dlat(
        self,
        section_index: int,
        progress: float,
        dlat: float,
    ) -> float | None:
        sgfile = self._preview.sgfile
        if sgfile is None or sgfile.num_xsects <= 0:
            return None
        xsect_entries: list[tuple[float, int]] = []
        for xsect_index, raw_dlat in enumerate(list(sgfile.xsect_dlats)):
            try:
                xsect_entries.append((float(raw_dlat), xsect_index))
            except (TypeError, ValueError):
                continue
        if not xsect_entries:
            return None
        xsect_entries.sort(key=lambda entry: entry[0])
        dlat_value = float(dlat)
        lower_dlat, lower_idx = xsect_entries[0]
        upper_dlat, upper_idx = xsect_entries[-1]
        if dlat_value <= lower_dlat:
            upper_dlat, upper_idx = lower_dlat, lower_idx
        elif dlat_value >= upper_dlat:
            lower_dlat, lower_idx = upper_dlat, upper_idx
        else:
            for entry_index in range(1, len(xsect_entries)):
                candidate_dlat, candidate_idx = xsect_entries[entry_index]
                if candidate_dlat >= dlat_value:
                    lower_dlat, lower_idx = xsect_entries[entry_index - 1]
                    upper_dlat, upper_idx = candidate_dlat, candidate_idx
                    break

        subsect = max(0.0, min(1.0, float(progress)))
        try:
            lower_altitude, _ = sg_xsect_altitude_grade_at(
                sgfile, section_index, subsect, lower_idx
            )
            upper_altitude, _ = sg_xsect_altitude_grade_at(
                sgfile, section_index, subsect, upper_idx
            )
        except Exception:
            return None
        if lower_idx == upper_idx or upper_dlat == lower_dlat:
            return float(lower_altitude)
        dlat_ratio = (dlat_value - lower_dlat) / (upper_dlat - lower_dlat)
        return float(lower_altitude) + (
            float(upper_altitude) - float(lower_altitude)
        ) * float(dlat_ratio)

    def _refresh_query_track_info_label(self) -> None:
        self._zoom_factor_label.setText(self._format_query_track_zoom_text())
        if not self._query_track_mode_active:
            self._query_track_info_label.setText("")
            self._preview.set_query_track_overlay_message("")
            return
        if self._query_track_info_frozen:
            freeze_suffix = "\n[Space: Unfreeze]"
        else:
            freeze_suffix = "\n[Space: Freeze]"
        if self._query_track_result is None:
            self._preview.set_query_track_overlay_message(
                "Inspect Track:\nHover over centerline" + freeze_suffix
            )
            return
        result = self._query_track_result
        query_text = self._format_query_track_text(result)
        self._preview.set_query_track_overlay_message(query_text + freeze_suffix)

    def _format_query_track_text(self, result: dict[str, object]) -> str:
        adjusted_dlong = result.get("adjusted_dlong")
        adjusted_text = (
            "–" if adjusted_dlong is None else self.format_length(float(adjusted_dlong))
        )
        elevation = result.get("centerline_elevation")
        elevation_text = (
            "–"
            if elevation is None
            else self._format_xsect_altitude(int(round(float(elevation))))
        )
        boundary_values = result.get("boundary_dlats", ())
        formatted_boundary_dlats: list[str] = []
        formatted_boundary_elevations: list[str] = []
        for boundary in boundary_values:
            if not isinstance(boundary, tuple) or len(boundary) < 2:
                continue
            name = boundary[0]
            dlat_value = boundary[1]
            if len(boundary) >= 3:
                boundary_elevation = boundary[2]
            else:
                boundary_elevation = None
            formatted_boundary_dlats.append(
                f"{name}: {self._format_fsect_dlat(float(dlat_value))}"
            )
            boundary_elevation_text = (
                "–"
                if boundary_elevation is None
                else self._format_xsect_altitude(int(round(float(boundary_elevation))))
            )
            formatted_boundary_elevations.append(f"{name}: {boundary_elevation_text}")
        boundaries_dlat_text = ", ".join(formatted_boundary_dlats) or "none"
        boundaries_elevation_text = ", ".join(formatted_boundary_elevations) or "none"
        return (
            "Inspect Track:\n"
            f"Section #: {result.get('section_index', '–')}\n"
            f"Adjusted DLONG: {adjusted_text}\n"
            f"Elevation at DLAT=0: {elevation_text}\n"
            f"Boundary DLATs: {boundaries_dlat_text}\n"
            f"Boundary Elevations: {boundaries_elevation_text}"
        )

    def _format_query_track_zoom_text(self) -> str:
        widget_size = self._preview.widget_size()
        transform = self._preview.current_transform(widget_size)
        if transform is None:
            return "Zoom Factor: –"
        pixels_per_500ths = max(float(transform[0]), 0.0)
        if pixels_per_500ths <= 0.0:
            return "Zoom Factor: –"
        units_per_pixel = units_from_500ths(
            1.0 / pixels_per_500ths, self._current_measurement_unit()
        )
        unit_label = self._measurement_unit_label(self._current_measurement_unit())
        return (
            f"Zoom Factor: 1 px = {units_per_pixel:.4f} {unit_label} "
            f"({pixels_per_500ths:.4f} px/500ths)"
        )

    def _on_fsect_cell_changed(self, row_index: int, column_index: int) -> None:
        if self._updating_fsect_table:
            return
        if row_index not in (2, 3):
            return
        section_index = self._selected_section_index
        if section_index is None:
            return
        fsects = self._preview.get_section_fsects(section_index)
        fsect_index = self._fsect_model_index_for_column(column_index)
        if fsect_index < 0 or fsect_index >= len(fsects):
            return
        item = self._fsect_table.item(row_index, column_index)
        if item is None:
            return
        text = item.text().strip()
        try:
            new_value = float(text)
        except ValueError:
            self._fsect_table.blockSignals(True)
            if row_index == 2:
                item.setText(self._format_fsect_dlat(fsects[fsect_index].end_dlat))
            else:
                item.setText(self._format_fsect_dlat(fsects[fsect_index].start_dlat))
            self._fsect_table.blockSignals(False)
            return
        new_value = self._fsect_dlat_from_display_units(new_value)
        if row_index == 2:
            self._preview.update_fsection_dlat(
                section_index,
                fsect_index,
                end_dlat=new_value,
                refresh_preview=False,
                emit_sections_changed=False,
            )
        else:
            self._preview.update_fsection_dlat(
                section_index,
                fsect_index,
                start_dlat=new_value,
                refresh_preview=False,
                emit_sections_changed=False,
            )
        normalize_on_commit = text != self._format_fsect_dlat(new_value)
        self._update_fsect_delta_cells(section_index, fsect_index)
        self._schedule_fsect_table_commit(normalize_on_commit)

    def _schedule_fsect_table_commit(self, normalize_on_commit: bool) -> None:
        self._fsect_table_commit_needs_normalization = (
            self._fsect_table_commit_needs_normalization or normalize_on_commit
        )
        self._fsect_table_commit_timer.start()

    def _on_fsect_table_commit_timer(self) -> None:
        self._preview.refresh_fsections_preview()
        if self.controller is not None and hasattr(
            self.controller, "mark_fsects_dirty"
        ):
            self.controller.mark_fsects_dirty(True)
        if self._fsect_table_commit_needs_normalization:
            self.update_selected_section_fsect_table()
        self._fsect_table_commit_needs_normalization = False

    def _update_fsect_dlat_cell(
        self, section_index: int, row_index: int, endpoint: str, new_dlat: float
    ) -> None:
        if section_index != self._selected_section_index:
            return
        column_index = self._fsect_column_for_model_index(row_index)
        if column_index < 0 or column_index >= self._fsect_table.columnCount():
            return
        table_row = 3 if endpoint == "start" else 2
        item = self._fsect_table.item(table_row, column_index)
        if item is None:
            item = QtWidgets.QTableWidgetItem("")
            item.setFlags(
                item.flags() | QtCore.Qt.ItemIsEditable | QtCore.Qt.ItemIsSelectable
            )
            self._fsect_table.setItem(table_row, column_index, item)
        self._fsect_table.blockSignals(True)
        item.setText(self._format_fsect_dlat(new_dlat))
        self._fsect_table.blockSignals(False)
        self._update_fsect_delta_cells(section_index, row_index)

    def _update_fsect_delta_cells(self, section_index: int, row_index: int) -> None:
        if section_index != self._selected_section_index:
            return
        fsects = self._preview.get_section_fsects(section_index)
        for delta_index in (row_index - 1, row_index):
            delta_column = self._fsect_column_for_model_index(delta_index)
            if delta_column < 0 or delta_column >= self._fsect_table.columnCount():
                continue
            set_fsect_delta_cell_text(
                self._fsect_table,
                4,
                delta_column,
                format_fsect_delta(
                    fsects, delta_index, "start", unit=self._current_measurement_unit()
                ),
            )
            set_fsect_delta_cell_text(
                self._fsect_table,
                1,
                delta_column,
                format_fsect_delta(
                    fsects, delta_index, "end", unit=self._current_measurement_unit()
                ),
            )

    def update_selected_section_fsect_table(self) -> None:
        self._update_fsect_table(self._selected_section_index)
        self._update_boundary_dlat_labels(self._selected_section_index)

    def _on_measurement_units_changed(self) -> None:
        previous_unit = self._measurement_unit_data
        self._measurement_unit_data = str(self._measurement_units_combo.currentData())
        self._sync_altitude_range_spin_units(previous_unit)
        self._sync_pitwall_height_spin_units(previous_unit)
        self.update_xsect_table_headers()
        self._update_fsect_table_headers()
        self._update_fsect_table(self._selected_section_index)
        self._update_boundary_dlat_labels(self._selected_section_index)
        self._refresh_query_track_info_label()
        self._refresh_wall_defaults_summary()
        self._update_ruler_button_state()
        if self._ruler_start_point is not None and self._ruler_end_point is not None:
            self._update_ruler_overlay(self._ruler_start_point, self._ruler_end_point)
        model = self._tsd_lines_table.model()
        if hasattr(model, "set_display_unit"):
            model.set_display_unit(self._current_measurement_unit())

    def _sync_pitwall_height_spin_units(self, previous_unit: str) -> None:
        current_unit = self._current_measurement_unit()
        wall_height_500ths = units_to_500ths(
            self._pitwall_wall_height_spin.value(), previous_unit
        )
        armco_height_500ths = units_to_500ths(
            self._pitwall_armco_height_spin.value(), previous_unit
        )

        decimals = self._measurement_unit_decimals(current_unit)
        step = self._measurement_unit_step(current_unit)
        suffix = f" {self._measurement_unit_label(current_unit)}"
        maximum = units_from_500ths(999999999, current_unit)

        for spin in (self._pitwall_wall_height_spin, self._pitwall_armco_height_spin):
            spin.blockSignals(True)
            spin.setDecimals(decimals)
            spin.setSingleStep(step)
            spin.setRange(0.0, maximum)
            spin.setSuffix(suffix)
            spin.blockSignals(False)

        self._pitwall_wall_height_spin.setValue(
            units_from_500ths(wall_height_500ths, current_unit)
        )
        self._pitwall_armco_height_spin.setValue(
            units_from_500ths(armco_height_500ths, current_unit)
        )

    def _update_fsect_table_headers(self) -> None:
        unit_label = self._fsect_dlat_units_label()
        self._fsect_table.setHorizontalHeaderLabels(
            [
                str(self._fsect_model_index_for_column(column_index))
                for column_index in range(self._fsect_table.columnCount())
            ]
        )
        self._fsect_table.setVerticalHeaderLabels(
            [
                "Type",
                f"End to next ({unit_label})",
                f"End DLAT ({unit_label})",
                f"Start DLAT ({unit_label})",
                f"Start to next ({unit_label})",
            ]
        )

    def _on_fsect_current_cell_changed(
        self,
        current_row: int,
        current_column: int,
        previous_row: int,
        previous_column: int,
    ) -> None:
        _ = (current_row, current_column, previous_row, previous_column)
        self._update_fsect_selected_column_header()

    def _update_fsect_selected_column_header(self) -> None:
        selected_column = self._fsect_table.currentColumn()
        for column_index in range(self._fsect_table.columnCount()):
            item = self._fsect_table.horizontalHeaderItem(column_index)
            if item is None:
                item = QtWidgets.QTableWidgetItem(
                    str(self._fsect_model_index_for_column(column_index))
                )
                self._fsect_table.setHorizontalHeaderItem(column_index, item)
            if column_index == selected_column:
                item.setBackground(QtGui.QColor(255, 230, 130))
                item.setForeground(QtGui.QColor(0, 0, 0))
                font = item.font()
                font.setBold(True)
                item.setFont(font)
            else:
                item.setBackground(QtGui.QBrush())
                item.setForeground(QtGui.QBrush())
                font = item.font()
                font.setBold(False)
                item.setFont(font)
        self._fsect_table.horizontalHeader().viewport().update()

    @staticmethod
    def _fsect_type_cell_color(surface_type: int, type2: int) -> QtGui.QColor:
        style = resolve_fsection_style(surface_type, type2)
        if (
            style is not None
            and style.role == "boundary"
            and style.boundary_color is not None
        ):
            color = QtGui.QColor(style.boundary_color)
        elif style is not None and style.surface_color is not None:
            color = QtGui.QColor(style.surface_color)
        else:
            color = QtGui.QColor(sg_rendering.DEFAULT_SURFACE_COLOR)
        return color.lighter(160)

    def _apply_fsect_type_combo_color(self, combo: QtWidgets.QComboBox) -> None:
        selection = combo.currentData()
        if selection is None:
            combo.setStyleSheet("")
            return
        surface_type, type2 = selection
        color = self._fsect_type_cell_color(int(surface_type), int(type2))
        text_color = "#000000" if color.lightness() >= 128 else "#ffffff"
        combo.setStyleSheet(
            "QComboBox { "
            f"background-color: {color.name()}; "
            f"color: {text_color}; "
            "}"
            "QComboBox QAbstractItemView { "
            "background-color: palette(base); "
            "color: palette(text); "
            "}"
        )

    def _fsect_model_index_for_column(self, column_index: int) -> int:
        return self._fsect_table.columnCount() - 1 - column_index

    def _fsect_column_for_model_index(self, fsect_index: int) -> int:
        return self._fsect_table.columnCount() - 1 - fsect_index

    def selected_fsect_index(self) -> int:
        return self._fsect_model_index_for_column(self._fsect_table.currentColumn())

    def select_fsect_index(self, fsect_index: int) -> None:
        self._fsect_table.setCurrentCell(
            0, self._fsect_column_for_model_index(fsect_index)
        )

    def _fsect_dlat_units_label(self) -> str:
        return self._measurement_unit_label(self._current_measurement_unit())

    def _fsect_dlat_to_display_units(self, value: float) -> float:
        return xsect_altitude_to_display_units(
            value, unit=self._current_measurement_unit()
        )

    def _fsect_dlat_from_display_units(self, value: float) -> float:
        return fsect_dlat_from_display_units(
            value, unit=self._current_measurement_unit()
        )

    def _format_fsect_dlat(self, value: float) -> str:
        return format_fsect_dlat(value, unit=self._current_measurement_unit())

    def altitude_display_to_feet(self, value: float) -> float:
        return altitude_display_to_feet(value, unit=self._current_measurement_unit())

    def feet_to_altitude_display(self, value_feet: float) -> float:
        return feet_to_altitude_display(
            value_feet, unit=self._current_measurement_unit()
        )

    def altitude_display_step(self) -> float:
        return self._measurement_unit_step(self._current_measurement_unit())

    def _format_altitude_for_units(self, altitude_500ths: int) -> str:
        return format_altitude_for_units(
            altitude_500ths, unit=self._current_measurement_unit()
        )

    def _sync_altitude_range_spin_units(self, previous_unit: str) -> None:
        current_unit = self._current_measurement_unit()

        current_min_500ths = units_to_500ths(
            self._altitude_min_spin.value(), previous_unit
        )
        current_max_500ths = units_to_500ths(
            self._altitude_max_spin.value(), previous_unit
        )

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
        self._altitude_min_spin.setValue(
            min(max(current_min_display, spin_min), spin_max - spin_step)
        )
        self._altitude_max_spin.setValue(
            max(min(current_max_display, spin_max), spin_min + spin_step)
        )

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
        self._apply_fsect_type_combo_color(widget)
        self._preview.update_fsection_type(
            section_index,
            row_index,
            surface_type=surface_type,
            type2=type2,
        )
        if self.controller is not None and hasattr(
            self.controller, "mark_fsects_dirty"
        ):
            self.controller.mark_fsects_dirty(True)

    def _on_fsect_diagram_dlat_changed(
        self, section_index: int, row_index: int, endpoint: str, new_dlat: float
    ) -> None:
        if self._fsect_drag_active:
            self.fsectDiagramDlatChangeRequested.emit(
                section_index,
                row_index,
                endpoint,
                new_dlat,
                False,
                False,
            )
            self._fsect_drag_dirty = True
            self._schedule_fsect_drag_refresh()
            self._update_fsect_dlat_cell(section_index, row_index, endpoint, new_dlat)
            return
        self.fsectDiagramDlatChangeRequested.emit(
            section_index,
            row_index,
            endpoint,
            new_dlat,
            True,
            True,
        )
        self._update_fsect_dlat_cell(section_index, row_index, endpoint, new_dlat)

    def _on_fsect_diagram_drag_started(
        self, section_index: int, row_index: int, endpoint: str, new_dlat: float
    ) -> None:
        _ = section_index, row_index, endpoint, new_dlat
        self._fsect_drag_active = True
        self._fsect_drag_dirty = False
        if self._fsect_drag_timer.isActive():
            self._fsect_drag_timer.stop()

    def _on_fsect_diagram_drag_ended(
        self, section_index: int, row_index: int, endpoint: str, new_dlat: float
    ) -> None:
        self._fsect_drag_active = False
        if self._fsect_drag_timer.isActive():
            self._fsect_drag_timer.stop()

        self.fsectDiagramDragCommitRequested.emit(
            section_index,
            row_index,
            endpoint,
            new_dlat,
        )
        self._fsect_drag_dirty = False

    def _schedule_fsect_drag_refresh(self) -> None:
        if not self._fsect_drag_timer.isActive():
            self._fsect_drag_timer.start()

    def _on_fsect_drag_timer(self) -> None:
        if not self._fsect_drag_active or not self._fsect_drag_dirty:
            return
        self.fsectDiagramDragRefreshRequested.emit()

    def set_preview_color_text(self, key: str, color: QtGui.QColor) -> None:
        controls = self._preview_color_controls.get(key)
        if controls is None:
            return
        hex_edit, color_swatch = controls
        value = color.name().upper()
        hex_edit.blockSignals(True)
        hex_edit.setText(value)
        hex_edit.blockSignals(False)
        color_swatch.setStyleSheet(
            f"background-color: {value}; border: 1px solid palette(mid);"
        )

    @staticmethod
    def parse_hex_color(value: str) -> QtGui.QColor | None:
        return parse_hex_color(value)

    def update_window_title(
        self,
        *,
        path: Path | None,
        project_path: Path | None = None,
        is_dirty: bool,
        is_untitled: bool = False,
    ) -> None:
        self.setWindowTitle(
            build_window_title(
                path=path,
                project_path=project_path,
                is_dirty=is_dirty,
                is_untitled=is_untitled,
            )
        )

    def set_sidebar_tab_dirty(self, tab_base_label: str, dirty: bool) -> None:
        base_label = self._sidebar_tab_base_labels.get(tab_base_label)
        if base_label is None:
            return
        display_label = f"{base_label}*" if dirty else base_label
        feature_tabs = self._sidebar_feature_tabs.get(base_label)
        if feature_tabs is not None:
            for index in range(feature_tabs.count()):
                tab_text = feature_tabs.tabText(index)
                if tab_text == base_label or tab_text == f"{base_label}*":
                    feature_tabs.setTabText(index, display_label)
                    break
            if dirty:
                self._dirty_sidebar_features.add(base_label)
            else:
                self._dirty_sidebar_features.discard(base_label)
            workflow_label = self._feature_to_workflow_tab.get(base_label)
            if workflow_label is not None:
                workflow_dirty = any(
                    self._feature_to_workflow_tab.get(feature) == workflow_label
                    for feature in self._dirty_sidebar_features
                )
                self._set_workflow_tab_dirty(workflow_label, workflow_dirty)
            return
        workflow_label = self._feature_to_workflow_tab.get(base_label, base_label)
        self._set_workflow_tab_dirty(workflow_label, dirty)

    def _set_workflow_tab_dirty(self, workflow_label: str, dirty: bool) -> None:
        display_label = f"{workflow_label}*" if dirty else workflow_label
        for index in range(self._right_sidebar_tabs.count()):
            tab_text = self._right_sidebar_tabs.tabText(index)
            if tab_text == workflow_label or tab_text == f"{workflow_label}*":
                self._right_sidebar_tabs.setTabText(index, display_label)
                return
