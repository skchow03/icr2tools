from __future__ import annotations

import logging
import math
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets

from sg_viewer.model.history import FileHistory
from sg_viewer.model.preview_fsection import PreviewFSection
from sg_viewer.services.fsect_generation_service import build_generated_fsects
from sg_viewer.model.sg_model import SectionPreview
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


class SGViewerController:
    """Coordinates actions, menus, and dialogs for the SG viewer window."""

    def __init__(self, window: QtWidgets.QMainWindow) -> None:
        self._window = window
        self._section_table_window: SectionTableWindow | None = None
        self._heading_table_window: HeadingTableWindow | None = None
        self._xsect_table_window: XsectTableWindow | None = None
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

        self._create_actions()
        self._create_menus()
        self._connect_signals()
        self._on_track_opacity_changed(self._window.track_opacity_slider.value())
        self._on_background_brightness_changed(
            self._window.background_brightness_slider.value()
        )
        self._load_measurement_unit_from_history()
        self._load_preview_colors_from_history()
        self._initialize_preview_color_controls()
        self._window.preview.sectionsChanged.connect(self._on_sections_changed)
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
            "Convert SG to TRK…",
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

        self._section_table_action = QtWidgets.QAction("Section Table", self._window)
        self._section_table_action.setEnabled(False)
        self._section_table_action.triggered.connect(self._section_editing_coordinator.show_section_table)

        self._heading_table_action = QtWidgets.QAction("Heading Table", self._window)
        self._heading_table_action.setEnabled(False)
        self._heading_table_action.triggered.connect(self._section_editing_coordinator.show_heading_table)

        self._xsect_table_action = QtWidgets.QAction("X-Section Table", self._window)
        self._xsect_table_action.setEnabled(False)
        self._xsect_table_action.triggered.connect(self._section_editing_coordinator.show_xsect_table)

        self._new_straight_mode_action = QtWidgets.QAction("New Straight", self._window)
        self._new_straight_mode_action.setCheckable(True)
        self._new_straight_mode_action.setChecked(self._window.new_straight_button.isChecked())
        self._new_straight_mode_action.setEnabled(self._window.new_straight_button.isEnabled())

        self._new_curve_mode_action = QtWidgets.QAction("New Curve", self._window)
        self._new_curve_mode_action.setCheckable(True)
        self._new_curve_mode_action.setChecked(self._window.new_curve_button.isChecked())
        self._new_curve_mode_action.setEnabled(self._window.new_curve_button.isEnabled())

        self._split_section_mode_action = QtWidgets.QAction("Split Section", self._window)
        self._split_section_mode_action.setCheckable(True)
        self._split_section_mode_action.setChecked(self._window.split_section_button.isChecked())
        self._split_section_mode_action.setEnabled(self._window.split_section_button.isEnabled())

        self._move_section_mode_action = QtWidgets.QAction("Move Section", self._window)
        self._move_section_mode_action.setCheckable(True)
        self._move_section_mode_action.setChecked(self._window.move_section_button.isChecked())
        self._move_section_mode_action.setEnabled(self._window.move_section_button.isEnabled())

        self._delete_section_mode_action = QtWidgets.QAction("Delete Section", self._window)
        self._delete_section_mode_action.setCheckable(True)
        self._delete_section_mode_action.setChecked(self._window.delete_section_button.isChecked())
        self._delete_section_mode_action.setEnabled(self._window.delete_section_button.isEnabled())

        self._set_start_finish_action = QtWidgets.QAction("Set Start/Finish", self._window)
        self._set_start_finish_action.setEnabled(self._window.set_start_finish_button.isEnabled())

        self._quit_action = QtWidgets.QAction("Quit", self._window)
        self._quit_action.setShortcut("Ctrl+Q")
        self._quit_action.triggered.connect(self._window.close)

        self._about_action = QtWidgets.QAction("About SG CREATE", self._window)
        self._about_action.triggered.connect(self._show_about_dialog)

    def _create_menus(self) -> None:
        file_menu = self._window.menuBar().addMenu("&File")
        file_menu.addAction(self._new_action)
        file_menu.addAction(self._open_action)
        file_menu.addMenu(self._open_recent_menu)
        import_menu = file_menu.addMenu("Import")
        import_menu.addAction(self._import_trk_action)
        import_menu.addAction(self._import_trk_from_dat_action)
        file_menu.addSeparator()
        file_menu.addAction(self._save_current_action)
        file_menu.addAction(self._save_action)
        file_menu.addSeparator()
        file_menu.addAction(self._quit_action)

        view_menu = self._window.menuBar().addMenu("View")
        view_menu.addAction(self._open_background_action)
        view_menu.addAction(self._background_settings_action)
        view_menu.addSeparator()
        view_menu.addAction(self._show_radii_action)
        view_menu.addAction(self._show_axes_action)
        view_menu.addAction(self._show_background_image_action)

        tools_menu = self._window.menuBar().addMenu("Tools")

        section_editing_menu = tools_menu.addMenu("Section Editing")
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

        conversion_menu = tools_menu.addMenu("Conversion")
        conversion_menu.addAction(self._convert_trk_action)

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

    def _generate_pitwall_txt(self) -> None:
        sections, _ = self._window.preview.get_section_set()
        if not sections:
            QtWidgets.QMessageBox.information(
                self._window,
                "Generate pitwall.txt",
                "There are no track sections available.",
            )
            return

        heights = self._prompt_pitwall_heights()
        if heights is None:
            return
        wall_height, armco_height = heights

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
                lines.append(
                    "BOUNDARY "
                    f"{boundary_number}: "
                    f"{start_dlong} "
                    f"{end_dlong} "
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

    def _prompt_pitwall_heights(self) -> tuple[int, int] | None:
        unit = str(self._window.measurement_units_combo.currentData())
        unit_label = self._window.fsect_display_unit_label()
        decimals = self._window.fsect_display_decimals()
        step = self._window.fsect_display_step()

        dialog = QtWidgets.QDialog(self._window)
        dialog.setWindowTitle("Generate pitwall.txt")
        layout = QtWidgets.QVBoxLayout(dialog)
        form = QtWidgets.QFormLayout()

        wall_spin = QtWidgets.QDoubleSpinBox(dialog)
        wall_spin.setDecimals(decimals)
        wall_spin.setSingleStep(step)
        wall_spin.setRange(0.0, 999999999.0)
        wall_spin.setValue(self._window.fsect_dlat_to_display_units(21000.0))
        wall_spin.setSuffix(f" {unit_label}")

        armco_spin = QtWidgets.QDoubleSpinBox(dialog)
        armco_spin.setDecimals(decimals)
        armco_spin.setSingleStep(step)
        armco_spin.setRange(0.0, 999999999.0)
        armco_spin.setValue(self._window.fsect_dlat_to_display_units(18000.0))
        armco_spin.setSuffix(f" {unit_label}")

        form.addRow("Wall height:", wall_spin)
        form.addRow("Armco height:", armco_spin)
        layout.addLayout(form)

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

        wall_height = int(units_to_500ths(wall_spin.value(), unit))
        armco_height = int(units_to_500ths(armco_spin.value(), unit))
        return wall_height, armco_height

    def _connect_signals(self) -> None:
        self._window.preview.selectedSectionChanged.connect(
            self._on_selected_section_changed
        )
        self._window.preview.sectionsChanged.connect(self._on_sections_changed)
        self._window.prev_button.clicked.connect(self._window.preview.select_previous_section)
        self._window.next_button.clicked.connect(self._window.preview.select_next_section)
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
        self._window.xsect_dlat_line_checkbox.toggled.connect(
            self._window.preview.set_show_xsect_dlat_line
        )
        self._window.copy_fsects_prev_button.clicked.connect(
            self._section_editing_coordinator.copy_fsects_to_previous
        )
        self._window.copy_fsects_next_button.clicked.connect(
            self._section_editing_coordinator.copy_fsects_to_next
        )
        self._window.add_fsect_button.clicked.connect(
            self._add_fsect_below_selected
        )
        self._window.delete_fsect_button.clicked.connect(
            self._delete_selected_fsect
        )
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

    def _on_right_sidebar_tab_changed(self, index: int) -> None:
        if self._window.right_sidebar_tabs.tabText(index) != "Fsects":
            return
        if not self._window.sg_fsects_checkbox.isChecked():
            self._window.sg_fsects_checkbox.setChecked(True)

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

    def _update_fsect_edit_buttons(self) -> None:
        selection = self._active_selection
        if selection is None:
            self._window.add_fsect_button.setEnabled(False)
            self._window.delete_fsect_button.setEnabled(False)
            return
        self._window.add_fsect_button.setEnabled(True)
        fsects = self._window.preview.get_section_fsects(selection.index)
        self._window.delete_fsect_button.setEnabled(bool(fsects))

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

    def _sync_after_section_mutation(self) -> None:
        """Sync UI after section list/data changes in a stable update order."""
        if not self._window.preview.is_interaction_dragging:
            self._refresh_elevation_profile()
            self._window.update_selection_sidebar(self._active_selection)
        self._refresh_elevation_inputs()
        self._update_track_length_display()
        self._update_copy_xsect_button()
        self._update_copy_fsects_buttons()
        self._update_fsect_edit_buttons()

    def _sync_after_xsect_value_change(self) -> None:
        """Sync profile and x-section views after altitude/grade data changes."""
        self._refresh_elevation_profile()
        self._refresh_xsect_elevation_panel()
        self._refresh_xsect_elevation_table()

    def _sync_after_xsect_value_change_lightweight(self) -> None:
        """Keep live slider edits responsive while still updating elevation graphs live."""
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
