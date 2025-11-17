from __future__ import annotations

from typing import List, Tuple

from PyQt5 import QtWidgets, QtCore

from icr2timing.overlays.running_order_overlay import (
    AVAILABLE_FIELDS,
    RunningOrderOverlayTable,
)
from icr2timing.ui.profile_manager import ProfileManager, Profile
from icr2timing.ui.services import SessionSnapshot


class ControlPanelPresenter(QtCore.QObject):
    """Encapsulates stateful interactions between the UI and overlay/profile data."""

    def __init__(
        self,
        parent: QtWidgets.QWidget,
        profile_manager: ProfileManager,
        running_order_overlay: RunningOrderOverlayTable,
        profile_combo: QtWidgets.QComboBox,
        fields_list: QtWidgets.QListWidget,
        custom_field_list: QtWidgets.QListWidget,
        spin_pos_change_duration: QtWidgets.QSpinBox,
        indicator_label: QtWidgets.QLabel,
        combo_columns: QtWidgets.QComboBox,
        radio_time: QtWidgets.QRadioButton,
        radio_speed: QtWidgets.QRadioButton,
        cb_sort_best: QtWidgets.QCheckBox,
        cb_abbrev: QtWidgets.QCheckBox,
        prox_overlay,
        cfg,
        cust_label_edit: QtWidgets.QLineEdit,
        cust_index_spin: QtWidgets.QSpinBox,
    ):
        super().__init__(parent)
        self._parent = parent
        self.profile_manager = profile_manager
        self._ro_overlay = running_order_overlay
        self.profile_combo = profile_combo
        self.fields_list = fields_list
        self.custom_field_list = custom_field_list
        self.spin_pos_change_duration = spin_pos_change_duration
        self.indicator_label = indicator_label
        self.combo_columns = combo_columns
        self.radio_time = radio_time
        self.radio_speed = radio_speed
        self.cb_sort_best = cb_sort_best
        self.cb_abbrev = cb_abbrev
        self.prox_overlay = prox_overlay
        self._cfg = cfg
        self.cust_label_edit = cust_label_edit
        self.cust_index_spin = cust_index_spin

    # --- Wiring helpers -------------------------------------------------
    def update_config(self, cfg) -> None:
        self._cfg = cfg

    def set_running_order_overlay(self, overlay: RunningOrderOverlayTable) -> None:
        self._ro_overlay = overlay

    # --- Field helpers ---------------------------------------------------
    def collect_field_keys(self, include_unchecked: bool = False) -> List[str]:
        keys: List[str] = []
        for i in range(self.fields_list.count()):
            item = self.fields_list.item(i)
            if item is None:
                continue
            key = item.data(QtCore.Qt.UserRole)
            if not key:
                continue
            if include_unchecked or item.checkState() == QtCore.Qt.Checked:
                keys.append(key)
        return keys

    def update_indicator_controls(self) -> None:
        indicator_enabled = "position_indicator" in self._ro_overlay.get_enabled_fields()
        self.spin_pos_change_duration.setEnabled(indicator_enabled)
        self.indicator_label.setEnabled(indicator_enabled)

    # --- Custom field helpers -------------------------------------------
    def add_custom_field(self) -> None:
        label = self.cust_label_edit.text().strip()
        index = self.cust_index_spin.value()
        if not label:
            return

        self._ro_overlay.add_custom_field(label, index)

        item = QtWidgets.QListWidgetItem(f"{label} ({index})")
        item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
        item.setCheckState(QtCore.Qt.Checked)
        item.setToolTip(f"Car data struct index {index} (custom field)")
        self.custom_field_list.addItem(item)

        self.cust_label_edit.clear()
        self.cust_index_spin.setValue(0)

    def remove_selected_custom_fields(self) -> None:
        for item in list(self.custom_field_list.selectedItems()):
            text = item.text()
            label = text.split(" (")[0]
            self._ro_overlay.remove_custom_field(label)
            self.custom_field_list.takeItem(self.custom_field_list.row(item))

    def handle_custom_field_toggled(self, item: QtWidgets.QListWidgetItem) -> None:
        text = item.text()
        label, idx_str = text.split(" (")
        idx = int(idx_str.rstrip(")"))

        if item.checkState() == QtCore.Qt.Checked:
            self._ro_overlay.add_custom_field(label, idx)
        else:
            self._ro_overlay.remove_custom_field(label)

    # --- Profile helpers -------------------------------------------------
    def save_current_profile(self) -> None:
        profile_name = self.profile_combo.currentText().strip()
        if not profile_name:
            return

        key_to_label = {field.key: field.label for field in AVAILABLE_FIELDS}
        ordered_keys = self.collect_field_keys()
        selected_labels = [key_to_label[k] for k in ordered_keys if k in key_to_label]
        indicator_enabled = "position_indicator" in ordered_keys

        profile = Profile(
            name=profile_name,
            columns=selected_labels,
            n_columns=self.combo_columns.itemData(self.combo_columns.currentIndex()),
            display_mode="speed" if self.radio_speed.isChecked() else "time",
            sort_by_best=self.cb_sort_best.isChecked(),
            use_abbrev=self.cb_abbrev.isChecked(),
            window_x=self._ro_overlay.widget().x(),
            window_y=self._ro_overlay.widget().y(),
            radar_x=self.prox_overlay.x(),
            radar_y=self.prox_overlay.y(),
            radar_visible=self.prox_overlay.isVisible(),
            radar_width=self.prox_overlay.width(),
            radar_height=self.prox_overlay.height(),
            radar_range_forward=self._cfg.radar_range_forward,
            radar_range_rear=self._cfg.radar_range_rear,
            radar_range_side=self._cfg.radar_range_side,
            radar_symbol=self.prox_overlay.symbol,
            radar_show_speeds=self.prox_overlay.show_speeds,
            radar_player_color=self._cfg.radar_player_color,
            radar_ai_ahead_color=self._cfg.radar_ai_ahead_color,
            radar_ai_behind_color=self._cfg.radar_ai_behind_color,
            radar_ai_alongside_color=self._cfg.radar_ai_alongside_color,
            position_indicator_duration=self.spin_pos_change_duration.value(),
            position_indicator_enabled=indicator_enabled,
            custom_fields=self._collect_checked_custom_fields(),
        )

        self.profile_manager.save(profile)
        if profile_name not in [self.profile_combo.itemText(i) for i in range(self.profile_combo.count())]:
            self.profile_combo.addItem(profile_name)
        self.profile_combo.setCurrentText(profile_name)

        QtWidgets.QMessageBox.information(
            self._parent,
            "Profile Saved",
            f"Current settings have been saved to profile '{profile_name}'.",
        )

    def delete_current_profile(self) -> None:
        profile_name = self.profile_combo.currentText()
        if not profile_name:
            return
        reply = QtWidgets.QMessageBox.question(
            self._parent,
            "Delete Profile",
            f"Delete profile '{profile_name}'?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if reply == QtWidgets.QMessageBox.Yes and self.profile_manager.delete(profile_name):
            idx = self.profile_combo.findText(profile_name)
            if idx >= 0:
                self.profile_combo.removeItem(idx)

    def add_new_profile(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(
            self._parent, "New Profile", "Enter profile name:"
        )
        if not ok or not name.strip():
            return

        key_to_label = {field.key: field.label for field in AVAILABLE_FIELDS}
        enabled_keys = self._ro_overlay.get_enabled_fields()
        selected_labels = [key_to_label[k] for k in enabled_keys if k in key_to_label]
        indicator_enabled = "position_indicator" in enabled_keys

        profile = Profile(
            name=name.strip(),
            columns=selected_labels,
            n_columns=self.combo_columns.itemData(self.combo_columns.currentIndex()),
            display_mode="speed" if self.radio_speed.isChecked() else "time",
            sort_by_best=self.cb_sort_best.isChecked(),
            use_abbrev=self.cb_abbrev.isChecked(),
            window_x=self._ro_overlay.widget().x(),
            window_y=self._ro_overlay.widget().y(),
            radar_x=self.prox_overlay.x(),
            radar_y=self.prox_overlay.y(),
            radar_visible=self.prox_overlay.isVisible(),
            radar_width=self.prox_overlay.width(),
            radar_height=self.prox_overlay.height(),
            radar_range_forward=self._cfg.radar_range_forward,
            radar_range_rear=self._cfg.radar_range_rear,
            radar_range_side=self._cfg.radar_range_side,
            radar_symbol=self.prox_overlay.symbol,
            radar_show_speeds=self.prox_overlay.show_speeds,
            radar_player_color=self._cfg.radar_player_color,
            radar_ai_ahead_color=self._cfg.radar_ai_ahead_color,
            radar_ai_behind_color=self._cfg.radar_ai_behind_color,
            radar_ai_alongside_color=self._cfg.radar_ai_alongside_color,
            position_indicator_duration=self.spin_pos_change_duration.value(),
            position_indicator_enabled=indicator_enabled,
        )

        self.profile_manager.save(profile)

        if name not in [self.profile_combo.itemText(i) for i in range(self.profile_combo.count())]:
            self.profile_combo.addItem(name)
        self.profile_combo.setCurrentText(name)

    # --- Session helpers -------------------------------------------------
    def build_session_snapshot(self) -> SessionSnapshot:
        ordered_keys = self.collect_field_keys()
        indicator_enabled = "position_indicator" in ordered_keys

        return SessionSnapshot(
            ordered_field_keys=ordered_keys,
            custom_fields=self._collect_checked_custom_fields(),
            n_columns=self.combo_columns.itemData(self.combo_columns.currentIndex()),
            display_mode="speed" if self.radio_speed.isChecked() else "time",
            sort_by_best=self.cb_sort_best.isChecked(),
            use_abbrev=self.cb_abbrev.isChecked(),
            ro_window_x=self._ro_overlay.widget().x(),
            ro_window_y=self._ro_overlay.widget().y(),
            radar_x=self.prox_overlay.x(),
            radar_y=self.prox_overlay.y(),
            radar_visible=self.prox_overlay.isVisible(),
            radar_width=self.prox_overlay.width(),
            radar_height=self.prox_overlay.height(),
            radar_range_forward=self._cfg.radar_range_forward,
            radar_range_rear=self._cfg.radar_range_rear,
            radar_range_side=self._cfg.radar_range_side,
            radar_symbol=self.prox_overlay.symbol,
            radar_show_speeds=self.prox_overlay.show_speeds,
            radar_player_color=self._cfg.radar_player_color,
            radar_ai_ahead_color=self._cfg.radar_ai_ahead_color,
            radar_ai_behind_color=self._cfg.radar_ai_behind_color,
            radar_ai_alongside_color=self._cfg.radar_ai_alongside_color,
            position_indicator_duration=self.spin_pos_change_duration.value(),
            position_indicator_enabled=indicator_enabled,
            available_fields=AVAILABLE_FIELDS,
        )

    # --- Internal helpers ------------------------------------------------
    def _collect_checked_custom_fields(self) -> List[Tuple[str, int]]:
        custom_fields: List[Tuple[str, int]] = []
        for i in range(self.custom_field_list.count()):
            item = self.custom_field_list.item(i)
            if not item:
                continue
            text = item.text()
            label, idx_str = text.split(" (")
            idx = int(idx_str.rstrip(")"))
            if item.checkState() == QtCore.Qt.Checked:
                custom_fields.append((label, idx))
        return custom_fields
