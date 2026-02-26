from __future__ import annotations

import json
import logging
import math
from time import perf_counter
from bisect import bisect_left
from pathlib import Path
from dataclasses import dataclass

from PyQt5 import QtCore, QtGui, QtWidgets

from sg_viewer.model.history import FileHistory
from sg_viewer.model.preview_fsection import PreviewFSection
from sg_viewer.services.fsect_generation_service import build_generated_fsects
from sg_viewer.services.mrk_io import (
    MarkBoundaryEntry,
    MarkFile,
    MarkTrackPosition,
    MarkUvRect,
    serialize_mrk,
)
from sg_viewer.services.sg_integrity_checks import IntegrityProgress, build_integrity_report
from sg_viewer.services.tsd_io import (
    TrackSurfaceDetailFile,
    TrackSurfaceDetailLine,
    parse_tsd,
    serialize_tsd,
)
from sg_viewer.model.sg_model import Point, SectionPreview
from sg_viewer.model.selection import SectionSelection
from sg_viewer.ui.altitude_units import (
    feet_from_500ths,
    feet_from_slider_units,
    feet_to_500ths,
    units_to_500ths,
)
from sg_viewer.ui.heading_table_dialog import HeadingTableWindow
from sg_viewer.ui.section_table_dialog import SectionTableWindow
from sg_viewer.ui.xsect_table_dialog import XsectEntry, XsectTableWindow
from sg_viewer.services import sg_rendering
from sg_viewer.ui.about import show_about_dialog
from sg_viewer.ui.bg_calibrator_minimal import Calibrator
from sg_viewer.ui.color_utils import parse_hex_color
from sg_viewer.ui.palette_dialog import PaletteColorDialog
from sg_viewer.ui.mrk_textures_dialog import (
    MrkTextureDefinition,
    MrkTexturePatternDialog,
    MrkTexturesDialog,
)
from sg_viewer.ui.models.tsd_lines_model import TsdLinesTableModel
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
)
from sg_viewer.model.track_model import TrackModel
from sg_viewer.runtime.viewer_runtime_api import ViewerRuntimeApi

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadedTsdFile:
    name: str
    lines: tuple[TrackSurfaceDetailLine, ...]


class SGViewerController:
    _TSD_SHOW_ALL_LABEL = "Show all TSDs"

    """Coordinates actions, menus, and dialogs for the SG viewer window."""

    def __init__(self, window: QtWidgets.QMainWindow) -> None:
        self._window = window
        self._section_table_window: SectionTableWindow | None = None
        self._heading_table_window: HeadingTableWindow | None = None
        self._xsect_table_window: XsectTableWindow | None = None
        self._integrity_report_window: QtWidgets.QDialog | None = None
        self._current_path: Path | None = None
        self._history = FileHistory()
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
        self._mrk_texture_definitions: tuple[MrkTextureDefinition, ...] = ()
        self._mrk_is_dirty = False
        self._tsd_is_dirty = False
        self._elevation_grade_is_dirty = False
        self._fsects_is_dirty = False
        self._sunny_palette: list[QtGui.QColor] | None = None
        self._sunny_palette_path: Path | None = None
        self._palette_colors_dialog: PaletteColorDialog | None = None
        self._loaded_tsd_files: list[LoadedTsdFile] = []
        self._active_tsd_file_index: int | None = None
        self._suspend_tsd_preview_refresh = False
        self._debug_tsd_perf = False
        self._last_tsd_preview_lines: list[TrackSurfaceDetailLine] = []
        self._last_tsd_adjusted_to_sg_ranges: tuple[list[tuple[float, float, float, float]], list[float]] = ([], [])
        self._tsd_lines_model = TsdLinesTableModel(self._window)
        self._window.tsd_lines_table.setModel(self._tsd_lines_model)
        self._tsd_preview_refresh_timer = QtCore.QTimer(self._window)
        self._tsd_preview_refresh_timer.setSingleShot(True)
        self._tsd_preview_refresh_timer.setInterval(60)
        self._tsd_preview_refresh_timer.timeout.connect(self._refresh_tsd_preview_lines)

        self._create_actions()
        self._create_menus()
        self._connect_signals()
        self._on_track_opacity_changed(self._window.track_opacity_slider.value())
        self._on_background_brightness_changed(
            self._window.background_brightness_slider.value()
        )
        self._on_mrk_wall_height_changed(self._window.pitwall_wall_height_spin.value())
        self._on_mrk_armco_height_changed(self._window.pitwall_armco_height_spin.value())
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
            "Click New Straight to begin drawing or File → Open SG."
        )
        self._update_track_length_display()

    def load_sg(self, path: Path) -> None:
        self._document_controller.load_sg(path)


    def _create_actions(self) -> None:
        self._new_action = QtWidgets.QAction("New", self._window)
        self._new_action.setShortcut("Ctrl+N")
        self._new_action.triggered.connect(self._start_new_track)


        self._open_action = QtWidgets.QAction("Open SG…", self._window)
        self._open_action.setShortcut("Ctrl+O")
        self._open_action.triggered.connect(self._file_menu_coordinator.open_file_dialog)

        self._load_sunny_palette_action = QtWidgets.QAction("Load SUNNY.PCX…", self._window)
        self._load_sunny_palette_action.triggered.connect(self._load_sunny_palette_dialog)

        self._import_trk_action = QtWidgets.QAction("Import TRK…", self._window)
        self._import_trk_action.triggered.connect(self._file_menu_coordinator.import_trk_file_dialog)

        self._import_trk_from_dat_action = QtWidgets.QAction(
            "Import TRK from DAT…",
            self._window,
        )
        self._import_trk_from_dat_action.triggered.connect(self._file_menu_coordinator.import_trk_from_dat_file_dialog)

        self._open_recent_menu = QtWidgets.QMenu("Open Recent", self._window)

        self._save_current_action = QtWidgets.QAction("Save", self._window)
        self._save_current_action.setShortcut("Ctrl+S")
        self._save_current_action.setEnabled(False)
        self._save_current_action.triggered.connect(self._file_menu_coordinator.save_current_file)

        self._save_action = QtWidgets.QAction("Save SG As…", self._window)
        self._save_action.setShortcut("Ctrl+Shift+S")
        self._save_action.setEnabled(True)
        self._save_action.triggered.connect(self._file_menu_coordinator.save_file_dialog)

        self._export_csv_on_save_action = QtWidgets.QAction("Export CSVs on Save", self._window)
        self._export_csv_on_save_action.setCheckable(True)
        self._export_csv_on_save_action.setChecked(True)
        self._export_csv_on_save_action.triggered.connect(self._toggle_export_csv_on_save)

        self._scale_track_action = QtWidgets.QAction(
            "Scale Track to Length…",
            self._window,
        )
        self._scale_track_action.setEnabled(False)
        self._scale_track_action.triggered.connect(self._scale_track)

        self._rotate_track_action = QtWidgets.QAction(
            "Rotate Track…",
            self._window,
        )
        self._rotate_track_action.setEnabled(False)
        self._rotate_track_action.triggered.connect(self._open_rotate_track_dialog)

        self._reverse_track_action = QtWidgets.QAction(
            "Reverse Track",
            self._window,
        )
        self._reverse_track_action.setEnabled(False)
        self._reverse_track_action.triggered.connect(self._reverse_track)

        self._convert_trk_action = QtWidgets.QAction(
            "Export SG to TRK…",
            self._window,
        )
        self._convert_trk_action.triggered.connect(self._convert_sg_to_trk)

        self._generate_fsects_action = QtWidgets.QAction(
            "Generate Fsects…",
            self._window,
        )
        self._generate_fsects_action.triggered.connect(self._open_generate_fsects_dialog)

        self._raise_lower_elevations_action = QtWidgets.QAction(
            "Raise/lower all elevations…",
            self._window,
        )
        self._raise_lower_elevations_action.setEnabled(False)
        self._raise_lower_elevations_action.triggered.connect(
            self._open_raise_lower_elevations_dialog
        )

        self._flatten_all_elevations_and_grade_action = QtWidgets.QAction(
            "Flatten all elevations + grade…",
            self._window,
        )
        self._flatten_all_elevations_and_grade_action.setEnabled(False)
        self._flatten_all_elevations_and_grade_action.triggered.connect(
            self._open_flatten_all_elevations_and_grade_dialog
        )

        self._generate_elevation_change_action = QtWidgets.QAction(
            "Generate elevation change…",
            self._window,
        )
        self._generate_elevation_change_action.setEnabled(False)
        self._generate_elevation_change_action.triggered.connect(
            self._open_generate_elevation_change_dialog
        )

        self._generate_pitwall_action = QtWidgets.QAction(
            "Generate pitwall.txt…",
            self._window,
        )
        self._generate_pitwall_action.setEnabled(False)
        self._generate_pitwall_action.triggered.connect(self._generate_pitwall_txt)

        self._open_background_action = QtWidgets.QAction(
            "Load Background Image…", self._window
        )
        self._open_background_action.setShortcut("Ctrl+B")
        self._open_background_action.triggered.connect(
            self._open_background_file_dialog
        )

        self._background_settings_action = QtWidgets.QAction(
            "Background Image Settings…", self._window
        )
        self._background_settings_action.setEnabled(False)
        self._background_settings_action.triggered.connect(
            self._show_background_settings_dialog
        )

        self._calibrate_background_action = QtWidgets.QAction(
            "Open Background Calibrator", self._window
        )
        self._calibrate_background_action.triggered.connect(
            self._launch_background_calibrator
        )

        self._show_radii_action = QtWidgets.QAction("Show Radii", self._window)
        self._show_radii_action.setCheckable(True)
        self._show_radii_action.setChecked(self._window.radii_button.isChecked())

        self._show_axes_action = QtWidgets.QAction("Show Axes", self._window)
        self._show_axes_action.setCheckable(True)
        self._show_axes_action.setChecked(self._window.axes_button.isChecked())

        self._show_background_image_action = QtWidgets.QAction(
            "Show Background Image", self._window
        )
        self._show_background_image_action.setCheckable(True)
        self._show_background_image_action.setChecked(
            self._window.background_image_checkbox.isChecked()
        )

        self._view_options_action = QtWidgets.QAction("View Options…", self._window)
        self._view_options_action.triggered.connect(self._window.show_view_options_dialog)

        self._section_table_action = QtWidgets.QAction("Section Table", self._window)
        self._section_table_action.setEnabled(False)
        self._section_table_action.triggered.connect(self._section_editing_coordinator.show_section_table)

        self._heading_table_action = QtWidgets.QAction("Heading Table", self._window)
        self._heading_table_action.setEnabled(False)
        self._heading_table_action.triggered.connect(self._section_editing_coordinator.show_heading_table)

        self._xsect_table_action = QtWidgets.QAction("X-Section Table", self._window)
        self._xsect_table_action.setEnabled(False)
        self._xsect_table_action.triggered.connect(self._section_editing_coordinator.show_xsect_table)

        self._mrk_add_entry_action = QtWidgets.QAction("Add MRK Entry", self._window)
        self._mrk_add_entry_action.setEnabled(self._window.mrk_add_entry_button.isEnabled())

        self._mrk_delete_entry_action = QtWidgets.QAction("Delete MRK Entry", self._window)
        self._mrk_delete_entry_action.setEnabled(self._window.mrk_delete_entry_button.isEnabled())

        self._mrk_textures_action = QtWidgets.QAction("MRK Textures…", self._window)
        self._mrk_textures_action.setEnabled(self._window.mrk_textures_button.isEnabled())

        self._mrk_generate_file_action = QtWidgets.QAction("Generate .MRK file…", self._window)
        self._mrk_generate_file_action.setEnabled(self._window.mrk_generate_file_button.isEnabled())

        self._mrk_save_entries_action = QtWidgets.QAction("Save MRK entries…", self._window)
        self._mrk_save_entries_action.setEnabled(self._window.mrk_save_button.isEnabled())

        self._mrk_load_entries_action = QtWidgets.QAction("Load MRK entries…", self._window)
        self._mrk_load_entries_action.setEnabled(self._window.mrk_load_button.isEnabled())

        self._previous_section_action = QtWidgets.QAction("Previous Section", self._window)
        self._previous_section_action.setShortcut("Ctrl+PgUp")

        self._next_section_action = QtWidgets.QAction("Next Section", self._window)
        self._next_section_action.setShortcut("Ctrl+PgDown")

        self._new_straight_mode_action = QtWidgets.QAction("New Straight", self._window)
        self._new_straight_mode_action.setShortcut("Ctrl+Alt+S")
        self._new_straight_mode_action.setCheckable(True)
        self._new_straight_mode_action.setChecked(self._window.new_straight_button.isChecked())
        self._previous_section_action.setEnabled(self._window.prev_button.isEnabled())
        self._next_section_action.setEnabled(self._window.next_button.isEnabled())
        self._new_straight_mode_action.setEnabled(self._window.new_straight_button.isEnabled())

        self._new_curve_mode_action = QtWidgets.QAction("New Curve", self._window)
        self._new_curve_mode_action.setShortcut("Ctrl+Alt+C")
        self._new_curve_mode_action.setCheckable(True)
        self._new_curve_mode_action.setChecked(self._window.new_curve_button.isChecked())
        self._new_curve_mode_action.setEnabled(self._window.new_curve_button.isEnabled())

        self._split_section_mode_action = QtWidgets.QAction("Split Section", self._window)
        self._split_section_mode_action.setCheckable(True)
        self._split_section_mode_action.setChecked(self._window.split_section_button.isChecked())
        self._split_section_mode_action.setEnabled(self._window.split_section_button.isEnabled())

        self._move_section_mode_action = QtWidgets.QAction("Move Section", self._window)
        self._move_section_mode_action.setShortcut("Ctrl+Alt+M")
        self._move_section_mode_action.setCheckable(True)
        self._move_section_mode_action.setChecked(self._window.move_section_button.isChecked())
        self._move_section_mode_action.setEnabled(self._window.move_section_button.isEnabled())

        self._delete_section_mode_action = QtWidgets.QAction("Delete Section", self._window)
        self._delete_section_mode_action.setShortcut("Ctrl+Alt+D")
        self._delete_section_mode_action.setCheckable(True)
        self._delete_section_mode_action.setChecked(self._window.delete_section_button.isChecked())
        self._delete_section_mode_action.setEnabled(self._window.delete_section_button.isEnabled())

        self._set_start_finish_action = QtWidgets.QAction("Set Start/Finish", self._window)
        self._set_start_finish_action.setEnabled(self._window.set_start_finish_button.isEnabled())

        self._copy_fsects_prev_action = QtWidgets.QAction(
            "Copy Fsects to Previous Section",
            self._window,
        )
        self._copy_fsects_prev_action.setEnabled(
            self._window.copy_fsects_prev_button.isEnabled()
        )

        self._copy_fsects_next_action = QtWidgets.QAction(
            "Copy Fsects to Next Section",
            self._window,
        )
        self._copy_fsects_next_action.setEnabled(
            self._window.copy_fsects_next_button.isEnabled()
        )

        self._add_fsect_action = QtWidgets.QAction("Add Fsect", self._window)
        self._add_fsect_action.setEnabled(self._window.add_fsect_button.isEnabled())

        self._delete_fsect_action = QtWidgets.QAction("Delete Fsect", self._window)
        self._delete_fsect_action.setEnabled(self._window.delete_fsect_button.isEnabled())

        self._run_integrity_checks_action = QtWidgets.QAction("Run SG Integrity Checks", self._window)
        self._run_integrity_checks_action.setEnabled(False)
        self._run_integrity_checks_action.triggered.connect(self._run_sg_integrity_checks)

        self._show_palette_colors_action = QtWidgets.QAction("Show SUNNY Palette Colors…", self._window)
        self._show_palette_colors_action.triggered.connect(self._show_palette_colors_dialog)

        self._quit_action = QtWidgets.QAction("Quit", self._window)
        self._quit_action.setShortcut("Ctrl+Q")
        self._quit_action.triggered.connect(self._window.close)

        self._about_action = QtWidgets.QAction("About SG CREATE", self._window)
        self._about_action.triggered.connect(self._show_about_dialog)

    def _create_menus(self) -> None:
        file_menu = self._window.menuBar().addMenu("&File")
        file_menu.addAction(self._new_action)
        file_menu.addAction(self._open_action)
        file_menu.addAction(self._load_sunny_palette_action)
        file_menu.addMenu(self._open_recent_menu)
        import_menu = file_menu.addMenu("Import")
        import_menu.addAction(self._import_trk_action)
        import_menu.addAction(self._import_trk_from_dat_action)
        file_menu.addSeparator()
        file_menu.addAction(self._save_current_action)
        file_menu.addAction(self._save_action)
        file_menu.addAction(self._export_csv_on_save_action)
        file_menu.addAction(self._convert_trk_action)
        file_menu.addSeparator()
        file_menu.addAction(self._quit_action)

        view_menu = self._window.menuBar().addMenu("View")
        view_menu.addAction(self._open_background_action)
        view_menu.addAction(self._background_settings_action)
        view_menu.addAction(self._view_options_action)
        view_menu.addSeparator()
        view_menu.addAction(self._show_radii_action)
        view_menu.addAction(self._show_axes_action)
        view_menu.addAction(self._show_background_image_action)

        tools_menu = self._window.menuBar().addMenu("Tools")

        section_editing_menu = tools_menu.addMenu("Section Editing")
        section_editing_menu.addAction(self._previous_section_action)
        section_editing_menu.addAction(self._next_section_action)
        section_editing_menu.addSeparator()
        section_editing_menu.addAction(self._new_straight_mode_action)
        section_editing_menu.addAction(self._new_curve_mode_action)
        section_editing_menu.addAction(self._split_section_mode_action)
        section_editing_menu.addAction(self._move_section_mode_action)
        section_editing_menu.addAction(self._delete_section_mode_action)
        section_editing_menu.addSeparator()
        section_editing_menu.addAction(self._set_start_finish_action)

        transform_menu = tools_menu.addMenu("Transform")
        transform_menu.addAction(self._scale_track_action)
        transform_menu.addAction(self._rotate_track_action)
        transform_menu.addAction(self._reverse_track_action)

        generate_menu = tools_menu.addMenu("Generate")
        generate_menu.addAction(self._generate_fsects_action)
        generate_menu.addAction(self._generate_pitwall_action)
        generate_menu.addAction(self._generate_elevation_change_action)

        elevation_menu = tools_menu.addMenu("Elevation")
        elevation_menu.addAction(self._raise_lower_elevations_action)
        elevation_menu.addAction(self._flatten_all_elevations_and_grade_action)

        fsects_menu = tools_menu.addMenu("Fsects")
        fsects_menu.addAction(self._copy_fsects_prev_action)
        fsects_menu.addAction(self._copy_fsects_next_action)
        fsects_menu.addSeparator()
        fsects_menu.addAction(self._add_fsect_action)
        fsects_menu.addAction(self._delete_fsect_action)

        mrk_menu = tools_menu.addMenu("MRK")
        mrk_menu.addAction(self._mrk_add_entry_action)
        mrk_menu.addAction(self._mrk_delete_entry_action)
        mrk_menu.addSeparator()
        mrk_menu.addAction(self._mrk_textures_action)
        mrk_menu.addAction(self._mrk_generate_file_action)
        mrk_menu.addAction(self._mrk_save_entries_action)
        mrk_menu.addAction(self._mrk_load_entries_action)

        tools_menu.addSeparator()
        tools_menu.addAction(self._show_palette_colors_action)
        tools_menu.addSeparator()
        tools_menu.addAction(self._run_integrity_checks_action)
        tools_menu.addSeparator()
        tools_menu.addAction(self._calibrate_background_action)

        window_menu = self._window.menuBar().addMenu("Window")
        window_menu.addAction(self._section_table_action)
        window_menu.addAction(self._heading_table_action)
        window_menu.addAction(self._xsect_table_action)

        self._window.set_section_table_action(self._section_table_action)
        self._window.set_heading_table_action(self._heading_table_action)
        self._window.set_xsect_table_action(self._xsect_table_action)

        help_menu = self._window.menuBar().addMenu("Help")
        help_menu.addAction(self._about_action)

    def _show_about_dialog(self) -> None:
        show_about_dialog(self._window)

    @staticmethod
    def _read_pcx_256_palette(path: Path) -> list[QtGui.QColor]:
        data = path.read_bytes()
        if len(data) < 769 or data[-769] != 0x0C:
            raise ValueError("Invalid or missing 256-color PCX palette marker")
        raw_palette = data[-768:]
        return [
            QtGui.QColor(raw_palette[i], raw_palette[i + 1], raw_palette[i + 2])
            for i in range(0, 768, 3)
        ]

    def _load_sunny_palette_dialog(self) -> None:
        default_directory = ""
        if self._current_path is not None:
            default_directory = str(self._current_path.parent)
        path_str, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._window,
            "Load SUNNY.PCX Palette",
            default_directory,
            "PCX files (*.pcx *.PCX);;All files (*)",
        )
        if not path_str:
            return

        self._load_sunny_palette(Path(path_str))

    def _load_sunny_palette(self, path: Path, *, persist_for_current_track: bool = True) -> bool:
        resolved_path = path.resolve()
        try:
            self._sunny_palette = self._read_pcx_256_palette(resolved_path)
            self._sunny_palette_path = resolved_path
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Load SUNNY.PCX Palette",
                f"Could not load palette from {path.name}:\n{exc}",
            )
            return False

        if persist_for_current_track and self._current_path is not None:
            self._history.set_sunny_palette(self._current_path, resolved_path)

        self._window.preview.set_tsd_palette(self._sunny_palette)
        self._window.show_status_message(
            f"Loaded SUNNY palette from {resolved_path.name} ({len(self._sunny_palette)} colors)."
        )
        return True

    def _show_palette_colors_dialog(self) -> None:
        if not self._sunny_palette:
            QtWidgets.QMessageBox.information(
                self._window,
                "SUNNY Palette",
                "Load SUNNY.PCX first from File → Load SUNNY.PCX…",
            )
            return

        if self._palette_colors_dialog is None:
            self._palette_colors_dialog = PaletteColorDialog(self._sunny_palette, self._window)
        else:
            self._palette_colors_dialog.close()
            self._palette_colors_dialog = PaletteColorDialog(self._sunny_palette, self._window)

        self._palette_colors_dialog.show()
        self._palette_colors_dialog.raise_()
        self._palette_colors_dialog.activateWindow()

    def _generate_pitwall_txt(self) -> None:
        sections, _ = self._window.preview.get_section_set()
        if not sections:
            QtWidgets.QMessageBox.information(
                self._window,
                "Generate pitwall.txt",
                "There are no track sections available.",
            )
            return

        wall_height = self._window.pitwall_wall_height_500ths()
        armco_height = self._window.pitwall_armco_height_500ths()

        output_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self._window,
            "Save pitwall.txt",
            "pitwall.txt",
            "Text Files (*.txt);;All Files (*)",
        )
        if not output_path:
            return

        path = Path(output_path)
        if not path.suffix:
            path = path.with_suffix(".txt")

        lines: list[str] = []
        for section_index, _section in enumerate(sections):
            section_range = self._window.adjusted_section_range_500ths(section_index)
            if section_range is None:
                fallback_range = self._window.preview.get_section_range(section_index)
                if fallback_range is None:
                    continue
                start_dlong = int(round(fallback_range[0]))
                end_dlong = int(round(fallback_range[1]))
            else:
                start_dlong, end_dlong = section_range

            fsects = self._window.preview.get_section_fsects(section_index)
            boundary_rows = [
                (row_index, fsect)
                for row_index, fsect in enumerate(fsects)
                if fsect.surface_type in {7, 8}
            ]
            boundary_rows.sort(
                key=lambda row_fsect: (
                    min(row_fsect[1].start_dlat, row_fsect[1].end_dlat),
                    max(row_fsect[1].start_dlat, row_fsect[1].end_dlat),
                    row_fsect[0],
                )
            )
            for boundary_number, (_row_index, fsect) in enumerate(boundary_rows):
                height = wall_height if fsect.surface_type == 7 else armco_height
                boundary_length = height * 4
                boundary_end_dlong = min(end_dlong, start_dlong + boundary_length)
                lines.append(
                    "BOUNDARY "
                    f"{boundary_number}: "
                    f"{start_dlong} "
                    f"{boundary_end_dlong} "
                    f"HEIGHT {height}"
                )

        try:
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError as exc:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Generate pitwall.txt",
                f"Could not save pitwall file:\n{exc}",
            )
            return

        opened = QtGui.QDesktopServices.openUrl(
            QtCore.QUrl.fromLocalFile(str(path.resolve()))
        )
        if not opened:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Generate pitwall.txt",
                f"Saved file, but could not open it automatically:\n{path}",
            )
            return

        self._window.show_status_message(f"Generated and opened {path.name}.")

    def _connect_signals(self) -> None:
        self._window.preview.selectedSectionChanged.connect(
            self._on_selected_section_changed
        )
        self._window.preview.sectionsChanged.connect(self._on_sections_changed)
        self._window.prev_button.clicked.connect(self._window.preview.select_previous_section)
        self._window.next_button.clicked.connect(self._window.preview.select_next_section)
        self._previous_section_action.triggered.connect(self._window.preview.select_previous_section)
        self._next_section_action.triggered.connect(self._window.preview.select_next_section)
        #self._window.new_track_button.clicked.connect(self._start_new_track)
        self._window.new_straight_button.toggled.connect(
            self._toggle_new_straight_mode
        )
        self._new_straight_mode_action.toggled.connect(
            self._toggle_new_straight_mode
        )
        self._window.new_curve_button.toggled.connect(self._toggle_new_curve_mode)
        self._new_curve_mode_action.toggled.connect(self._toggle_new_curve_mode)
        self._window.set_start_finish_button.clicked.connect(
            self._window.preview.activate_set_start_finish_mode
        )
        self._set_start_finish_action.triggered.connect(
            self._window.preview.activate_set_start_finish_mode
        )
        self._window.preview.newStraightModeChanged.connect(
            self._on_new_straight_mode_changed
        )
        self._window.preview.newCurveModeChanged.connect(self._on_new_curve_mode_changed)
        self._window.delete_section_button.toggled.connect(
            self._toggle_delete_section_mode
        )
        self._delete_section_mode_action.toggled.connect(
            self._toggle_delete_section_mode
        )
        self._window.split_section_button.toggled.connect(
            self._toggle_split_section_mode
        )
        self._split_section_mode_action.toggled.connect(
            self._toggle_split_section_mode
        )
        self._window.move_section_button.toggled.connect(
            self._toggle_move_section_mode
        )
        self._move_section_mode_action.toggled.connect(
            self._toggle_move_section_mode
        )
        self._window.preview.deleteModeChanged.connect(self._on_delete_mode_changed)
        self._window.preview.splitSectionModeChanged.connect(self._on_split_mode_changed)
        self._window.preview.interactionDragChanged.connect(
            self._on_preview_drag_state_changed
        )
        self._delete_shortcut.activated.connect(self._handle_delete_shortcut)
        self._window.radii_button.toggled.connect(self._window.preview.set_show_curve_markers)
        self._window.axes_button.toggled.connect(self._window.preview.set_show_axes)
        self._window.background_image_checkbox.toggled.connect(
            self._window.preview.set_show_background_image
        )
        self._show_radii_action.toggled.connect(self._window.radii_button.setChecked)
        self._show_axes_action.toggled.connect(self._window.axes_button.setChecked)
        self._show_background_image_action.toggled.connect(
            self._window.background_image_checkbox.setChecked
        )
        self._new_straight_mode_action.toggled.connect(
            self._window.new_straight_button.setChecked
        )
        self._new_curve_mode_action.toggled.connect(
            self._window.new_curve_button.setChecked
        )
        self._split_section_mode_action.toggled.connect(
            self._window.split_section_button.setChecked
        )
        self._move_section_mode_action.toggled.connect(
            self._window.move_section_button.setChecked
        )
        self._delete_section_mode_action.toggled.connect(
            self._window.delete_section_button.setChecked
        )
        self._window.radii_button.toggled.connect(self._show_radii_action.setChecked)
        self._window.axes_button.toggled.connect(self._show_axes_action.setChecked)
        self._window.background_image_checkbox.toggled.connect(
            self._show_background_image_action.setChecked
        )
        self._window.new_straight_button.toggled.connect(
            self._new_straight_mode_action.setChecked
        )
        self._window.new_curve_button.toggled.connect(
            self._new_curve_mode_action.setChecked
        )
        self._window.split_section_button.toggled.connect(
            self._split_section_mode_action.setChecked
        )
        self._window.move_section_button.toggled.connect(
            self._move_section_mode_action.setChecked
        )
        self._window.delete_section_button.toggled.connect(
            self._delete_section_mode_action.setChecked
        )
        self._window.background_brightness_slider.valueChanged.connect(
            self._on_background_brightness_changed
        )
        self._window.track_opacity_slider.valueChanged.connect(
            self._on_track_opacity_changed
        )
        self._window.sg_fsects_checkbox.toggled.connect(
            self._window.preview.set_show_sg_fsects
        )
        self._window.right_sidebar_tabs.currentChanged.connect(
            self._on_right_sidebar_tab_changed
        )
        self._window.mrk_add_entry_button.clicked.connect(self._on_mrk_add_entry_requested)
        self._window.mrk_delete_entry_button.clicked.connect(self._on_mrk_delete_entry_requested)
        self._window.mrk_textures_button.clicked.connect(self._on_mrk_textures_requested)
        self._window.mrk_generate_file_button.clicked.connect(self._on_mrk_generate_file_requested)
        self._window.mrk_save_button.clicked.connect(self._on_mrk_save_requested)
        self._window.mrk_load_button.clicked.connect(self._on_mrk_load_requested)
        self._window.generate_pitwall_button.clicked.connect(self._generate_pitwall_txt)
        self._window.pitwall_wall_height_spin.valueChanged.connect(self._on_mrk_wall_height_changed)
        self._window.pitwall_armco_height_spin.valueChanged.connect(self._on_mrk_armco_height_changed)
        self._mrk_add_entry_action.triggered.connect(self._on_mrk_add_entry_requested)
        self._mrk_delete_entry_action.triggered.connect(self._on_mrk_delete_entry_requested)
        self._mrk_textures_action.triggered.connect(self._on_mrk_textures_requested)
        self._mrk_generate_file_action.triggered.connect(self._on_mrk_generate_file_requested)
        self._mrk_save_entries_action.triggered.connect(self._on_mrk_save_requested)
        self._mrk_load_entries_action.triggered.connect(self._on_mrk_load_requested)
        self._window.mrk_entries_table.itemSelectionChanged.connect(self._on_mrk_entry_selection_changed)
        self._window.mrk_entries_table.itemChanged.connect(self._on_mrk_entry_item_changed)
        self._window.mrk_entries_table.cellDoubleClicked.connect(self._on_mrk_entry_cell_double_clicked)
        self._window.tsd_add_line_button.clicked.connect(self._on_tsd_add_line_requested)
        self._window.tsd_delete_line_button.clicked.connect(self._on_tsd_delete_line_requested)
        self._window.tsd_generate_file_button.clicked.connect(self._on_tsd_generate_file_requested)
        self._window.tsd_load_file_button.clicked.connect(self._on_tsd_load_file_requested)
        self._window.tsd_files_combo.currentIndexChanged.connect(self._on_tsd_file_selection_changed)
        self._tsd_lines_model.dataChanged.connect(self._on_tsd_data_changed)
        self._tsd_lines_model.rowsInserted.connect(self._schedule_tsd_preview_refresh)
        self._tsd_lines_model.rowsRemoved.connect(self._schedule_tsd_preview_refresh)
        self._tsd_lines_model.modelReset.connect(self._schedule_tsd_preview_refresh)
        tsd_selection_model = self._window.tsd_lines_table.selectionModel()
        if tsd_selection_model is not None:
            tsd_selection_model.selectionChanged.connect(self._on_tsd_selection_changed)
        self._window.xsect_dlat_line_checkbox.toggled.connect(
            self._window.preview.set_show_xsect_dlat_line
        )
        self._window.copy_fsects_prev_button.clicked.connect(
            self._section_editing_coordinator.copy_fsects_to_previous
        )
        self._copy_fsects_prev_action.triggered.connect(
            self._section_editing_coordinator.copy_fsects_to_previous
        )
        self._window.copy_fsects_next_button.clicked.connect(
            self._section_editing_coordinator.copy_fsects_to_next
        )
        self._copy_fsects_next_action.triggered.connect(
            self._section_editing_coordinator.copy_fsects_to_next
        )
        self._window.add_fsect_button.clicked.connect(
            self._add_fsect_below_selected
        )
        self._add_fsect_action.triggered.connect(self._add_fsect_below_selected)
        self._window.delete_fsect_button.clicked.connect(
            self._delete_selected_fsect
        )
        self._delete_fsect_action.triggered.connect(self._delete_selected_fsect)
        self._window.xsect_combo.currentIndexChanged.connect(
            self._refresh_elevation_profile
        )
        self._window.copy_xsect_button.clicked.connect(self._elevation_ui_coordinator.copy_xsect_to_all)
        self._window.altitude_slider.valueChanged.connect(
            self._on_altitude_slider_changed
        )
        self._window.altitude_slider.sliderReleased.connect(
            self._on_altitude_slider_released
        )
        self._window.altitude_min_spin.valueChanged.connect(
            lambda _value: self._elevation_ui_coordinator.on_altitude_range_changed("min")
        )
        self._window.altitude_max_spin.valueChanged.connect(
            lambda _value: self._elevation_ui_coordinator.on_altitude_range_changed("max")
        )
        self._window.altitude_set_range_button.clicked.connect(
            self._open_altitude_range_dialog
        )
        self._window.grade_spin.valueChanged.connect(self._on_grade_slider_changed)
        self._window.grade_spin.sliderReleased.connect(
            self._on_grade_edit_finished
        )
        self._window.grade_set_range_button.clicked.connect(
            self._open_grade_range_dialog
        )
        self._window.preview.scaleChanged.connect(self._on_scale_changed)
        self._window.profile_widget.sectionClicked.connect(
            self._elevation_ui_coordinator.on_profile_section_clicked
        )
        self._window.profile_widget.altitudeDragged.connect(
            self._elevation_ui_coordinator.on_profile_altitude_dragged
        )
        self._window.profile_widget.altitudeDragFinished.connect(
            self._elevation_ui_coordinator.on_profile_altitude_drag_finished
        )
        self._window.xsect_elevation_widget.xsectClicked.connect(
            self._on_xsect_node_clicked
        )
        self._window.xsect_elevation_table.cellChanged.connect(
            self._on_xsect_table_cell_changed
        )
        self._window.fsectDiagramDlatChangeRequested.connect(
            self._on_fsect_diagram_dlat_change_requested
        )
        self._window.fsectDiagramDragRefreshRequested.connect(
            self._window.preview.refresh_fsections_preview_lightweight
        )
        self._window.fsectDiagramDragCommitRequested.connect(
            self._on_fsect_diagram_drag_commit_requested
        )
        self._window.measurement_units_combo.currentIndexChanged.connect(
            self._on_measurement_units_changed
        )
        for key, (hex_edit, color_swatch) in self._window.preview_color_controls.items():
            hex_edit.editingFinished.connect(
                lambda color_key=key, widget=hex_edit: self._on_preview_color_text_changed(
                    color_key, widget
                )
            )
            color_swatch.clicked.connect(
                lambda _checked=False, color_key=key: self._on_pick_preview_color(color_key)
            )

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

    def _confirm_discard_unsaved_mrk(self, title: str, action_description: str) -> bool:
        if not self._mrk_is_dirty:
            return True
        response = QtWidgets.QMessageBox.question(
            self._window,
            title,
            f"You have unsaved MRK changes. Continue and {action_description} without saving?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        return response == QtWidgets.QMessageBox.Yes

    def _set_mrk_dirty(self, dirty: bool) -> None:
        self._mrk_is_dirty = dirty
        self._window.set_sidebar_tab_dirty("Walls", dirty)

    def _set_tsd_dirty(self, dirty: bool) -> None:
        self._tsd_is_dirty = dirty
        self._window.set_sidebar_tab_dirty("TSD", dirty)

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
        return labels

    def mark_fsects_dirty(self, dirty: bool) -> None:
        self._mark_fsects_dirty(dirty)

    def _persist_mrk_state_for_current_track(self) -> None:
        if self._current_path is None:
            return
        self._history.set_mrk_state(self._current_path, self._collect_mrk_state())

    def _load_mrk_state_for_current_track(self) -> None:
        self._set_mrk_dirty(False)
        self._mrk_texture_definitions = ()
        table = self._window.mrk_entries_table
        table.blockSignals(True)
        table.setRowCount(0)
        table.blockSignals(False)

        if self._current_path is None:
            self._update_mrk_highlights_from_table()
            return

        state = self._history.get_mrk_state(self._current_path)
        if not isinstance(state, dict):
            self._update_mrk_highlights_from_table()
            return

        try:
            self._apply_mrk_state(state, mark_dirty=False)
        except ValueError:
            logger.warning("Unable to restore MRK state for %s", self._current_path, exc_info=True)
            self._mrk_texture_definitions = ()
            table.blockSignals(True)
            table.setRowCount(0)
            table.blockSignals(False)
            self._update_mrk_highlights_from_table()

    def _on_mrk_wall_select_requested(self) -> None:
        table = self._window.mrk_entries_table
        selected_rows = table.selectionModel().selectedRows()
        if not selected_rows:
            self._window.preview.set_selected_mrk_wall(None, None, None)
            self._update_mrk_highlights_from_table()
            return
        row = selected_rows[0].row()
        section_index = self._table_int_value(table, row, 0)
        boundary_index = self._table_int_value(table, row, 1)
        wall_index = self._table_int_value(table, row, 2)
        self._window.preview.set_selected_mrk_wall(
            boundary_index,
            section_index,
            wall_index,
        )
        self._update_mrk_highlights_from_table()

    def _on_mrk_add_entry_requested(self) -> None:
        table = self._window.mrk_entries_table
        row = table.rowCount()
        table.insertRow(row)
        values = [0, 0, 0, 1]
        for column, value in enumerate(values):
            item = QtWidgets.QTableWidgetItem(str(int(value)))
            item.setTextAlignment(int(QtCore.Qt.AlignCenter))
            table.setItem(row, column, item)
        self._set_mrk_side_cell(row, self._auto_detect_mrk_side(0, 0))
        table.setItem(row, 5, QtWidgets.QTableWidgetItem(self._default_texture_pattern_for_wall_count(1)))
        table.selectRow(row)
        self._set_mrk_dirty(True)
        self._persist_mrk_state_for_current_track()
        self._update_mrk_highlights_from_table()

    def _on_mrk_delete_entry_requested(self) -> None:
        table = self._window.mrk_entries_table
        selected_rows = table.selectionModel().selectedRows()
        if not selected_rows:
            return
        table.removeRow(selected_rows[0].row())
        self._set_mrk_dirty(True)
        self._persist_mrk_state_for_current_track()
        self._update_mrk_highlights_from_table()


    def _on_tsd_add_line_requested(self) -> None:
        row = self._tsd_lines_model.add_default_row()
        self._window.tsd_lines_table.selectRow(row)
        self._sync_active_tsd_file_from_model()
        self._refresh_tsd_preview_lines()
        self._set_tsd_dirty(True)

    def _on_tsd_delete_line_requested(self) -> None:
        selection_model = self._window.tsd_lines_table.selectionModel()
        if selection_model is None:
            return
        selected_rows = selection_model.selectedRows()
        if not selected_rows:
            return
        self._tsd_lines_model.remove_row(selected_rows[0].row())
        self._sync_active_tsd_file_from_model()
        self._refresh_tsd_preview_lines()
        self._set_tsd_dirty(True)

    def _on_tsd_generate_file_requested(self) -> None:
        path_str, _selected_filter = QtWidgets.QFileDialog.getSaveFileName(
            self._window,
            "Generate TSD File",
            "",
            "TSD Files (*.tsd)",
        )
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix.lower() != ".tsd":
            path = path.with_suffix(".tsd")

        try:
            detail_file = self._build_tsd_file_from_model()
            path.write_text(serialize_tsd(detail_file), encoding="utf-8")
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Generate TSD Failed",
                str(exc),
            )
            return
        self._upsert_loaded_tsd_file(path.name, tuple(detail_file.lines))
        self._refresh_tsd_preview_lines()
        self._set_tsd_dirty(False)
        self._window.show_status_message(f"Generated TSD file {path.name}")

    def _on_tsd_load_file_requested(self) -> None:
        path_str, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
            self._window,
            "Load TSD File",
            "",
            "TSD Files (*.tsd *.TSD);;All files (*)",
        )
        if not path_str:
            return

        path = Path(path_str)
        started = perf_counter()
        try:
            detail_file = parse_tsd(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Load TSD Failed",
                str(exc),
            )
            return

        self._add_loaded_tsd_file(path.name, tuple(detail_file.lines), select=True)
        self._set_tsd_dirty(False)
        self._log_tsd_perf("TSD load duration", started)
        self._window.show_status_message(
            f"Loaded TSD file {path.name} ({len(self._loaded_tsd_files)} total)"
        )

    def _sync_active_tsd_file_from_model(self) -> None:
        if self._active_tsd_file_index is None:
            return
        if self._active_tsd_file_index < 0 or self._active_tsd_file_index >= len(self._loaded_tsd_files):
            return
        active_file = self._loaded_tsd_files[self._active_tsd_file_index]
        self._loaded_tsd_files[self._active_tsd_file_index] = LoadedTsdFile(
            name=active_file.name,
            lines=self._tsd_lines_model.all_lines(),
        )

    def _clear_loaded_tsd_files(self) -> None:
        self._loaded_tsd_files = []
        self._active_tsd_file_index = None
        combo = self._window.tsd_files_combo
        previous_block_state = combo.blockSignals(True)
        try:
            combo.clear()
            combo.addItem(self._TSD_SHOW_ALL_LABEL)
            combo.setCurrentIndex(0)
            combo.setEnabled(False)
        finally:
            combo.blockSignals(previous_block_state)
        self._populate_tsd_table(TrackSurfaceDetailFile(lines=()))
        self._set_tsd_dirty(False)

    def _add_loaded_tsd_file(
        self,
        name: str,
        lines: tuple[TrackSurfaceDetailLine, ...],
        *,
        select: bool,
    ) -> None:
        self._loaded_tsd_files.append(LoadedTsdFile(name=name, lines=tuple(lines)))
        combo = self._window.tsd_files_combo
        previous_block_state = combo.blockSignals(True)
        try:
            if combo.count() == 0:
                combo.addItem(self._TSD_SHOW_ALL_LABEL)
            combo.addItem(name)
            combo.setEnabled(True)
            if select:
                combo.setCurrentIndex(combo.count() - 1)
        finally:
            combo.blockSignals(previous_block_state)
        if select:
            self._set_active_tsd_file(len(self._loaded_tsd_files) - 1)

    def _upsert_loaded_tsd_file(
        self,
        name: str,
        lines: tuple[TrackSurfaceDetailLine, ...],
    ) -> None:
        if self._active_tsd_file_index is None:
            self._add_loaded_tsd_file(name, lines, select=True)
            return
        self._loaded_tsd_files[self._active_tsd_file_index] = LoadedTsdFile(
            name=name,
            lines=tuple(lines),
        )
        combo = self._window.tsd_files_combo
        previous_block_state = combo.blockSignals(True)
        try:
            combo.setItemText(self._active_tsd_file_index + 1, name)
        finally:
            combo.blockSignals(previous_block_state)

    def _set_active_tsd_file(self, index: int) -> None:
        if index < 0 or index >= len(self._loaded_tsd_files):
            return
        if self._active_tsd_file_index is not None and self._active_tsd_file_index != index:
            self._sync_active_tsd_file_from_model()
        self._active_tsd_file_index = index
        detail_file = TrackSurfaceDetailFile(lines=self._loaded_tsd_files[index].lines)
        self._populate_tsd_table(detail_file)

    def _on_tsd_file_selection_changed(self, index: int) -> None:
        if index <= 0:
            self._sync_active_tsd_file_from_model()
            self._active_tsd_file_index = None
            self._populate_tsd_table(TrackSurfaceDetailFile(lines=self._all_loaded_tsd_lines()))
            return
        self._set_active_tsd_file(index - 1)

    def _all_loaded_tsd_lines(self) -> tuple[TrackSurfaceDetailLine, ...]:
        lines: list[TrackSurfaceDetailLine] = []
        for loaded_file in self._loaded_tsd_files:
            lines.extend(loaded_file.lines)
        return tuple(lines)

    def _populate_tsd_table(self, detail_file: TrackSurfaceDetailFile) -> None:
        started = perf_counter()
        self._suspend_tsd_preview_refresh = True
        table = self._window.tsd_lines_table
        previous_block_state = table.blockSignals(True)
        try:
            self._tsd_lines_model.replace_lines(detail_file.lines)
        finally:
            table.blockSignals(previous_block_state)
            self._suspend_tsd_preview_refresh = False

        self._refresh_tsd_preview_lines()
        self._log_tsd_perf("TSD table populate duration", started)

    def _on_tsd_selection_changed(
        self,
        _selected: QtCore.QItemSelection,
        _deselected: QtCore.QItemSelection,
    ) -> None:
        self._center_viewport_on_selected_tsd_line()
        self._schedule_tsd_preview_refresh()

    def _center_viewport_on_selected_tsd_line(self) -> None:
        selection_model = self._window.tsd_lines_table.selectionModel()
        if selection_model is None:
            return
        selected_rows = selection_model.selectedRows()
        if not selected_rows:
            return

        line = self._tsd_lines_model.line_at(selected_rows[0].row())
        if line is None:
            return

        center_point = self._tsd_line_center_point(line)
        if center_point is None:
            return

        self._window.preview.center_view_on_point(center_point)

    def _tsd_line_center_point(self, line: TrackSurfaceDetailLine) -> Point | None:
        sections, _ = self._window.preview.get_section_set()
        if not sections:
            return None

        adjusted_to_sg_ranges = self._last_tsd_adjusted_to_sg_ranges
        if not adjusted_to_sg_ranges[0]:
            adjusted_to_sg_ranges = self._build_adjusted_to_sg_ranges(sections)
            self._last_tsd_adjusted_to_sg_ranges = adjusted_to_sg_ranges

        preview_line = self._convert_tsd_line_for_preview(
            line,
            sections,
            adjusted_to_sg_ranges,
        )

        track_length = max(
            (float(section.start_dlong) + float(section.length) for section in sections),
            default=0.0,
        )
        if track_length <= 0.0:
            return None

        start = float(preview_line.start_dlong) % track_length
        end = float(preview_line.end_dlong) % track_length
        span = (end - start) % track_length
        if math.isclose(span, 0.0):
            return None

        midpoint_dlong = (start + span * 0.5) % track_length
        midpoint_dlat = float(preview_line.start_dlat) + (
            float(preview_line.end_dlat) - float(preview_line.start_dlat)
        ) * 0.5
        return self._point_on_track_at_dlong(sections, midpoint_dlong, midpoint_dlat, track_length)

    @staticmethod
    def _point_on_track_at_dlong(
        sections: list[SectionPreview],
        dlong: float,
        dlat: float,
        track_length: float,
    ) -> Point | None:
        if not sections or track_length <= 0.0:
            return None

        wrapped_dlong = float(dlong) % track_length
        for section in sections:
            length = float(section.length)
            if length <= 0.0:
                continue
            start = float(section.start_dlong)
            end = start + length
            in_range = start <= wrapped_dlong < end
            if end > track_length:
                wrapped_end = end - track_length
                in_range = in_range or wrapped_dlong < wrapped_end
            if not in_range:
                continue

            fraction = (wrapped_dlong - start) / length
            if end > track_length and wrapped_dlong < start:
                fraction = (wrapped_dlong + track_length - start) / length
            fraction = max(0.0, min(1.0, fraction))
            return SGViewerController._point_on_section(section, fraction, dlat)

        return SGViewerController._point_on_section(sections[-1], 1.0, dlat)

    @staticmethod
    def _point_on_section(section: SectionPreview, fraction: float, dlat: float) -> Point:
        sx, sy = section.start
        ex, ey = section.end
        center = section.center

        if center is None:
            dx = ex - sx
            dy = ey - sy
            cx = sx + dx * fraction
            cy = sy + dy * fraction
            length = math.hypot(dx, dy)
            if length <= 0.0:
                return (cx, cy)
            nx = -dy / length
            ny = dx / length
            return (cx + nx * dlat, cy + ny * dlat)

        center_x, center_y = center
        start_vec = (sx - center_x, sy - center_y)
        end_vec = (ex - center_x, ey - center_y)
        base_radius = math.hypot(start_vec[0], start_vec[1])
        if base_radius <= 0.0:
            return (sx, sy)

        start_angle = math.atan2(start_vec[1], start_vec[0])
        end_angle = math.atan2(end_vec[1], end_vec[0])

        heading = section.start_heading
        if heading is not None:
            cross = start_vec[0] * heading[1] - start_vec[1] * heading[0]
            ccw = cross > 0 if not math.isclose(cross, 0.0, abs_tol=1e-12) else (
                start_vec[0] * end_vec[1] - start_vec[1] * end_vec[0]
            ) > 0
        else:
            ccw = (start_vec[0] * end_vec[1] - start_vec[1] * end_vec[0]) > 0

        delta = end_angle - start_angle
        if ccw:
            while delta <= 0:
                delta += math.tau
        else:
            while delta >= 0:
                delta -= math.tau

        angle = start_angle + delta * fraction
        radius = max(0.0, base_radius + (-1.0 if ccw else 1.0) * dlat)
        return (
            center_x + math.cos(angle) * radius,
            center_y + math.sin(angle) * radius,
        )

    def _schedule_tsd_preview_refresh(self, *_args: object) -> None:
        if self._suspend_tsd_preview_refresh:
            return
        self._tsd_preview_refresh_timer.start()

    def _refresh_tsd_preview_lines(self) -> None:
        started = perf_counter()
        sections, _ = self._window.preview.get_section_set()

        range_started = perf_counter()
        adjusted_to_sg_ranges = self._build_adjusted_to_sg_ranges(sections)
        self._last_tsd_adjusted_to_sg_ranges = adjusted_to_sg_ranges
        self._log_tsd_perf("build adjusted_to_sg_ranges", range_started)

        convert_started = perf_counter()
        lines = list(self._tsd_lines_model.all_lines())
        preview_lines = [
            self._convert_tsd_line_for_preview(line, sections, adjusted_to_sg_ranges)
            for line in lines
        ]
        self._last_tsd_preview_lines = list(preview_lines)
        self._log_tsd_perf("convert TSD lines", convert_started)

        set_started = perf_counter()
        self._window.preview.set_tsd_lines(tuple(preview_lines))
        self._log_tsd_perf("preview.set_tsd_lines", set_started)
        self._log_tsd_perf("TSD preview refresh duration", started)

    def _on_tsd_data_changed(
        self,
        top_left: QtCore.QModelIndex,
        bottom_right: QtCore.QModelIndex,
        _roles: list[int] | None = None,
    ) -> None:
        if self._suspend_tsd_preview_refresh:
            return
        if not top_left.isValid() or not bottom_right.isValid():
            self._schedule_tsd_preview_refresh()
            return
        if top_left.row() != bottom_right.row():
            self._schedule_tsd_preview_refresh()
            return

        row = top_left.row()
        line = self._tsd_lines_model.line_at(row)
        if line is None:
            self._schedule_tsd_preview_refresh()
            return

        sections, _ = self._window.preview.get_section_set()
        adjusted_to_sg_ranges = self._last_tsd_adjusted_to_sg_ranges
        if not adjusted_to_sg_ranges[0]:
            adjusted_to_sg_ranges = self._build_adjusted_to_sg_ranges(sections)
            self._last_tsd_adjusted_to_sg_ranges = adjusted_to_sg_ranges

        if row >= len(self._last_tsd_preview_lines):
            self._schedule_tsd_preview_refresh()
            return

        self._last_tsd_preview_lines[row] = self._convert_tsd_line_for_preview(
            line,
            sections,
            adjusted_to_sg_ranges,
        )
        self._window.preview.set_tsd_lines(tuple(self._last_tsd_preview_lines))
        self._sync_active_tsd_file_from_model()
        self._set_tsd_dirty(True)

    def _log_tsd_perf(self, label: str, started: float) -> None:
        if not self._debug_tsd_perf:
            return
        print(f"[tsd_perf] {label}: {(perf_counter() - started) * 1000:.2f} ms")

    def _build_tsd_file_from_model(self) -> TrackSurfaceDetailFile:
        lines = self._tsd_lines_model.all_lines()
        if not lines:
            raise ValueError("No TSD lines to export.")
        return TrackSurfaceDetailFile(lines=lines)

    def _convert_tsd_line_for_preview(
        self,
        line: TrackSurfaceDetailLine,
        sections: list[SectionPreview],
        adjusted_to_sg_ranges: tuple[
            list[tuple[float, float, float, float]],
            list[float],
        ],
    ) -> TrackSurfaceDetailLine:
        if not sections:
            return line

        start_dlong = self._adjusted_dlong_to_sg_dlong(
            line.start_dlong,
            adjusted_to_sg_ranges,
        )
        end_dlong = self._adjusted_dlong_to_sg_dlong(
            line.end_dlong,
            adjusted_to_sg_ranges,
        )
        return TrackSurfaceDetailLine(
            color_index=line.color_index,
            width_500ths=line.width_500ths,
            start_dlong=start_dlong,
            start_dlat=line.start_dlat,
            end_dlong=end_dlong,
            end_dlat=line.end_dlat,
            command=line.command,
        )

    def _build_adjusted_to_sg_ranges(
        self,
        sections: list[SectionPreview],
    ) -> tuple[list[tuple[float, float, float, float]], list[float]]:
        section_ranges: list[tuple[float, float, float, float]] = []
        section_boundaries: list[float] = []
        for section_index, section in enumerate(sections):
            adjusted_range = self._window.adjusted_section_range_500ths(section_index)
            if adjusted_range is None:
                return [], []
            adjusted_start, adjusted_end = adjusted_range
            sg_start = float(section.start_dlong)
            sg_end = sg_start + float(section.length)
            section_ranges.append(
                (float(adjusted_start), float(adjusted_end), sg_start, sg_end)
            )
            section_boundaries.extend((float(adjusted_start), float(adjusted_end)))
        section_boundaries.sort()
        return section_ranges, section_boundaries

    def _find_adjusted_segment_index(
        self,
        normalized_dlong: float,
        section_ranges: list[tuple[float, float, float, float]],
        section_boundaries: list[float],
    ) -> int | None:
        if not section_ranges or not section_boundaries:
            return None

        boundary_index = bisect_left(section_boundaries, normalized_dlong)
        candidate = max(0, min(len(section_ranges) - 1, (boundary_index - 1) // 2))
        adjusted_start, adjusted_end, _, _ = section_ranges[candidate]
        if adjusted_start <= normalized_dlong <= adjusted_end:
            return candidate

        if candidate + 1 < len(section_ranges):
            next_start, next_end, _, _ = section_ranges[candidate + 1]
            if next_start <= normalized_dlong <= next_end:
                return candidate + 1

        return None

    def _adjusted_dlong_to_sg_dlong(
        self,
        adjusted_dlong: int,
        adjusted_to_sg_ranges: tuple[
            list[tuple[float, float, float, float]],
            list[float],
        ],
    ) -> int:
        section_ranges, section_boundaries = adjusted_to_sg_ranges
        if not section_ranges:
            return int(adjusted_dlong)

        total_adjusted_length = section_ranges[-1][1]
        if total_adjusted_length <= 0:
            return int(adjusted_dlong)

        normalized = float(adjusted_dlong) % total_adjusted_length
        segment_index = self._find_adjusted_segment_index(
            normalized,
            section_ranges,
            section_boundaries,
        )
        if segment_index is None:
            return int(round(section_ranges[-1][3]))

        adjusted_start, adjusted_end, sg_start, sg_end = section_ranges[segment_index]
        adjusted_length = adjusted_end - adjusted_start
        if adjusted_length < 0:
            return int(round(section_ranges[-1][3]))
        if math.isclose(adjusted_length, 0.0):
            return int(round(sg_start))
        fraction = (normalized - adjusted_start) / adjusted_length
        return int(round(sg_start + fraction * (sg_end - sg_start)))


    def _on_mrk_textures_requested(self) -> None:
        dialog = MrkTexturesDialog(self._window, self._mrk_texture_definitions)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        try:
            self._mrk_texture_definitions = dialog.texture_definitions()
        except ValueError as exc:
            QtWidgets.QMessageBox.warning(self._window, "Invalid MRK Texture", str(exc))
            return
        self._set_mrk_dirty(True)
        self._persist_mrk_state_for_current_track()
        self._update_mrk_highlights_from_table()

    def _default_texture_pattern_for_wall_count(self, wall_count: int) -> str:
        if not self._mrk_texture_definitions:
            return ""
        cycle = [definition.texture_name for definition in self._mrk_texture_definitions]
        pattern = [cycle[index % len(cycle)] for index in range(max(0, wall_count))]
        return ",".join(pattern)

    def _normalize_mrk_side(self, value: str) -> str:
        normalized = value.strip().lower()
        if normalized == "right":
            return "Right"
        return "Left"

    def _set_mrk_side_cell(self, row: int, side: str) -> None:
        table = self._window.mrk_entries_table
        combo = QtWidgets.QComboBox(table)
        combo.addItems(["Left", "Right"])
        combo.setCurrentText(self._normalize_mrk_side(side))
        combo.currentTextChanged.connect(lambda _value: self._on_mrk_side_changed())
        table.setCellWidget(row, 4, combo)

    def _on_mrk_side_changed(self) -> None:
        self._set_mrk_dirty(True)
        self._persist_mrk_state_for_current_track()
        self._update_mrk_highlights_from_table()

    def _mrk_side_for_row(self, row: int) -> str:
        widget = self._window.mrk_entries_table.cellWidget(row, 4)
        if isinstance(widget, QtWidgets.QComboBox):
            return self._normalize_mrk_side(widget.currentText())
        return self._normalize_mrk_side(self._table_text_value(self._window.mrk_entries_table, row, 4))

    def _auto_detect_mrk_side(self, section_index: int, boundary_index: int) -> str:
        model = self._window.preview.sg_preview_model
        if model is None or section_index < 0 or section_index >= len(model.fsects):
            return "Left"
        fsect = model.fsects[section_index]
        if boundary_index < 0 or boundary_index >= len(fsect.boundaries):
            return "Left"
        boundary = fsect.boundaries[boundary_index]
        start = boundary.attrs.get("dlat_start")
        end = boundary.attrs.get("dlat_end")
        if start is not None and end is not None:
            mean_dlat = (float(start) + float(end)) * 0.5
            if mean_dlat < 0:
                return "Right"
            if mean_dlat > 0:
                return "Left"
        return "Left"

    def _on_mrk_entry_selection_changed(self) -> None:
        table = self._window.mrk_entries_table
        selected_rows = table.selectionModel().selectedRows()
        if not selected_rows:
            return
        row = selected_rows[0].row()
        self._on_mrk_wall_select_requested()


    def _allowed_mrk_texture_names(self) -> set[str]:
        return {definition.texture_name for definition in self._mrk_texture_definitions}

    def _on_mrk_entry_cell_double_clicked(self, row: int, column: int) -> None:
        if column != 5:
            return
        if not self._mrk_texture_definitions:
            QtWidgets.QMessageBox.information(
                self._window,
                "No MRK Textures Defined",
                "Define MRK textures first using the Textures dialog.",
            )
            return
        table = self._window.mrk_entries_table
        existing_item = table.item(row, 5)
        current = [] if existing_item is None else [token.strip() for token in existing_item.text().split(",") if token.strip()]
        dialog = MrkTexturePatternDialog(
            self._window,
            [definition.texture_name for definition in self._mrk_texture_definitions],
            current,
        )
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return
        updated = ",".join(dialog.selected_pattern())
        table.blockSignals(True)
        if existing_item is None:
            table.setItem(row, 5, QtWidgets.QTableWidgetItem(updated))
        else:
            existing_item.setText(updated)
        table.blockSignals(False)
        self._set_mrk_dirty(True)
        self._persist_mrk_state_for_current_track()
        self._update_mrk_highlights_from_table()

    def _on_mrk_entry_item_changed(self, item: QtWidgets.QTableWidgetItem) -> None:
        row = item.row()
        column = item.column()
        table = self._window.mrk_entries_table
        if column in {0, 1, 2, 3}:
            raw = item.text().strip()
            try:
                value = max(0, int(raw))
            except ValueError:
                value = 0
            table.blockSignals(True)
            item.setText(str(value))
            item.setTextAlignment(int(QtCore.Qt.AlignCenter))
            table.blockSignals(False)
        if column == 4:
            table.blockSignals(True)
            item.setText(self._normalize_mrk_side(item.text()))
            item.setTextAlignment(int(QtCore.Qt.AlignCenter))
            table.blockSignals(False)
        if column == 5:
            allowed = self._allowed_mrk_texture_names()
            tokens = [token.strip() for token in item.text().split(",") if token.strip()]
            if allowed and any(token not in allowed for token in tokens):
                QtWidgets.QMessageBox.warning(
                    self._window,
                    "Invalid Texture Pattern",
                    "Texture pattern entries must reference predefined texture names.",
                )
                table.blockSignals(True)
                item.setText(
                    self._default_texture_pattern_for_wall_count(
                        int(table.item(row, 3).text()) if table.item(row, 3) else 1
                    )
                )
                table.blockSignals(False)
        self._set_mrk_dirty(True)
        self._persist_mrk_state_for_current_track()
        self._update_mrk_highlights_from_table()

    def _update_mrk_highlights_from_table(self) -> None:
        table = self._window.mrk_entries_table
        highlights: list[tuple[int, int, int, int, str]] = []
        color_lookup = {definition.texture_name: definition.highlight_color for definition in self._mrk_texture_definitions}
        model = self._window.preview.sg_preview_model

        def _parse_non_negative_int(item: QtWidgets.QTableWidgetItem | None) -> int | None:
            if item is None:
                return None
            try:
                return max(0, int(item.text().strip()))
            except (TypeError, ValueError):
                return None

        for row in range(table.rowCount()):
            section_index = _parse_non_negative_int(table.item(row, 0))
            boundary_index = _parse_non_negative_int(table.item(row, 1))
            wall_index = _parse_non_negative_int(table.item(row, 2))
            wall_count = _parse_non_negative_int(table.item(row, 3))
            if None in {section_index, boundary_index, wall_index, wall_count}:
                continue

            pattern_item = table.item(row, 5)
            textures = [] if pattern_item is None else [token.strip() for token in pattern_item.text().split(",") if token.strip()]
            if model is None:
                wall_positions = [(section_index, wall_index + offset) for offset in range(max(0, wall_count))]
            else:
                try:
                    wall_positions = [
                        (position_section, position_wall)
                        for position_section, position_wall, _wall_ranges in self._iter_mrk_wall_positions(
                            model,
                            section_index=section_index,
                            boundary_index=boundary_index,
                            wall_index=wall_index,
                            wall_count=wall_count,
                        )
                    ]
                except ValueError:
                    continue

            for offset, (position_section, position_wall) in enumerate(wall_positions):
                texture_name = textures[offset % len(textures)] if textures else ""
                if not texture_name:
                    continue
                color = color_lookup.get(texture_name)
                if not color:
                    continue
                highlights.append((boundary_index, position_section, position_wall, 1, color))
        self._window.preview.set_highlighted_mrk_walls(highlights)

    def _collect_mrk_state(self) -> dict[str, object]:
        table = self._window.mrk_entries_table
        entries: list[dict[str, object]] = []
        for row in range(table.rowCount()):
            entries.append(
                {
                    "track_section": self._table_int_value(table, row, 0),
                    "boundary": self._table_int_value(table, row, 1),
                    "starting_wall": self._table_int_value(table, row, 2),
                    "wall_count": self._table_int_value(table, row, 3),
                    "side": self._table_text_value(table, row, 4) or "Left",
                    "texture_pattern": self._table_text_value(table, row, 5),
                }
            )
        texture_definitions = [
            {
                "texture_name": definition.texture_name,
                "mip_filename": definition.mip_name,
                "upper_left_u": definition.upper_left_u,
                "upper_left_v": definition.upper_left_v,
                "lower_right_u": definition.lower_right_u,
                "lower_right_v": definition.lower_right_v,
                "highlight_color": definition.highlight_color,
            }
            for definition in self._mrk_texture_definitions
        ]
        return {
            "format": "sg_viewer_mrk",
            "version": 1,
            "texture_definitions": texture_definitions,
            "entries": entries,
        }

    def _apply_mrk_state(self, state: dict[str, object], *, mark_dirty: bool = True) -> None:
        textures_raw = state.get("texture_definitions", [])
        entries_raw = state.get("entries", [])
        if not isinstance(textures_raw, list) or not isinstance(entries_raw, list):
            raise ValueError("JSON must include list fields 'texture_definitions' and 'entries'.")

        texture_definitions: list[MrkTextureDefinition] = []
        for index, raw in enumerate(textures_raw):
            if not isinstance(raw, dict):
                raise ValueError(f"Texture definition #{index + 1} must be an object.")
            texture_definitions.append(
                MrkTextureDefinition(
                    texture_name=str(raw.get("texture_name", "")).strip(),
                    mip_name=str(raw.get("mip_filename", raw.get("mip_name", ""))).strip(),
                    upper_left_u=int(raw.get("upper_left_u", 0)),
                    upper_left_v=int(raw.get("upper_left_v", 0)),
                    lower_right_u=int(raw.get("lower_right_u", 0)),
                    lower_right_v=int(raw.get("lower_right_v", 0)),
                    highlight_color=str(raw.get("highlight_color", "#FFFF00")).strip() or "#FFFF00",
                )
            )

        table = self._window.mrk_entries_table
        table.blockSignals(True)
        table.setRowCount(0)
        for index, raw in enumerate(entries_raw):
            if not isinstance(raw, dict):
                table.blockSignals(False)
                raise ValueError(f"MRK entry #{index + 1} must be an object.")
            row = table.rowCount()
            table.insertRow(row)
            values = [
                int(raw.get("track_section", 0)),
                int(raw.get("boundary", 0)),
                int(raw.get("starting_wall", 0)),
                max(1, int(raw.get("wall_count", 1))),
                str(raw.get("side", "Left")).strip() or "Left",
                str(raw.get("texture_pattern", "")).strip(),
            ]
            for column, value in enumerate(values):
                if column == 4:
                    self._set_mrk_side_cell(row, str(value))
                    continue
                item = QtWidgets.QTableWidgetItem(str(value))
                if column < 5:
                    item.setTextAlignment(int(QtCore.Qt.AlignCenter))
                table.setItem(row, column, item)
        table.blockSignals(False)

        self._mrk_texture_definitions = tuple(texture_definitions)
        self._set_mrk_dirty(mark_dirty)
        if mark_dirty:
            self._persist_mrk_state_for_current_track()
        self._update_mrk_highlights_from_table()

    def _table_int_value(self, table: QtWidgets.QTableWidget, row: int, column: int) -> int:
        item = table.item(row, column)
        if item is None:
            return 0
        try:
            return int(item.text().strip())
        except (TypeError, ValueError):
            return 0

    def _table_text_value(self, table: QtWidgets.QTableWidget, row: int, column: int) -> str:
        widget = table.cellWidget(row, column)
        if isinstance(widget, QtWidgets.QComboBox):
            return widget.currentText().strip()
        item = table.item(row, column)
        return "" if item is None else item.text().strip()

    def _on_mrk_save_requested(self) -> None:
        path_str, _selected_filter = QtWidgets.QFileDialog.getSaveFileName(
            self._window,
            "Save MRK Entries and Textures",
            "",
            "JSON Files (*.json)",
        )
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        payload = self._collect_mrk_state()
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self._set_mrk_dirty(False)
        self._persist_mrk_state_for_current_track()
        self._window.show_status_message(f"Saved MRK data to {path.name}")

    def _on_mrk_generate_file_requested(self) -> None:
        path_str, _selected_filter = QtWidgets.QFileDialog.getSaveFileName(
            self._window,
            "Generate MRK File",
            "",
            "MRK Files (*.mrk)",
        )
        if not path_str:
            return
        path = Path(path_str)
        if path.suffix.lower() != ".mrk":
            path = path.with_suffix(".mrk")

        try:
            mark_file = self._build_mark_file_from_table()
            path.write_text(serialize_mrk(mark_file), encoding="utf-8")
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Generate MRK Failed",
                str(exc),
            )
            return
        self._window.show_status_message(f"Generated MRK file {path.name}")

    def _build_mark_file_from_table(self) -> MarkFile:
        model = self._window.preview.sg_preview_model
        if model is None:
            raise ValueError("No SG preview model is available for MRK generation.")

        texture_lookup = {
            definition.texture_name: definition for definition in self._mrk_texture_definitions
        }
        table = self._window.mrk_entries_table
        entries: list[MarkBoundaryEntry] = []
        pointer_index = 1

        for row in range(table.rowCount()):
            section_index = self._table_int_value(table, row, 0)
            boundary_index = self._table_int_value(table, row, 1)
            wall_index = self._table_int_value(table, row, 2)
            wall_count = max(0, self._table_int_value(table, row, 3))
            if wall_count <= 0:
                continue
            side = self._mrk_side_for_row(row)

            textures = [
                token.strip()
                for token in self._table_text_value(table, row, 5).split(",")
                if token.strip()
            ]
            if not textures:
                raise ValueError(f"Row {row + 1}: texture pattern is required.")

            wall_ranges = self._wall_ranges_for_section_boundary(
                model,
                section_index=section_index,
                boundary_index=boundary_index,
            )
            if not wall_ranges:
                raise ValueError(
                    f"Row {row + 1}: no wall geometry found for section {section_index}, boundary {boundary_index}."
                )

            for offset, (current_section, current_wall, current_wall_ranges) in enumerate(
                self._iter_mrk_wall_positions(
                    model,
                    section_index=section_index,
                    boundary_index=boundary_index,
                    wall_index=wall_index,
                    wall_count=wall_count,
                )
            ):
                texture_name = textures[offset % len(textures)]
                texture = texture_lookup.get(texture_name)
                if texture is None:
                    raise ValueError(
                        f"Row {row + 1}: texture {texture_name!r} is not defined in MRK textures."
                    )
                start_distance, end_distance = current_wall_ranges[current_wall]
                entries.append(
                    MarkBoundaryEntry(
                        pointer_name=f"mrk{pointer_index}",
                        boundary_id=boundary_index,
                        mip_name=texture.mip_name,
                        uv_rect=MarkUvRect(
                            upper_left_u=texture.lower_right_u if side == "Right" else texture.upper_left_u,
                            upper_left_v=texture.upper_left_v,
                            lower_right_u=texture.upper_left_u if side == "Right" else texture.lower_right_u,
                            lower_right_v=texture.lower_right_v,
                        ),
                        start=self._mark_track_position(current_section, start_distance, current_wall_ranges),
                        end=self._mark_track_position(current_section, end_distance, current_wall_ranges),
                    )
                )
                pointer_index += 1

        if not entries:
            raise ValueError("No MRK entries to export.")
        return MarkFile(entries=tuple(entries))

    def _wall_ranges_for_section_boundary(
        self,
        model,
        *,
        section_index: int,
        boundary_index: int,
    ) -> list[tuple[float, float]]:
        if section_index < 0 or section_index >= len(model.fsects):
            return []
        fsect = model.fsects[section_index]
        if boundary_index < 0 or boundary_index >= len(fsect.boundaries):
            return []
        boundary = fsect.boundaries[boundary_index]
        target_length = self._mrk_target_length_for_surface_type(getattr(fsect, "surface_type", 0))
        points = [
            (float(point[0]), float(point[1]))
            for point in boundary.points
            if point is not None
        ]
        if len(points) < 2:
            return []
        segment_lengths = [
            math.hypot(points[index + 1][0] - points[index][0], points[index + 1][1] - points[index][1])
            for index in range(len(points) - 1)
        ]
        total = sum(segment_lengths)
        if total <= 0.0:
            return []
        segment_count = max(1, int(round(total / target_length)))
        spacing = total / float(segment_count)
        cuts = [0.0]
        cuts.extend(spacing * index for index in range(1, segment_count))
        cuts.append(total)
        return [(cuts[index], cuts[index + 1]) for index in range(len(cuts) - 1)]

    def _mrk_target_length_for_surface_type(self, surface_type: int) -> float:
        if surface_type == 8:
            return max(1.0, float(self._window.pitwall_armco_height_500ths()) * 4.0)
        return max(1.0, float(self._window.pitwall_wall_height_500ths()) * 4.0)

    def _mark_track_position(
        self,
        section_index: int,
        distance_along_boundary: float,
        wall_ranges: list[tuple[float, float]],
    ) -> MarkTrackPosition:
        total = wall_ranges[-1][1] if wall_ranges else 0.0
        if total <= 0.0:
            fraction = 0.0
        else:
            fraction = distance_along_boundary / total
        fraction = max(0.0, min(1.0, fraction))
        return MarkTrackPosition(section=section_index, fraction=fraction)

    def _iter_mrk_wall_positions(
        self,
        model,
        *,
        section_index: int,
        boundary_index: int,
        wall_index: int,
        wall_count: int,
    ) -> list[tuple[int, int, list[tuple[float, float]]]]:
        if wall_count <= 0:
            return []

        if section_index < 0 or section_index >= len(model.fsects):
            raise ValueError(f"Track section {section_index} is out of range.")

        current_section = section_index
        current_wall_index = max(0, wall_index)
        remaining = wall_count
        positions: list[tuple[int, int, list[tuple[float, float]]]] = []

        while remaining > 0:
            if current_section >= len(model.fsects):
                raise ValueError(
                    f"Track section {section_index} with starting wall {wall_index} and wall count {wall_count} "
                    "extends beyond available section geometry."
                )

            wall_ranges = self._wall_ranges_for_section_boundary(
                model,
                section_index=current_section,
                boundary_index=boundary_index,
            )
            if not wall_ranges:
                raise ValueError(
                    f"No wall geometry found for section {current_section}, boundary {boundary_index}."
                )

            wall_total = len(wall_ranges)
            if current_wall_index >= wall_total:
                current_wall_index -= wall_total
                current_section += 1
                continue

            available = wall_total - current_wall_index
            take = min(remaining, available)
            for offset in range(take):
                positions.append((current_section, current_wall_index + offset, wall_ranges))
            remaining -= take
            current_section += 1
            current_wall_index = 0

        return positions

    def _on_mrk_load_requested(self) -> None:
        path_str, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
            self._window,
            "Load MRK Entries and Textures",
            "",
            "JSON Files (*.json)",
        )
        if not path_str:
            return
        path = Path(path_str)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("Top-level JSON value must be an object.")
            self._apply_mrk_state(payload, mark_dirty=False)
            self._persist_mrk_state_for_current_track()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Load MRK JSON Failed",
                str(exc),
            )
            return
        self._window.show_status_message(f"Loaded MRK data from {path.name}")

    def _on_right_sidebar_tab_changed(self, index: int) -> None:
        tab_name = self._window.right_sidebar_tabs.tabText(index).rstrip("*")
        if tab_name in {"Fsects", "Walls"} and not self._window.sg_fsects_checkbox.isChecked():
            self._window.sg_fsects_checkbox.setChecked(True)
        is_mrk_tab = tab_name == "Walls"
        is_tsd_tab = tab_name == "TSD"
        self._window.preview.set_show_mrk_notches(is_mrk_tab)
        self._window.preview.set_show_tsd_lines(is_tsd_tab)
        if is_mrk_tab:
            self._update_mrk_highlights_from_table()
        else:
            self._window.preview.set_highlighted_mrk_walls(())

    def _on_mrk_wall_height_changed(self, _value: float) -> None:
        self._window.preview.set_mrk_wall_height_500ths(
            self._window.pitwall_wall_height_500ths()
        )

    def _on_mrk_armco_height_changed(self, _value: float) -> None:
        self._window.preview.set_mrk_armco_height_500ths(
            self._window.pitwall_armco_height_500ths()
        )

    def _on_track_opacity_changed(self, value: int) -> None:
        clamped_value = max(0, min(100, int(value)))
        self._window.track_opacity_value_label.setText(str(clamped_value))
        self._window.preview.set_track_opacity(clamped_value / 100.0)

    def _on_background_brightness_changed(self, value: int) -> None:
        clamped_value = max(-100, min(100, int(value)))
        self._window.background_brightness_value_label.setText(str(clamped_value))
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


    def _apply_saved_sunny_palette(self, sg_path: Path | None = None) -> None:
        path = sg_path or self._current_path
        if path is None:
            return
        palette_path = self._history.get_sunny_palette(path)
        if palette_path is None:
            return
        self._load_sunny_palette(palette_path, persist_for_current_track=False)

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

    def _on_new_curve_mode_changed(self, active: bool) -> None:
        button = self._window.new_curve_button
        button.setChecked(active)
        if active:
            button.setStyleSheet("background-color: #3f51b5; color: white;")
        else:
            button.setStyleSheet(self._new_curve_default_style)

    def _on_delete_mode_changed(self, active: bool) -> None:
        button = self._window.delete_section_button
        button.setChecked(active)
        if active:
            button.setStyleSheet("background-color: #b53f3f; color: white;")
        else:
            button.setStyleSheet(self._delete_default_style)

    def _on_split_mode_changed(self, active: bool) -> None:
        button = self._window.split_section_button
        button.setChecked(active)
        if active:
            button.setStyleSheet("background-color: #3fb5b5; color: white;")
        else:
            button.setStyleSheet(self._split_default_style)

    def _on_move_section_mode_changed(self, active: bool) -> None:
        button = self._window.move_section_button
        button.setChecked(active)
        if active:
            button.setStyleSheet("background-color: #4caf50; color: white;")
        else:
            button.setStyleSheet(self._move_section_default_style)

    def _on_scale_changed(self, scale: float) -> None:
        _ = scale

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

    def _toggle_export_csv_on_save(self, enabled: bool) -> None:
        self._document_controller.set_export_csv_on_save(enabled)

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
        self._window.copy_xsect_button.setEnabled(combo_enabled and bool(sections))

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
            self._add_fsect_action.setEnabled(False)
            self._delete_fsect_action.setEnabled(False)
            return
        self._window.add_fsect_button.setEnabled(True)
        self._add_fsect_action.setEnabled(True)
        fsects = self._window.preview.get_section_fsects(selection.index)
        delete_enabled = bool(fsects)
        self._window.delete_fsect_button.setEnabled(delete_enabled)
        self._delete_fsect_action.setEnabled(delete_enabled)

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
        if self._window.show_generate_elevation_change_dialog(xsect_index=xsect_index):
            self._reset_altitude_range_for_track()
            self._refresh_elevation_profile()
            self._refresh_xsect_elevation_panel()
            self._refresh_xsect_elevation_table()

    def _apply_altitude_edit(self, live: bool = False, slider_value: int | None = None) -> None:
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

    def _on_grade_slider_changed(self, value: int) -> None:
        self._elevation_panel_controller.on_grade_slider_changed(value)

    def _on_grade_edit_finished(self) -> None:
        self._elevation_panel_controller.on_grade_edit_finished()

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

            close_button = QtWidgets.QPushButton("Close", self._integrity_report_window)
            close_button.clicked.connect(self._integrity_report_window.close)
            self._integrity_report_window.finished.connect(lambda _result: self._on_integrity_report_window_hidden())
            button_row = QtWidgets.QHBoxLayout()
            button_row.addStretch(1)
            button_row.addWidget(close_button)
            layout.addLayout(button_row)

        text_edit = self._integrity_report_window.findChild(QtWidgets.QPlainTextEdit, "integrityReportText")
        if text_edit is not None:
            text_edit.setPlainText(report.text)
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
        self._refresh_xsect_elevation_panel()
        self._update_track_length_display()
        self._window.update_selection_sidebar(self._active_selection)

    def _on_measurement_units_changed(self) -> None:
        self._elevation_ui_coordinator.on_measurement_units_changed()
        self._sync_after_measurement_unit_change()

    def _on_xsect_table_cell_changed(self, row_index: int, column_index: int) -> None:
        self._elevation_panel_controller.on_xsect_table_cell_changed(row_index, column_index)
