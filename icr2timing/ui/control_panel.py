"""
control_panel.py

Control panel window now built from control_panel.ui (Qt Designer).
Uses OverlayManager (multi-overlay) + ProfileManager.
"""

import time
import os, configparser, sys
from PyQt5 import QtWidgets, QtCore, uic, QtGui


import logging
log = logging.getLogger(__name__)

from updater.overlay_manager import OverlayManager
from overlays.running_order_overlay import RunningOrderOverlayTable, AVAILABLE_FIELDS
from ui.profile_manager import ProfileManager, Profile, LAST_SESSION_KEY
from overlays.proximity_overlay import ProximityOverlay
from overlays.track_map_overlay import TrackMapOverlay
from overlays.individual_car_overlay import IndividualCarOverlay
from car_data_editor import CarDataEditorWidget
from core.config import Config
from core.version import __version__
from core.telemetry_laps import TelemetryLapLogger


CAR_STATE_INDEX_PIT_RELEASE_TIMER = 98


class ControlPanel(QtWidgets.QMainWindow):
    exe_path_changed = QtCore.pyqtSignal(str)

    def __init__(self, updater, mem=None, cfg=None):
        super().__init__()
        uic.loadUi(
            os.path.join(os.path.dirname(__file__), "control_panel.ui"),
            self
        )

        self.updater = updater
        self._mem = mem
        self._cfg = cfg or Config()
        self._latest_state = None
        self._car_data_editor_widget = None

        # --- Overlay Manager ---
        self.manager = OverlayManager()
        self.ro_overlay = RunningOrderOverlayTable()
        self.manager.add_overlay(self.ro_overlay)

        # Radar handled separately (not added to OverlayManager)
        self.prox_overlay = ProximityOverlay()
        if self.updater:
            self.updater.state_updated.connect(self.prox_overlay.on_state_updated)
            self.updater.error.connect(self.prox_overlay.on_error)

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

        if self.updater:
            self.manager.connect_updater(self.updater)
            self.updater.error.connect(self._on_error_from_updater)

        # Track map overlay
        self.track_overlay = TrackMapOverlay()
        if self.updater:
            self.updater.state_updated.connect(self.track_overlay.on_state_updated)
            self.updater.error.connect(self.track_overlay.on_error)

        # Individual car overlay
        self.indiv_overlay = IndividualCarOverlay()
        if self.updater:
            self.updater.state_updated.connect(self.indiv_overlay.on_state_updated)
            self.updater.error.connect(self.indiv_overlay.on_error)

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

        if self.updater and self._mem:
            container_layout = getattr(self, "carDataEditorLayout", None)
            container_parent = getattr(self, "carDataEditorContainer", None)
            if isinstance(container_layout, QtWidgets.QLayout):
                while container_layout.count():
                    item = container_layout.takeAt(0)
                    widget = item.widget()
                    if widget is not None:
                        widget.deleteLater()
                self._car_data_editor_widget = CarDataEditorWidget(
                    self.updater,
                    self._mem,
                    self._cfg,
                    status_callback=self.statusbar.showMessage,
                    parent=container_parent,
                )
                container_layout.addWidget(self._car_data_editor_widget)
                self.updater.state_updated.connect(
                    self._car_data_editor_widget.on_state_updated
                )
                self.updater.error.connect(self._car_data_editor_widget.on_error)
            else:
                log.warning("Car data editor container layout missing; widget not created")

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

        # Profiles
        self.profileCombo.currentTextChanged.connect(self._load_profile)
        self.addProfileBtn.clicked.connect(self._add_new_profile)
        self.saveProfileBtn.clicked.connect(self._save_current_profile)
        self.deleteProfileBtn.clicked.connect(self._delete_current_profile)

        # Driver names / sorting
        self.cbAbbrev.stateChanged.connect(self._update_abbrev)
        self.cbSortBest.stateChanged.connect(self._update_sorting)

        # Lap display
        self.radioTime.setChecked(True)
        self.radioTime.toggled.connect(self._update_display_mode)
        self.radioSpeed.toggled.connect(self._update_display_mode)

        # Columns & layout
        self.field_checks = {}
        for field in AVAILABLE_FIELDS:
            cb = QtWidgets.QCheckBox(field.label, self.fieldsContainer)
            cb.setChecked(True)
            cb.stateChanged.connect(self._update_fields)
            self.fieldsLayout.addWidget(cb)
            self.field_checks[field.key] = cb

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
        if self.updater:
            self.updater.state_updated.connect(self._on_state_updated_update_carlist)

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

        # --- Game EXE selection ---
        self.btnSelectExe.clicked.connect(self._choose_exe)
        self.lblExePath.setText(self._current_exe_path())

        # --- Track Map Settings tab connections ---
        # Scale slider (value is 10–200, map to 0.1–2.0 scale factor)
        self.sliderMapScale.setMinimum(10)
        self.sliderMapScale.setMaximum(200)
        self.sliderMapScale.setValue(int(self.track_overlay._scale_factor * 100))
        self.sliderMapScale.valueChanged.connect(
            lambda val: self.track_overlay.set_scale_factor(val / 100.0)
        )

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
    # EXE path handling
    # -------------------------------
    def _current_exe_path(self) -> str:
        cfg = Config()
        return cfg.game_exe or "No EXE selected"

    def _save_exe_path(self, path: str):
        cfgfile = os.path.join(os.path.dirname(sys.argv[0]), "settings.ini")
        parser = configparser.ConfigParser()
        parser.read(cfgfile)
        if "paths" not in parser:
            parser.add_section("paths")
        parser["paths"]["game_exe"] = path
        with open(cfgfile, "w") as f:
            parser.write(f)

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

        # ✅ Update global Config() instances in memory
        from core import config as cfgmod
        cfgmod._parser.set("paths", "game_exe", path)
        cfgmod._parser.write(open(cfgmod._cfgfile, "w"))

        # clear mute so TrackMapOverlay can retry loading
        self.track_overlay._last_load_failed = False

        # Also patch the live default Config in memory
        cfgmod.Config.game_exe = path
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
    def _toggle_indiv_overlay(self):
        idx_data = self.selectIndividualCar.currentData()
        if idx_data is None:
            return

        self.indiv_overlay.car_index = idx_data

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

    def _update_fields(self):
        enabled = [k for k, cb in self.field_checks.items() if cb.isChecked()]
        self.ro_overlay.set_enabled_fields(enabled)

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
        # Build a snapshot of current car numbers
        current_numbers = [
            str(driver.car_number)
            for driver in state.drivers.values()
            if driver and driver.car_number is not None
        ]

        # if no change, do nothing
        if getattr(self, "_last_car_numbers", None) == current_numbers:
            return

        # store new set and repopulate
        self._last_car_numbers = current_numbers

        self.selectIndividualCar.blockSignals(True)
        self.selectIndividualCar.clear()
        for idx, driver in state.drivers.items():
            if not driver or driver.car_number is None:
                continue
            # text is car number only, data is struct index
            self.selectIndividualCar.addItem(str(driver.car_number), idx)
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
        wanted_keys = {label_to_key.get(lbl) for lbl in prof.columns if lbl in label_to_key}

        # Columns
        for k, cb in self.field_checks.items():
            cb.setChecked(k in wanted_keys)

        if prof.n_columns != (self.comboCols.currentIndex() + 1):
            self.comboCols.setCurrentIndex(prof.n_columns - 1)
        else:
            self.ro_overlay.set_enabled_fields(list(wanted_keys))

        if prof.display_mode == "speed":
            self.radioSpeed.setChecked(True)
        else:
            self.radioTime.setChecked(True)

        self.cbSortBest.setChecked(prof.sort_by_best)
        self.cbAbbrev.setChecked(prof.use_abbrev)
        self.cbAutosize.setChecked(self.ro_overlay._autosize_enabled)

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
            self.customFieldList.addItem(item)


    def _save_current_profile(self):
        profile_name = self.profileCombo.currentText().strip()
        if not profile_name:
            return

        # Columns
        key_to_label = {field.key: field.label for field in AVAILABLE_FIELDS}
        selected_labels = [key_to_label[k] for k, cb in self.field_checks.items() if cb.isChecked()]

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

        profile = Profile(
            name=name.strip(),
            columns=selected_labels,
            n_columns=self.comboCols.itemData(self.comboCols.currentIndex()),
            display_mode="speed" if self.radioSpeed.isChecked() else "time",
            sort_by_best=self.cbSortBest.isChecked(),
            use_abbrev=self.cbAbbrev.isChecked(),
            window_x=self.ro_overlay.widget().x(),
            window_y=self.ro_overlay.widget().y(),
        )
        # Radar state
        profile.radar_x = self.prox_overlay.x()
        profile.radar_y = self.prox_overlay.y()
        profile.radar_visible = self.prox_overlay.isVisible()

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
        from core.telemetry_laps import TelemetryLapLogger

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
        from core.config import Config

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
                    from core.config import Config
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
        from overlays.running_order_overlay import AVAILABLE_FIELDS
        key_to_label = {field.key: field.label for field in AVAILABLE_FIELDS}
        enabled_keys = self.ro_overlay.get_enabled_fields()
        selected_labels = [key_to_label[k] for k in enabled_keys if k in key_to_label]

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
            custom_fields=custom_fields,   # ✅ new
        )
        self.profiles.save_last_session(profile)

        if self._car_data_editor_widget is not None:
            try:
                self._car_data_editor_widget.shutdown()
            except Exception:
                log.exception('Failed to shut down car data editor widget')

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
            if self.track_overlay and self.track_overlay.isVisible():
                self.track_overlay.close()
        except Exception:
            pass

        try:
            if self.prox_overlay and self.prox_overlay.isVisible():
                self.prox_overlay.close()
        except Exception:
            pass

        # Call parent closeEvent
        super().closeEvent(event)
