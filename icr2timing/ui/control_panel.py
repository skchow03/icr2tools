"""
control_panel.py

Control panel window now built from control_panel.ui (Qt Designer).
Uses OverlayManager (multi-overlay) + ProfileManager.
"""

import time
import os
from PyQt5 import QtWidgets, QtCore, uic, QtGui


import logging
log = logging.getLogger(__name__)

from icr2timing.updater.overlay_manager import OverlayManager
from icr2timing.overlays.running_order_overlay import (
    RunningOrderOverlayTable,
    AVAILABLE_FIELDS,
)
from icr2timing.ui.profile_manager import ProfileManager, Profile, LAST_SESSION_KEY
from icr2timing.overlays.proximity_overlay import ProximityOverlay
from icr2timing.overlays.track_map_overlay import TrackMapOverlay
from icr2timing.overlays.experimental_track_surface_overlay import (
    ExperimentalTrackSurfaceOverlay,
)
from icr2timing.overlays.individual_car_overlay import IndividualCarOverlay
from icr2timing.core.config import Config, reload_settings
from icr2timing.core.installations import InstallationManager, Installation
from icr2timing.core.version import __version__
from icr2timing.core.telemetry_laps import TelemetryLapLogger
from icr2timing.ui.installation_editor import InstallationEditorDialog


CAR_STATE_INDEX_PIT_RELEASE_TIMER = 98


class ControlPanel(QtWidgets.QMainWindow):
    exe_path_changed = QtCore.pyqtSignal(str)
    installation_switch_requested = QtCore.pyqtSignal(str, str)

    def __init__(self, updater, mem=None, cfg=None):
        super().__init__()
        uic.loadUi(
            os.path.join(os.path.dirname(__file__), "control_panel.ui"),
            self
        )

        self.updater = None
        self._mem = None
        self._cfg = cfg or Config()
        self._latest_state = None
        self._updater_thread = None

        self.installations = InstallationManager()
        self._running_installation_key = self.installations.get_active_key()
        self._suppress_installation_events = False

        # --- Overlay Manager ---
        self.manager = OverlayManager()
        self.ro_overlay = RunningOrderOverlayTable()
        self.manager.add_overlay(self.ro_overlay)

        # Radar handled separately (not added to OverlayManager)
        self.prox_overlay = ProximityOverlay()

        # After creating self.prox_overlay
        radar_cfg = self.prox_overlay.cfg

        self._set_button_color(self.btnPlayerColor, radar_cfg.radar_player_color)
        self._set_button_color(self.btnAheadColor, radar_cfg.radar_ai_ahead_color)
        self._set_button_color(self.btnBehindColor, radar_cfg.radar_ai_behind_color)
        self._set_button_color(self.btnAlongColor, radar_cfg.radar_ai_alongside_color)

        self.spinRadarWidth.setValue(radar_cfg.radar_width)
        self.spinRadarHeight.setValue(radar_cfg.radar_height)

        self.spinRadarForward.setValue(radar_cfg.radar_range_forward)
        self.spinRadarRear.setValue(radar_cfg.radar_range_rear)
        self.spinRadarSide.setValue(radar_cfg.radar_range_side)

        # symbol dropdown
        self.comboRadarSymbol.setCurrentText(radar_cfg.radar_symbol.capitalize())


        # --- Radar Settings connections ---   
        self.spinRadarWidth.valueChanged.connect(lambda v: self.prox_overlay.set_size(v, self.spinRadarHeight.value()))
        self.spinRadarHeight.valueChanged.connect(lambda v: self.prox_overlay.set_size(self.spinRadarWidth.value(), v))

        self.spinRadarForward.valueChanged.connect(lambda v: self.prox_overlay.set_range(forward=v))
        self.spinRadarRear.valueChanged.connect(lambda v: self.prox_overlay.set_range(rear=v))
        self.spinRadarSide.valueChanged.connect(lambda v: self.prox_overlay.set_range(side=v))

        self.comboRadarSymbol.currentTextChanged.connect(
            lambda t: self.prox_overlay.set_symbol(t.lower())
        )


        # color pickers
        self.btnPlayerColor.clicked.connect(lambda: self._pick_radar_color("player"))
        self.btnAheadColor.clicked.connect(lambda: self._pick_radar_color("ahead"))
        self.btnBehindColor.clicked.connect(lambda: self._pick_radar_color("behind"))
        self.btnAlongColor.clicked.connect(lambda: self._pick_radar_color("alongside"))

        # Updater connections handled in attach_runtime()

        # Track map overlay
        self.track_overlay = TrackMapOverlay()

        # Experimental surface overlay
        self.surface_overlay = ExperimentalTrackSurfaceOverlay()
        self.surface_overlay.set_scale_factor(self.track_overlay._scale_factor)

        # Individual car overlay
        self.indiv_overlay = IndividualCarOverlay(
            mem=None, cfg=self._cfg, status_callback=self.statusbar.showMessage
        )
        self.indiv_overlay.set_status_callback(self.statusbar.showMessage)

        self.btnToggleIndividualTelemetry.clicked.connect(self._toggle_indiv_overlay)
        self.selectIndividualCar.currentIndexChanged.connect(self._on_select_individual_car)


        # --- Telemetry Lap Logger ---
        self.lap_logger = None
        self._lap_logger_enabled = False
        self.btnLapLogger.clicked.connect(self._toggle_lap_logger)
        self.btnLapLogger.setText("Enable Lap Logger")
        self._recording_file = None
        self.btnReleaseAllCars.clicked.connect(self._release_all_cars)
        self.btnForcePitStops.clicked.connect(self._force_all_cars_to_pit)

        # --- Profile Manager ---
        self.profiles = ProfileManager()
        self.profileCombo.addItems(self.profiles.list_profiles())

        # --- Connect signals ---
        # Overlay controls
        self.btnToggleOverlay.clicked.connect(self._toggle_overlay)
        self.btnReset.clicked.connect(self._reset_pbs)
        self.btnQuit.clicked.connect(self.close)
        self.btnRadar.clicked.connect(self._toggle_radar)
        self.btnTrackMap.clicked.connect(self._toggle_track_map)
        self.btnSurfaceOverlay.clicked.connect(self._toggle_surface_overlay)

        # Profiles
        self.profileCombo.currentTextChanged.connect(self._load_profile)
        self.addProfileBtn.clicked.connect(self._add_new_profile)
        self.saveProfileBtn.clicked.connect(self._save_current_profile)
        self.deleteProfileBtn.clicked.connect(self._delete_current_profile)

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

        self._update_indicator_controls()

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
        self.btnAddField.clicked.connect(self._on_add_field)
        self.btnRemoveField.clicked.connect(self._on_remove_field)
        self.customFieldList.itemChanged.connect(self._on_custom_field_toggled)
        

        # Polling
        self.spinPoll.setValue(self.updater._poll_ms if self.updater else 250)
        self.spinPoll.valueChanged.connect(self._update_poll_ms)

        # Other
        self.aboutButton.clicked.connect(self.show_about_dialog)

        self.cbOBSCapture.stateChanged.connect(
            lambda s: self.set_obs_capture_mode(s == QtCore.Qt.Checked)
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

        # --- Installation controls ---
        self.comboInstallations.currentIndexChanged.connect(self._on_installation_changed)
        self.btnAddInstallation.clicked.connect(self._add_installation)
        self.btnEditInstallation.clicked.connect(self._edit_installation)
        self.btnSelectExe.clicked.connect(self._choose_exe)
        self._refresh_installations(self.installations.get_active_key())

        self.attach_runtime(updater, mem, self._cfg)

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
        last = self.profiles.load_last_session()
        if last:
            self._apply_profile_object(last)
            self._sync_radar_ui_from_overlay()   # ✅ new line
            self.prox_overlay.update()  # ✅ force redraw using loaded settings

    # -------------------------------
    # Installation handling
    # -------------------------------
    def _refresh_installations(self, select_key: str | None = None):
        installs = self.installations.list_installations()
        if select_key is None:
            select_key = self.installations.get_active_key()

        self._suppress_installation_events = True
        self.comboInstallations.clear()
        for inst in installs:
            self.comboInstallations.addItem(inst.name, inst.key)
        if select_key:
            idx = self.comboInstallations.findData(select_key)
            if idx >= 0:
                self.comboInstallations.setCurrentIndex(idx)
        self._suppress_installation_events = False

        active = self.installations.get_installation(select_key) if select_key else None
        self._apply_installation(active)

    def _apply_installation(self, installation: Installation | None):
        if not installation:
            self.lblExePath.setText("No EXE selected")
            self.lblExePath.setToolTip("")
            self.lblInstallDetails.setText("Version: — | Keywords: —")
            return

        exe_path = installation.exe_path or ""
        display_path = exe_path or "No EXE selected"
        self.lblExePath.setText(display_path)
        self.lblExePath.setToolTip(exe_path)

        keywords = installation.keywords or []
        keyword_text = ", ".join(keywords) if keywords else "—"
        details = f"Version: {installation.version.upper()} | Keywords: {keyword_text}"
        self.lblInstallDetails.setText(details)

    def _on_installation_changed(self, index: int):
        if self._suppress_installation_events:
            return
        key = self.comboInstallations.itemData(index)
        if not key:
            return
        previous = self._running_installation_key
        self._request_installation_switch(key, previous)

    def _request_installation_switch(self, key: str, previous: str | None):
        inst = self.installations.set_active(key)
        reload_settings()
        self._apply_installation(inst)

        if not previous or previous == key:
            self._running_installation_key = key
            return

        self.installation_switch_requested.emit(key, previous)

    def _add_installation(self):
        dialog = InstallationEditorDialog(self)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return

        data = dialog.result_payload()
        inst = self.installations.add_installation(
            data["name"], data["exe_path"], data["version"], data["keywords"]
        )
        reload_settings()
        self._refresh_installations(select_key=inst.key)
        previous = self._running_installation_key
        self._request_installation_switch(inst.key, previous)
        self.statusbar.showMessage(f"Added installation: {inst.name}", 4000)

    def _edit_installation(self):
        key = self.comboInstallations.currentData()
        if not key:
            return
        inst = self.installations.get_installation(key)
        if not inst:
            return

        dialog = InstallationEditorDialog(self, installation=inst)
        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return

        data = dialog.result_payload()
        updated = self.installations.update_installation(
            key,
            name=data["name"],
            exe_path=data["exe_path"],
            version=data["version"],
            keywords=data["keywords"],
        )
        reload_settings()
        self._refresh_installations(select_key=key)

        if updated and self._running_installation_key == key:
            self._apply_runtime_config(Config())
            setattr(self.track_overlay, "_last_load_failed", False)
        if updated:
            self.statusbar.showMessage(f"Updated installation: {updated.name}", 4000)

    def _choose_exe(self):
        key = self.comboInstallations.currentData()
        if not key:
            return

        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select INDYCAR.EXE or CART.EXE",
            "",
            "Executable Files (*.exe);;All Files (*)"
        )
        if not path:
            return

        updated = self.installations.update_installation(key, exe_path=path)
        reload_settings()
        self._refresh_installations(select_key=key)

        if updated and self._running_installation_key == key:
            self._apply_runtime_config(Config())
            setattr(self.track_overlay, "_last_load_failed", False)

        self.exe_path_changed.emit(path)
        base = os.path.basename(path)
        self.statusbar.showMessage(f"Game EXE set: {base}", 4000)
        log.info(f"[ControlPanel] Updated game_exe for installation '{key}' to: {path}")

    def confirm_installation_switch(self, key: str):
        self._running_installation_key = key
        inst = self.installations.get_installation(key)
        self._apply_installation(inst)
        if inst:
            self.statusbar.showMessage(f"Switched to installation: {inst.name}", 4000)

    def revert_installation_switch(self, key: str):
        self.installations.set_active(key)
        reload_settings()
        self._refresh_installations(select_key=key)
        self._running_installation_key = key

    def _apply_runtime_config(self, cfg: Config):
        self._cfg = cfg
        self.prox_overlay.apply_config(cfg)
        self.track_overlay.apply_config(cfg)
        self.indiv_overlay.set_backend(self._mem, cfg)
        self._sync_radar_ui_from_overlay()

    def _disconnect_runtime_signals(self):
        if not self.updater:
            return
        try:
            self.manager.disconnect_updater(self.updater)
        except Exception:
            pass

        slots = [
            self.prox_overlay.on_state_updated,
            self.track_overlay.on_state_updated,
            self.surface_overlay.on_state_updated,
            self.indiv_overlay.on_state_updated,
            self._on_state_updated_update_carlist,
        ]
        for slot in slots:
            try:
                self.updater.state_updated.disconnect(slot)
            except Exception:
                pass

        error_slots = [
            self.prox_overlay.on_error,
            self.track_overlay.on_error,
            self.surface_overlay.on_error,
            self.indiv_overlay.on_error,
            self._on_error_from_updater,
        ]
        for slot in error_slots:
            try:
                self.updater.error.disconnect(slot)
            except Exception:
                pass

        if self._lap_logger_enabled and self.lap_logger:
            try:
                self.updater.state_updated.disconnect(self.lap_logger.on_state_updated)
            except Exception:
                pass

    def attach_runtime(self, updater, mem, cfg=None, thread=None):
        self._disconnect_runtime_signals()
        self.updater = updater
        self._mem = mem
        self._updater_thread = thread
        runtime_cfg = cfg or Config()
        self._apply_runtime_config(runtime_cfg)

        if self.updater:
            self.manager.connect_updater(self.updater)
            self.updater.state_updated.connect(self.prox_overlay.on_state_updated)
            self.updater.error.connect(self.prox_overlay.on_error)
            self.updater.state_updated.connect(self.track_overlay.on_state_updated)
            self.updater.error.connect(self.track_overlay.on_error)
            self.updater.state_updated.connect(self.surface_overlay.on_state_updated)
            self.updater.error.connect(self.surface_overlay.on_error)
            self.updater.state_updated.connect(self.indiv_overlay.on_state_updated)
            self.updater.error.connect(self.indiv_overlay.on_error)
            self.updater.state_updated.connect(self._on_state_updated_update_carlist)
            self.updater.error.connect(self._on_error_from_updater)
            if self._lap_logger_enabled and self.lap_logger:
                self.updater.state_updated.connect(self.lap_logger.on_state_updated)

        self.spinPoll.setValue(self.updater._poll_ms if self.updater else 250)

    def detach_runtime(self):
        self._disconnect_runtime_signals()
        self.updater = None
        self._mem = None
        self._updater_thread = None


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
        self.ro_overlay.on_error(msg)
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
        if self._recording_file:
            msg += f" | Recording → {self._recording_file}"
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
    def _toggle_overlay(self):
        if self.ro_overlay.widget().isVisible():
            self.ro_overlay.widget().hide()
            self.btnToggleOverlay.setText("Show Overlay")
        else:
            self.ro_overlay.widget().show()
            self.ro_overlay.widget().raise_()
            self.btnToggleOverlay.setText("Hide Overlay")

    def _on_map_scale_changed(self, val: int):
        scale = max(10, min(200, val)) / 100.0
        self.track_overlay.set_scale_factor(scale)
        self.surface_overlay.set_scale_factor(scale)

    def _toggle_radar(self):
        if self.prox_overlay.isVisible():
            self.prox_overlay.hide()
            self.btnRadar.setText("Show Radar")
        else:
            self.prox_overlay.show()
            self.prox_overlay.raise_()
            self.btnRadar.setText("Hide Radar")

    def _toggle_track_map(self):
        if self.track_overlay.isVisible():
            self.track_overlay.hide()
            self.btnTrackMap.setText("Show Track Map")
        else:
            self.track_overlay.show()
            self.track_overlay.raise_()
            self.track_overlay.activateWindow()
            self.btnTrackMap.setText("Hide Track Map")

    def _toggle_surface_overlay(self):
        if self.surface_overlay.isVisible():
            self.surface_overlay.hide()
            self.btnSurfaceOverlay.setText("Show Surface Overlay")
        else:
            self.surface_overlay.show()
            self.surface_overlay.raise_()
            self.surface_overlay.activateWindow()
            self.btnSurfaceOverlay.setText("Hide Surface Overlay")
    def _toggle_indiv_overlay(self):
        idx_data = self.selectIndividualCar.currentData()
        if idx_data is None:
            return

        self.indiv_overlay.set_car_index(idx_data)

        if self.indiv_overlay.isVisible():
            self.indiv_overlay.hide()
            self.btnToggleIndividualTelemetry.setText("Show telemetry overlay")
        else:
            self.indiv_overlay.show()
            self.indiv_overlay.raise_()
            self.btnToggleIndividualTelemetry.setText("Hide telemetry overlay")



    def _reset_pbs(self):
        self.manager.reset_pbs()

    def _update_sorting(self):
        self.ro_overlay.set_sort_by_best(self.cbSortBest.isChecked())

    def _update_abbrev(self):
        self.ro_overlay.set_use_abbreviations(self.cbAbbrev.isChecked())

    def _update_indicator_controls(self):
        indicator_enabled = "position_indicator" in self.ro_overlay.get_enabled_fields()
        self.spinPosChangeDuration.setEnabled(indicator_enabled)
        self.lblPositionIndicatorDuration.setEnabled(indicator_enabled)

    def _collect_field_keys(self, include_unchecked: bool = False):
        keys = []
        for i in range(self.fieldsList.count()):
            item = self.fieldsList.item(i)
            if item is None:
                continue
            key = item.data(QtCore.Qt.UserRole)
            if not key:
                continue
            if include_unchecked or item.checkState() == QtCore.Qt.Checked:
                keys.append(key)
        return keys

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
        enabled = self._collect_field_keys()
        self.ro_overlay.set_enabled_fields(enabled)
        self._update_indicator_controls()

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
        self.manager.remove_overlay(self.ro_overlay)
        self.ro_overlay.widget().close()
        new_ro = RunningOrderOverlayTable(n_columns=val)
        self.ro_overlay = new_ro
        self.manager.add_overlay(new_ro)
        if self.updater:
            self.manager.connect_updater(self.updater)
        self._update_fields()
        if old_geom is not None:
            self.ro_overlay.widget().setGeometry(old_geom)
        if was_visible:
            self.ro_overlay.widget().show()

    def _on_state_updated_update_carlist(self, state):
        """Update car list only if the set of car numbers has changed."""
        self._latest_state = state
        # Build a snapshot of current car numbers and names
        current_snapshot = [
            (driver.car_number, driver.name or "")
            for _, driver in sorted(state.drivers.items())
            if driver and driver.car_number is not None
        ]

        # if no change, do nothing
        if getattr(self, "_last_car_snapshot", None) == current_snapshot:
            return

        # store new set and repopulate
        self._last_car_snapshot = current_snapshot

        self.selectIndividualCar.blockSignals(True)
        self.selectIndividualCar.clear()
        for idx, driver in sorted(state.drivers.items()):
            if not driver or driver.car_number is None:
                continue
            name = (driver.name or "").strip()
            if name:
                display_text = f"{driver.car_number} - {name}"
            else:
                display_text = str(driver.car_number)
            # text includes car number (and name when available); data is struct index
            self.selectIndividualCar.addItem(display_text, idx)
        self.selectIndividualCar.blockSignals(False)



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
        self.prox_overlay.move(prof.radar_x, prof.radar_y)
        self.prox_overlay.resize(prof.radar_width, prof.radar_height)
        self.prox_overlay.set_range(
            forward=prof.radar_range_forward,
            rear=prof.radar_range_rear,
            side=prof.radar_range_side,
        )
        self.prox_overlay.set_symbol(prof.radar_symbol)
        self.prox_overlay.set_show_speeds(prof.radar_show_speeds)
        self.prox_overlay.set_colors(
            player=prof.radar_player_color,
            ahead=prof.radar_ai_ahead_color,
            behind=prof.radar_ai_behind_color,
            alongside=prof.radar_ai_alongside_color,
        )
        self._set_button_color(self.btnPlayerColor, prof.radar_player_color)
        self._set_button_color(self.btnAheadColor, prof.radar_ai_ahead_color)
        self._set_button_color(self.btnBehindColor, prof.radar_ai_behind_color)
        self._set_button_color(self.btnAlongColor, prof.radar_ai_alongside_color)

        # ✅ Custom fields
        self.customFieldList.clear()
        for label, idx in prof.custom_fields:
            self.ro_overlay.add_custom_field(label, idx)
            item = QtWidgets.QListWidgetItem(f"{label} ({idx})")
            item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
            item.setCheckState(QtCore.Qt.Checked)
            item.setToolTip(f"Car data struct index {idx} (custom field)")
            self.customFieldList.addItem(item)


    def _save_current_profile(self):
        profile_name = self.profileCombo.currentText().strip()
        if not profile_name:
            return

        # Columns
        key_to_label = {field.key: field.label for field in AVAILABLE_FIELDS}
        ordered_keys = self._collect_field_keys()
        selected_labels = [key_to_label[k] for k in ordered_keys if k in key_to_label]
        indicator_enabled = "position_indicator" in ordered_keys

        # Custom fields (only save checked)
        custom_fields = []
        for i in range(self.customFieldList.count()):
            item = self.customFieldList.item(i)
            text = item.text()
            label, idx_str = text.split(" (")
            idx = int(idx_str.rstrip(")"))
            if item.checkState() == QtCore.Qt.Checked:
                custom_fields.append((label, idx))

        profile = Profile(
            name=profile_name,
            columns=selected_labels,
            n_columns=self.comboCols.itemData(self.comboCols.currentIndex()),
            display_mode="speed" if self.radioSpeed.isChecked() else "time",
            sort_by_best=self.cbSortBest.isChecked(),
            use_abbrev=self.cbAbbrev.isChecked(),
            window_x=self.ro_overlay.widget().x(),
            window_y=self.ro_overlay.widget().y(),
            radar_x=self.prox_overlay.x(),
            radar_y=self.prox_overlay.y(),
            radar_visible=self.prox_overlay.isVisible(),
            radar_width=self.prox_overlay.width(),
            radar_height=self.prox_overlay.height(),
            radar_range_forward=self.prox_overlay.cfg.radar_range_forward,
            radar_range_rear=self.prox_overlay.cfg.radar_range_rear,
            radar_range_side=self.prox_overlay.cfg.radar_range_side,
            radar_symbol=self.prox_overlay.symbol,
            radar_show_speeds=self.prox_overlay.show_speeds,
            radar_player_color=self.prox_overlay.cfg.radar_player_color,
            radar_ai_ahead_color=self.prox_overlay.cfg.radar_ai_ahead_color,
            radar_ai_behind_color=self.prox_overlay.cfg.radar_ai_behind_color,
            radar_ai_alongside_color=self.prox_overlay.cfg.radar_ai_alongside_color,
            position_indicator_duration=self.spinPosChangeDuration.value(),
            position_indicator_enabled=indicator_enabled,
            custom_fields=custom_fields,
        )

        self.profiles.save(profile)
        if profile_name not in [self.profileCombo.itemText(i) for i in range(self.profileCombo.count())]:
            self.profileCombo.addItem(profile_name)
        self.profileCombo.setCurrentText(profile_name)

        QtWidgets.QMessageBox.information(
            self,
            "Profile Saved",
            f"Current settings have been saved to profile '{profile_name}'."
        )

    def _delete_current_profile(self):
        profile_name = self.profileCombo.currentText()
        if not profile_name:
            return
        reply = QtWidgets.QMessageBox.question(
            self,
            "Delete Profile",
            f"Delete profile '{profile_name}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )
        if reply == QtWidgets.QMessageBox.Yes and self.profiles.delete(profile_name):
            idx = self.profileCombo.findText(profile_name)
            if idx >= 0:
                self.profileCombo.removeItem(idx)

    def _add_new_profile(self):
        """Create a new profile from current settings."""
        # Ask the user for a name
        name, ok = QtWidgets.QInputDialog.getText(self, "New Profile", "Enter profile name:")
        if not ok or not name.strip():
            return

        key_to_label = {field.key: field.label for field in AVAILABLE_FIELDS}
        enabled_keys = self.ro_overlay.get_enabled_fields()
        selected_labels = [key_to_label[k] for k in enabled_keys if k in key_to_label]
        indicator_enabled = "position_indicator" in enabled_keys

        profile = Profile(
            name=name.strip(),
            columns=selected_labels,
            n_columns=self.comboCols.itemData(self.comboCols.currentIndex()),
            display_mode="speed" if self.radioSpeed.isChecked() else "time",
            sort_by_best=self.cbSortBest.isChecked(),
            use_abbrev=self.cbAbbrev.isChecked(),
            window_x=self.ro_overlay.widget().x(),
            window_y=self.ro_overlay.widget().y(),
            radar_x=self.prox_overlay.x(),
            radar_y=self.prox_overlay.y(),
            radar_visible=self.prox_overlay.isVisible(),
            radar_width=self.prox_overlay.width(),
            radar_height=self.prox_overlay.height(),
            radar_range_forward=self.prox_overlay.cfg.radar_range_forward,
            radar_range_rear=self.prox_overlay.cfg.radar_range_rear,
            radar_range_side=self.prox_overlay.cfg.radar_range_side,
            radar_symbol=self.prox_overlay.symbol,
            radar_show_speeds=self.prox_overlay.show_speeds,
            radar_player_color=self.prox_overlay.cfg.radar_player_color,
            radar_ai_ahead_color=self.prox_overlay.cfg.radar_ai_ahead_color,
            radar_ai_behind_color=self.prox_overlay.cfg.radar_ai_behind_color,
            radar_ai_alongside_color=self.prox_overlay.cfg.radar_ai_alongside_color,
            position_indicator_duration=self.spinPosChangeDuration.value(),
            position_indicator_enabled=indicator_enabled,
        )
        # Radar state

        self.profiles.save(profile)

        if name not in [self.profileCombo.itemText(i) for i in range(self.profileCombo.count())]:
            self.profileCombo.addItem(name)
        self.profileCombo.setCurrentText(name)


    def _on_add_field(self):
        label = self.custLabel.text().strip()
        index = self.custIndex.value()
        if not label:
            return

        # Add to overlay immediately
        self.ro_overlay.add_custom_field(label, index)

        # Add to QListWidget with a checkbox
        item = QtWidgets.QListWidgetItem(f"{label} ({index})")
        item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
        item.setCheckState(QtCore.Qt.Checked)
        item.setToolTip(f"Car data struct index {index} (custom field)")
        self.customFieldList.addItem(item)

        # Clear inputs
        self.custLabel.clear()
        self.custIndex.setValue(0)

    def _on_remove_field(self):
        for item in self.customFieldList.selectedItems():
            text = item.text()
            label = text.split(" (")[0]
            # Remove from overlay and from list
            self.ro_overlay.remove_custom_field(label)
            self.customFieldList.takeItem(self.customFieldList.row(item))


    def _on_custom_field_toggled(self, item: QtWidgets.QListWidgetItem):
        text = item.text()
        label, idx_str = text.split(" (")
        idx = int(idx_str.rstrip(")"))

        if item.checkState() == QtCore.Qt.Checked:
            self.ro_overlay.add_custom_field(label, idx)
        else:
            # Don’t forget: we’re only hiding it, not deleting the entry
            self.ro_overlay.remove_custom_field(label)



    def _toggle_widget(self, widget):
        if widget.isVisible():
            widget.hide()
        else:
            widget.show()
            widget.raise_()

    def _toggle_lap_logger(self):
        """Enable/disable lap telemetry logging."""
        from icr2timing.core.telemetry_laps import TelemetryLapLogger

        if self._lap_logger_enabled:
            # --- Disable current logger ---
            try:
                log.info(f"[ControlPanel] Disabling Lap Logger")
                self.updater.state_updated.disconnect(self.lap_logger.on_state_updated)
            except Exception:
                pass
            self._lap_logger_enabled = False
            self.btnLapLogger.setText("Enable Lap Logger")
            self._recording_file = None

        else:
            # --- Create a new logger and enable it ---
            self.lap_logger = TelemetryLapLogger("telemetry_laps")
            try:
                self.updater.state_updated.connect(self.lap_logger.on_state_updated)
                self._lap_logger_enabled = True
                self.btnLapLogger.setText("Disable Lap Logger")
                self._recording_file = self.lap_logger.get_filename()
            except Exception as e:
                log.error(f"[ControlPanel] Error enabling Lap Logger: {e}")
                self._lap_logger_enabled = False
                self._recording_file = None

        # Refresh status bar to reflect current state
        self._update_status()

    def _release_all_cars(self):
        """Force pit release countdown to 1 for all cars in the current state."""
        if not self._mem:
            self.statusbar.showMessage("Pit release unavailable: no memory connection", 5000)
            return

        state = self._latest_state or getattr(self.ro_overlay, "_last_state", None)
        if state is None:
            self.statusbar.showMessage("No telemetry state available yet", 3000)
            return

        base = self._cfg.car_state_base
        stride = self._cfg.car_state_size
        field_offset = CAR_STATE_INDEX_PIT_RELEASE_TIMER * 4

        updated = 0
        try:
            for struct_idx, car_state in state.car_states.items():
                if not car_state or len(getattr(car_state, "values", [])) <= CAR_STATE_INDEX_PIT_RELEASE_TIMER:
                    continue
                exe_offset = base + struct_idx * stride + field_offset
                self._mem.write(exe_offset, "i32", 1)
                updated += 1
        except Exception as exc:
            log.exception("Failed to release all cars from pits")
            self.statusbar.showMessage(f"Failed to release all cars: {exc}", 5000)
            return

        if updated:
            self.statusbar.showMessage(f"Pit release set to 1 for {updated} cars", 3000)
        else:
            self.statusbar.showMessage("No eligible cars found to release", 3000)

    def _force_all_cars_to_pit(self):
        """Force fuel remaining to 1 lap for all cars in the current state."""
        if not self._mem:
            self.statusbar.showMessage("Force pit unavailable: no memory connection", 5000)
            return

        state = self._latest_state or getattr(self.ro_overlay, "_last_state", None)
        if state is None:
            self.statusbar.showMessage("No telemetry state available yet", 3000)
            return

        base = self._cfg.car_state_base
        stride = self._cfg.car_state_size
        field_offset = self._cfg.fuel_laps_remaining
        field_index = field_offset // 4

        updated = 0
        try:
            for struct_idx, car_state in state.car_states.items():
                values = getattr(car_state, "values", [])
                if not car_state or len(values) <= field_index:
                    continue
                exe_offset = base + struct_idx * stride + field_offset
                self._mem.write(exe_offset, "i32", 1)
                updated += 1
        except Exception as exc:
            log.exception("Failed to force all cars to pit")
            self.statusbar.showMessage(f"Failed to force pit stops: {exc}", 5000)
            return

        if updated:
            self.statusbar.showMessage(f"Fuel set to 1 lap for {updated} cars", 3000)
        else:
            self.statusbar.showMessage("No eligible cars found to adjust fuel", 3000)

    def set_obs_capture_mode(self, enabled: bool):
        """
        Toggle overlays between translucent always-on-top 'overlay' mode (for Windy)
        and opaque 'OBS capture' mode (for streaming).
        Preserves visibility, transparency, and unique window titles.
        """
        from PyQt5 import QtCore
        from icr2timing.core.config import Config

        overlays = [
            self.ro_overlay.widget(),
            self.prox_overlay,
            self.track_overlay,
        ]

        for o in overlays:
            if o is None:
                continue

            was_visible = o.isVisible()
            geom = o.geometry()
            o.hide()

            if enabled:
                # --- OBS capture mode ---
                flags = QtCore.Qt.FramelessWindowHint | QtCore.Qt.Window
                translucent = False
            else:
                # --- Normal overlay mode (above Windy) ---
                flags = (
                    QtCore.Qt.FramelessWindowHint
                    | QtCore.Qt.Tool
                    | QtCore.Qt.WindowStaysOnTopHint
                )
                translucent = True

            o.setWindowFlags(flags)
            o.setAttribute(QtCore.Qt.WA_TranslucentBackground, translucent)

            # --- Give each overlay a unique title for OBS ---
            if enabled:
                if o is self.ro_overlay.widget():
                    o.setWindowTitle("ICR2 Timing - Running Order")
                elif o is self.track_overlay:
                    o.setWindowTitle("ICR2 Timing - Track Map")
                elif o is self.prox_overlay:
                    o.setWindowTitle("ICR2 Timing - Radar")
            else:
                o.setWindowTitle("")

            # --- Radar-specific transparency handling ---
            if hasattr(o, "cfg"):
                try:
                    from icr2timing.core.config import Config
                    o.cfg = Config()
                    o._update_ranges_from_cfg()
                    if translucent:
                        o.background.setAlpha(128)
                    else:
                        o.background.setAlpha(255)
                except Exception as e:
                    print(f"[ControlPanel] Radar transparency update failed: {e}")

            # --- Force DWM surface rebuild so transparency resets correctly ---
            o.setGeometry(geom)
            if was_visible:
                o.show()
                o.raise_()
                o.repaint()
            else:
                o.show()
                o.repaint()
                o.hide()

        mode = "OBS Capture" if enabled else "Overlay"
        self.statusbar.showMessage(f"Switched to {mode} mode")





    def _set_button_color(self, button: QtWidgets.QPushButton, rgba_str: str):
        """Color the button using an rgba string like '255,0,0,255'."""
        try:
            r, g, b, a = [int(x) for x in rgba_str.split(",")]
            button.setStyleSheet(
                f"background-color: rgba({r},{g},{b},{a}); border: 1px solid #444;"
            )
        except Exception:
            button.setStyleSheet("")


    def _pick_radar_color(self, which: str):
        # Get current color from overlay config
        cfg = self.prox_overlay.cfg
        if which == "player":
            current = cfg.radar_player_color
        elif which == "ahead":
            current = cfg.radar_ai_ahead_color
        elif which == "behind":
            current = cfg.radar_ai_behind_color
        elif which == "alongside":
            current = cfg.radar_ai_alongside_color
        else:
            current = "255,255,255,255"

        # Parse "r,g,b,a" → QColor
        parts = [int(x) for x in current.split(",")]
        while len(parts) < 4:
            parts.append(255)
        initial_color = QtGui.QColor(*parts)

        # Open color dialog with that as default
        color = QtWidgets.QColorDialog.getColor(initial_color, self, f"Select {which} color")
        if not color.isValid():
            return

        # Convert to string and apply
        rgba_str = f"{color.red()},{color.green()},{color.blue()},{color.alpha()}"

        if which == "player":
            self.prox_overlay.set_colors(player=rgba_str)
            self._set_button_color(self.btnPlayerColor, rgba_str)
            cfg.radar_player_color = rgba_str
        elif which == "ahead":
            self.prox_overlay.set_colors(ahead=rgba_str)
            self._set_button_color(self.btnAheadColor, rgba_str)
            cfg.radar_ai_ahead_color = rgba_str
        elif which == "behind":
            self.prox_overlay.set_colors(behind=rgba_str)
            self._set_button_color(self.btnBehindColor, rgba_str)
            cfg.radar_ai_behind_color = rgba_str
        elif which == "alongside":
            self.prox_overlay.set_colors(alongside=rgba_str)
            self._set_button_color(self.btnAlongColor, rgba_str)
            cfg.radar_ai_alongside_color = rgba_str

    def _sync_radar_ui_from_overlay(self):
        """Update all radar tab widgets to match the overlay's current config."""
        cfg = self.prox_overlay.cfg

        # Size
        self.spinRadarWidth.setValue(self.prox_overlay.width())
        self.spinRadarHeight.setValue(self.prox_overlay.height())

        # Ranges
        self.spinRadarForward.setValue(cfg.radar_range_forward)
        self.spinRadarRear.setValue(cfg.radar_range_rear)
        self.spinRadarSide.setValue(cfg.radar_range_side)

        # Symbol
        self.comboRadarSymbol.setCurrentText(cfg.radar_symbol.capitalize())

        # Colors
        self._set_button_color(self.btnPlayerColor, cfg.radar_player_color)
        self._set_button_color(self.btnAheadColor, cfg.radar_ai_ahead_color)
        self._set_button_color(self.btnBehindColor, cfg.radar_ai_behind_color)
        self._set_button_color(self.btnAlongColor, cfg.radar_ai_alongside_color)

    def _on_select_individual_car(self, index):
        """When user picks a new car number, update overlay's car index."""
        idx_data = self.selectIndividualCar.itemData(index)
        if idx_data is None:
            return
        self.indiv_overlay.set_car_index(idx_data)


    # -------------------------------
    # One-shot resize
    # -------------------------------
    def _resize_columns_once(self):
        self.ro_overlay.resize_columns_now()

    # -------------------------------
    # Close event = save last session
    # -------------------------------
    def closeEvent(self, event):
        # --- Save last session profile ---
        key_to_label = {field.key: field.label for field in AVAILABLE_FIELDS}
        ordered_keys = self._collect_field_keys()
        selected_labels = [key_to_label[k] for k in ordered_keys if k in key_to_label]
        indicator_enabled = "position_indicator" in ordered_keys

        custom_fields = []
        for i in range(self.customFieldList.count()):
            item = self.customFieldList.item(i)
            text = item.text()
            label, idx_str = text.split(" (")
            idx = int(idx_str.rstrip(")"))
            if item.checkState() == QtCore.Qt.Checked:
                custom_fields.append((label, idx))

        profile = Profile(
            name=LAST_SESSION_KEY,
            columns=selected_labels,
            n_columns=self.comboCols.itemData(self.comboCols.currentIndex()),
            display_mode="speed" if self.radioSpeed.isChecked() else "time",
            sort_by_best=self.cbSortBest.isChecked(),
            use_abbrev=self.cbAbbrev.isChecked(),
            window_x=self.ro_overlay.widget().x(),
            window_y=self.ro_overlay.widget().y(),
            radar_x=self.prox_overlay.x(),
            radar_y=self.prox_overlay.y(),
            radar_visible=self.prox_overlay.isVisible(),
            radar_width=self.prox_overlay.width(),
            radar_height=self.prox_overlay.height(),
            radar_range_forward=self.prox_overlay.cfg.radar_range_forward,
            radar_range_rear=self.prox_overlay.cfg.radar_range_rear,
            radar_range_side=self.prox_overlay.cfg.radar_range_side,
            radar_symbol=self.prox_overlay.symbol,
            radar_show_speeds=self.prox_overlay.show_speeds,
            radar_player_color=self.prox_overlay.cfg.radar_player_color,
            radar_ai_ahead_color=self.prox_overlay.cfg.radar_ai_ahead_color,
            radar_ai_behind_color=self.prox_overlay.cfg.radar_ai_behind_color,
            radar_ai_alongside_color=self.prox_overlay.cfg.radar_ai_alongside_color,
            position_indicator_duration=self.spinPosChangeDuration.value(),
            position_indicator_enabled=indicator_enabled,
            custom_fields=custom_fields,   # ✅ new
        )
        self.profiles.save_last_session(profile)

        # --- Stop updater thread cleanly ---
        if self.updater:
            try:
                QtCore.QMetaObject.invokeMethod(
                    self.updater,
                    "stop",
                    QtCore.Qt.QueuedConnection
                )
            except Exception as e:
                print(f"[ControlPanel] Error stopping updater: {e}")

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
