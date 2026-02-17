from __future__ import annotations

import logging
import math
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets

from sg_viewer.geometry.topology import is_closed_loop, loop_length
from sg_viewer.model.history import FileHistory
from sg_viewer.model.preview_fsection import PreviewFSection
from sg_viewer.services.fsect_generation_service import build_generated_fsects
from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.model.selection import SectionSelection
from sg_viewer.ui.altitude_units import (
    feet_from_500ths,
    feet_from_slider_units,
    feet_to_500ths,
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
    DocumentController,
    ElevationController,
    ElevationPanelController,
    InteractionController,
    SectionsController,
)
from sg_viewer.model.track_model import TrackModel

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
        self._document_controller = DocumentController(self, logger)
        self._background_controller = BackgroundController(self, logger)
        self._elevation_panel_controller = ElevationPanelController(self)
        self._sections_controller = SectionsController(self)

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
        self._refresh_recent_menu()
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
        self._open_action.triggered.connect(self._open_file_dialog)

        self._import_trk_action = QtWidgets.QAction("Import TRK…", self._window)
        self._import_trk_action.triggered.connect(self._import_trk_file_dialog)

        self._import_trk_from_dat_action = QtWidgets.QAction(
            "Import TRK from DAT…",
            self._window,
        )
        self._import_trk_from_dat_action.triggered.connect(self._import_trk_from_dat_file_dialog)

        self._open_recent_menu = QtWidgets.QMenu("Open Recent", self._window)

        self._save_current_action = QtWidgets.QAction("Save", self._window)
        self._save_current_action.setShortcut("Ctrl+S")
        self._save_current_action.setEnabled(False)
        self._save_current_action.triggered.connect(self._save_current_file)

        self._save_action = QtWidgets.QAction("Save SG As…", self._window)
        self._save_action.setShortcut("Ctrl+Shift+S")
        self._save_action.setEnabled(True)
        self._save_action.triggered.connect(self._save_file_dialog)

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

        self._section_table_action = QtWidgets.QAction("Section Table", self._window)
        self._section_table_action.setEnabled(False)
        self._section_table_action.triggered.connect(self._show_section_table)

        self._heading_table_action = QtWidgets.QAction("Heading Table", self._window)
        self._heading_table_action.setEnabled(False)
        self._heading_table_action.triggered.connect(self._show_heading_table)

        self._xsect_table_action = QtWidgets.QAction("X-Section Table", self._window)
        self._xsect_table_action.setEnabled(False)
        self._xsect_table_action.triggered.connect(self._show_xsect_table)

        self._quit_action = QtWidgets.QAction("Quit", self._window)
        self._quit_action.setShortcut("Ctrl+Q")
        self._quit_action.triggered.connect(self._window.close)

        self._about_action = QtWidgets.QAction("About SG CREATE", self._window)
        self._about_action.triggered.connect(self._show_about_dialog)

    def _create_menus(self) -> None:
        file_menu = self._window.menuBar().addMenu("&File")
        file_menu.addAction(self._new_action)
        file_menu.addSeparator()
        file_menu.addAction(self._open_action)
        file_menu.addAction(self._import_trk_action)
        file_menu.addAction(self._import_trk_from_dat_action)
        file_menu.addMenu(self._open_recent_menu)
        file_menu.addAction(self._save_current_action)
        file_menu.addAction(self._save_action)
        file_menu.addAction(self._open_background_action)
        file_menu.addAction(self._background_settings_action)
#        file_menu.addAction(self._calibrate_background_action)
        file_menu.addSeparator()
        file_menu.addAction(self._quit_action)

        tools_menu = self._window.menuBar().addMenu("Tools")
        tools_menu.addAction(self._scale_track_action)
        tools_menu.addAction(self._rotate_track_action)
        tools_menu.addAction(self._reverse_track_action)
        tools_menu.addAction(self._convert_trk_action)
        tools_menu.addAction(self._generate_fsects_action)
        tools_menu.addAction(self._raise_lower_elevations_action)
        tools_menu.addAction(self._flatten_all_elevations_and_grade_action)
        tools_menu.addAction(self._calibrate_background_action)
        tools_menu.addSeparator()
        tools_menu.addAction(self._section_table_action)
        tools_menu.addAction(self._heading_table_action)
        tools_menu.addAction(self._xsect_table_action)

        self._window.set_section_table_action(self._section_table_action)
        self._window.set_heading_table_action(self._heading_table_action)
        self._window.set_xsect_table_action(self._xsect_table_action)

        help_menu = self._window.menuBar().addMenu("Help")
        help_menu.addAction(self._about_action)

    def _show_about_dialog(self) -> None:
        show_about_dialog(self._window)

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
        self._window.new_curve_button.toggled.connect(self._toggle_new_curve_mode)
        self._window.set_start_finish_button.clicked.connect(
            self._window.preview.activate_set_start_finish_mode
        )
        self._window.preview.newStraightModeChanged.connect(
            self._on_new_straight_mode_changed
        )
        self._window.preview.newCurveModeChanged.connect(self._on_new_curve_mode_changed)
        self._window.delete_section_button.toggled.connect(
            self._toggle_delete_section_mode
        )
        self._window.split_section_button.toggled.connect(
            self._toggle_split_section_mode
        )
        self._window.move_section_button.toggled.connect(
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
            self._copy_fsects_to_previous
        )
        self._window.copy_fsects_next_button.clicked.connect(
            self._copy_fsects_to_next
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
        self._window.copy_xsect_button.clicked.connect(self._copy_xsect_to_all)
        self._window.altitude_slider.valueChanged.connect(
            self._on_altitude_slider_changed
        )
        self._window.altitude_slider.sliderReleased.connect(
            self._on_altitude_slider_released
        )
        self._window.altitude_min_spin.valueChanged.connect(
            lambda _value: self._on_altitude_range_changed("min")
        )
        self._window.altitude_max_spin.valueChanged.connect(
            lambda _value: self._on_altitude_range_changed("max")
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
            self._on_profile_section_clicked
        )
        self._window.profile_widget.altitudeDragged.connect(
            self._on_profile_altitude_dragged
        )
        self._window.profile_widget.altitudeDragFinished.connect(
            self._on_profile_altitude_drag_finished
        )
        self._window.xsect_elevation_widget.xsectClicked.connect(
            self._on_xsect_node_clicked
        )
        self._window.xsect_elevation_table.cellChanged.connect(
            self._on_xsect_table_cell_changed
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
        self._background_controller.open_background_file_dialog()

    def _show_background_settings_dialog(self) -> None:
        self._background_controller.show_background_settings_dialog()

    def _launch_background_calibrator(self) -> None:
        self._background_controller.launch_background_calibrator()

    def _apply_calibrator_values(self, data: dict) -> None:
        self._background_controller.apply_calibrator_values(data)

    def _open_file_dialog(self) -> None:
        self._document_controller.open_file_dialog()

    def _import_trk_file_dialog(self) -> None:
        self._document_controller.import_trk_file_dialog()

    def _import_trk_from_dat_file_dialog(self) -> None:
        self._document_controller.import_trk_from_dat_file_dialog()

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
        self._on_altitude_range_changed()



    def _save_file_dialog(self) -> None:
        self._document_controller.save_file_dialog()

    def _save_current_file(self) -> None:
        self._document_controller.save_current_file()

    def _save_to_path(self, path: Path) -> None:
        self._document_controller.save_to_path(path)

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
        self._document_controller.convert_sg_to_trk()

    def _ensure_saved_sg(self) -> Path | None:
        return self._document_controller.ensure_saved_sg()

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
        self._open_recent_menu.clear()
        recent_paths = self._history.get_recent_paths()
        if not recent_paths:
            empty_action = QtWidgets.QAction("No recent files", self._open_recent_menu)
            empty_action.setEnabled(False)
            self._open_recent_menu.addAction(empty_action)
            return

        for path in recent_paths:
            action = QtWidgets.QAction(str(path), self._open_recent_menu)
            action.triggered.connect(lambda checked=False, p=path: self.load_sg(p))
            self._open_recent_menu.addAction(action)

    def _on_sections_changed(self) -> None:
        self._sections_controller.on_sections_changed()
        self._sync_after_section_mutation()

    def _show_section_table(self) -> None:
        sections, track_length = self._window.preview.get_section_set()
        if not sections:
            QtWidgets.QMessageBox.information(
                self._window, "No Sections", "Load an SG file to view sections."
            )
            return

        if self._section_table_window is None:
            self._section_table_window = SectionTableWindow(self._window)
            self._section_table_window.on_sections_edited(self._apply_section_table_edits)

        self._section_table_window.set_sections(sections, track_length)
        self._section_table_window.show()
        self._section_table_window.raise_()
        self._section_table_window.activateWindow()

    def _update_section_table(self) -> None:
        if self._section_table_window is None:
            return

        sections, track_length = self._window.preview.get_section_set()
        self._section_table_window.set_sections(sections, track_length)

    def _apply_section_table_edits(self, sections: list[SectionPreview]) -> None:
        self._window.preview.set_sections(sections)
        self._update_heading_table()

    def _show_heading_table(self) -> None:
        headings = self._window.preview.get_section_headings()
        if not headings:
            QtWidgets.QMessageBox.information(
                self._window, "No Headings", "Load an SG file to view headings."
            )
            return

        if self._heading_table_window is None:
            self._heading_table_window = HeadingTableWindow(self._window)

        self._heading_table_window.set_headings(headings)
        self._heading_table_window.show()
        self._heading_table_window.raise_()
        self._heading_table_window.activateWindow()

    def _update_heading_table(self) -> None:
        if self._heading_table_window is None:
            return

        headings = self._window.preview.get_section_headings()
        self._heading_table_window.set_headings(headings)

    def _show_xsect_table(self) -> None:
        metadata = self._window.preview.get_xsect_metadata()
        if not metadata:
            QtWidgets.QMessageBox.information(
                self._window,
                "No X-Sections",
                "Load an SG file to view X-section DLAT values.",
            )
            return

        if self._xsect_table_window is None:
            self._xsect_table_window = XsectTableWindow(self._window)
            self._xsect_table_window.on_xsects_edited(self._apply_xsect_table_edits)

        self._xsect_table_window.set_xsects(metadata)
        self._xsect_table_window.show()
        self._xsect_table_window.raise_()
        self._xsect_table_window.activateWindow()

    def _update_xsect_table(self) -> None:
        if self._xsect_table_window is None:
            return

        metadata = self._window.preview.get_xsect_metadata()
        self._xsect_table_window.set_xsects(metadata)

    def _apply_xsect_table_edits(self, entries: list[XsectEntry]) -> None:
        if not entries:
            return
        sorted_entries = sorted(entries, key=lambda entry: entry.dlat)
        if len(sorted_entries) < 2:
            return
        payload = [
            (entry.key if entry.key is not None and entry.key >= 0 else None, entry.dlat)
            for entry in sorted_entries
        ]
        old_selected = self._current_xsect_index()
        if not self._window.preview.set_xsect_definitions(payload):
            QtWidgets.QMessageBox.warning(
                self._window,
                "X-Section Table",
                "Unable to update X-section DLAT values.",
            )
            return

        new_selected = None
        if old_selected is not None:
            for idx, (key, _) in enumerate(payload):
                if key == old_selected:
                    new_selected = idx
                    break

        self._populate_xsect_choices(preferred_index=new_selected)
        self._refresh_elevation_profile()

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
        self._background_controller.clear_background_state()
#        self._calibrate_background_action.setEnabled(False)

    def _apply_saved_background(self, sg_path: Path | None = None) -> None:
        self._background_controller.apply_saved_background(sg_path)

    def _persist_background_state(self) -> None:
        self._background_controller.persist_background_state()

    def _update_track_length_display(self) -> None:
        sections, _ = self._window.preview.get_section_set()
        if not sections:
            self._window.update_track_length_label("Track Length: –")
            return

        if not is_closed_loop(sections):
            self._window.update_track_length_label("Track Length: Not a closed loop")
            return

        try:
            total_length = loop_length(sections)
        except ValueError:
            self._window.update_track_length_label("Track Length: Not a closed loop")
            return

        length_value = self._window.format_length_with_secondary(total_length)
        self._window.update_track_length_label(
            f"Track Length: {length_value}"
        )

    def _on_selected_section_changed(self, selection: SectionSelection | None) -> None:
        self._active_selection = selection
        self._sync_after_selection_change()

    def _on_profile_section_clicked(self, section_index: int) -> None:
        self._window.preview.selection_manager.set_selected_section(section_index)

    def _on_profile_altitude_dragged(self, section_index: int, altitude: float) -> None:
        xsect_index = self._current_xsect_index()
        if xsect_index is None:
            return

        self._elevation_controller.begin_drag()
        try:
            if self._window.preview.set_section_xsect_altitude(
                section_index, xsect_index, altitude, validate=False
            ):
                self._refresh_elevation_profile()
                self._refresh_xsect_elevation_panel()
                if (
                    self._active_selection is not None
                    and self._active_selection.index == section_index
                ):
                    self._refresh_elevation_inputs()
        finally:
            self._elevation_controller.end_drag()

    def _on_profile_altitude_drag_finished(self, section_index: int) -> None:
        _ = section_index
        self._window.preview.validate_document()

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

    def _on_altitude_range_changed(self, changed: str | None = None) -> None:
        self._elevation_panel_controller.on_altitude_range_changed(changed)

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

    def _apply_altitude_edit(self) -> None:
        selection = self._active_selection
        xsect_index = self._current_xsect_index()
        if selection is None or xsect_index is None:
            return

        altitude_feet = feet_from_slider_units(self._window.altitude_slider.value())
        altitude = feet_to_500ths(altitude_feet)
        if self._window.preview.set_section_xsect_altitude(
            selection.index, xsect_index, altitude, validate=False
        ):
            self._sync_after_xsect_value_change()

    def _apply_grade_edit(self) -> None:
        selection = self._active_selection
        xsect_index = self._current_xsect_index()
        if selection is None or xsect_index is None:
            return

        grade = self._window.grade_spin.value()
        if self._window.preview.set_section_xsect_grade(
            selection.index, xsect_index, grade, validate=False
        ):
            self._sync_after_xsect_value_change()

    def _copy_xsect_to_all(self) -> None:
        if self._elevation_panel_controller.copy_xsect_to_all():
            self._sync_after_xsect_value_change()

    def _copy_fsects_to_previous(self) -> None:
        self._sections_controller.copy_fsects_to_previous()

    def _copy_fsects_to_next(self) -> None:
        self._sections_controller.copy_fsects_to_next()

    def _copy_fsects_to_neighbor(self, *, direction: str) -> None:
        self._sections_controller.copy_fsects_to_neighbor(direction=direction)

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
        self._history.set_measurement_unit(
            str(self._window.measurement_units_combo.currentData())
        )
        self._sync_after_measurement_unit_change()

    def _on_xsect_table_cell_changed(self, row_index: int, column_index: int) -> None:
        self._elevation_panel_controller.on_xsect_table_cell_changed(row_index, column_index)
