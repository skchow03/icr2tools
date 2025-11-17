"""UI section helpers used by ControlPanel."""

from __future__ import annotations

from typing import Tuple

from PyQt5 import QtCore, QtGui, QtWidgets


class OverlayControlsSection(QtCore.QObject):
    """Manage overlay control buttons within the Live Timing tab."""

    toggle_overlay_requested = QtCore.pyqtSignal()
    reset_requested = QtCore.pyqtSignal()
    quit_requested = QtCore.pyqtSignal()
    radar_toggle_requested = QtCore.pyqtSignal()
    track_map_toggle_requested = QtCore.pyqtSignal()
    surface_overlay_toggle_requested = QtCore.pyqtSignal()

    def __init__(
        self,
        *,
        btn_toggle_overlay: QtWidgets.QPushButton,
        btn_reset: QtWidgets.QPushButton,
        btn_quit: QtWidgets.QPushButton,
        btn_radar: QtWidgets.QPushButton,
        btn_track_map: QtWidgets.QPushButton,
        btn_surface_overlay: QtWidgets.QPushButton,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._btn_toggle_overlay = btn_toggle_overlay
        self._btn_radar = btn_radar
        self._btn_track_map = btn_track_map
        self._btn_surface_overlay = btn_surface_overlay
        btn_toggle_overlay.clicked.connect(self.toggle_overlay_requested.emit)
        btn_reset.clicked.connect(self.reset_requested.emit)
        btn_quit.clicked.connect(self.quit_requested.emit)
        btn_radar.clicked.connect(self.radar_toggle_requested.emit)
        btn_track_map.clicked.connect(self.track_map_toggle_requested.emit)
        btn_surface_overlay.clicked.connect(
            self.surface_overlay_toggle_requested.emit
        )

    def set_overlay_visible(self, visible: bool) -> None:
        text = "Hide Overlay" if visible else "Show Overlay"
        self._btn_toggle_overlay.setText(text)

    def set_radar_visible(self, visible: bool) -> None:
        text = "Hide Radar" if visible else "Show Radar"
        self._btn_radar.setText(text)

    def set_track_map_visible(self, visible: bool) -> None:
        text = "Hide Track Map" if visible else "Show Track Map"
        self._btn_track_map.setText(text)

    def set_surface_overlay_visible(self, visible: bool) -> None:
        text = "Hide Surface Overlay" if visible else "Show Surface Overlay"
        self._btn_surface_overlay.setText(text)


class RadarSettingsSection(QtCore.QObject):
    """Encapsulate radar settings UI and live overlay updates."""

    def __init__(
        self,
        *,
        overlay: QtWidgets.QWidget,
        config_store,
        parent: QtWidgets.QWidget,
        spin_width: QtWidgets.QSpinBox,
        spin_height: QtWidgets.QSpinBox,
        spin_forward: QtWidgets.QSpinBox,
        spin_rear: QtWidgets.QSpinBox,
        spin_side: QtWidgets.QSpinBox,
        combo_symbol: QtWidgets.QComboBox,
        btn_player_color: QtWidgets.QPushButton,
        btn_ahead_color: QtWidgets.QPushButton,
        btn_behind_color: QtWidgets.QPushButton,
        btn_along_color: QtWidgets.QPushButton,
        color_button_setter,
    ) -> None:
        super().__init__(parent)
        self._overlay = overlay
        self._config_store = config_store
        self._parent_widget = parent
        self._set_button_color = color_button_setter
        self._spin_width = spin_width
        self._spin_height = spin_height
        self._spin_forward = spin_forward
        self._spin_rear = spin_rear
        self._spin_side = spin_side
        self._combo_symbol = combo_symbol
        self._btn_player_color = btn_player_color
        self._btn_ahead_color = btn_ahead_color
        self._btn_behind_color = btn_behind_color
        self._btn_along_color = btn_along_color

        self._apply_config()
        self._wire_signals()
        self._config_store.overlay_setting_changed.connect(
            self._on_overlay_settings_changed
        )

    # ------------------------------------------------------------------
    def _apply_config(self) -> None:
        cfg = self._config_store.config
        self._spin_width.setValue(cfg.radar_width)
        self._spin_height.setValue(cfg.radar_height)
        self._spin_forward.setValue(cfg.radar_range_forward)
        self._spin_rear.setValue(cfg.radar_range_rear)
        self._spin_side.setValue(cfg.radar_range_side)
        self._combo_symbol.setCurrentText(cfg.radar_symbol.capitalize())
        self._set_button_color(self._btn_player_color, cfg.radar_player_color)
        self._set_button_color(self._btn_ahead_color, cfg.radar_ai_ahead_color)
        self._set_button_color(self._btn_behind_color, cfg.radar_ai_behind_color)
        self._set_button_color(self._btn_along_color, cfg.radar_ai_alongside_color)

    def _wire_signals(self) -> None:
        self._spin_width.valueChanged.connect(self._on_size_changed)
        self._spin_height.valueChanged.connect(self._on_size_changed)
        self._spin_forward.valueChanged.connect(
            lambda v: self._overlay.set_range(forward=v)
        )
        self._spin_rear.valueChanged.connect(lambda v: self._overlay.set_range(rear=v))
        self._spin_side.valueChanged.connect(lambda v: self._overlay.set_range(side=v))
        self._combo_symbol.currentTextChanged.connect(
            lambda t: self._overlay.set_symbol(t.lower())
        )
        self._btn_player_color.clicked.connect(
            lambda: self._pick_radar_color("player")
        )
        self._btn_ahead_color.clicked.connect(lambda: self._pick_radar_color("ahead"))
        self._btn_behind_color.clicked.connect(
            lambda: self._pick_radar_color("behind")
        )
        self._btn_along_color.clicked.connect(
            lambda: self._pick_radar_color("alongside")
        )

    # ------------------------------------------------------------------
    def _on_size_changed(self, _value: int) -> None:
        self._overlay.set_size(
            self._spin_width.value(),
            self._spin_height.value(),
        )

    def _on_overlay_settings_changed(self, section: str) -> None:
        if section != "radar":
            return
        self.sync_from_store()

    def sync_from_store(self) -> None:
        """Update UI widgets to match the persistent config store."""
        cfg = self._config_store.config
        blockers = [
            QtCore.QSignalBlocker(self._spin_width),
            QtCore.QSignalBlocker(self._spin_height),
            QtCore.QSignalBlocker(self._spin_forward),
            QtCore.QSignalBlocker(self._spin_rear),
            QtCore.QSignalBlocker(self._spin_side),
            QtCore.QSignalBlocker(self._combo_symbol),
        ]
        try:
            self._spin_width.setValue(cfg.radar_width)
            self._spin_height.setValue(cfg.radar_height)
            self._spin_forward.setValue(cfg.radar_range_forward)
            self._spin_rear.setValue(cfg.radar_range_rear)
            self._spin_side.setValue(cfg.radar_range_side)
            self._combo_symbol.setCurrentText(cfg.radar_symbol.capitalize())
        finally:
            for blocker in blockers:
                del blocker
        self._set_button_color(self._btn_player_color, cfg.radar_player_color)
        self._set_button_color(self._btn_ahead_color, cfg.radar_ai_ahead_color)
        self._set_button_color(self._btn_behind_color, cfg.radar_ai_behind_color)
        self._set_button_color(self._btn_along_color, cfg.radar_ai_alongside_color)

    def apply_profile(self, profile) -> None:
        """Apply radar-related values from a saved profile."""
        self._overlay.move(profile.radar_x, profile.radar_y)
        self._overlay.resize(profile.radar_width, profile.radar_height)
        self._overlay.set_range(
            forward=profile.radar_range_forward,
            rear=profile.radar_range_rear,
            side=profile.radar_range_side,
        )
        self._overlay.set_symbol(profile.radar_symbol)
        self._overlay.set_show_speeds(profile.radar_show_speeds)
        self._overlay.set_colors(
            player=profile.radar_player_color,
            ahead=profile.radar_ai_ahead_color,
            behind=profile.radar_ai_behind_color,
            alongside=profile.radar_ai_alongside_color,
        )
        self._set_button_color(self._btn_player_color, profile.radar_player_color)
        self._set_button_color(self._btn_ahead_color, profile.radar_ai_ahead_color)
        self._set_button_color(self._btn_behind_color, profile.radar_ai_behind_color)
        self._set_button_color(self._btn_along_color, profile.radar_ai_alongside_color)
        self.sync_from_store()

    def _pick_radar_color(self, which: str) -> None:
        cfg = self._config_store.config
        current = {
            "player": cfg.radar_player_color,
            "ahead": cfg.radar_ai_ahead_color,
            "behind": cfg.radar_ai_behind_color,
            "alongside": cfg.radar_ai_alongside_color,
        }.get(which, "255,255,255,255")

        parts = [int(x) for x in current.split(",") if x]
        while len(parts) < 4:
            parts.append(255)
        initial = QtGui.QColor(*parts)
        color = QtWidgets.QColorDialog.getColor(
            initial,
            self._parent_widget,
            f"Select {which} color",
        )
        if not color.isValid():
            return

        rgba_str = f"{color.red()},{color.green()},{color.blue()},{color.alpha()}"
        if which == "player":
            self._overlay.set_colors(player=rgba_str)
            self._set_button_color(self._btn_player_color, rgba_str)
        elif which == "ahead":
            self._overlay.set_colors(ahead=rgba_str)
            self._set_button_color(self._btn_ahead_color, rgba_str)
        elif which == "behind":
            self._overlay.set_colors(behind=rgba_str)
            self._set_button_color(self._btn_behind_color, rgba_str)
        elif which == "alongside":
            self._overlay.set_colors(alongside=rgba_str)
            self._set_button_color(self._btn_along_color, rgba_str)


class ProfileManagementSection(QtCore.QObject):
    """Handle UI interactions for profile management widgets."""

    profile_selected = QtCore.pyqtSignal(str)
    add_requested = QtCore.pyqtSignal()
    save_requested = QtCore.pyqtSignal()
    delete_requested = QtCore.pyqtSignal()

    def __init__(
        self,
        *,
        manager,
        combo: QtWidgets.QComboBox,
        add_button: QtWidgets.QPushButton,
        save_button: QtWidgets.QPushButton,
        delete_button: QtWidgets.QPushButton,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._manager = manager
        self._combo = combo
        combo.addItems(manager.list_profiles())
        combo.currentTextChanged.connect(self.profile_selected.emit)
        add_button.clicked.connect(self.add_requested.emit)
        save_button.clicked.connect(self.save_requested.emit)
        delete_button.clicked.connect(self.delete_requested.emit)

    def refresh_profiles(self) -> None:
        self._combo.blockSignals(True)
        self._combo.clear()
        self._combo.addItems(self._manager.list_profiles())
        self._combo.blockSignals(False)


class TelemetryControlsSection(QtCore.QObject):
    """Wire telemetry management widgets to high-level signals."""

    lap_logger_toggle_requested = QtCore.pyqtSignal()
    release_all_cars_requested = QtCore.pyqtSignal()
    force_all_cars_requested = QtCore.pyqtSignal()
    individual_overlay_toggle_requested = QtCore.pyqtSignal()
    individual_car_selected = QtCore.pyqtSignal(int)

    def __init__(
        self,
        *,
        btn_lap_logger: QtWidgets.QPushButton,
        btn_release_all: QtWidgets.QPushButton,
        btn_force_pits: QtWidgets.QPushButton,
        btn_toggle_individual: QtWidgets.QPushButton,
        select_individual_car: QtWidgets.QComboBox,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._lap_logger_button = btn_lap_logger
        self._car_combo = select_individual_car
        self._toggle_individual_button = btn_toggle_individual
        self._last_car_snapshot: list[Tuple[int, str]] | None = None

        btn_lap_logger.setText("Enable Lap Logger")
        btn_lap_logger.clicked.connect(self.lap_logger_toggle_requested.emit)
        btn_release_all.clicked.connect(self.release_all_cars_requested.emit)
        btn_force_pits.clicked.connect(self.force_all_cars_requested.emit)
        btn_toggle_individual.clicked.connect(
            self.individual_overlay_toggle_requested.emit
        )
        select_individual_car.currentIndexChanged.connect(
            self._emit_car_selection
        )

    def set_lap_logger_enabled(self, enabled: bool) -> None:
        text = "Disable Lap Logger" if enabled else "Enable Lap Logger"
        self._lap_logger_button.setText(text)

    def update_car_list(self, state) -> None:
        if state is None:
            return
        current_snapshot: list[Tuple[int, str]] = [
            (driver.car_number, driver.name or "")
            for _, driver in sorted(state.drivers.items())
            if driver and driver.car_number is not None
        ]
        if self._last_car_snapshot == current_snapshot:
            return
        self._last_car_snapshot = current_snapshot

        self._car_combo.blockSignals(True)
        self._car_combo.clear()
        for idx, driver in sorted(state.drivers.items()):
            if not driver or driver.car_number is None:
                continue
            name = (driver.name or "").strip()
            if name:
                display_text = f"{driver.car_number} - {name}"
            else:
                display_text = str(driver.car_number)
            self._car_combo.addItem(display_text, idx)
        self._car_combo.blockSignals(False)

    def current_car_index(self):
        return self._car_combo.currentData()

    def set_individual_overlay_visible(self, visible: bool) -> None:
        text = "Hide telemetry overlay" if visible else "Show telemetry overlay"
        self._toggle_individual_button.setText(text)

    def _emit_car_selection(self, index: int) -> None:
        idx_data = self._car_combo.itemData(index)
        if idx_data is None:
            return
        self.individual_car_selected.emit(idx_data)

