"""
control_panel.py

Control panel window now built from control_panel.ui (Qt Designer).
Uses OverlayManager (multi-overlay) + ProfileManager.
"""

import time
import os, sys
from PyQt5 import QtWidgets, QtCore, uic


import logging
log = logging.getLogger(__name__)

from icr2timing.overlays.running_order_overlay import (
    RunningOrderOverlayTable,
    AVAILABLE_FIELDS,
)
from icr2timing.ui.overlay_controller import OverlayController
from icr2timing.ui.profile_manager import ProfileManager, Profile
from icr2timing.ui.control_panel_presenter import ControlPanelPresenter
from icr2timing.ui.control_sections import (
    OverlayControlsSection,
    ProfileManagementSection,
    RadarSettingsSection,
    TelemetryControlsSection,
)
from icr2timing.overlays.proximity_overlay import ProximityOverlay
from icr2timing.overlays.track_map_overlay import TrackMapOverlay
from icr2timing.overlays.experimental_track_surface_overlay import (
    ExperimentalTrackSurfaceOverlay,
)
from icr2timing.overlays.individual_car_overlay import IndividualCarOverlay
from icr2timing.core.config import Config
from icr2timing.core.version import __version__
from icr2timing.ui.services import TelemetryServiceController


class ControlPanel(QtWidgets.QMainWindow):
    exe_path_changed = QtCore.pyqtSignal(str)

    def __init__(self, updater, mem=None, cfg=None, shutdown_hook=None):
        super().__init__()
        uic.loadUi(
            os.path.join(os.path.dirname(__file__), "control_panel.ui"),
            self
        )

        self.updater = updater
        self._mem = mem
        self._config_store = Config.store()
        self._cfg = cfg or self._config_store.config
        self._config_store.config_changed.connect(self._on_config_changed)
        self._latest_state = None
        self._shutdown_hook = shutdown_hook

        # --- Overlay Manager ---
        self.ro_overlay = RunningOrderOverlayTable()

        # Radar handled separately (not added to OverlayManager)
        self.prox_overlay = ProximityOverlay()

        # After creating self.prox_overlay
        self.radar_settings = RadarSettingsSection(
            overlay=self.prox_overlay,
            config_store=self._config_store,
            parent=self,
            spin_width=self.spinRadarWidth,
            spin_height=self.spinRadarHeight,
            spin_forward=self.spinRadarForward,
            spin_rear=self.spinRadarRear,
            spin_side=self.spinRadarSide,
            combo_symbol=self.comboRadarSymbol,
            btn_player_color=self.btnPlayerColor,
            btn_ahead_color=self.btnAheadColor,
            btn_behind_color=self.btnBehindColor,
            btn_along_color=self.btnAlongColor,
            color_button_setter=self._set_button_color,
        )

        # Track map overlay
        self.track_overlay = TrackMapOverlay()

        # Experimental surface overlay
        self.surface_overlay = ExperimentalTrackSurfaceOverlay()
        self.surface_overlay.set_scale_factor(self.track_overlay._scale_factor)

        # Individual car overlay
        self.indiv_overlay = IndividualCarOverlay(
            mem=self._mem, cfg=self._cfg, status_callback=self.statusbar.showMessage
        )
        self.indiv_overlay.set_status_callback(self.statusbar.showMessage)

        self.overlay_controller = OverlayController(
            updater=self.updater,
            config_store=self._config_store,
            running_order_overlay=self.ro_overlay,
            radar_overlay=self.prox_overlay,
            track_overlay=self.track_overlay,
            surface_overlay=self.surface_overlay,
            individual_overlay=self.indiv_overlay,
            running_order_state_handler=self._on_state_updated_with_fps,
        )

        # Profile / session managers
        self.profiles = ProfileManager()

        if self.updater:
            self.updater.error.connect(self._on_error_from_updater)

        # --- Telemetry Lap Logger ---
        self.telemetry_controls = TelemetryControlsSection(
            btn_lap_logger=self.btnLapLogger,
            btn_release_all=self.btnReleaseAllCars,
            btn_force_pits=self.btnForcePitStops,
            btn_toggle_individual=self.btnToggleIndividualTelemetry,
            select_individual_car=self.selectIndividualCar,
            parent=self,
        )

        self.telemetry_controller = TelemetryServiceController(
            updater=self.updater,
            mem=self._mem,
            cfg=self._cfg,
            telemetry_controls=self.telemetry_controls,
            profile_manager=self.profiles,
            state_provider=self._current_state,
            status_callback=self.statusbar.showMessage,
            parent=self,
        )
        self.telemetry_controller.individual_overlay_toggle_requested.connect(
            self._on_individual_overlay_toggle_requested
        )
        self.telemetry_controller.individual_car_selected.connect(
            self._on_select_individual_car
        )

        self.presenter = ControlPanelPresenter(
            parent=self,
            profile_manager=self.profiles,
            running_order_overlay=self.ro_overlay,
            profile_combo=self.profileCombo,
            fields_list=self.fieldsList,
            custom_field_list=self.customFieldList,
            spin_pos_change_duration=self.spinPosChangeDuration,
            indicator_label=self.lblPositionIndicatorDuration,
            combo_columns=self.comboCols,
            radio_time=self.radioTime,
            radio_speed=self.radioSpeed,
            cb_sort_best=self.cbSortBest,
            cb_abbrev=self.cbAbbrev,
            prox_overlay=self.prox_overlay,
            cfg=self._cfg,
            cust_label_edit=self.custLabel,
            cust_index_spin=self.custIndex,
        )

        # --- Connect signals ---
        # Overlay controls
        self.overlay_controls = OverlayControlsSection(
            btn_toggle_overlay=self.btnToggleOverlay,
            btn_reset=self.btnReset,
            btn_quit=self.btnQuit,
            btn_radar=self.btnRadar,
            btn_track_map=self.btnTrackMap,
            btn_surface_overlay=self.btnSurfaceOverlay,
            parent=self,
        )
        self.overlay_controls.toggle_overlay_requested.connect(
            self._toggle_running_order_overlay
        )
        self.overlay_controls.reset_requested.connect(self._reset_pbs)
        self.overlay_controls.quit_requested.connect(self.close)
        self.overlay_controls.radar_toggle_requested.connect(self._toggle_radar)
        self.overlay_controls.track_map_toggle_requested.connect(
            self._toggle_track_map
        )
        self.overlay_controls.surface_overlay_toggle_requested.connect(
            self._toggle_surface_overlay
        )

        # Profiles
        self.profile_controls = ProfileManagementSection(
            manager=self.profiles,
            combo=self.profileCombo,
            add_button=self.addProfileBtn,
            save_button=self.saveProfileBtn,
            delete_button=self.deleteProfileBtn,
            parent=self,
        )
        self.profile_controls.profile_selected.connect(self._load_profile)
        self.profile_controls.add_requested.connect(self.presenter.add_new_profile)
        self.profile_controls.save_requested.connect(self.presenter.save_current_profile)
        self.profile_controls.delete_requested.connect(
            self.presenter.delete_current_profile
        )

        # Driver names / sorting
        self.cbAbbrev.stateChanged.connect(self._update_abbrev)
        self.cbSortBest.stateChanged.connect(self._update_sorting)

        # Position change indicator duration
        self.spinPosChangeDuration.setValue(
            int(round(self.ro_overlay.get_position_indicator_duration()))
        )
        self.spinPosChangeDuration.valueChanged.connect(
            lambda v: self.ro_overlay.set_position_indicator_duration(v)
        )

        # Lap display
        self.radioTime.setChecked(True)
        self.radioTime.toggled.connect(self._update_display_mode)
        self.radioSpeed.toggled.connect(self._update_display_mode)

        # Columns & layout
        self.fieldsList.setDragDropMode(QtWidgets.QAbstractItemView.InternalMove)
        self.fieldsList.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.fieldsList.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self._suppress_field_updates = True
        self.fieldsList.clear()
        for field in AVAILABLE_FIELDS:
            item = QtWidgets.QListWidgetItem(field.label)
            item.setFlags(
                item.flags()
                | QtCore.Qt.ItemIsUserCheckable
                | QtCore.Qt.ItemIsDragEnabled
            )
            item.setCheckState(QtCore.Qt.Checked)
            item.setData(QtCore.Qt.UserRole, field.key)
            if field.tooltip:
                item.setToolTip(field.tooltip)
            self.fieldsList.addItem(item)
        self._suppress_field_updates = False
        self.fieldsList.itemChanged.connect(self._on_field_item_changed)
        if self.fieldsList.model() is not None:
            self.fieldsList.model().rowsMoved.connect(self._on_fields_reordered)

        self.btnFieldUp.clicked.connect(lambda: self._move_selected_field(-1))
        self.btnFieldDown.clicked.connect(lambda: self._move_selected_field(1))

        self.presenter.update_indicator_controls()

        # Combo for columns (1–4)
        for i in range(1, 5):
            self.comboCols.addItem(str(i), i)
        self.comboCols.setCurrentIndex(self.ro_overlay.widget().n_columns - 1)
        self.comboCols.currentIndexChanged.connect(self._update_columns)

        self.btnResizeOnce.clicked.connect(self._resize_columns_once)
        self.cbAutosize.stateChanged.connect(
            lambda _: self.ro_overlay.set_autosize_enabled(self.cbAutosize.isChecked())
        )

        # Custom fields
        self.btnAddField.clicked.connect(self.presenter.add_custom_field)
        self.btnRemoveField.clicked.connect(self.presenter.remove_selected_custom_fields)
        self.customFieldList.itemChanged.connect(self.presenter.handle_custom_field_toggled)
        

        # Polling
        self.spinPoll.setValue(self.updater._poll_ms if self.updater else 250)
        self.spinPoll.valueChanged.connect(self._update_poll_ms)

        # Other
        self.aboutButton.clicked.connect(self.show_about_dialog)
        if self.updater:
            self.updater.state_updated.connect(self._on_state_updated_update_carlist)

        self.cbOBSCapture.stateChanged.connect(
            lambda s: self.overlay_controller.set_obs_capture_mode(
                s == QtCore.Qt.Checked
            )
        )


        # Status bar + FPS
        self._fps_timer = QtCore.QTimer()
        self._fps_timer.timeout.connect(self._update_fps_label)
        self._fps_timer.start(1000)

        self._frame_count = 0
        self._fps = 0
        self._total_time = 0.0
        self._avg_ms = 0.0
        self._last_update_time = None
        self._measured_intervals = []

        # Initialize overlay fields
        self._update_fields()

        # --- Game EXE selection ---
        self.btnSelectExe.clicked.connect(self._choose_exe)
        self.lblExePath.setText(self._current_exe_path())

        # --- Track Map Settings tab connections ---
        # Scale slider (value is 10–200, map to 0.1–2.0 scale factor)
        self.sliderMapScale.setMinimum(10)
        self.sliderMapScale.setMaximum(200)
        self.sliderMapScale.setValue(int(self.track_overlay._scale_factor * 100))
        self.sliderMapScale.valueChanged.connect(self._on_map_scale_changed)

        # Show car numbers checkbox
        self.cbShowNumbers.setChecked(self.track_overlay._show_numbers)
        self.cbShowNumbers.stateChanged.connect(
            lambda state: self.track_overlay.set_show_numbers(state == QtCore.Qt.Checked)
        )

        # Color cars by LP line checkbox
        self.cbColorByLP.setChecked(self.track_overlay._color_by_lp)
        self.cbColorByLP.stateChanged.connect(
            lambda state: self.track_overlay.set_color_by_lp(state == QtCore.Qt.Checked)
        )

        # Bubble size slider
        self.sliderBubbleSize.setValue(self.track_overlay._bubble_size)
        self.sliderBubbleSize.valueChanged.connect(
            lambda val: self.track_overlay.set_bubble_size(val)
        )

        # Track line thickness slider
        self.sliderLineThickness.setMinimum(1)
        self.sliderLineThickness.setMaximum(20)
        self.sliderLineThickness.setValue(self.track_overlay._line_thickness)
        self.sliderLineThickness.valueChanged.connect(
            lambda val: self.track_overlay.set_line_thickness(val)
        )


        # Restore last session
        last = self.telemetry_controller.load_last_session()
        if last:
            self._apply_profile_object(last)
            self.radar_settings.sync_from_store()
            self.prox_overlay.update()  # ✅ force redraw using loaded settings

    # -------------------------------
    # EXE path handling
    # -------------------------------
    def _current_exe_path(self) -> str:
        cfg = self._cfg
        return cfg.game_exe or "No EXE selected"

    def _save_exe_path(self, path: str):
        Config.save({"exe_info": {"game_exe": path}})

    def _choose_exe(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select INDYCAR.EXE or CART.EXE",
            "",
            "Executable Files (*.exe);;All Files (*)"
        )
        if not path:
            return

        self._save_exe_path(path)
        self.lblExePath.setText(path)
        self.statusbar.showMessage(f"Game EXE set: {os.path.basename(path)}")

        # clear mute so TrackMapOverlay can retry loading
        self.track_overlay._last_load_failed = False

        self.exe_path_changed.emit(path)

        log.info(f"[ControlPanel] Updated game_exe in live config to: {path}")


    # -------------------------------
    # FPS wrapper and updater slots
    # -------------------------------
    @QtCore.pyqtSlot(object)
    def _on_state_updated_with_fps(self, state):
        start = time.perf_counter()
        self._frame_count += 1
        now = time.perf_counter()
        if self._last_update_time is not None:
            interval = (now - self._last_update_time) * 1000.0
            self._measured_intervals.append(interval)
            if len(self._measured_intervals) > 100:
                self._measured_intervals.pop(0)
        self._last_update_time = now
        self.ro_overlay.on_state_updated(state)
        end = time.perf_counter()
        self._total_time += (end - start)

    @QtCore.pyqtSlot(str)
    def _on_error_from_updater(self, msg: str):
        self.statusbar.showMessage(f"Error: {msg}")

    def _update_fps_label(self):
        self._fps = self._frame_count
        self._avg_ms = (self._total_time / self._frame_count * 1000.0) if self._frame_count else 0.0
        self._frame_count = 0
        self._total_time = 0.0
        self._update_status()

    def _update_status(self):
        avg_interval = (
            sum(self._measured_intervals) / len(self._measured_intervals)
            if self._measured_intervals else 0.0
        )
        miles = self.ro_overlay._track_length or 0.0
        track = getattr(self.ro_overlay._last_state, "track_name", "")

        msg = f"v{__version__} | Track length: {miles:.3f} mi | Track: {track}"
        controller = getattr(self, "telemetry_controller", None)
        recording_file = (
            controller.lap_logger_recording_file if controller else None
        )
        if recording_file:
            msg += f" | Recording → {recording_file}"
        self.statusbar.showMessage(msg)

    def show_about_dialog(self):
        QtWidgets.QMessageBox.about(
            self,
            "About ICR2 Timing",
            f"<b>ICR2 Timing Overlay</b><br>"
            f"Version {__version__}<br><br>"
            f"Developed by SK Chow<br>"
        )

    # -------------------------------
    # Overlay actions
    # -------------------------------
    def _toggle_running_order_overlay(self):
        visible = self.overlay_controller.toggle_running_order()
        self.overlay_controls.set_overlay_visible(bool(visible))

    def _on_map_scale_changed(self, val: int):
        scale = max(10, min(200, val)) / 100.0
        self.track_overlay.set_scale_factor(scale)
        self.surface_overlay.set_scale_factor(scale)

    def _toggle_radar(self):
        visible = self.overlay_controller.toggle_radar()
        self.overlay_controls.set_radar_visible(bool(visible))

    def _toggle_track_map(self):
        visible = self.overlay_controller.toggle_track_map()
        self.overlay_controls.set_track_map_visible(bool(visible))

    def _toggle_surface_overlay(self):
        visible = self.overlay_controller.toggle_surface_overlay()
        self.overlay_controls.set_surface_overlay_visible(bool(visible))
    @QtCore.pyqtSlot(object)
    def _on_individual_overlay_toggle_requested(self, idx_data):
        if idx_data is None:
            return
        visible = self.overlay_controller.toggle_individual_overlay(idx_data)
        if visible is None:
            return
        self.telemetry_controller.set_individual_overlay_visible(bool(visible))



    def _reset_pbs(self):
        self.overlay_controller.reset_personal_bests()

    def _update_sorting(self):
        self.ro_overlay.set_sort_by_best(self.cbSortBest.isChecked())

    def _update_abbrev(self):
        self.ro_overlay.set_use_abbreviations(self.cbAbbrev.isChecked())

    def _move_selected_field(self, direction: int):
        if getattr(self, "_suppress_field_updates", False):
            return

        current_row = self.fieldsList.currentRow()
        if current_row < 0:
            return

        target_row = current_row + direction
        if target_row < 0 or target_row >= self.fieldsList.count():
            return

        self._suppress_field_updates = True
        item = self.fieldsList.takeItem(current_row)
        if item is None:
            self._suppress_field_updates = False
            return
        self.fieldsList.insertItem(target_row, item)
        self.fieldsList.setCurrentRow(target_row)
        self._suppress_field_updates = False
        self._on_fields_reordered()

    def _on_field_item_changed(self, _item):
        if getattr(self, "_suppress_field_updates", False):
            return
        self._update_fields()

    def _on_fields_reordered(self, *args):
        if getattr(self, "_suppress_field_updates", False):
            return
        self._update_fields()

    def _update_fields(self):
        if getattr(self, "_suppress_field_updates", False):
            return
        enabled = self.presenter.collect_field_keys()
        self.ro_overlay.set_enabled_fields(enabled)
        self.presenter.update_indicator_controls()

    def _update_display_mode(self):
        mode = "time" if self.radioTime.isChecked() else "speed"
        self.ro_overlay.set_display_mode(mode)

    def _update_poll_ms(self, val: int):
        if self.updater:
            QtCore.QMetaObject.invokeMethod(
                self.updater,
                "set_poll_interval",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(int, int(val))
            )

    def _update_columns(self, index: int):
        val = self.comboCols.itemData(index)
        if not val:
            return
        old_geom = self.ro_overlay.widget().geometry()
        was_visible = self.ro_overlay.widget().isVisible()
        old_widget = self.ro_overlay.widget()
        old_widget.close()
        new_ro = RunningOrderOverlayTable(n_columns=val)
        self.ro_overlay = new_ro
        self.presenter.set_running_order_overlay(new_ro)
        self.overlay_controller.replace_running_order_overlay(
            new_ro, state_handler=self._on_state_updated_with_fps
        )
        self._update_fields()
        if old_geom is not None:
            self.ro_overlay.widget().setGeometry(old_geom)
        if was_visible:
            self.ro_overlay.widget().show()

    def _on_state_updated_update_carlist(self, state):
        """Update car list only if the set of car numbers has changed."""
        self._latest_state = state
        self.telemetry_controls.update_car_list(state)



    # -------------------------------
    # Profile management
    # -------------------------------
    def _load_profile(self, profile_name: str):
        prof = self.profiles.load(profile_name)
        if prof:
            self._apply_profile_object(prof)

    def _apply_profile_object(self, prof: Profile):
        label_to_key = {field.label: field.key for field in AVAILABLE_FIELDS}
        label_to_key["SincePit"] = "laps_since_yellow"
        ordered_keys = []
        seen_keys = set()
        for lbl in prof.columns:
            key = label_to_key.get(lbl)
            if key and key not in seen_keys:
                ordered_keys.append(key)
                seen_keys.add(key)

        # Columns
        self._suppress_field_updates = True
        key_to_item = {}
        for i in range(self.fieldsList.count()):
            item = self.fieldsList.item(i)
            if item is None:
                continue
            key = item.data(QtCore.Qt.UserRole)
            if key:
                key_to_item[key] = item

        insert_row = 0
        for key in ordered_keys:
            item = key_to_item.get(key)
            if item is None:
                continue
            current_row = self.fieldsList.row(item)
            moved_item = self.fieldsList.takeItem(current_row)
            self.fieldsList.insertItem(insert_row, moved_item)
            insert_row += 1

        for i in range(self.fieldsList.count()):
            item = self.fieldsList.item(i)
            if item is None:
                continue
            key = item.data(QtCore.Qt.UserRole)
            item.setCheckState(
                QtCore.Qt.Checked if key in ordered_keys else QtCore.Qt.Unchecked
            )

        self._suppress_field_updates = False
        self._update_fields()

        if prof.n_columns != (self.comboCols.currentIndex() + 1):
            self.comboCols.setCurrentIndex(prof.n_columns - 1)

        if prof.display_mode == "speed":
            self.radioSpeed.setChecked(True)
        else:
            self.radioTime.setChecked(True)

        self.cbSortBest.setChecked(prof.sort_by_best)
        self.cbAbbrev.setChecked(prof.use_abbrev)
        self.cbAutosize.setChecked(self.ro_overlay._autosize_enabled)

        self.spinPosChangeDuration.blockSignals(True)
        self.spinPosChangeDuration.setValue(int(round(prof.position_indicator_duration)))
        self.spinPosChangeDuration.blockSignals(False)
        self.ro_overlay.set_position_indicator_duration(prof.position_indicator_duration)

        self.ro_overlay.widget().move(prof.window_x, prof.window_y)

        if self.ro_overlay._last_state:
            self.ro_overlay.on_state_updated(self.ro_overlay._last_state, update_bests=False)

        # Restore radar geometry & settings
        self.radar_settings.apply_profile(prof)

        # ✅ Custom fields
        self.customFieldList.clear()
        for label, idx in prof.custom_fields:
            self.ro_overlay.add_custom_field(label, idx)
            item = QtWidgets.QListWidgetItem(f"{label} ({idx})")
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked)
            item.setToolTip(f"Car data struct index {idx} (custom field)")
            self.customFieldList.addItem(item)
    def _set_button_color(self, button: QtWidgets.QPushButton, rgba_str: str):
        """Color the button using an rgba string like '255,0,0,255'."""
        try:
            r, g, b, a = [int(x) for x in rgba_str.split(",")]
            button.setStyleSheet(
                f"background-color: rgba({r},{g},{b},{a}); border: 1px solid #444;"
            )
        except Exception:
            button.setStyleSheet("")


    def _on_config_changed(self, cfg):
        self._cfg = cfg
        self.presenter.update_config(cfg)
        self.lblExePath.setText(self._current_exe_path())
        if hasattr(self, "telemetry_controller"):
            self.telemetry_controller.update_config(cfg)

    def _on_select_individual_car(self, car_index):
        """When user picks a new car number, update overlay's car index."""
        if car_index is None:
            return
        self.indiv_overlay.set_car_index(car_index)


    # -------------------------------
    # One-shot resize
    # -------------------------------
    def _resize_columns_once(self):
        self.ro_overlay.resize_columns_now()

    # -------------------------------
    # Close event = save last session
    # -------------------------------
    def closeEvent(self, event):
        if self._shutdown_hook:
            try:
                self._shutdown_hook()
            finally:
                self._shutdown_hook = None
        snapshot = self.presenter.build_session_snapshot()
        self.telemetry_controller.save_last_session(snapshot)
        self.telemetry_controller.shutdown()

        # --- Close overlays so they don't keep the process alive ---
        try:
            if self.ro_overlay:
                ro_widget = self.ro_overlay.widget()
                if ro_widget and ro_widget.isVisible():
                    ro_widget.close()
        except Exception:
            pass

        try:
            if self.track_overlay and self.track_overlay.isVisible():
                self.track_overlay.close()
        except Exception:
            pass

        try:
            if self.surface_overlay and self.surface_overlay.isVisible():
                self.surface_overlay.close()
        except Exception:
            pass

        try:
            if self.prox_overlay and self.prox_overlay.isVisible():
                self.prox_overlay.close()
        except Exception:
            pass

        try:
            if self.indiv_overlay and self.indiv_overlay.isVisible():
                self.indiv_overlay.close()
        except Exception:
            pass

        # Call parent closeEvent
        super().closeEvent(event)

    def _current_state(self):
        return self._latest_state or getattr(self.ro_overlay, "_last_state", None)
