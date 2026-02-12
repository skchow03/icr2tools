from __future__ import annotations

import logging
import math
import json
import subprocess
import sys
import uuid
from pathlib import Path

from PyQt5 import QtCore, QtGui, QtWidgets, QtNetwork

from sg_viewer.geometry.topology import is_closed_loop, loop_length
from sg_viewer.geometry.sg_geometry import rotate_section
from sg_viewer.models.history import FileHistory
from sg_viewer.models.preview_fsection import PreviewFSection
from sg_viewer.models.sg_model import SectionPreview
from sg_viewer.models.selection import SectionSelection
from sg_viewer.model.sg_document import SGDocument
from sg_viewer.ui.altitude_units import (
    feet_from_500ths,
    feet_from_slider_units,
    feet_to_500ths,
    feet_to_slider_units,
    units_from_500ths,
    units_to_500ths,
)
from sg_viewer.ui.background_image_dialog import BackgroundImageDialog
from sg_viewer.ui.generate_fsects_dialog import GenerateFsectsDialog
from sg_viewer.ui.heading_table_dialog import HeadingTableWindow
from sg_viewer.ui.scale_track_dialog import ScaleTrackDialog
from sg_viewer.ui.rotate_track_dialog import RotateTrackDialog
from sg_viewer.ui.section_table_dialog import SectionTableWindow
from sg_viewer.ui.xsect_table_dialog import XsectEntry, XsectTableWindow
from sg_viewer.ui.elevation_profile import (
    ElevationProfileData,
    elevation_profile_alt_bounds,
)
from sg_viewer.ui.xsect_elevation import XsectElevationData
from sg_viewer.rendering.fsection_style_map import FENCE_TYPE2
from sg_viewer.services import sg_rendering
from sg_viewer.ui.about import show_about_dialog

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
        self._current_profile: ElevationProfileData | None = None
        self._deferred_profile_refresh = False
        self._profile_dragging = False
        self._profile_editing = False
        self._calibrator_server_name = f"sg_viewer_calibrator_{uuid.uuid4().hex}"
        self._calibrator_server = QtNetwork.QLocalServer(self._window)
        self._calibrator_server.newConnection.connect(
            self._on_calibrator_values_received
        )
        QtNetwork.QLocalServer.removeServer(self._calibrator_server_name)
        self._calibrator_server.listen(self._calibrator_server_name)
        self._delete_shortcut = QtWidgets.QShortcut(
            QtGui.QKeySequence(QtCore.Qt.Key_Delete),
            self._window,
        )
        self._delete_shortcut.setContext(QtCore.Qt.WidgetWithChildrenShortcut)

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
        path = path.resolve()
        self._clear_background_state()
        logger.info("Loading SG file %s", path)
        try:
            self._window.preview.load_sg_file(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self._window, "Failed to load SG", str(exc))
            logger.exception("Failed to load SG file")
            return

        warnings = self._window.preview.last_load_warnings()
        if warnings:
            display_warnings = warnings[:5]
            extra_count = max(0, len(warnings) - len(display_warnings))
            details = "\n".join(f"• {warning}" for warning in display_warnings)
            if extra_count:
                details = f"{details}\n• ...and {extra_count} more"
            QtWidgets.QMessageBox.warning(
                self._window,
                "SG loaded with warnings",
                "This SG file has disconnected or invalid section links. "
                "The track has been loaded, but some sections may be unlinked.\n\n"
                f"{details}",
            )

        self._window.show_status_message(f"Loaded {path}")
        self._current_path = path
        self._is_untitled = False
        self._history.record_open(path)

        self._window.update_window_title(
            path=path,
            is_dirty=False,
        )

        self._window.set_table_actions_enabled(True)
        self._window.refresh_fsects_button.setEnabled(True)
        self._window.new_straight_button.setEnabled(True)
        self._window.new_curve_button.setEnabled(True)
        self._window.delete_section_button.setEnabled(True)
        self._window.preview.set_trk_comparison(None)
        sections, _ = self._window.preview.get_section_set()
        self._window.set_start_finish_button.setEnabled(bool(sections))
        self._window.split_section_button.setEnabled(bool(sections))
        self._window.split_section_button.setChecked(False)
        self._save_action.setEnabled(True)
        self._apply_saved_background(path)
        self._refresh_recent_menu()
        self._update_section_table()
        self._update_heading_table()
        self._update_xsect_table()
        self._populate_xsect_choices()
        self._refresh_elevation_profile()
        self._reset_altitude_range_for_track()
        self._update_track_length_display()


    def _create_actions(self) -> None:
        self._new_action = QtWidgets.QAction("New", self._window)
        self._new_action.setShortcut("Ctrl+N")
        self._new_action.triggered.connect(self._start_new_track)


        self._open_action = QtWidgets.QAction("Open SG…", self._window)
        self._open_action.setShortcut("Ctrl+O")
        self._open_action.triggered.connect(self._open_file_dialog)

        self._open_recent_menu = QtWidgets.QMenu("Open Recent", self._window)

        self._save_action = QtWidgets.QAction("Save SG As…", self._window)
        self._save_action.setShortcut("Ctrl+Shift+S")
        self._save_action.setEnabled(True)
        self._save_action.triggered.connect(self._save_file_dialog)

        self._recalc_action = QtWidgets.QAction(
            "Recalculate Lengths && DLONGs",
            self._window,
        )
        self._recalc_action.triggered.connect(self._recalculate_dlongs)

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

        self._about_action = QtWidgets.QAction("About SG Viewer", self._window)
        self._about_action.triggered.connect(self._show_about_dialog)

    def _create_menus(self) -> None:
        file_menu = self._window.menuBar().addMenu("&File")
        file_menu.addAction(self._new_action)
        file_menu.addSeparator()
        file_menu.addAction(self._open_action)
        file_menu.addMenu(self._open_recent_menu)
        file_menu.addAction(self._save_action)
        file_menu.addAction(self._open_background_action)
        file_menu.addAction(self._background_settings_action)
#        file_menu.addAction(self._calibrate_background_action)
        file_menu.addSeparator()
        file_menu.addAction(self._quit_action)

        tools_menu = self._window.menuBar().addMenu("Tools")
        tools_menu.addAction(self._recalc_action)
        tools_menu.addAction(self._scale_track_action)
        tools_menu.addAction(self._rotate_track_action)
        tools_menu.addAction(self._convert_trk_action)
        tools_menu.addAction(self._generate_fsects_action)
        tools_menu.addAction(self._raise_lower_elevations_action)
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
        self._window.refresh_fsects_button.clicked.connect(
            self._refresh_fsects_preview
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
        color = self._window.parse_hex_color(widget.text())
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
        if dragging:
            return

        if self._deferred_profile_refresh:
            self._deferred_profile_refresh = False
            self._refresh_elevation_profile()

    def _open_background_file_dialog(self) -> None:
        options = QtWidgets.QFileDialog.Options()
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._window,
            "Open Background Image",
            "",
            "Image files (*.png *.jpg *.jpeg *.bmp *.pcx);;All files (*)",
            options=options,
        )
        if not file_path:
            return

        try:
            self._window.preview.load_background_image(Path(file_path))
        except Exception as exc:
            QtWidgets.QMessageBox.critical(
                self._window, "Failed to load background", str(exc)
            )
            logger.exception("Failed to load background image")
            return

        self._background_settings_action.setEnabled(True)
        self._window.show_status_message(f"Loaded background image {file_path}")
        self._persist_background_state()

    def _show_background_settings_dialog(self) -> None:
        if not self._window.preview.has_background_image():
            QtWidgets.QMessageBox.information(
                self._window,
                "No Background",
                "Load a background image before adjusting its settings.",
            )
            return

        scale, (origin_u, origin_v) = self._window.preview.get_background_settings()
        dialog = BackgroundImageDialog(self._window, scale, origin_u, origin_v)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            new_scale, new_u, new_v = dialog.get_values()
            if new_scale <= 0:
                QtWidgets.QMessageBox.warning(
                    self._window,
                    "Invalid Scale",
                    "500ths per pixel must be greater than zero.",
                )
                return
            self._window.preview.set_background_settings(
                new_scale, (new_u, new_v)
            )
            self._window.show_status_message("Updated background image settings")
            self._persist_background_state()

    def _launch_background_calibrator(self) -> None:
        calibrator_path = Path(__file__).with_name("bg_calibrator_minimal.py")
        if not calibrator_path.exists():
            QtWidgets.QMessageBox.critical(
                self._window,
                "Calibrator Not Found",
                f"{calibrator_path} could not be located.",
            )
            logger.error("Background calibrator script missing at %s", calibrator_path)
            return

        try:
            command = [sys.executable, str(calibrator_path)]
            background_image_path = self._window.preview.get_background_image_path()
            if background_image_path is not None:
                command.append(str(background_image_path))
            command.extend(["--send-endpoint", self._calibrator_server_name])
            subprocess.Popen(command)
        except FileNotFoundError:
            QtWidgets.QMessageBox.critical(
                self._window,
                "Calibrator Not Found",
                f"{calibrator_path} could not be located.",
            )
            logger.exception("Failed to launch background calibrator")
            return

        self._window.show_status_message(
            "Opened background calibrator in a separate window"
        )

    def _on_calibrator_values_received(self) -> None:
        while self._calibrator_server.hasPendingConnections():
            socket = self._calibrator_server.nextPendingConnection()
            if socket is None:
                return
            if not socket.waitForReadyRead(1500):
                socket.disconnectFromServer()
                continue

            payload = bytes(socket.readAll()).decode("utf-8", errors="replace")
            socket.disconnectFromServer()
            try:
                data = json.loads(payload)
                scale = float(data["units_per_pixel"])
                upper_left = data["upper_left"]
                origin_u = float(upper_left[0])
                origin_v = float(upper_left[1])
                image_path_value = data.get("image_path")
                image_path = (
                    Path(image_path_value)
                    if isinstance(image_path_value, str) and image_path_value
                    else None
                )
            except (ValueError, TypeError, KeyError, IndexError, json.JSONDecodeError):
                logger.warning("Invalid background calibration payload: %s", payload)
                self._window.show_status_message(
                    "Ignored invalid calibration values from calibrator"
                )
                continue

            if scale <= 0:
                self._window.show_status_message(
                    "Ignored calibration values with non-positive scale"
                )
                continue

            if image_path is not None:
                try:
                    self._window.preview.load_background_image(image_path)
                except Exception:
                    logger.warning(
                        "Failed to load calibrator background image %s",
                        image_path,
                        exc_info=True,
                    )

            self._window.preview.set_background_settings(scale, (origin_u, origin_v))
            self._background_settings_action.setEnabled(
                self._window.preview.has_background_image()
            )
            self._persist_background_state()
            self._window.show_status_message(
                "Applied calibration values from background calibrator"
            )

    def _open_file_dialog(self) -> None:
        options = QtWidgets.QFileDialog.Options()
        file_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self._window,
            "Open SG file",
            "",
            "SG files (*.sg *.SG);;All files (*)",
            options=options,
        )
        if file_path:
            self.load_sg(Path(file_path))

    def _start_new_track(self, *, confirm: bool = True) -> None:
        if confirm and self._should_confirm_reset():
            response = QtWidgets.QMessageBox.question(
                self._window,
                "Start New Track?",
                "Any unsaved changes will be lost. Continue?",
            )
            if response != QtWidgets.QMessageBox.Yes:
                return

        self._clear_background_state()
        self._current_path = None
        self._window.preview.start_new_track()
        self._active_selection = None
        self._window.update_selection_sidebar(None)
        self._window.set_table_actions_enabled(False)
        self._xsect_table_action.setEnabled(True)
        self._window.refresh_fsects_button.setEnabled(False)
        self._window.delete_section_button.setEnabled(False)
        self._window.delete_section_button.setChecked(False)
        self._window.delete_section_button.setStyleSheet(self._delete_default_style)
        self._window.split_section_button.setChecked(False)
        self._window.split_section_button.setEnabled(False)
        self._window.set_start_finish_button.setEnabled(False)
        self._scale_track_action.setEnabled(False)
        self._rotate_track_action.setEnabled(False)
        self._raise_lower_elevations_action.setEnabled(False)
        self._update_xsect_table()
        self._populate_xsect_choices()
        self._refresh_elevation_profile()
        self._reset_altitude_range(0.0, 50.0)
        self._save_action.setEnabled(True)
        self._window.new_straight_button.setEnabled(True)
        self._window.new_curve_button.setEnabled(True)
        self._window.preview.set_trk_comparison(None)
        self._window.show_status_message(
            "New track ready. Click New Straight to start drawing."
        )
        self._is_untitled = True
        self._window.update_window_title(
            path=None,
            is_dirty=False,
            is_untitled=True,
        )
        self._update_track_length_display()

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
        if self._window.preview.sgfile is None:
            QtWidgets.QMessageBox.information(
                self._window, "No SG Loaded", "Load an SG file before saving."
            )
            return

        default_path = str(self._current_path) if self._current_path else ""
        options = QtWidgets.QFileDialog.Options()
        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self._window,
            "Save SG As",
            default_path,
            "SG files (*.sg *.SG);;All files (*)",
            options=options,
        )
        if not file_path:
            return

        path = Path(file_path)
        if path.suffix.lower() != ".sg":
            path = path.with_suffix(".sg")

        try:
            self._window.preview.save_sg(path)
        except Exception as exc:  # pragma: no cover - UI feedback only
            QtWidgets.QMessageBox.critical(
                self._window, "Failed to save SG", str(exc)
            )
            logger.exception("Failed to save SG file")
            return

        self._current_path = path
        self._window.show_status_message(f"Saved {path}")
        self._history.record_save(path)
        self._refresh_recent_menu()
        self._persist_background_state()
        self._convert_sg_to_csv(path)

        self._window.update_window_title(
            path=self._current_path,
            is_dirty=False,
        )

    def _recalculate_dlongs(self) -> None:
        preview = self._window.preview
        if not preview.recalculate_dlongs():
            return

        self._window.show_status_message(
            "Recalculated all curve lengths and DLONGs"
        )

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

    def _refresh_fsects_preview(self) -> None:
        if self._window.preview.refresh_fsections_preview():
            self._window.show_status_message(
                "Refreshed Fsects preview from current geometry."
            )
            if self._active_selection is not None:
                self._window.update_selection_sidebar(self._active_selection)
            return

        self._window.show_status_message(
            "Load an SG file with sections before refreshing Fsects preview."
        )


    def _convert_sg_to_csv(self, sg_path: Path) -> None:
        sg2csv_path = (
            Path(__file__).resolve().parents[2] / "icr2_core" / "trk" / "sg2csv.py"
        )

        try:
            result = subprocess.run(
                [sys.executable, str(sg2csv_path), str(sg_path)],
                cwd=sg2csv_path.parent,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:  # pragma: no cover - UI feedback only
            error_output = exc.stderr or exc.stdout or str(exc)
            QtWidgets.QMessageBox.warning(
                self._window,
                "CSV Export Failed",
                f"SG saved but CSV export failed:\n{error_output}",
            )
            logger.exception("Failed to convert SG to CSV")
            return

        if result.stdout:
            logger.info(result.stdout)
        self._window.show_status_message(
            f"Saved {sg_path} and exported CSVs next to it"
        )

    def _convert_sg_to_trk(self) -> None:
        sg_path = self._ensure_saved_sg()
        if sg_path is None:
            return
        try:
            self._window.preview.enable_trk_overlay()
        except Exception as exc:
            logger.exception("Failed to build TRK overlay", exc_info=exc)

        default_output = sg_path.with_suffix(".trk")
        options = QtWidgets.QFileDialog.Options()
        output_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self._window,
            "Save TRK As",
            str(default_output),
            "TRK files (*.trk *.TRK);;All files (*)",
            options=options,
        )
        if not output_path:
            return

        trk_path = Path(output_path)
        if trk_path.suffix.lower() != ".trk":
            trk_path = trk_path.with_suffix(".trk")

        sg2trk_path = (
            Path(__file__).resolve().parents[2] / "icr2_core" / "trk" / "sg2trk.py"
        )

        try:
            subprocess.run(
                [
                    sys.executable,
                    str(sg2trk_path),
                    str(sg_path),
                    "--format",
                    "trk",
                    "--output",
                    str(trk_path.with_suffix("")),
                ],
                cwd=sg2trk_path.parent,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:  # pragma: no cover - UI feedback only
            error_output = exc.stderr or exc.stdout or str(exc)
            QtWidgets.QMessageBox.warning(
                self._window,
                "TRK Export Failed",
                f"SG saved but TRK export failed:\n{error_output}",
            )
            logger.exception("Failed to convert SG to TRK")
            return

        if trk_path.exists():
            self._window.show_status_message(f"Saved TRK to {trk_path}")
        else:
            self._window.show_status_message("TRK export completed.")

    def _ensure_saved_sg(self) -> Path | None:
        if self._window.preview.sgfile is None:
            QtWidgets.QMessageBox.information(
                self._window, "No SG Loaded", "Load an SG file before exporting."
            )
            return None

        if self._current_path is None or self._window.preview.has_unsaved_changes:
            QtWidgets.QMessageBox.information(
                self._window,
                "Save Required",
                "Save the SG file before converting to TRK.",
            )
            self._save_file_dialog()

        if self._current_path is None or self._window.preview.has_unsaved_changes:
            return None

        return self._current_path

    def _start_new_straight(self) -> None:
        self._window.delete_section_button.setChecked(False)
        self._window.split_section_button.setChecked(False)
        if not self._window.preview.begin_new_straight():
            self._window.show_status_message(
                "Start a new track or load an SG file before creating new straights."
            )
            self._on_new_straight_mode_changed(False)
            return

        self._window.show_status_message(
            "Click to place the start of the new straight."
        )

    def _start_new_curve(self) -> None:
        self._window.delete_section_button.setChecked(False)
        self._window.split_section_button.setChecked(False)
        if not self._window.preview.begin_new_curve():
            self._window.show_status_message(
                "Create a track with an unconnected node before adding a curve."
            )
            self._on_new_curve_mode_changed(False)
            return

        self._window.show_status_message(
            "Click an unconnected node to start the new curve."
        )

    def _toggle_delete_section_mode(self, checked: bool) -> None:
        if checked:
            self._window.new_straight_button.setChecked(False)
            self._window.new_curve_button.setChecked(False)
            self._window.split_section_button.setChecked(False)
            if not self._window.preview.begin_delete_section():
                self._window.delete_section_button.setChecked(False)
                return
            self._window.show_status_message("Click a section to delete it.")
        else:
            self._window.preview.cancel_delete_section()

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
        if checked:
            self._window.delete_section_button.setChecked(False)
            self._window.new_curve_button.setChecked(False)
            self._window.split_section_button.setChecked(False)
            self._start_new_straight()
            return

        self._window.preview.cancel_creation()

    def _toggle_new_curve_mode(self, checked: bool) -> None:
        if checked:
            self._window.delete_section_button.setChecked(False)
            self._window.new_straight_button.setChecked(False)
            self._window.split_section_button.setChecked(False)
            self._start_new_curve()
            return

        self._window.preview.cancel_creation()

    def _toggle_split_section_mode(self, checked: bool) -> None:
        if checked:
            self._window.delete_section_button.setChecked(False)
            self._window.new_straight_button.setChecked(False)
            self._window.new_curve_button.setChecked(False)
            if not self._window.preview.begin_split_section():
                self._window.split_section_button.setChecked(False)
                return
            self._window.show_status_message(
                "Hover over a section to choose where to split it."
            )
        else:
            self._window.preview.cancel_split_section()

    def _toggle_move_section_mode(self, checked: bool) -> None:
        self._window.preview.set_section_drag_enabled(checked)
        self._on_move_section_mode_changed(checked)

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
        sections, _ = self._window.preview.get_section_set()
        has_sections = bool(sections)

        self._window.delete_section_button.setEnabled(has_sections)
        self._window.split_section_button.setEnabled(has_sections)
        self._window.move_section_button.setEnabled(has_sections)
        if not has_sections:
            self._window.delete_section_button.setChecked(False)
            self._window.delete_section_button.setStyleSheet(
                self._delete_default_style
            )
        if not has_sections:
            self._window.split_section_button.setChecked(False)
        self._window.set_start_finish_button.setEnabled(has_sections)
        self._section_table_action.setEnabled(has_sections)
        self._heading_table_action.setEnabled(has_sections)
        self._window.refresh_fsects_button.setEnabled(
            has_sections and self._window.preview.sgfile is not None
        )
        self._scale_track_action.setEnabled(
            has_sections and is_closed_loop(sections)
        )
        self._rotate_track_action.setEnabled(has_sections)
        self._raise_lower_elevations_action.setEnabled(has_sections)

        # Save is allowed once anything exists or changes
        self._save_action.setEnabled(True)

        # Mark document dirty
        if self._is_untitled:
            self._window.update_window_title(
                path=None,
                is_dirty=True,
                is_untitled=True,
            )
        elif self._current_path is not None:
            self._window.update_window_title(
                path=self._current_path,
                is_dirty=True,
            )

        if self._window.preview.is_interaction_dragging:
            self._deferred_profile_refresh = True
        else:
            self._refresh_elevation_profile()
        self._refresh_elevation_inputs()
        self._update_track_length_display()
        self._update_copy_xsect_button()
        self._update_copy_fsects_buttons()
        self._update_fsect_edit_buttons()

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
        sections, _ = self._window.preview.get_section_set()
        if not sections or not is_closed_loop(sections):
            QtWidgets.QMessageBox.information(
                self._window,
                "Scale Track",
                "Scaling is only available when the track forms a closed loop.",
            )
            return

        try:
            current_length = loop_length(sections)
        except ValueError:
            QtWidgets.QMessageBox.information(
                self._window,
                "Scale Track",
                "Scaling is only available when the track forms a closed loop.",
            )
            return

        dialog = ScaleTrackDialog(self._window, current_length)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return

        target_length = dialog.get_target_length()
        if target_length <= 0:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Scale Track",
                "Desired track length must be greater than zero.",
            )
            return

        if math.isclose(target_length, current_length, rel_tol=1e-6):
            self._window.show_status_message("Track already at desired length.")
            return

        status = self._window.preview.scale_track_to_length(target_length)
        if not status:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Scale Track",
                "Scaling could not be applied. Ensure the track is a valid closed loop.",
            )
            return

        self._window.show_status_message(status)
        self._update_track_length_display()

    def _open_rotate_track_dialog(self) -> None:
        sections, _ = self._window.preview.get_section_set()
        if not sections:
            QtWidgets.QMessageBox.information(
                self._window,
                "Rotate Track",
                "There are no track sections available to rotate.",
            )
            return

        original_sections = list(sections)
        dialog = RotateTrackDialog(self._window)
        dialog.angleChanged.connect(
            lambda angle_deg: self._apply_track_rotation_preview(
                original_sections,
                angle_deg,
            )
        )

        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            self._window.preview.set_sections(original_sections)
            return

        self._window.show_status_message(
            f"Rotated track by {dialog.angle_degrees():+.1f}° around origin."
        )

    def _apply_track_rotation_preview(
        self,
        base_sections: list[SectionPreview],
        angle_degrees: float,
    ) -> None:
        angle_radians = math.radians(angle_degrees)
        rotated_sections = [rotate_section(section, angle_radians) for section in base_sections]
        self._window.preview.set_sections(rotated_sections)

    def _open_generate_fsects_dialog(self) -> None:
        sections, _ = self._window.preview.get_section_set()
        if not sections:
            QtWidgets.QMessageBox.information(
                self._window,
                "No Sections",
                "There are no track sections available for fsect generation.",
            )
            return

        dialog = GenerateFsectsDialog(
            self._window,
            unit_label=self._window.fsect_display_unit_label(),
            decimals=self._window.fsect_display_decimals(),
            step=self._window.fsect_display_step(),
            track_width=30.0,
            left_grass_width=10.0,
            right_grass_width=10.0,
            grass_surface_type=0,
            wall_surface_type=7,
            fence_enabled=False,
        )
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return

        track_width = self._window.fsect_dlat_from_display_units(dialog.track_width())
        left_grass = self._window.fsect_dlat_from_display_units(
            dialog.left_grass_width()
        )
        right_grass = self._window.fsect_dlat_from_display_units(
            dialog.right_grass_width()
        )
        grass_surface_type = dialog.grass_surface_type()
        wall_surface_type = dialog.wall_surface_type()
        if track_width <= 0:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Invalid Track Width",
                "Track width must be greater than zero.",
            )
            return
        if left_grass < 0 or right_grass < 0:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Invalid Grass Width",
                "Grass widths must be zero or greater.",
            )
            return

        wall_width = self._window.fsect_dlat_from_display_units(
            self._window.fsect_display_step()
        )
        if wall_width <= 0:
            wall_width = 1.0

        base_fsects = self._build_generated_fsects(
            template=dialog.template(),
            track_width=track_width,
            left_grass=left_grass,
            right_grass=right_grass,
            grass_surface_type=grass_surface_type,
            wall_surface_type=wall_surface_type,
            wall_width=wall_width,
            fence_enabled=dialog.fence_enabled(),
        )
        fsects_by_section = [list(base_fsects) for _ in sections]
        if not self._window.preview.replace_all_fsects(fsects_by_section):
            QtWidgets.QMessageBox.warning(
                self._window,
                "Generate Fsects Failed",
                "Unable to apply generated fsects to the current track.",
            )
            return

        if not self._window.sg_fsects_checkbox.isChecked():
            self._window.sg_fsects_checkbox.setChecked(True)
        self._window.show_status_message("Generated fsects for all sections.")

    @staticmethod
    def _build_generated_fsects(
        *,
        template: str,
        track_width: float,
        left_grass: float,
        right_grass: float,
        grass_surface_type: int,
        wall_surface_type: int,
        wall_width: float,
        fence_enabled: bool,
    ) -> list[PreviewFSection]:
        fence_type2 = min(FENCE_TYPE2) if fence_enabled and FENCE_TYPE2 else 0

        def wall(start: float, end: float) -> PreviewFSection:
            return PreviewFSection(
                start_dlat=start,
                end_dlat=start,
                surface_type=wall_surface_type,
                type2=fence_type2,
            )

        def surface(start: float, end: float, surface_type: int) -> PreviewFSection:
            return PreviewFSection(
                start_dlat=start,
                end_dlat=start,
                surface_type=surface_type,
                type2=0,
            )

        fsects: list[PreviewFSection] = []
        half_track = track_width * 0.5

        if template == "street":
            fsects.append(wall(-half_track, -half_track))
            fsects.append(surface(-half_track, half_track, 5))
            fsects.append(wall(half_track, half_track + wall_width))
            return fsects

        if template == "oval":
            fsects.append(wall(-half_track, -half_track))
            fsects.append(surface(-half_track, half_track, 5))
            if left_grass > 0:
                fsects.append(
                    surface(half_track, half_track + left_grass, grass_surface_type)
                )
            fsects.append(
                wall(half_track + left_grass, half_track + left_grass + wall_width)
            )
            return fsects

        fsects.append(
            wall(-half_track - right_grass, -half_track - right_grass)
        )
        if right_grass > 0:
            fsects.append(
                surface(-half_track - right_grass, -half_track, grass_surface_type)
            )
        fsects.append(surface(-half_track, half_track, 5))
        if left_grass > 0:
            fsects.append(
                surface(half_track, half_track + left_grass, grass_surface_type)
            )
        fsects.append(
            wall(half_track + left_grass, half_track + left_grass + wall_width)
        )
        return fsects

    def _populate_xsect_choices(self, preferred_index: int | None = None) -> None:
        metadata = self._window.preview.get_xsect_metadata()
        combo = self._window.xsect_combo
        unit = str(self._window.measurement_units_combo.currentData())
        unit_label = {"feet": "ft", "meter": "m", "inch": "in", "500ths": "500ths"}.get(unit, "500ths")
        decimals = {"feet": 1, "meter": 3, "inch": 1, "500ths": 0}.get(unit, 0)

        combo.blockSignals(True)
        combo.clear()
        for idx, dlat in metadata:
            display_dlat = units_from_500ths(dlat, unit)
            if decimals == 0:
                formatted_dlat = f"{int(round(display_dlat))}"
            else:
                formatted_dlat = f"{display_dlat:.{decimals}f}".rstrip("0").rstrip(".")
            combo.addItem(f"{idx} (DLAT {formatted_dlat} {unit_label})", idx)
        combo.setEnabled(bool(metadata))
        if metadata:
            target_index = 0
            if preferred_index is not None:
                target_index = max(0, min(preferred_index, len(metadata) - 1))
            combo.setCurrentIndex(target_index)
        combo.blockSignals(False)
        self._update_copy_xsect_button()

    def _refresh_elevation_profile(self) -> None:
        combo = self._window.xsect_combo
        if not combo.isEnabled():
            self._window.preview.set_selected_xsect_index(None)
            self._window.profile_widget.set_profile_data(None)
            self._current_profile = None
            self._refresh_elevation_inputs()
            self._refresh_xsect_elevation_panel()
            return

        current_index = combo.currentData()
        if current_index is None:
            current_index = combo.currentIndex()
        self._window.preview.set_selected_xsect_index(int(current_index))

        samples_per_section = self._current_samples_per_section()
        profile = self._window.preview.build_elevation_profile(
            int(current_index),
            samples_per_section=samples_per_section,
        )
        if profile is not None:
            profile.unit = self._window.xsect_altitude_unit()
            profile.unit_label = self._window.xsect_altitude_unit_label()
            profile.decimals = self._window.xsect_altitude_display_decimals()
            global_bounds: tuple[float, float] | None = None
            if (
                (self._profile_dragging or self._profile_editing)
                and self._current_profile is not None
            ):
                global_bounds = self._current_profile.y_range
            else:
                global_bounds = self._window.preview.get_elevation_profile_bounds(
                    samples_per_section=samples_per_section
                )
            if global_bounds is not None:
                profile.y_range = global_bounds
        self._window.profile_widget.set_profile_data(profile)
        self._current_profile = profile
        self._refresh_elevation_inputs()
        self._update_copy_xsect_button()
        self._refresh_xsect_elevation_panel()

    def _current_samples_per_section(self) -> int:
        return 10

    def _clear_background_state(self) -> None:
        self._window.preview.clear_background_image()
        self._background_settings_action.setEnabled(False)
#        self._calibrate_background_action.setEnabled(False)

    def _apply_saved_background(self, sg_path: Path | None = None) -> None:
        path = sg_path or self._current_path
        if path is None:
            return

        background_data = self._history.get_background(path)
        if not background_data:
            return

        image_path, scale, origin = background_data
        if not image_path.exists():
            logger.info("Stored background image %s is missing", image_path)
            return

        try:
            self._window.preview.load_background_image(image_path)
            self._window.preview.set_background_settings(scale, origin)
        except Exception as exc:  # pragma: no cover - UI feedback only
            logger.exception("Failed to restore background image", exc_info=exc)
            self._window.show_status_message(
                f"Could not restore background image {image_path}"
            )
            return

        self._background_settings_action.setEnabled(True)
#        self._calibrate_background_action.setEnabled(True)
        self._window.show_status_message(
            f"Restored background image {image_path} for {path.name}"
        )

    def _persist_background_state(self) -> None:
        if self._current_path is None:
            return

        background_path = self._window.preview.get_background_image_path()
        if background_path is None:
            return

        scale, origin = self._window.preview.get_background_settings()
        self._history.set_background(self._current_path, background_path, scale, origin)

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
        self._window.update_selection_sidebar(selection)
        self._refresh_elevation_inputs()
        self._refresh_xsect_elevation_panel()
        self._update_copy_fsects_buttons()
        self._update_fsect_edit_buttons()

    def _on_profile_section_clicked(self, section_index: int) -> None:
        self._window.preview.selection_manager.set_selected_section(section_index)

    def _on_profile_altitude_dragged(self, section_index: int, altitude: float) -> None:
        xsect_index = self._current_xsect_index()
        if xsect_index is None:
            return

        self._profile_dragging = True
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
            self._profile_dragging = False

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
        selection = self._active_selection
        xsect_index = self._current_xsect_index()
        if selection is None or xsect_index is None:
            self._window.update_elevation_inputs(None, None, False)
            return

        altitude, grade = self._window.preview.get_section_xsect_values(
            selection.index, xsect_index
        )
        enabled = altitude is not None and grade is not None
        self._window.update_elevation_inputs(altitude, grade, enabled)

    def _on_altitude_slider_changed(self, value: int) -> None:
        self._window.update_altitude_display(value)
        self._profile_editing = True
        self._apply_altitude_edit()

    def _on_altitude_slider_released(self) -> None:
        self._window.preview.validate_document()
        if self._profile_editing:
            self._profile_editing = False
            self._refresh_elevation_profile()

    def _on_altitude_range_changed(self, changed: str | None = None) -> None:
        min_spin = self._window.altitude_min_spin
        max_spin = self._window.altitude_max_spin
        min_value = self._window.altitude_display_to_feet(min_spin.value())
        max_value = self._window.altitude_display_to_feet(max_spin.value())
        min_gap = self._window.altitude_display_step()
        min_gap_feet = self._window.altitude_display_to_feet(min_gap)
        if min_value >= max_value:
            if changed == "min":
                max_value = min(
                    min_value + min_gap_feet,
                    self._window.altitude_display_to_feet(max_spin.maximum()),
                )
                max_spin.blockSignals(True)
                max_spin.setValue(self._window.feet_to_altitude_display(max_value))
                max_spin.blockSignals(False)
            else:
                min_value = max(
                    max_value - min_gap_feet,
                    self._window.altitude_display_to_feet(min_spin.minimum()),
                )
                min_spin.blockSignals(True)
                min_spin.setValue(self._window.feet_to_altitude_display(min_value))
                min_spin.blockSignals(False)

        min_slider = feet_to_slider_units(min_value)
        max_slider = feet_to_slider_units(max_value)
        self._window.altitude_slider.setRange(min_slider, max_slider)
        slider_value = self._window.altitude_slider.value()
        if slider_value < min_slider:
            self._window.altitude_slider.setValue(min_slider)
        elif slider_value > max_slider:
            self._window.altitude_slider.setValue(max_slider)

    def _open_altitude_range_dialog(self) -> None:
        dialog = QtWidgets.QDialog(self._window)
        dialog.setWindowTitle("Set Elevation Range")
        layout = QtWidgets.QFormLayout(dialog)
        min_spin = QtWidgets.QDoubleSpinBox(dialog)
        max_spin = QtWidgets.QDoubleSpinBox(dialog)
        source_min = self._window.altitude_min_spin
        source_max = self._window.altitude_max_spin
        min_spin.setDecimals(source_min.decimals())
        max_spin.setDecimals(source_max.decimals())
        min_spin.setSingleStep(source_min.singleStep())
        max_spin.setSingleStep(source_max.singleStep())
        min_spin.setSuffix(source_min.suffix())
        max_spin.setSuffix(source_max.suffix())
        min_spin.setRange(source_min.minimum(), source_min.maximum())
        max_spin.setRange(source_max.minimum(), source_max.maximum())
        min_spin.setValue(source_min.value())
        max_spin.setValue(source_max.value())
        layout.addRow("Minimum:", min_spin)
        layout.addRow("Maximum:", max_spin)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return

        min_value = min_spin.value()
        max_value = max_spin.value()
        min_gap = source_min.singleStep()
        if min_value >= max_value:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Invalid Elevation Range",
                "Minimum elevation must be less than maximum elevation.",
            )
            return
        if max_value - min_value < min_gap:
            max_value = min_value + min_gap

        source_min.setValue(min_value)
        source_max.setValue(max_value)

    def _open_grade_range_dialog(self) -> None:
        dialog = QtWidgets.QDialog(self._window)
        dialog.setWindowTitle("Set Grade Range")
        layout = QtWidgets.QFormLayout(dialog)
        min_spin = QtWidgets.QSpinBox(dialog)
        max_spin = QtWidgets.QSpinBox(dialog)
        min_spin.setRange(-5000, 4999)
        max_spin.setRange(-4999, 5000)
        min_spin.setValue(self._window.grade_spin.minimum())
        max_spin.setValue(self._window.grade_spin.maximum())
        layout.addRow("Minimum:", min_spin)
        layout.addRow("Maximum:", max_spin)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return

        min_value = min_spin.value()
        max_value = max_spin.value()
        if min_value >= max_value:
            QtWidgets.QMessageBox.warning(
                self._window,
                "Invalid Grade Range",
                "Minimum grade must be less than maximum grade.",
            )
            return

        self._window.grade_spin.setRange(min_value, max_value)
        current_value = self._window.grade_spin.value()
        if current_value < min_value:
            self._window.grade_spin.setValue(min_value)
        elif current_value > max_value:
            self._window.grade_spin.setValue(max_value)

    def _open_raise_lower_elevations_dialog(self) -> None:
        if self._window.preview.sgfile is None:
            QtWidgets.QMessageBox.information(
                self._window,
                "No SG Loaded",
                "Load an SG file before adjusting elevations.",
            )
            return

        dialog = QtWidgets.QDialog(self._window)
        dialog.setWindowTitle("Raise/Lower All Elevations")
        layout = QtWidgets.QFormLayout(dialog)

        amount_spin = QtWidgets.QDoubleSpinBox(dialog)
        unit_combo = QtWidgets.QComboBox(dialog)
        unit_combo.addItem("Feet", "feet")
        unit_combo.addItem("Meter", "meter")
        unit_combo.addItem("Inch", "inch")
        unit_combo.addItem("500ths", "500ths")
        current_unit = str(self._window.measurement_units_combo.currentData())
        current_index = unit_combo.findData(current_unit)
        if current_index >= 0:
            unit_combo.setCurrentIndex(current_index)

        unit_decimals = {"feet": 1, "meter": 3, "inch": 1, "500ths": 0}
        unit_steps = {"feet": 0.1, "meter": 0.05, "inch": 1.0, "500ths": 50.0}
        unit_labels = {"feet": "ft", "meter": "m", "inch": "in", "500ths": "500ths"}

        def _sync_spin_for_unit() -> None:
            unit = str(unit_combo.currentData())
            amount_spin.setDecimals(unit_decimals.get(unit, 0))
            amount_spin.setSingleStep(unit_steps.get(unit, 1.0))
            amount_spin.setSuffix(f" {unit_labels.get(unit, unit)}")
            amount_spin.setRange(-1_000_000_000, 1_000_000_000)

        unit_combo.currentIndexChanged.connect(_sync_spin_for_unit)
        _sync_spin_for_unit()

        layout.addRow("Change by:", amount_spin)
        layout.addRow("Unit of Measurement:", unit_combo)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)

        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return

        delta_display = amount_spin.value()
        unit = str(unit_combo.currentData())
        delta = units_to_500ths(delta_display, unit)
        if delta == 0:
            return
        self._window.show_status_message("Updating elevations…")
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        update_successful = False
        try:
            if not self._window.preview.offset_all_elevations(delta):
                QtWidgets.QMessageBox.warning(
                    self._window,
                    "Elevation Update Failed",
                    "Unable to update elevations. Ensure elevation data is available.",
                )
                return
            self._refresh_elevation_profile()
            update_successful = True
        finally:
            QtWidgets.QApplication.restoreOverrideCursor()
            if update_successful:
                self._window.show_status_message("Elevations updated.")

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
            self._refresh_elevation_profile()
            self._refresh_xsect_elevation_panel()
            self._refresh_xsect_elevation_table()

    def _apply_grade_edit(self) -> None:
        selection = self._active_selection
        xsect_index = self._current_xsect_index()
        if selection is None or xsect_index is None:
            return

        grade = self._window.grade_spin.value()
        if self._window.preview.set_section_xsect_grade(
            selection.index, xsect_index, grade, validate=False
        ):
            self._refresh_elevation_profile()
            self._refresh_xsect_elevation_panel()
            self._refresh_xsect_elevation_table()

    def _copy_xsect_to_all(self) -> None:
        xsect_index = self._current_xsect_index()
        if xsect_index is None:
            return

        sections, _ = self._window.preview.get_section_set()
        if not sections:
            QtWidgets.QMessageBox.information(
                self._window,
                "No Sections",
                "Load an SG file with sections before copying x-section data.",
            )
            return

        response = QtWidgets.QMessageBox.warning(
            self._window,
            "Copy X-Section Data?",
            (
                "This will replace every other x-section's altitude and grade data "
                "with the values from the selected x-section.\n\nContinue?"
            ),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if response != QtWidgets.QMessageBox.Yes:
            return

        if not self._window.preview.copy_xsect_data_to_all(xsect_index):
            QtWidgets.QMessageBox.warning(
                self._window,
                "Copy Failed",
                "Unable to copy x-section data. Ensure all sections have elevation data.",
            )
            return

        self._refresh_elevation_profile()
        self._refresh_xsect_elevation_panel()
        self._window.show_status_message(
            f"Copied x-section {xsect_index} data to all x-sections."
        )

    def _copy_fsects_to_previous(self) -> None:
        self._copy_fsects_to_neighbor(direction="previous")

    def _copy_fsects_to_next(self) -> None:
        self._copy_fsects_to_neighbor(direction="next")

    def _copy_fsects_to_neighbor(self, *, direction: str) -> None:
        selection = self._active_selection
        if selection is None:
            return
        if direction == "previous":
            target_index = selection.previous_id
        elif direction == "next":
            target_index = selection.next_id
        else:
            return

        sections, _ = self._window.preview.get_section_set()
        if target_index < 0 or target_index >= len(sections):
            QtWidgets.QMessageBox.information(
                self._window,
                "Copy Fsects",
                f"No {direction} section is connected to this section.",
            )
            return

        edge = "start" if direction == "previous" else "end"
        if not self._window.preview.copy_section_fsects(
            selection.index, target_index, edge=edge
        ):
            QtWidgets.QMessageBox.warning(
                self._window,
                "Copy Failed",
                "Unable to copy fsect data to the requested section.",
            )
            return

        self._window.preview.selection_manager.set_selected_section(target_index)
        self._window.show_status_message(
            f"Copied fsects from section {selection.index} to {direction} section {target_index}."
        )

    def _add_fsect_below_selected(self) -> None:
        selection = self._active_selection
        if selection is None:
            return
        section_index = selection.index
        fsects = self._window.preview.get_section_fsects(section_index)
        if not fsects:
            new_fsect = PreviewFSection(
                start_dlat=-300000,
                end_dlat=-300000,
                surface_type=7,
                type2=0,
            )
            insert_index = 0
        else:
            row_index = self._window.fsect_table.currentRow()
            if row_index < 0 or row_index >= len(fsects):
                self._window.show_status_message(
                    "Select an Fsect row to add below."
                )
                return
            current = fsects[row_index]
            new_fsect = PreviewFSection(
                start_dlat=current.start_dlat,
                end_dlat=current.end_dlat,
                surface_type=current.surface_type,
                type2=current.type2,
            )
            insert_index = row_index + 1
        self._window.preview.insert_fsection(
            section_index,
            insert_index,
            new_fsect,
        )
        self._window.update_selection_sidebar(selection)
        self._window.fsect_table.setCurrentCell(insert_index, 0)
        self._update_fsect_edit_buttons()
        self._window.show_status_message(
            f"Added fsect at row {insert_index}."
        )

    def _delete_selected_fsect(self) -> None:
        selection = self._active_selection
        if selection is None:
            return
        row_index = self._window.fsect_table.currentRow()
        fsects = self._window.preview.get_section_fsects(selection.index)
        if row_index < 0 or row_index >= len(fsects):
            self._window.show_status_message(
                "Select an Fsect row to delete."
            )
            return
        self._window.preview.delete_fsection(selection.index, row_index)
        self._window.update_selection_sidebar(selection)
        remaining = len(self._window.preview.get_section_fsects(selection.index))
        if remaining:
            self._window.fsect_table.setCurrentCell(
                min(row_index, remaining - 1),
                0,
            )
        self._update_fsect_edit_buttons()
        self._window.show_status_message(
            f"Deleted fsect row {row_index}."
        )

    def _on_grade_slider_changed(self, value: int) -> None:
        self._window.update_grade_display(value)
        self._profile_editing = True
        self._apply_grade_edit()

    def _on_grade_edit_finished(self) -> None:
        self._window.preview.validate_document()
        if self._profile_editing:
            self._profile_editing = False
            self._refresh_elevation_profile()

    def _refresh_xsect_elevation_panel(self) -> None:
        selection = self._active_selection
        if selection is None:
            self._window.xsect_elevation_widget.set_xsect_data(None)
            self._refresh_xsect_elevation_table()
            return

        altitudes = self._window.preview.get_section_xsect_altitudes(selection.index)
        metadata = self._window.preview.get_xsect_metadata()
        xsect_dlats = [dlat for _, dlat in metadata] if metadata else None
        y_range = (
            elevation_profile_alt_bounds(self._current_profile)
            if self._current_profile is not None
            else None
        )
        self._window.xsect_elevation_widget.set_xsect_data(
            XsectElevationData(
                section_index=selection.index,
                altitudes=[
                    float(value) if value is not None else None for value in altitudes
                ],
                xsect_dlats=xsect_dlats,
                selected_xsect_index=self._current_xsect_index(),
                y_range=y_range,
                unit=self._window.xsect_altitude_unit(),
                unit_label=self._window.xsect_altitude_unit_label(),
                decimals=self._window.xsect_altitude_display_decimals(),
            )
        )
        self._refresh_xsect_elevation_table()

    def _refresh_xsect_elevation_table(self) -> None:
        selection = self._active_selection
        if selection is None:
            self._window.update_xsect_elevation_table(
                [], [], None, enabled=False
            )
            return

        altitudes = self._window.preview.get_section_xsect_altitudes(selection.index)
        grades = self._window.preview.get_section_xsect_grades(selection.index)
        enabled = bool(altitudes) and bool(grades)
        self._window.update_xsect_elevation_table(
            altitudes,
            grades,
            self._current_xsect_index(),
            enabled=enabled,
        )

    def _on_measurement_units_changed(self) -> None:
        self._history.set_measurement_unit(
            str(self._window.measurement_units_combo.currentData())
        )
        selected_xsect = self._current_xsect_index()
        self._populate_xsect_choices(preferred_index=selected_xsect)
        self._refresh_elevation_inputs()
        self._window.update_xsect_table_headers()
        self._refresh_xsect_elevation_table()
        self._refresh_xsect_elevation_panel()
        self._update_track_length_display()
        self._window.update_selection_sidebar(self._active_selection)

    def _on_xsect_table_cell_changed(self, row_index: int, column_index: int) -> None:
        if self._window.is_updating_xsect_table:
            return
        if column_index not in (1, 2):
            return
        selection = self._active_selection
        if selection is None:
            return
        item = self._window.xsect_elevation_table.item(row_index, column_index)
        if item is None:
            return
        text = item.text().strip()
        if not text:
            self._refresh_xsect_elevation_table()
            return

        if column_index == 1:
            try:
                display_value = float(text)
            except ValueError:
                self._refresh_xsect_elevation_table()
                return
            altitude = self._window.xsect_altitude_from_display_units(display_value)
            if self._window.preview.set_section_xsect_altitude(
                selection.index, row_index, altitude, validate=False
            ):
                self._refresh_elevation_profile()
                self._refresh_xsect_elevation_panel()
                self._refresh_xsect_elevation_table()
        else:
            try:
                grade = int(text)
            except ValueError:
                self._refresh_xsect_elevation_table()
                return
            if self._window.preview.set_section_xsect_grade(
                selection.index, row_index, grade, validate=False
            ):
                self._refresh_elevation_profile()
                self._refresh_xsect_elevation_panel()
                self._refresh_xsect_elevation_table()

        if row_index == self._current_xsect_index():
            self._refresh_elevation_inputs()
