from __future__ import annotations

import logging
import math
import random
import re
import subprocess
import sys
from time import perf_counter
from bisect import bisect_left
from pathlib import Path
from typing import Callable

from PyQt5 import QtCore, QtGui, QtWidgets

from sg_viewer.replacecolors import DEFAULT_TRACK3D_COLORS
from sg_viewer.model.history import FileHistory
from sg_viewer.services.sg_settings_store import SGSettingsStore
from sg_viewer.model.preview_fsection import PreviewFSection
from sg_viewer.services.fsect_generation_service import build_generated_fsects
from sg_viewer.services.sg_integrity_checks import (
    IntegrityProgress,
    build_integrity_report,
    format_integrity_memo,
)
from sg_viewer.services.tsd_io import (
    TrackSurfaceDetailFile,
    TrackSurfaceDetailLine,
    parse_tsd,
    serialize_tsd,
)
from sg_viewer.services.tsd_objects import (
    TsdDashedLinesObject,
    TsdDoubleSolidLineObject,
    TsdPitStallsObject,
    TsdTransverseLineObject,
    TsdZebraCrossingObject,
    tsd_object_from_payload,
    tsd_object_to_payload,
)
from sg_viewer.services.skid_marks import (
    DEFAULT_SKID_COLORS,
    SkidMarkGenerationParameters,
    generate_skid_mark_lines,
    parse_colors_csv,
    parse_skid_sections_csv,
)
from sg_viewer.services.trackside_objects import (
    TracksideObject,
    normalize_trackside_filename,
    normalize_rotation_point,
    serialize_objects_txt,
    trackside_object_from_payload,
    trackside_object_to_payload,
)
from sg_viewer.model.sg_model import Point, SectionPreview
from sg_viewer.model.selection import SectionSelection
from sg_viewer.ui.altitude_units import (
    feet_from_500ths,
    feet_from_slider_units,
    feet_to_500ths,
    units_to_500ths,
)
from sg_viewer.ui.presentation.units_presenter import (
    measurement_unit_decimals,
    measurement_unit_label,
    measurement_unit_step,
)
from sg_viewer.ui.heading_table_dialog import HeadingTableWindow
from sg_viewer.ui.section_table_dialog import SectionTableWindow
from sg_viewer.ui.xsect_table_dialog import XsectEntry, XsectTableWindow
from sg_viewer.ui.tso_attributes_dialog import TracksideObjectAttributesDialog
from sg_viewer.services import sg_rendering
from sg_viewer.ui.about import show_about_dialog
from sg_viewer.ui.bg_calibrator_minimal import Calibrator
from sg_viewer.io.track3d_parser import parse_track3d_detail_list_dlong_ranges, parse_track3d_section_dlongs
from sg_viewer.ui.controllers import (
    BackgroundController,
    BackgroundUiCoordinator,
    DocumentController,
    ElevationController,
    ElevationPanelController,
    ElevationUiCoordinator,
    FileMenuCoordinator,
    InteractionController,
    SectionEditingCoordinator,
    SectionsController,
    TsdSignalController,
    Track3DController,
)
from sg_viewer.model.track_model import TrackModel
from sg_viewer.ui.controllers.features.setup_builders import ViewerActionBuilder, ViewerMenuBuilder
from sg_viewer.ui.actions import (
    FileActions,
    FsectActions,
    HelpActions,
    MrkActions,
    SectionEditingActions,
    Track3DActions,
    TsdActions,
    TsoActions,
    ViewActions,
    ViewerActionGroups,
    build_viewer_menu_bar,
)
from sg_viewer.ui.controllers.features.mrk_controller import MrkController
from sg_viewer.ui.controllers.features.tsd_controller import TsdController
from sg_viewer.ui.controllers.features.trackside_objects_controller import TracksideObjectsController
from sg_viewer.ui.controllers.features.track3d_tools_controller import Track3DToolsController
from sg_viewer.ui.controllers.features.state_controllers import (
    MrkFeatureState,
    Track3dPaletteFeatureState,
    TsdFeatureState,
)
from sg_viewer.preview_runtime.preview_runtime_api import ViewerRuntimeApi

logger = logging.getLogger(__name__)

_TSO_DYNAMIC_LINE_PATTERN = re.compile(
    r'^\s*__TSO\d+:\s*DYNAMIC\s+'
    r'(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*'
    r'(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*'
    r'-?\d+\s*,\s*EXTERN\s*"([^"]+)"\s*;\s*$',
    re.IGNORECASE,
)





class SGViewerController:
    _TSD_SHOW_ALL_LABEL = "Show all TSDs"
    _ELEVATION_TAB_BASE_LABEL = "Elevation/Grade"

    """Coordinates actions, menus, and dialogs for the SG viewer window."""

    def __init__(self, window: QtWidgets.QMainWindow) -> None:
        self._window = window
        self._section_table_window: SectionTableWindow | None = None
        self._heading_table_window: HeadingTableWindow | None = None
        self._xsect_table_window: XsectTableWindow | None = None
        self._tso_attributes_dialog: TracksideObjectAttributesDialog | None = None
        self._integrity_report_window: QtWidgets.QDialog | None = None
        self._unique_tso_filenames_window: QtWidgets.QDialog | None = None
        self._section_dlongs_window: QtWidgets.QDialog | None = None
        self._current_path: Path | None = None
        self._mrk_state = MrkFeatureState()
        self._project_working_directory: Path | None = None
        self._history = FileHistory()
        self._sg_settings_store = SGSettingsStore()
        self._new_straight_default_style = window.new_straight_button.styleSheet()
        self._new_curve_default_style = window.new_curve_button.styleSheet()
        self._delete_default_style = window.delete_section_button.styleSheet()
        self._split_default_style = window.split_section_button.styleSheet()
        self._move_section_default_style = window.move_section_button.styleSheet()
        self._is_untitled = False
        self._active_selection: SectionSelection | None = None
        self._elevation_controller = ElevationController()
        self._calibrator_window: Calibrator | None = None
        self._delete_shortcut = QtWidgets.QShortcut(
            QtGui.QKeySequence(QtCore.Qt.Key_Delete),
            self._window,
        )
        self._delete_shortcut.setContext(QtCore.Qt.WidgetWithChildrenShortcut)
        self.interaction_controller = InteractionController(TrackModel([]))
        self._runtime_api = ViewerRuntimeApi(preview_context=self._window.preview)
        self._document_controller = DocumentController(self, logger)
        self._background_controller = BackgroundController(self, logger)
        self._elevation_panel_controller = ElevationPanelController(self)
        self._sections_controller = SectionsController(self)
        self._file_menu_coordinator = FileMenuCoordinator(self, self._document_controller)
        self._section_editing_coordinator = SectionEditingCoordinator(self, self._sections_controller)
        self._elevation_ui_coordinator = ElevationUiCoordinator(self, self._elevation_panel_controller)
        self._background_ui_coordinator = BackgroundUiCoordinator(self._background_controller)
        self._mrk_controller = MrkController(self)
        self._tsd_controller = TsdController(self)
        self._tsd_signal_controller = TsdSignalController(self)
        self._trackside_objects_controller = TracksideObjectsController(self)
        self._track3d_controller = Track3DController(self)
        self._track3d_tools_controller = Track3DToolsController(self)
        self._tsd_state = TsdFeatureState(self._window)
        self._track3d_palette_state = Track3dPaletteFeatureState()
        self._elevation_grade_is_dirty = False
        self._fsects_is_dirty = False
        self._trackside_objects_is_dirty = False
        self._land_objects_is_dirty = False
        self._tso_visibility_is_dirty = False
        self._tso_modify_elevations_dialog: QtWidgets.QDialog | None = None

        self._action_builder = ViewerActionBuilder(self)
        self._menu_builder = ViewerMenuBuilder(self)
        self._create_actions()
        self._create_menus()
        self._connect_signals()
        self._on_track_opacity_changed(self._window.track_opacity_spin.value())
        self._on_background_brightness_changed(
            self._window.background_brightness_spin.value()
        )
        self._on_mrk_wall_height_changed(self._window.pitwall_wall_height_spin.value())
        self._on_mrk_armco_height_changed(self._window.pitwall_armco_height_spin.value())
        self._autosize_mrk_table_columns()
        self._load_measurement_unit_from_history()
        self._load_preview_colors_from_history()
        self._initialize_preview_color_controls()
        self._window.preview.sectionsChanged.connect(self._on_sections_changed)
        self._window.preview.document.elevation_changed.connect(
            lambda _section_id: self._mark_elevation_grade_dirty(True)
        )
        self._window.preview.document.elevations_bulk_changed.connect(
            lambda: self._mark_elevation_grade_dirty(True)
        )
        self._window.preview.set_section_drag_enabled(
            self._window.move_section_button.isChecked()
        )
        self._on_move_section_mode_changed(
            self._window.move_section_button.isChecked()
        )
        self._file_menu_coordinator.refresh_recent_menu()
        self._start_new_track(confirm=False)
        self._window.show_status_message(
            "Click New Straight to begin drawing or File → Import → Import .SG."
        )
        self._update_track_length_display()

    def __getattr__(self, name: str):
        if name.startswith(("_on_tsd_", "_refresh_tsd_", "_build_tsd_", "_convert_tsd_", "_open_tsd_", "_schedule_tsd_")) or name in {
            "_save_tsd_to_path",
            "_move_tsd_line",
            "_confirm_tsd_file_removal",
            "_sync_active_tsd_file_from_model",
            "_clear_loaded_tsd_files",
            "_add_loaded_tsd_file",
            "_upsert_loaded_tsd_file",
            "_set_active_tsd_file",
            "_update_tsd_remove_file_button_enabled",
            "_all_loaded_tsd_lines",
            "_populate_tsd_table",
            "_center_viewport_on_selected_tsd_line",
            "_tsd_line_center_point",
            "_point_on_track_at_dlong",
            "_point_on_section",
            "_log_tsd_perf",
            "_build_adjusted_to_sg_ranges",
            "_find_adjusted_segment_index",
            "_adjusted_dlong_to_sg_dlong",
            "_all_tsd_lines",
            "_selected_row_indices",
            "_center_viewport_on_tsd_object",
            "_tsd_object_dlong_range",
            "_tsd_object_center_point",
            "_move_tsd_object",
        }:
            return getattr(self._tsd_controller, name)
        if (
            name.startswith(("_on_mrk_", "_mrk_", "_manual_wall_"))
            or name in {
                "_generate_pitwall_txt",
                "_confirm_discard_unsaved_mrk",
                "_set_mrk_dirty",
                "_persist_mrk_state_for_current_track",
                "_load_mrk_state_for_current_track",
                "_pitwall_lines_with_manual_overrides",
                "_persist_manual_wall_height_overrides_for_current_track",
                "_load_manual_wall_height_overrides_for_current_track",
                "_persist_mrk_wall_heights_for_current_track",
                "_load_mrk_wall_heights_for_current_track",
                "_collect_mrk_state",
                "_apply_mrk_state",
                "_build_mark_file_from_table",
                "_update_mrk_highlights_from_table",
                "_autosize_mrk_table_columns",
            }
        ):
            return getattr(self._mrk_controller, name)
        if (
            name.startswith(("_on_tso_", "_refresh_tso_", "_set_tso_", "_tso_"))
            or name.startswith(("_on_preview_tso_", "_trackside_"))
            or name in {
                "_trackside_objects",
                "_selected_trackside_object_indices",
                "_objects_tab_selected_trackside_object_indices",
                "_auto_update_tso_relative_z",
                "_open_tso_attributes_dialog",
                "_center_viewport_on_selected_tso",
                "_update_tso_table_position_cells",
                "_upsert_tso_table_row",
                "_ensure_tso_table_row_button",
                "_format_tso_distance_for_display",
                "_parse_tso_distance_from_display",
                "_build_default_tso",
                "_find_trackside_object_at_point",
                "_rotation_pivot_local_offsets",
                "_move_tso",
                "_parse_trackside_objects_from_3d_text",
                "_closest_boundary_elevation_for_tso",
                "_build_tso_boundary_elevation_context",
                "_closest_boundary_elevation_for_tso_with_context",
                "_replace_tso_dynamic_section_in_3d_text",
                "_format_tso_dynamic_line",
                "_tso_persist_timer",
                "_tso_visibility_sidebar_dirty",
                "_tso_visibility_sidebar_refresh_pending",
            }
        ):
            return getattr(self._trackside_objects_controller, name)
        raise AttributeError(name)

    def __setattr__(self, name: str, value: object) -> None:
        if name in {"_mrk_texture_definitions", "_mrk_is_dirty", "_manual_wall_height_overrides"} and "_mrk_controller" in self.__dict__:
            setattr(self._mrk_controller, name, value)
            return
        if name.startswith("_") and "_trackside_objects_controller" in self.__dict__:
            tso_names = {
                "_trackside_objects",
                "_selected_trackside_object_indices",
                "_objects_tab_selected_trackside_object_indices",
                "_tso_add_mode_active",
                "_tso_stamp_mode_active",
                "_tso_box_select_mode_active",
                "_tso_stamp_filename",
                "_auto_update_tso_relative_z",
                "_tso_persist_timer",
                "_tso_visibility_sidebar_dirty",
                "_tso_visibility_sidebar_refresh_pending",
            }
            if name in tso_names:
                setattr(self._trackside_objects_controller, name, value)
                return
        super().__setattr__(name, value)

    def load_sg(self, path: Path) -> None:
        self._document_controller.load_sg(path)

    @property
    def _loaded_tsd_files(self): return self._tsd_state.loaded_files
    @_loaded_tsd_files.setter
    def _loaded_tsd_files(self, value): self._tsd_state.loaded_files = value
    @property
    def _tsd_objects(self): return self._tsd_state.objects
    @_tsd_objects.setter
    def _tsd_objects(self, value): self._tsd_state.objects = value
    @property
    def _tsd_lines_model(self): return self._tsd_state.lines_model
    @_tsd_lines_model.setter
    def _tsd_lines_model(self, value): self._tsd_state.lines_model = value
    @property
    def _tsd_preview_refresh_timer(self): return self._tsd_state.preview_refresh_timer
    @_tsd_preview_refresh_timer.setter
    def _tsd_preview_refresh_timer(self, value): self._tsd_state.preview_refresh_timer = value
    @property
    def _tsd_is_dirty(self): return self._tsd_state.is_dirty
    @_tsd_is_dirty.setter
    def _tsd_is_dirty(self, value): self._tsd_state.is_dirty = value
    @property
    def _tsd_object_dialog_preview_object(self): return self._tsd_state.object_dialog_preview_object
    @_tsd_object_dialog_preview_object.setter
    def _tsd_object_dialog_preview_object(self, value): self._tsd_state.object_dialog_preview_object = value
    @property
    def _editing_tsd_object_index(self): return self._tsd_state.editing_object_index
    @_editing_tsd_object_index.setter
    def _editing_tsd_object_index(self, value): self._tsd_state.editing_object_index = value
    @property
    def _active_tsd_file_index(self): return self._tsd_state.active_file_index
    @_active_tsd_file_index.setter
    def _active_tsd_file_index(self, value): self._tsd_state.active_file_index = value
    @property
    def _suspend_tsd_preview_refresh(self): return self._tsd_state.suspend_preview_refresh
    @_suspend_tsd_preview_refresh.setter
    def _suspend_tsd_preview_refresh(self, value): self._tsd_state.suspend_preview_refresh = value
    @property
    def _debug_tsd_perf(self): return self._tsd_state.debug_perf
    @_debug_tsd_perf.setter
    def _debug_tsd_perf(self, value): self._tsd_state.debug_perf = value
    @property
    def _last_tsd_preview_lines(self): return self._tsd_state.last_preview_lines
    @_last_tsd_preview_lines.setter
    def _last_tsd_preview_lines(self, value): self._tsd_state.last_preview_lines = value
    @property
    def _last_tsd_adjusted_to_sg_ranges(self): return self._tsd_state.last_adjusted_to_sg_ranges
    @_last_tsd_adjusted_to_sg_ranges.setter
    def _last_tsd_adjusted_to_sg_ranges(self, value): self._tsd_state.last_adjusted_to_sg_ranges = value

    @property
    @property
    def _skid_marks_dialog(self): return self._track3d_palette_state.skid_marks_dialog
    @_skid_marks_dialog.setter
    def _skid_marks_dialog(self, value): self._track3d_palette_state.skid_marks_dialog = value
    @property
    def _generated_skid_mark_lines(self): return self._track3d_palette_state.generated_skid_mark_lines
    @_generated_skid_mark_lines.setter
    def _generated_skid_mark_lines(self, value): self._track3d_palette_state.generated_skid_mark_lines = value
    @property
    def _skid_marks_rows_text(self): return self._track3d_palette_state.skid_marks_rows_text
    @_skid_marks_rows_text.setter
    def _skid_marks_rows_text(self, value): self._track3d_palette_state.skid_marks_rows_text = value
    @property
    def _skid_marks_colors(self): return self._track3d_palette_state.skid_marks_colors
    @_skid_marks_colors.setter
    def _skid_marks_colors(self, value): self._track3d_palette_state.skid_marks_colors = value

    def _create_actions(self) -> None:
        self._action_builder.create_actions()

    def _create_actions_impl(self) -> None:
        self._action_groups = ViewerActionGroups(
            file=FileActions(
                self._window,
                self._start_new_track,
                self._file_menu_coordinator.import_sg_file_dialog,
                self._file_menu_coordinator.open_project_file_dialog,
                self._track3d_tools_controller._load_sunny_palette_dialog,
                self._file_menu_coordinator.import_trk_file_dialog,
                self._file_menu_coordinator.import_trk_from_dat_file_dialog,
                self._file_menu_coordinator.save_current_file,
                self._file_menu_coordinator.save_project_file_dialog,
                self._file_menu_coordinator.save_file_dialog,
                self._convert_sg_to_trk,
                self._export_current_sg_to_csv,
                self._window.close,
            ),
            view=ViewActions(
                self._window,
                self._open_background_file_dialog,
                self._show_background_settings_dialog,
                self._window.show_view_options_dialog,
                self._choose_project_working_folder,
                self._clear_project_working_folder,
                self._show_track_section_dlongs_dialog,
                self._window.set_studio_chatter_enabled,
            ),
            section_editing=SectionEditingActions(
                self._window,
                self._scale_track,
                self._open_rotate_track_dialog,
                self._reverse_track,
                self._section_editing_coordinator.show_section_table,
                self._section_editing_coordinator.show_heading_table,
                self._section_editing_coordinator.show_xsect_table,
            ),
            fsect=FsectActions(
                self._window,
                self._open_generate_fsects_dialog,
                self._open_raise_lower_elevations_dialog,
                self._open_flatten_all_elevations_and_grade_dialog,
                self._open_generate_elevation_change_dialog,
                self._generate_pitwall_txt,
            ),
            mrk=MrkActions(self._window),
            tsd=TsdActions(self._window, self._track3d_tools_controller._show_palette_colors_dialog),
            tso=TsoActions(
                self._window,
                self._launch_tso_generator,
                self._show_unique_tso_filenames_dialog,
            ),
            track3d=Track3DActions(
                self._window,
                self._launch_background_calibrator,
                self._track3d_tools_controller._open_three_d_tools_dialog,
                self._run_sg_integrity_checks,
            ),
            help=HelpActions(self._window, self._show_about_dialog),
        )
        self._window.run_full_integrity_check_button.clicked.connect(self._run_sg_integrity_checks)
        self._window.raise_lower_elevations_button.clicked.connect(
            self._open_raise_lower_elevations_dialog
        )
        self._window.flatten_elevations_button.clicked.connect(
            self._open_flatten_all_elevations_and_grade_dialog
        )
        self._publish_action_group_attributes()

    def _publish_action_group_attributes(self) -> None:
        for group in self._action_groups.__dict__.values():
            for name, value in group.__dict__.items():
                if name == "parent" or callable(value):
                    continue
                setattr(self, f"_{name}", value)

    def _create_menus(self) -> None:
        self._menu_builder.create_menus()

    def _create_menus_impl(self) -> None:
        build_viewer_menu_bar(self._window, self._action_groups)

    def _show_about_dialog(self) -> None:
        show_about_dialog(self._window)

    def _settings_path_for(self, sg_path: Path) -> Path:
        return self._sg_settings_store._settings_path(sg_path)

    def _dialog_default_directory(self) -> str:
        if self._project_working_directory is not None:
            return str(self._project_working_directory)
        if self._current_path is not None:
            return str(self._current_path.parent)
        return ""

    def _dialog_default_file_path(self, filename: str) -> str:
        default_directory = self._dialog_default_directory()
        if not default_directory:
            return filename
        return str(Path(default_directory) / filename)

    def _set_project_working_directory(self, directory: Path | None, *, persist: bool = True) -> None:
        if directory is None:
            self._project_working_directory = None
            self._clear_project_working_folder_action.setEnabled(False)
            if persist and self._current_path is not None:
                self._document_controller.persist_project_metadata()
            return

        resolved = directory.resolve()
        self._project_working_directory = resolved
        self._clear_project_working_folder_action.setEnabled(True)
        if persist and self._current_path is not None:
            self._document_controller.persist_project_metadata()

    def _choose_project_working_folder(self) -> None:
        selected = QtWidgets.QFileDialog.getExistingDirectory(
            self._window,
            "Select Project Working Folder",
            self._dialog_default_directory(),
        )
        if not selected:
            return
        selected_path = Path(selected).resolve()
        self._set_project_working_directory(selected_path, persist=True)
        self._window.show_status_message(f"Project working folder set to {selected_path}")

    def _clear_project_working_folder(self) -> None:
        self._set_project_working_directory(None, persist=True)
        self._window.show_status_message("Project working folder cleared.")

    def _show_unique_tso_filenames_dialog(self) -> None:
        if self._unique_tso_filenames_window is None:
            self._unique_tso_filenames_window = QtWidgets.QDialog(self._window)
            self._unique_tso_filenames_window.setWindowTitle("Unique TSO filenames")
            self._unique_tso_filenames_window.setWindowModality(QtCore.Qt.NonModal)
            self._unique_tso_filenames_window.setAttribute(
                QtCore.Qt.WA_DeleteOnClose,
                False,
            )
            self._unique_tso_filenames_window.resize(480, 560)

            layout = QtWidgets.QVBoxLayout(self._unique_tso_filenames_window)
            text_edit = QtWidgets.QPlainTextEdit(self._unique_tso_filenames_window)
            text_edit.setObjectName("uniqueTsoFilenamesText")
            text_edit.setReadOnly(True)
            text_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
            layout.addWidget(text_edit)

            close_button = QtWidgets.QPushButton("Close", self._unique_tso_filenames_window)
            close_button.clicked.connect(self._unique_tso_filenames_window.close)
            button_row = QtWidgets.QHBoxLayout()
            button_row.addStretch(1)
            button_row.addWidget(close_button)
            layout.addLayout(button_row)

        unique_filenames = sorted(
            {
                normalize_trackside_filename(obj.filename)
                for obj in self._trackside_objects
                if normalize_trackside_filename(obj.filename)
            }
        )
        text = "\n".join(unique_filenames)
        if not text:
            text = "No TSOs found."

        text_edit = self._unique_tso_filenames_window.findChild(
            QtWidgets.QPlainTextEdit,
            "uniqueTsoFilenamesText",
        )
        if text_edit is not None:
            text_edit.setPlainText(text)

        self._unique_tso_filenames_window.show()
        self._unique_tso_filenames_window.raise_()
        self._unique_tso_filenames_window.activateWindow()

    def _show_track_section_dlongs_dialog(self) -> None:
        if self._current_path is None or not self._current_path.exists():
            QtWidgets.QMessageBox.information(
                self._window,
                "Track Section DLONGs",
                "Load a saved project before viewing section DLONGs.",
            )
            return

        track3d_path = self._current_path.with_suffix(".3d")
        if not track3d_path.exists():
            fallback_path = self._current_path.with_suffix(".3D")
            track3d_path = fallback_path if fallback_path.exists() else track3d_path

        if not track3d_path.exists():
            QtWidgets.QMessageBox.information(
                self._window,
                "Track Section DLONGs",
                f"No track .3d file was found next to {self._current_path.name}.",
            )
            return

        rows = parse_track3d_section_dlongs(track3d_path)
        if not rows:
            text = "No section DLONG DATA blocks were found."
        else:
            lines = [
                f"sec{row.section}_l{row.sub_index}: {', '.join(str(value) for value in row.dlongs)}"
                for row in rows
            ]
            text = "\n".join(lines)

        if self._section_dlongs_window is None:
            self._section_dlongs_window = QtWidgets.QDialog(self._window)
            self._section_dlongs_window.setWindowTitle("Track Section DLONGs")
            self._section_dlongs_window.setWindowModality(QtCore.Qt.NonModal)
            self._section_dlongs_window.setAttribute(
                QtCore.Qt.WA_DeleteOnClose,
                False,
            )
            self._section_dlongs_window.resize(580, 640)

            layout = QtWidgets.QVBoxLayout(self._section_dlongs_window)
            text_edit = QtWidgets.QPlainTextEdit(self._section_dlongs_window)
            text_edit.setObjectName("sectionDlongsText")
            text_edit.setReadOnly(True)
            text_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
            layout.addWidget(text_edit)

            close_button = QtWidgets.QPushButton("Close", self._section_dlongs_window)
            close_button.clicked.connect(self._section_dlongs_window.close)
            button_row = QtWidgets.QHBoxLayout()
            button_row.addStretch(1)
            button_row.addWidget(close_button)
            layout.addLayout(button_row)

        text_edit = self._section_dlongs_window.findChild(
            QtWidgets.QPlainTextEdit,
            "sectionDlongsText",
        )
        if text_edit is not None:
            text_edit.setPlainText(text)

        self._section_dlongs_window.show()
        self._section_dlongs_window.raise_()
        self._section_dlongs_window.activateWindow()




    def _connect_signals(self) -> None:
        self._sections_controller.connect_signals()
        self._section_editing_coordinator.connect_signals()
        self._elevation_ui_coordinator.connect_signals()
        self._background_controller.connect_signals()
        self._mrk_controller.connect_signals()
        self._tsd_signal_controller.connect_signals()
        self._trackside_objects_controller.connect_signals()
        self._track3d_controller.connect_signals()

    def confirm_close(self) -> bool:
        return self.confirm_discard_unsaved_for_action("Close SG Viewer")

    def confirm_discard_unsaved_for_action(self, action_label: str) -> bool:
        unsaved_items = self._collect_unsaved_item_labels()
        if not unsaved_items:
            return True
        message = (
            "You have unsaved changes in:\n"
            + "\n".join(f"• {item}" for item in unsaved_items)
            + f"\n\nContinue and {action_label.lower()} without saving?"
        )
        confirm_text = (
            "Close without saving"
            if action_label == "Close SG Viewer"
            else "Continue without saving"
        )
        return self._confirm_discard_dialog(
            title=f"{action_label}?",
            message=message,
            confirm_text=confirm_text,
        )

    def _confirm_discard_dialog(self, title: str, message: str, confirm_text: str) -> bool:
        dialog = QtWidgets.QMessageBox(self._window)
        dialog.setIcon(QtWidgets.QMessageBox.Warning)
        dialog.setWindowTitle(title)
        dialog.setText(message)
        discard_button = dialog.addButton(confirm_text, QtWidgets.QMessageBox.DestructiveRole)
        cancel_button = dialog.addButton("Cancel", QtWidgets.QMessageBox.RejectRole)
        dialog.setDefaultButton(cancel_button)
        dialog.exec()
        return dialog.clickedButton() == discard_button

    def _confirm_discard_unsaved_track(
        self, title: str, action_description: str
    ) -> bool:
        if not self._window.preview.has_unsaved_changes:
            return True
        response = QtWidgets.QMessageBox.question(
            self._window,
            title,
            f"You have unsaved SG changes. Continue and {action_description} without saving?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return response == QtWidgets.QMessageBox.Yes



    def _set_tsd_dirty(self, dirty: bool) -> None:
        self._tsd_is_dirty = dirty
        self._window.set_sidebar_tab_dirty("TSD", dirty)

    def _set_trackside_objects_dirty(self, dirty: bool) -> None:
        self._trackside_objects_is_dirty = dirty
        self._window.set_sidebar_tab_dirty("Objects", dirty)

    def set_land_objects_dirty(self, dirty: bool) -> None:
        self._land_objects_is_dirty = dirty
        self._window.set_sidebar_tab_dirty("Draw land objects", dirty)

    def _set_tso_visibility_dirty(self, dirty: bool) -> None:
        self._tso_visibility_is_dirty = dirty
        self._window.set_sidebar_tab_dirty("TSO Visibility", dirty)

    def _mark_elevation_grade_dirty(self, dirty: bool) -> None:
        self._elevation_grade_is_dirty = dirty
        self._window.set_sidebar_tab_dirty("Elevation/Grade", dirty)

    def _mark_fsects_dirty(self, dirty: bool) -> None:
        self._fsects_is_dirty = dirty
        self._window.set_sidebar_tab_dirty("Fsects", dirty)

    def _collect_unsaved_item_labels(self) -> list[str]:
        labels: list[str] = []
        if self._elevation_grade_is_dirty:
            labels.append("Elevation/Grade")
        if self._fsects_is_dirty:
            labels.append("Fsects")
        if self._window.preview.has_unsaved_changes and not labels:
            labels.append("SG track geometry")
        if self._mrk_is_dirty:
            labels.append("MRK entries")
        if self._tsd_is_dirty:
            labels.append("TSD lines")
        if self._trackside_objects_is_dirty:
            labels.append("Trackside objects")
        if self._land_objects_is_dirty:
            labels.append("Draw land objects")
        if self._tso_visibility_is_dirty:
            labels.append("TSO visibility")
        return labels

    def mark_fsects_dirty(self, dirty: bool) -> None:
        self._mark_fsects_dirty(dirty)




    def _persist_tsd_state_for_current_track(self) -> None:
        start = perf_counter()
        if self._current_path is None:
            return
        files = [
            loaded.source_path
            for loaded in self._loaded_tsd_files
            if loaded.source_path is not None
        ]
        self._sg_settings_store.set_tsd_files(self._current_path, files, self._active_tsd_file_index)
        self._sg_settings_store.set_tsd_objects(
            self._current_path,
            [tsd_object_to_payload(obj) for obj in self._tsd_objects],
        )
        self._sg_settings_store.set_tsd_skid_marks_state(
            self._current_path,
            {
                "rows_csv": self._skid_marks_rows_text,
                "colors_csv": ",".join(str(value) for value in self._skid_marks_colors),
            },
        )
        self._sg_settings_store.set_trackside_objects(
            self._current_path,
            [trackside_object_to_payload(obj) for obj in self._trackside_objects],
        )
        self._sg_settings_store.set_land_objects(
            self._current_path,
            self._window.serialize_land_objects(),
        )
        self._sg_settings_store.set_tso_visibility_object_lists(
            self._current_path,
            self._window.tso_visibility_sidebar.serialize_object_lists(),
        )
        self._sg_settings_store.set_tso_visibility_detail_lists(
            self._current_path,
            self._window.tso_visibility_sidebar.serialize_detail_lists(),
        )
        self._sg_settings_store.set_tso_auto_update_relative_z(
            self._current_path,
            self._auto_update_tso_relative_z,
        )
        logger.debug("Persisted full TSD state in %.3f ms", (perf_counter() - start) * 1000.0)

    def _persist_trackside_objects_for_current_track(self) -> None:
        start = perf_counter()
        if self._current_path is None:
            return
        self._sg_settings_store.set_trackside_objects(
            self._current_path,
            [trackside_object_to_payload(obj) for obj in self._trackside_objects],
        )
        logger.debug("Persisted trackside objects in %.3f ms", (perf_counter() - start) * 1000.0)

    def _schedule_trackside_objects_persist(self) -> None:
        if self._current_path is None:
            return
        self._tso_persist_timer.start()

    def _load_tsd_state_for_current_track(self, progress_callback: Callable[[int, str], None] | None = None) -> None:
        self._clear_loaded_tsd_files()
        self._window.load_land_objects([])
        self._generated_skid_mark_lines = ()
        self._skid_marks_rows_text = ""
        self._skid_marks_colors = DEFAULT_SKID_COLORS
        self._track3d_tools_controller._selected_track3d_path = None
        self._track3d_tools_controller._track3d_colors = dict(DEFAULT_TRACK3D_COLORS)
        self._window.set_selected_track3d_path_text("none")
        self._window.set_selected_colors_path_text("defaults")
        if progress_callback is not None:
            progress_callback(0, "Resetting TSD and object project state…")
        self._sync_tso_visibility_section_dlongs()
        if self._current_path is None:
            self.set_land_objects_dirty(False)
            return
        persisted_auto_update_relative_z = self._sg_settings_store.get_tso_auto_update_relative_z(self._current_path)
        self._auto_update_tso_relative_z = bool(persisted_auto_update_relative_z) if persisted_auto_update_relative_z is not None else False
        checkbox = self._window.tso_auto_update_relative_z_checkbox
        previous_state = checkbox.blockSignals(True)
        checkbox.setChecked(self._auto_update_tso_relative_z)
        checkbox.blockSignals(previous_state)
        if progress_callback is not None:
            progress_callback(1, "Restoring Track3D file and color settings…")
        persisted_track3d_colors = self._sg_settings_store.get_track3d_colors(self._current_path)
        if isinstance(persisted_track3d_colors, dict):
            merged_colors = dict(DEFAULT_TRACK3D_COLORS)
            for name, value in persisted_track3d_colors.items():
                if name in merged_colors:
                    merged_colors[name] = int(value)
            self._track3d_tools_controller._track3d_colors = merged_colors
            self._window.set_selected_colors_path_text("custom")
        persisted_track3d_path = self._sg_settings_store.get_track3d_file(self._current_path)
        if persisted_track3d_path is not None:
            self._track3d_tools_controller._set_selected_track3d_path(persisted_track3d_path, persist=False)
        else:
            auto_track3d_path = self._track3d_tools_controller._track3d_path_for_current_project()
            if auto_track3d_path is not None:
                self._track3d_tools_controller._set_selected_track3d_path(auto_track3d_path, persist=False)
        files, active_index = self._sg_settings_store.get_tsd_files(self._current_path)
        if progress_callback is not None:
            progress_callback(2, "Restoring TSD object definitions and skid marks…")
        self._tsd_objects = []
        self._trackside_objects = []
        for raw_object in self._sg_settings_store.get_tsd_objects(self._current_path):
            try:
                self._tsd_objects.append(tsd_object_from_payload(raw_object))
            except (ValueError, TypeError, KeyError):
                logger.warning("Unable to restore TSD object %s", raw_object, exc_info=True)
        skid_state = self._sg_settings_store.get_tsd_skid_marks_state(self._current_path)
        if isinstance(skid_state, dict):
            raw_rows = skid_state.get("rows_csv")
            raw_colors = skid_state.get("colors_csv")
            if isinstance(raw_rows, str):
                self._skid_marks_rows_text = raw_rows
            if isinstance(raw_colors, str):
                try:
                    self._skid_marks_colors = parse_colors_csv(raw_colors)
                except ValueError:
                    self._skid_marks_colors = DEFAULT_SKID_COLORS
        self._refresh_tsd_objects_table()
        if self._tsd_objects:
            self._enable_tsd_preview_overlay()
            self._refresh_tsd_preview_lines()
        if progress_callback is not None:
            progress_callback(3, "Restoring trackside object definitions…")
        self._trackside_objects = []
        for raw_object in self._sg_settings_store.get_trackside_objects(self._current_path):
            try:
                self._trackside_objects.append(trackside_object_from_payload(raw_object))
            except ValueError:
                continue
        self._refresh_tso_table()
        if progress_callback is not None:
            progress_callback(4, "Restoring TSO visibility lists and land objects…")
        self._window.tso_visibility_sidebar.load_object_lists_from_payload(
            self._sg_settings_store.get_tso_visibility_object_lists(self._current_path)
        )
        self._window.tso_visibility_sidebar.load_detail_lists_from_payload(
            self._sg_settings_store.get_tso_visibility_detail_lists(self._current_path)
        )
        self._window.load_land_objects(self._sg_settings_store.get_land_objects(self._current_path))
        total_files = len(files)
        for index, path in enumerate(files, start=1):
            if progress_callback is not None:
                progress_callback(5, f"Loading TSD file {index} of {total_files}: {path.name}…")
            if not path.exists():
                continue
            try:
                detail_file = parse_tsd(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                logger.warning("Unable to restore TSD file %s", path, exc_info=True)
                continue
            self._add_loaded_tsd_file(path.name, tuple(detail_file.lines), select=False, source_path=path.resolve())
        if progress_callback is not None:
            progress_callback(6, "Activating restored TSD selection and overlays…")
        if self._loaded_tsd_files:
            self._enable_tsd_preview_overlay()
            target_index = active_index if isinstance(active_index, int) and 0 <= active_index < len(self._loaded_tsd_files) else None
            if target_index is None:
                self._window.tsd_files_combo.setCurrentIndex(0)
                self._on_tsd_file_selection_changed(0)
            else:
                self._window.tsd_files_combo.setCurrentIndex(target_index + 1)
                self._set_active_tsd_file(target_index)
        self._set_tsd_dirty(False)
        self._set_trackside_objects_dirty(False)
        self.set_land_objects_dirty(False)


    def _sync_tso_visibility_section_dlongs(self) -> None:
        track3d_path = self._track3d_tools_controller._track3d_path_for_current_project()
        rows = parse_track3d_section_dlongs(track3d_path) if track3d_path is not None else []
        self._window.tso_visibility_sidebar.set_section_dlong_rows(rows)
        if track3d_path is not None:
            self._window.tso_visibility_sidebar.set_detail_list_dlong_rows(parse_track3d_detail_list_dlong_ranges(track3d_path))
            self._window.tso_visibility_sidebar.load_detail_lists_from_track3d_if_empty(str(track3d_path))

        starts_by_section: dict[int, tuple[int, ...]] = {}
        grouped: dict[int, list[tuple[int, int]]] = {}
        for row in rows:
            if not row.dlongs:
                continue
            grouped.setdefault(int(row.section), []).append((int(row.sub_index), int(row.dlongs[0])))
        for section, values in grouped.items():
            starts_by_section[section] = tuple(start for _, start in sorted(values, key=lambda item: item[0]))
        self._window.set_section_subindex_metadata(starts_by_section)








































    def _on_right_sidebar_tab_changed(self, index: int) -> None:
        tab_name = self._window.active_sidebar_tab_name()
        self._window.update_mouse_usage_text()
        if tab_name != self._ELEVATION_TAB_BASE_LABEL:
            self._elevation_panel_controller.cancel_live_edits()
        if tab_name in {"Fsects", "Walls"} and not self._window.sg_fsects_checkbox.isChecked():
            self._window.sg_fsects_checkbox.setChecked(True)
        is_mrk_tab = tab_name == "Walls"
        is_tsd_tab = tab_name == "TSD"
        is_objects_tab = tab_name == "Objects"
        is_tso_visibility_tab = tab_name == "TSO Visibility"
        if self._tso_box_select_mode_active and not is_objects_tab:
            self._set_tso_box_select_mode_active(False)
        self._window.preview.set_show_mrk_notches(is_mrk_tab)
        if is_tsd_tab or is_objects_tab or is_tso_visibility_tab:
            self._window.preview.set_show_tsd_lines(True)
        self._window.preview.set_show_trackside_objects(
            is_objects_tab
            or is_tso_visibility_tab
            or self._window.trackside_objects_overlay_checkbox.isChecked()
        )
        self._apply_tsd_centerline_visibility_mode()
        self._apply_trackside_drag_scope()
        if is_mrk_tab:
            self._update_mrk_highlights_from_table()
        else:
            self._window.preview.set_highlighted_mrk_walls(())
        if is_tso_visibility_tab:
            self._flush_tso_visibility_sidebar_refresh_if_needed()


    def _on_trackside_objects_overlay_toggled(self, checked: bool) -> None:
        current_index = self._window.right_sidebar_tabs.currentIndex()
        tab_name = self._window.active_sidebar_tab_name() if current_index >= 0 else ""
        self._window.preview.set_show_trackside_objects(
            bool(checked) or tab_name in {"Objects", "TSO Visibility"}
        )

    def _on_tsd_hide_centerline_nodes_toggled(self, _checked: bool) -> None:
        self._apply_tsd_centerline_visibility_mode()

    def _apply_tsd_centerline_visibility_mode(self) -> None:
        current_index = self._window.right_sidebar_tabs.currentIndex()
        tab_name = self._window.active_sidebar_tab_name() if current_index >= 0 else ""
        hide_centerline_nodes = (
            tab_name == "TSD"
            and self._window.tsd_hide_centerline_nodes_checkbox.isChecked()
        )
        if tab_name == "Draw land objects":
            hide_centerline_nodes = True
        self._window.preview.set_show_centerline_and_nodes(not hide_centerline_nodes)
        geometry_active = (
            current_index >= 0
            and self._window.right_sidebar_tabs.tabText(current_index).rstrip("*") == "Geometry"
        )
        self._window.preview.set_centerline_editing_enabled(
            geometry_active and not hide_centerline_nodes
        )

    def _is_tso_visibility_tab_active(self) -> bool:
        current_index = self._window.right_sidebar_tabs.currentIndex()
        if current_index < 0:
            return False
        tab_name = self._window.active_sidebar_tab_name()
        return tab_name == "TSO Visibility"

    def _is_objects_tab_active(self) -> bool:
        current_index = self._window.right_sidebar_tabs.currentIndex()
        if current_index < 0:
            return False
        tab_name = self._window.active_sidebar_tab_name()
        return tab_name == "Objects"

    def _mark_tso_visibility_sidebar_dirty(self) -> None:
        self._tso_visibility_sidebar_dirty = True

    def _schedule_tso_visibility_sidebar_refresh(self) -> None:
        if self._tso_visibility_sidebar_refresh_pending:
            return
        self._tso_visibility_sidebar_refresh_pending = True
        QtCore.QTimer.singleShot(0, self._flush_tso_visibility_sidebar_refresh_if_needed)

    def _flush_tso_visibility_sidebar_refresh_if_needed(self) -> None:
        self._tso_visibility_sidebar_refresh_pending = False
        if not self._tso_visibility_sidebar_dirty:
            return
        if not self._is_tso_visibility_tab_active():
            return
        start = perf_counter()
        metadata: dict[int, tuple[str, str]] = {}
        for index, tso in enumerate(self._trackside_objects):
            metadata[index] = (
                normalize_trackside_filename(tso.filename),
                tso.description.strip(),
            )
        self._window.tso_visibility_sidebar.update_available_tso_metadata(
            tuple(range(len(self._trackside_objects))),
            metadata,
            refresh=True,
        )
        self._tso_visibility_sidebar_dirty = False
        logger.debug("TSO visibility sidebar deferred refresh %.3f ms", (perf_counter() - start) * 1000.0)

    def _apply_trackside_drag_scope(self) -> None:
        if self._is_objects_tab_active():
            self._window.preview.set_trackside_move_enabled_indices(
                tuple(self._objects_tab_selected_trackside_object_indices)
            )
            return
        self._window.preview.set_trackside_move_enabled_indices(())






    def _autosize_tsd_lines_table_columns(self) -> None:
        self._window.tsd_lines_table.resizeColumnsToContents()

    def _on_track_opacity_changed(self, value: int) -> None:
        clamped_value = max(0, min(100, int(value)))
        if self._window.track_opacity_spin.value() != clamped_value:
            self._window.track_opacity_spin.setValue(clamped_value)
        self._window.preview.set_track_opacity(clamped_value / 100.0)

    def _on_background_brightness_changed(self, value: int) -> None:
        clamped_value = max(-100, min(100, int(value)))
        if self._window.background_brightness_spin.value() != clamped_value:
            self._window.background_brightness_spin.setValue(clamped_value)
        self._window.preview.set_background_brightness(clamped_value)

    def _on_fsect_diagram_dlat_change_requested(
        self,
        section_index: int,
        row_index: int,
        endpoint: str,
        new_dlat: float,
        refresh_preview: bool,
        emit_sections_changed: bool,
    ) -> None:
        kwargs = {
            "refresh_preview": refresh_preview,
            "emit_sections_changed": emit_sections_changed,
        }
        self._mark_fsects_dirty(True)
        if endpoint == "start":
            self._window.preview.update_fsection_dlat(
                section_index,
                row_index,
                start_dlat=new_dlat,
                **kwargs,
            )
            return
        self._window.preview.update_fsection_dlat(
            section_index,
            row_index,
            end_dlat=new_dlat,
            **kwargs,
        )

    def _on_fsect_diagram_drag_commit_requested(
        self,
        section_index: int,
        row_index: int,
        endpoint: str,
        new_dlat: float,
    ) -> None:
        self._on_fsect_diagram_dlat_change_requested(
            section_index,
            row_index,
            endpoint,
            new_dlat,
            False,
            True,
        )
        self._window.preview.refresh_fsections_preview()
        self._window.update_selected_section_fsect_table()


    def _load_measurement_unit_from_history(self) -> None:
        unit = self._history.get_measurement_unit()
        if unit is None:
            return
        combo = self._window.measurement_units_combo
        index = combo.findData(unit)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _initialize_preview_color_controls(self) -> None:
        for key in self._window.preview_color_controls:
            color = self._current_preview_color_for_key(key)
            self._window.set_preview_color_text(key, color)

    def _load_preview_colors_from_history(self) -> None:
        defaults: dict[str, str] = {}
        for key in self._window.preview_color_controls:
            defaults[key] = self._current_preview_color_for_key(key).name().upper()
        resolved = self._history.ensure_preview_colors(defaults)
        for key, value in resolved.items():
            parsed = QtGui.QColor(value)
            if parsed.isValid():
                self._apply_preview_color(key, parsed, save=False)

    def _current_preview_color_for_key(self, key: str) -> QtGui.QColor:
        if key.startswith("fsect_"):
            surface_id = int(key.split("_", maxsplit=1)[1])
            return QtGui.QColor(sg_rendering.SURFACE_COLORS.get(surface_id, sg_rendering.DEFAULT_SURFACE_COLOR))
        return self._window.preview.preview_color(key)

    def _apply_preview_color(
        self,
        key: str,
        color: QtGui.QColor,
        *,
        save: bool = True,
    ) -> None:
        if key.startswith("fsect_"):
            surface_id = int(key.split("_", maxsplit=1)[1])
            sg_rendering.SURFACE_COLORS[surface_id] = QtGui.QColor(color)
            if surface_id == 7:
                sg_rendering.WALL_COLOR = QtGui.QColor(color)
            elif surface_id == 8:
                sg_rendering.ARMCO_COLOR = QtGui.QColor(color)
            self._window.preview.update()
        else:
            self._window.preview.set_preview_color(key, color)
        self._window.set_preview_color_text(key, color)
        if save:
            self._history.set_preview_color(key, color.name().upper())

    def _on_preview_color_text_changed(
        self, key: str, widget: QtWidgets.QLineEdit
    ) -> None:
        color = parse_hex_color(widget.text())
        if color is None:
            current = self._current_preview_color_for_key(key)
            self._window.set_preview_color_text(key, current)
            return
        self._apply_preview_color(key, color)

    def _on_pick_preview_color(self, key: str) -> None:
        initial = self._current_preview_color_for_key(key)
        color = QtWidgets.QColorDialog.getColor(initial, self._window, "Choose Color")
        if not color.isValid():
            return
        self._apply_preview_color(key, color)

    def _should_confirm_reset(self) -> bool:
        sections, _ = self._window.preview.get_section_set()
        return self._window.preview.has_unsaved_changes or bool(sections)

    def _on_new_straight_mode_changed(self, active: bool) -> None:
        button = self._window.new_straight_button
        button.setChecked(active)
        if active:
            button.setStyleSheet("background-color: #3f51b5; color: white;")
        else:
            button.setStyleSheet(self._new_straight_default_style)
        self._window.update_mouse_usage_text()

    def _on_new_curve_mode_changed(self, active: bool) -> None:
        button = self._window.new_curve_button
        button.setChecked(active)
        if active:
            button.setStyleSheet("background-color: #3f51b5; color: white;")
        else:
            button.setStyleSheet(self._new_curve_default_style)
        self._window.update_mouse_usage_text()

    def _on_delete_mode_changed(self, active: bool) -> None:
        button = self._window.delete_section_button
        button.setChecked(active)
        if active:
            button.setStyleSheet("background-color: #b53f3f; color: white;")
        else:
            button.setStyleSheet(self._delete_default_style)
        self._window.update_mouse_usage_text()

    def _on_split_mode_changed(self, active: bool) -> None:
        button = self._window.split_section_button
        button.setChecked(active)
        if active:
            button.setStyleSheet("background-color: #3fb5b5; color: white;")
        else:
            button.setStyleSheet(self._split_default_style)
        self._window.update_mouse_usage_text()

    def _on_move_section_mode_changed(self, active: bool) -> None:
        button = self._window.move_section_button
        button.setChecked(active)
        if active:
            button.setStyleSheet("background-color: #4caf50; color: white;")
        else:
            button.setStyleSheet(self._move_section_default_style)
        self._window.update_mouse_usage_text()

    def _on_scale_changed(self, scale: float) -> None:
        _ = scale
        self._window._refresh_query_track_info_label()

    def _on_preview_drag_state_changed(self, dragging: bool) -> None:
        if not dragging:
            self._refresh_elevation_profile()
            self._window.update_selection_sidebar(self._active_selection)

    def _open_background_file_dialog(self) -> None:
        self._background_ui_coordinator.open_background_file_dialog()

    def _show_background_settings_dialog(self) -> None:
        self._background_ui_coordinator.show_background_settings_dialog()

    def _launch_background_calibrator(self) -> None:
        self._background_ui_coordinator.launch_background_calibrator()

    def _launch_tso_generator(self) -> None:
        command: list[str]
        if getattr(sys, "frozen", False):
            command = [sys.executable, "--launch-tso-generator"]
        else:
            script_path = Path(__file__).resolve().parents[2] / "tso_generator" / "tso_generator.py"
            if not script_path.is_file():
                QtWidgets.QMessageBox.warning(
                    self._window,
                    "Open TSO Generator",
                    f"Could not find tso_generator.py at:\n{script_path}",
                )
                return
            command = [sys.executable, str(script_path)]

        try:
            subprocess.Popen(command)
        except OSError as exc:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Open TSO Generator",
                f"Failed to open TSO Generator:\n{exc}",
            )
            return

        self._window.show_status_message("Opened TSO Generator")

    def _apply_calibrator_values(self, data: dict) -> None:
        self._background_ui_coordinator.apply_calibrator_values(data)

    def _start_new_track(self, *, confirm: bool = True) -> None:
        self._document_controller.start_new_track(confirm=confirm)

    def _reset_altitude_range_for_track(self) -> None:
        sgfile = self._window.preview.sgfile
        if sgfile is None:
            return

        altitudes: list[int] = []
        for section in sgfile.sects:
            section_altitudes = list(getattr(section, "alt", []) or [])
            altitudes.extend(section_altitudes)

        if not altitudes:
            return

        min_altitude = feet_from_500ths(min(altitudes))
        max_altitude = feet_from_500ths(max(altitudes))
        self._reset_altitude_range(min_altitude, max_altitude)

    def _reset_altitude_range(self, min_altitude: float, max_altitude: float) -> None:
        min_spin = self._window.altitude_min_spin
        max_spin = self._window.altitude_max_spin
        min_value = min(min_altitude, max_altitude)
        max_value = max(min_altitude, max_altitude)
        if math.isclose(min_value, max_value):
            max_value = min_value + 0.1

        min_spin.blockSignals(True)
        max_spin.blockSignals(True)
        min_spin.setValue(min_value)
        max_spin.setValue(max_value)
        min_spin.blockSignals(False)
        max_spin.blockSignals(False)
        self._elevation_ui_coordinator.on_altitude_range_changed()



    def _save_to_path(self, path: Path) -> None:
        self._file_menu_coordinator.save_to_path(path)

    def _export_current_sg_to_csv(self) -> None:
        sg_path = self._document_controller.ensure_saved_sg()
        if sg_path is None:
            return
        self._document_controller.convert_sg_to_csv(sg_path)

    def _recalculate_elevations(self) -> None:
        preview = self._window.preview
        if preview.recalculate_elevations():
            message = (
                preview.last_elevation_recalc_message()
                or "Recalculated elevation profile."
            )
            self._window.show_status_message(message)
            self._refresh_elevation_profile()
            return

        reason = preview.last_elevation_recalc_message()
        if reason:
            self._window.show_status_message(
                f"Unable to recalculate elevations: {reason}"
            )
            return

        self._window.show_status_message(
            "Unable to recalculate elevations for this track."
        )


    def _convert_sg_to_csv(self, sg_path: Path) -> None:
        self._document_controller.convert_sg_to_csv(sg_path)

    def _convert_sg_to_trk(self) -> None:
        self._file_menu_coordinator.convert_sg_to_trk()

    def _ensure_saved_sg(self) -> Path | None:
        return self._file_menu_coordinator.ensure_saved_sg()

    def _start_new_straight(self) -> None:
        self._sections_controller.start_new_straight()

    def _start_new_curve(self) -> None:
        self._sections_controller.start_new_curve()

    def _toggle_delete_section_mode(self, checked: bool) -> None:
        self._sections_controller.toggle_delete_section_mode(checked)

    def _handle_delete_shortcut(self) -> None:
        if not self._window.delete_section_button.isEnabled():
            return
        if self._should_skip_delete_shortcut_for_focus():
            return

        selected_index = self._window.preview.selection_manager.selected_section_index
        if selected_index is None:
            self._window.show_status_message("Select a section to delete.")
            return

        response = QtWidgets.QMessageBox.question(
            self._window,
            "Delete Section",
            f"Delete selected section #{selected_index}?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if response != QtWidgets.QMessageBox.Yes:
            return

        self._window.preview.delete_selected_section()

    def _should_skip_delete_shortcut_for_focus(self) -> bool:
        focused = QtWidgets.QApplication.focusWidget()
        if focused is None:
            return False

        editable_types = (
            QtWidgets.QLineEdit,
            QtWidgets.QTextEdit,
            QtWidgets.QPlainTextEdit,
            QtWidgets.QAbstractSpinBox,
        )
        if isinstance(focused, editable_types):
            return True

        if isinstance(focused, QtWidgets.QAbstractItemView):
            return focused.state() == QtWidgets.QAbstractItemView.EditingState

        return False

    def _toggle_new_straight_mode(self, checked: bool) -> None:
        self._sections_controller.toggle_new_straight_mode(checked)

    def _toggle_new_curve_mode(self, checked: bool) -> None:
        self._sections_controller.toggle_new_curve_mode(checked)

    def _toggle_split_section_mode(self, checked: bool) -> None:
        self._sections_controller.toggle_split_section_mode(checked)

    def _toggle_move_section_mode(self, checked: bool) -> None:
        self._sections_controller.toggle_move_section_mode(checked)

    def _refresh_recent_menu(self) -> None:
        self._file_menu_coordinator.refresh_recent_menu()

    def _on_sections_changed(self) -> None:
        self._sections_controller.on_sections_changed()
        self._sync_section_editing_menu_actions()
        self._sync_after_section_mutation()

    def _sync_section_editing_menu_actions(self) -> None:
        self._previous_section_action.setEnabled(self._window.prev_button.isEnabled())
        self._next_section_action.setEnabled(self._window.next_button.isEnabled())
        self._new_straight_mode_action.setEnabled(self._window.new_straight_button.isEnabled())
        self._new_curve_mode_action.setEnabled(self._window.new_curve_button.isEnabled())
        self._split_section_mode_action.setEnabled(self._window.split_section_button.isEnabled())
        self._move_section_mode_action.setEnabled(self._window.move_section_button.isEnabled())
        self._delete_section_mode_action.setEnabled(self._window.delete_section_button.isEnabled())
        self._set_start_finish_action.setEnabled(self._window.set_start_finish_button.isEnabled())

    def _update_section_table(self) -> None:
        self._section_editing_coordinator.update_section_table()

    def _apply_section_table_edits(self, sections: list[SectionPreview]) -> None:
        self._section_editing_coordinator.apply_section_table_edits(sections)

    def _update_heading_table(self) -> None:
        self._section_editing_coordinator.update_heading_table()

    def _update_xsect_table(self) -> None:
        self._section_editing_coordinator.update_xsect_table()

    def _apply_xsect_table_edits(self, entries: list[XsectEntry]) -> None:
        self._section_editing_coordinator.apply_xsect_table_edits(entries)

    def _scale_track(self) -> None:
        self._sections_controller.scale_track()

    def _open_rotate_track_dialog(self) -> None:
        self._sections_controller.open_rotate_track_dialog()

    def _apply_track_rotation_preview(self, base_sections: list[SectionPreview], angle_degrees: float) -> None:
        self._sections_controller.apply_track_rotation_preview(base_sections, angle_degrees)

    def _open_generate_fsects_dialog(self) -> None:
        self._sections_controller.open_generate_fsects_dialog()

    def _reverse_track(self) -> None:
        self._sections_controller.reverse_track()

    @staticmethod
    def _build_generated_fsects(*, template: str, track_width: float, left_grass: float, right_grass: float, grass_surface_type: int, wall_surface_type: int, wall_width: float, fence_enabled: bool) -> list[PreviewFSection]:
        return build_generated_fsects(template=template, track_width=track_width, left_grass=left_grass, right_grass=right_grass, grass_surface_type=grass_surface_type, wall_surface_type=wall_surface_type, wall_width=wall_width, fence_enabled=fence_enabled)

    def _populate_xsect_choices(self, preferred_index: int | None = None) -> None:
        self._elevation_panel_controller.populate_xsect_choices(preferred_index=preferred_index)

    def _refresh_elevation_profile(self) -> None:
        self._elevation_panel_controller.refresh_elevation_profile()

    def _current_samples_per_section(self) -> int:
        return 10

    def _clear_background_state(self) -> None:
        self._background_ui_coordinator.clear_background_state()
#        self._calibrate_background_action.setEnabled(False)

    def _apply_saved_background(self, sg_path: Path | None = None) -> None:
        self._background_ui_coordinator.apply_saved_background(sg_path)

    def _persist_background_state(self) -> None:
        self._background_ui_coordinator.persist_background_state()

    def _update_track_length_display(self) -> None:
        sections, _ = self._window.preview.get_section_set()
        if not sections:
            self._window.update_track_length_label("Track Length: –")
            return

        metrics = self._runtime_api.track_metrics_intent(sections)
        if metrics.status_messages and metrics.status_messages[0] == "Track Length: Not a closed loop":
            self._window.update_track_length_label("Track Length: Not a closed loop")
            return

        if not metrics.status_messages:
            self._window.update_track_length_label("Track Length: Not a closed loop")
            return

        total_length = float(metrics.status_messages[0])

        length_value = self._window.format_length_with_secondary(total_length)
        self._window.update_track_length_label(
            f"Track Length: {length_value}"
        )

    def _on_selected_section_changed(self, selection: SectionSelection | None) -> None:
        self._active_selection = selection
        self._sync_after_selection_change()

    def _on_xsect_node_clicked(self, xsect_index: int) -> None:
        combo = self._window.xsect_combo
        if not combo.isEnabled():
            return
        target_index = combo.findData(xsect_index)
        if target_index == -1:
            target_index = xsect_index
        combo.setCurrentIndex(target_index)

    def _update_copy_xsect_button(self) -> None:
        combo_enabled = self._window.xsect_combo.isEnabled()
        sections, _ = self._window.preview.get_section_set()
        can_generate = combo_enabled and bool(sections)
        self._window.copy_xsect_button.setEnabled(can_generate)
        self._window.generate_elevation_change_button.setEnabled(can_generate)
        self._generate_elevation_change_action.setEnabled(can_generate)

    def _update_copy_fsects_buttons(self) -> None:
        selection = self._active_selection
        sections, _ = self._window.preview.get_section_set()
        total_sections = len(sections)
        has_selection = selection is not None and total_sections > 0
        prev_enabled = False
        next_enabled = False
        if has_selection:
            prev_index = selection.previous_id
            next_index = selection.next_id
            prev_enabled = 0 <= prev_index < total_sections
            next_enabled = 0 <= next_index < total_sections
        self._window.copy_fsects_prev_button.setEnabled(prev_enabled)
        self._window.copy_fsects_next_button.setEnabled(next_enabled)
        self._copy_fsects_prev_action.setEnabled(prev_enabled)
        self._copy_fsects_next_action.setEnabled(next_enabled)

    def _update_fsect_edit_buttons(self) -> None:
        selection = self._active_selection
        if selection is None:
            self._window.add_fsect_button.setEnabled(False)
            self._window.delete_fsect_button.setEnabled(False)
            self._window.move_fsect_up_button.setEnabled(False)
            self._window.move_fsect_down_button.setEnabled(False)
            self._add_fsect_action.setEnabled(False)
            self._delete_fsect_action.setEnabled(False)
            self._move_fsect_up_action.setEnabled(False)
            self._move_fsect_down_action.setEnabled(False)
            self._window.swap_fsect_types_button.setEnabled(False)
            self._swap_fsect_types_action.setEnabled(False)
            return
        self._window.add_fsect_button.setEnabled(True)
        self._add_fsect_action.setEnabled(True)
        self._window.swap_fsect_types_button.setEnabled(True)
        self._swap_fsect_types_action.setEnabled(True)
        fsects = self._window.preview.get_section_fsects(selection.index)
        row_index = self._window.selected_fsect_index()
        delete_enabled = bool(fsects)
        move_up_enabled = bool(fsects) and row_index > 0
        move_down_enabled = bool(fsects) and 0 <= row_index < len(fsects) - 1
        self._window.delete_fsect_button.setEnabled(delete_enabled)
        self._delete_fsect_action.setEnabled(delete_enabled)
        self._window.move_fsect_up_button.setEnabled(move_up_enabled)
        self._window.move_fsect_down_button.setEnabled(move_down_enabled)
        self._move_fsect_up_action.setEnabled(move_up_enabled)
        self._move_fsect_down_action.setEnabled(move_down_enabled)

    def _current_xsect_index(self) -> int | None:
        combo = self._window.xsect_combo
        if not combo.isEnabled():
            return None
        current_index = combo.currentData()
        if current_index is None:
            current_index = combo.currentIndex()
        try:
            return int(current_index)
        except (TypeError, ValueError):
            return None

    def _refresh_elevation_inputs(self) -> None:
        self._elevation_panel_controller.refresh_elevation_inputs()

    def _on_altitude_slider_changed(self, value: int) -> None:
        self._elevation_panel_controller.on_altitude_slider_changed(value)

    def _on_altitude_slider_released(self) -> None:
        self._elevation_panel_controller.on_altitude_slider_released()

    def _open_altitude_range_dialog(self) -> None:
        self._elevation_panel_controller.open_altitude_range_dialog()

    def _open_grade_range_dialog(self) -> None:
        self._elevation_panel_controller.open_grade_range_dialog()

    def _open_raise_lower_elevations_dialog(self) -> None:
        self._elevation_panel_controller.open_raise_lower_elevations_dialog()

    def _open_flatten_all_elevations_and_grade_dialog(self) -> None:
        if self._elevation_panel_controller.open_flatten_all_elevations_and_grade_dialog():
            self._reset_altitude_range_for_track()
            self._refresh_elevation_profile()
            self._refresh_xsect_elevation_panel()
            self._refresh_xsect_elevation_table()

    def _open_generate_elevation_change_dialog(self) -> None:
        xsect_index = self._current_xsect_index()
        if xsect_index is None:
            QtWidgets.QMessageBox.information(
                self._window,
                "Generate elevation change",
                "Select an x-section before generating an elevation change.",
            )
            return
        self._window.show_generate_elevation_change_dialog(xsect_index=xsect_index)

    def _on_generate_elevation_change_applied(self) -> None:
        self._reset_altitude_range_for_track()
        self._refresh_elevation_profile()
        self._refresh_xsect_elevation_panel()
        self._refresh_xsect_elevation_table()

    def _apply_altitude_edit(self, live: bool = False, slider_value: int | None = None) -> None:
        if not self._is_elevation_tab_active():
            return
        selection = self._active_selection
        xsect_index = self._current_xsect_index()
        if selection is None or xsect_index is None:
            return

        altitude_slider_value = (
            self._window.altitude_slider.value() if slider_value is None else slider_value
        )
        altitude_feet = feet_from_slider_units(altitude_slider_value)
        altitude = feet_to_500ths(altitude_feet)
        if self._window.preview.set_section_xsect_altitude(
            selection.index, xsect_index, altitude, validate=False
        ):
            if live:
                self._sync_after_xsect_value_change_lightweight()
            else:
                self._sync_after_xsect_value_change()

    def _apply_grade_edit(self, live: bool = False, grade_value: int | None = None) -> None:
        if not self._is_elevation_tab_active():
            return
        selection = self._active_selection
        xsect_index = self._current_xsect_index()
        if selection is None or xsect_index is None:
            return

        grade = self._window.grade_spin.value() if grade_value is None else grade_value
        if self._window.preview.set_section_xsect_grade(
            selection.index, xsect_index, grade, validate=False
        ):
            if live:
                self._sync_after_xsect_value_change_lightweight()
            else:
                self._sync_after_xsect_value_change()

    def _add_fsect_below_selected(self) -> None:
        self._sections_controller.add_fsect_below_selected()

    def _delete_selected_fsect(self) -> None:
        self._sections_controller.delete_selected_fsect()

    def _move_selected_fsect_up(self) -> None:
        self._sections_controller.move_selected_fsect_up()

    def _move_selected_fsect_down(self) -> None:
        self._sections_controller.move_selected_fsect_down()

    def _on_grade_slider_changed(self, value: int) -> None:
        self._elevation_panel_controller.on_grade_slider_changed(value)

    def _on_grade_edit_finished(self) -> None:
        self._elevation_panel_controller.on_grade_edit_finished()

    def _is_elevation_tab_active(self) -> bool:
        current_index = self._window.right_sidebar_tabs.currentIndex()
        if current_index < 0:
            return False
        tab_name = self._window.active_sidebar_tab_name()
        return tab_name == self._ELEVATION_TAB_BASE_LABEL

    def _refresh_xsect_elevation_panel(self) -> None:
        self._elevation_panel_controller.refresh_xsect_elevation_panel()

    def _refresh_xsect_elevation_table(self) -> None:
        self._elevation_panel_controller.refresh_xsect_elevation_table()

    def _run_sg_integrity_checks(self) -> None:
        sections, _ = self._window.preview.get_section_set()
        if not sections:
            QtWidgets.QMessageBox.information(
                self._window,
                "SG Integrity Checks",
                "There are no sections available to analyze.",
            )
            return

        fsects_by_section = [
            self._window.preview.get_section_fsects(index)
            for index in range(len(sections))
        ]

        progress_dialog = QtWidgets.QProgressDialog(
            "Running SG integrity checks...",
            "Cancel",
            0,
            100,
            self._window,
        )
        progress_dialog.setWindowTitle("SG Integrity Checks")
        progress_dialog.setWindowModality(QtCore.Qt.WindowModal)
        progress_dialog.setMinimumDuration(0)
        progress_dialog.setAutoClose(False)
        progress_dialog.setAutoReset(False)
        progress_dialog.setValue(0)
        progress_dialog.show()

        canceled = False

        def _on_progress(progress: IntegrityProgress) -> None:
            nonlocal canceled
            total = max(progress.total, 1)
            value = int((progress.current / total) * 100)
            progress_dialog.setLabelText(progress.message)
            progress_dialog.setValue(max(0, min(100, value)))
            QtWidgets.QApplication.processEvents()
            if progress_dialog.wasCanceled():
                canceled = True
                raise RuntimeError("SG integrity checks canceled by user")

        try:
            report = build_integrity_report(
                sections,
                fsects_by_section,
                measurement_unit=str(self._window.measurement_units_combo.currentData()),
                on_progress=_on_progress,
            )
        except RuntimeError as exc:
            if canceled:
                QtWidgets.QMessageBox.information(
                    self._window,
                    "SG Integrity Checks",
                    "Integrity checks were canceled.",
                )
                return
            raise exc
        finally:
            progress_dialog.close()

        if self._integrity_report_window is None:
            self._integrity_report_window = QtWidgets.QDialog(self._window)
            self._integrity_report_window.setWindowTitle("SG Integrity Checks")
            self._integrity_report_window.setWindowModality(QtCore.Qt.NonModal)
            self._integrity_report_window.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
            self._integrity_report_window.resize(920, 640)

            layout = QtWidgets.QVBoxLayout(self._integrity_report_window)
            text_edit = QtWidgets.QPlainTextEdit(self._integrity_report_window)
            text_edit.setObjectName("integrityReportText")
            text_edit.setReadOnly(True)
            text_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
            layout.addWidget(text_edit)

            copy_button = QtWidgets.QPushButton("Copy Report", self._integrity_report_window)
            copy_button.clicked.connect(text_edit.selectAll)
            copy_button.clicked.connect(text_edit.copy)

            close_button = QtWidgets.QPushButton("Close", self._integrity_report_window)
            close_button.clicked.connect(self._integrity_report_window.close)
            self._integrity_report_window.finished.connect(lambda _result: self._on_integrity_report_window_hidden())
            button_row = QtWidgets.QHBoxLayout()
            button_row.addStretch(1)
            button_row.addWidget(copy_button)
            button_row.addWidget(close_button)
            layout.addLayout(button_row)

        text_edit = self._integrity_report_window.findChild(QtWidgets.QPlainTextEdit, "integrityReportText")
        if text_edit is not None:
            text_edit.setPlainText(format_integrity_memo(report))
        self._window.preview.set_integrity_boundary_violation_points(
            (
                *report.boundary_ownership_violation_points,
                *report.centerline_spacing_violation_points,
            )
        )
        self._integrity_report_window.show()
        self._integrity_report_window.raise_()
        self._integrity_report_window.activateWindow()


    def _on_integrity_report_window_hidden(self) -> None:
        self._window.preview.clear_integrity_boundary_violation_points()

    def _sync_after_section_mutation(self) -> None:
        """Sync UI after section list/data changes in a stable update order."""
        self._window.invalidate_adjusted_section_range_cache()
        self._last_tsd_adjusted_to_sg_ranges = ([], [])
        if not self._window.preview.is_interaction_dragging:
            self._refresh_elevation_profile()
            self._window.update_selection_sidebar(self._active_selection)
        self._refresh_elevation_inputs()
        self._update_track_length_display()
        self._update_copy_xsect_button()
        self._update_copy_fsects_buttons()
        self._update_fsect_edit_buttons()
        sections, _ = self._window.preview.get_section_set()
        self._window.tso_visibility_sidebar.set_current_track_section_count(len(sections))
        self._run_integrity_checks_action.setEnabled(bool(sections))

    def _sync_after_xsect_value_change(self) -> None:
        """Sync profile and x-section views after altitude/grade data changes."""
        self._window.invalidate_adjusted_section_range_cache()
        self._last_tsd_adjusted_to_sg_ranges = ([], [])
        self._refresh_elevation_profile()
        self._refresh_xsect_elevation_panel()
        self._refresh_xsect_elevation_table()

    def _sync_after_xsect_value_change_lightweight(self) -> None:
        """Keep live slider edits responsive while still updating elevation graphs live."""
        self._window.invalidate_adjusted_section_range_cache()
        self._last_tsd_adjusted_to_sg_ranges = ([], [])
        self._elevation_panel_controller.refresh_elevation_profile(refresh_table=False)
        if hasattr(self._window.preview, "request_repaint"):
            self._window.preview.request_repaint_throttled(min_interval_ms=33)

    def _sync_after_selection_change(self) -> None:
        """Sync selection-bound controls and panels after selected section changes."""
        self._window.update_selection_sidebar(self._active_selection)
        self._refresh_elevation_inputs()
        self._refresh_xsect_elevation_panel()
        self._update_copy_fsects_buttons()
        self._update_fsect_edit_buttons()

    def _sync_after_measurement_unit_change(self) -> None:
        """Sync unit-sensitive controls and displays after unit selection changes."""
        selected_xsect = self._current_xsect_index()
        self._populate_xsect_choices(preferred_index=selected_xsect)
        self._refresh_elevation_inputs()
        self._window.update_xsect_table_headers()
        self._refresh_xsect_elevation_table()
        self._section_editing_coordinator.update_xsect_table()
        self._refresh_xsect_elevation_panel()
        self._update_track_length_display()
        self._refresh_tso_table()
        self._window.update_selection_sidebar(self._active_selection)
        if self._tso_attributes_dialog is not None:
            self._tso_attributes_dialog.set_measurement_unit(self._window.current_measurement_unit())

    def _on_measurement_units_changed(self) -> None:
        self._elevation_ui_coordinator.on_measurement_units_changed()
        self._sync_after_measurement_unit_change()

    def _on_xsect_table_cell_changed(self, row_index: int, column_index: int) -> None:
        self._elevation_panel_controller.on_xsect_table_cell_changed(row_index, column_index)

    def _on_xsect_table_selection_changed(self) -> None:
        if self._window.is_updating_xsect_table:
            return
        row_index = self._window.xsect_elevation_table.currentRow()
        if row_index < 0:
            return
        self._on_xsect_node_clicked(row_index)


def _install_feature_controller_wrapper_methods() -> None:
    """Expose extracted feature methods on SGViewerController during migration.

    Historically callers reached feature behavior directly through
    SGViewerController.  The feature implementations now live on smaller
    controller objects, but tests and third-party extensions still need a
    stable migration window.  Install thin wrappers for extracted methods that
    are not already implemented directly on SGViewerController.
    """

    feature_controllers = (
        ("_tsd_controller", TsdController),
        ("_mrk_controller", MrkController),
        ("_track3d_tools_controller", Track3DToolsController),
        ("_trackside_objects_controller", TracksideObjectsController),
    )

    def _make_wrapper(controller_attr: str, method_name: str):
        def _wrapper(self, *args, **kwargs):
            return getattr(getattr(self, controller_attr), method_name)(*args, **kwargs)

        _wrapper.__name__ = method_name
        _wrapper.__qualname__ = f"SGViewerController.{method_name}"
        _wrapper.__doc__ = f"Compatibility wrapper for {controller_attr}.{method_name}."
        return _wrapper

    for controller_attr, controller_type in feature_controllers:
        for method_name, method in controller_type.__dict__.items():
            if not method_name.startswith("_") or method_name.startswith("__"):
                continue
            if isinstance(method, property) or not callable(method):
                continue
            if method_name in SGViewerController.__dict__:
                continue
            setattr(
                SGViewerController,
                method_name,
                _make_wrapper(controller_attr, method_name),
            )


_install_feature_controller_wrapper_methods()
