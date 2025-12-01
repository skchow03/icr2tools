"""QObject-based singleton store for configuration management."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Mapping, Optional

try:  # pragma: no cover - PyQt5 not available in headless CI
    from PyQt5 import QtCore
except ImportError:  # pragma: no cover
    class _SimpleSignal:
        def __init__(self) -> None:
            self._slots = []

        def connect(self, slot):
            self._slots.append(slot)

        def emit(self, *args, **kwargs):
            for slot in list(self._slots):
                slot(*args, **kwargs)

    class _SignalDescriptor:
        def __set_name__(self, owner, name):
            self._name = f"__signal_{name}"

        def __get__(self, instance, owner):
            if instance is None:
                return self
            signal = getattr(instance, self._name, None)
            if signal is None:
                signal = _SimpleSignal()
                setattr(instance, self._name, signal)
            return signal

    class _QtCore:
        class QObject:
            def __init__(self, *_, **__):
                pass

        @staticmethod
        def pyqtSignal(*_args, **_kwargs):
            return _SignalDescriptor()

    QtCore = _QtCore()

from icr2timing.core.config_backend import (
    ConfigBackend,
    EXE_INFO_SECTION,
    EXE_VERSIONS,
    VERSION_ALIASES,
)

OFFSETS = {
    "REND32A": {
        "run_order_base": 0x000EF638,
        "car_numbers_base": 0x000EDE88,
        "driver_names_base": 0x000EDF3E,
        "cars_addr": 0x0E71A8,
        "laps_addr": 0xB8C98,
        "car_state_base": 0x000E1DC4,
        "track_length_addr": 0x000F15BC,
        "current_track_addr": 0x000F823D,
    },
    "DOS102": {
        "run_order_base": 0xDAA1C,
        "car_numbers_base": 0xCB700,
        "driver_names_base": 0xCAD8E,
        "cars_addr": 0xDAA18,
        "laps_addr": 0xAD578,
        "car_state_base": 0xD5638,
        "track_length_addr": 0xDFFB4,
        "current_track_addr": 0xE2EE9,
        "session_timer_addr": 0xDC61C,
    },
    "WINDY101": {
        "run_order_base": 0x50FD64,
        "car_numbers_base": 0x515120,
        "driver_names_base": 0x5153B6,
        "cars_addr": 0x524664,
        "laps_addr": 0x4F1DBC,
        "car_state_base": 0x51DC5C,
        "track_length_addr": 0x527C00,
        "current_track_addr": 0x527D58,
    },
}


@dataclass
class ConfigModel:
    # These will be patched during load
    run_order_base: int = 0
    car_numbers_base: int = 0
    driver_names_base: int = 0
    cars_addr: int = 0
    laps_addr: int = 0
    car_state_base: int = 0
    track_length_addr: int = 0
    current_track_addr: int = 0
    session_timer_addr: int = 0
    version: str = "REND32A"

    # Common fields
    entry_bytes_name: int = 26
    car_state_size: int = 0x214
    field_laps_left: int = 32 * 4
    field_lap_clock_start: int = 23 * 4
    field_lap_clock_end: int = 22 * 4
    field_laps_down: int = 24 * 4
    car_status: int = 37 * 4
    current_lap: int = 38 * 4
    current_lp: int = 52 * 4
    fuel_laps_remaining: int = 35 * 4
    dlat: int = 11 * 4
    dlong: int = 31 * 4
    current_track_maxlen: int = 9

    # UI defaults (overridable by INI)
    poll_ms: int = 250
    font_size: int = 8
    font_family: str = "Arial"
    player_index: int = 1
    fudge_px: int = 2
    resize_throttle_ms: int = 333

    # Mapping knobs
    order_index_base: int = 0
    names_index_base: int = 0
    numbers_index_base: int = 0
    names_shift: int = -1
    numbers_shift: int = -1

    # Validation
    max_cars: int = 200
    max_laps: int = 10000

    # Overlay column widths
    col_widths: Dict[str, int] = field(
        default_factory=lambda: {
            "Pos": 28,
            "Δ": 20,
            "Car#": 38,
            "Driver_full": 100,
            "Driver_abbrev": 50,
            "Laps": 50,
            "Gap": 65,
            "Last": 65,
            "Best": 65,
            "LP": 38,
            "Fuel": 38,
            "DLONG": 65,
            "DLAT": 65,
            "Lead": 50,
            "SincePit": 70,
            "SinceYL": 70,
            "PitRel": 65,
            "Qual": 65,
            "default": 50,
        }
    )

    # Colors
    background_rgba: str = "0,0,0,180"
    text_color: str = "white"
    header_bg: str = "#222"
    header_fg: str = "white"
    grid_color: str = "#333"

    best_global: str = "#a0f"
    best_personal: str = "#0f0"
    pitting: str = "#ffcc00"
    retired: str = "#ff8888"
    player_row: str = "#444"

    # Radar overlay
    radar_width: int = 300
    radar_height: int = 300
    radar_range_lengths: int = 2
    radar_range_widths: int = 5
    radar_car_length_in: int = 201
    radar_car_width_in: int = 76
    radar_player_color: str = "0,255,0,255"
    radar_ai_color: str = "255,255,255,255"
    radar_background: str = "0,0,0,128"
    radar_range_forward: int = 2
    radar_range_rear: int = 1
    radar_range_side: int = 5
    radar_ai_ahead_color: str = "0,128,255,255"
    radar_ai_behind_color: str = "255,64,64,255"
    radar_ai_alongside_color: str = "255,255,0,255"
    radar_symbol: str = "rectangle"
    radar_show_speeds: bool = False

    # Paths
    game_exe: str = ""


class ConfigStore(QtCore.QObject):
    config_changed = QtCore.pyqtSignal(object)
    overlay_setting_changed = QtCore.pyqtSignal(str)

    OVERLAY_SECTIONS = {"overlay", "colors", "radar"}

    def __init__(self, backend: Optional[ConfigBackend] = None) -> None:
        super().__init__()
        self._backend = backend or ConfigBackend()
        self._config = ConfigModel()
        self.reload()

    @property
    def config(self) -> ConfigModel:
        return self._config

    def reload(self) -> ConfigModel:
        data = self._backend.load()
        cfg = ConfigModel()

        self._apply_overlay_settings(cfg, data)

        version = self._backend.get_exe_info_option(data, "version", fallback=cfg.version).upper()
        normalized_version = VERSION_ALIASES.get(version, version)
        if normalized_version not in OFFSETS:
            supported_versions = ", ".join(sorted(OFFSETS))
            raise ValueError(
                "Unsupported memory version: "
                f"{version}. Supported versions: {supported_versions}"
            )

        self._backend.validate_executable(data, normalized_version)
        for key, value in OFFSETS[normalized_version].items():
            setattr(cfg, key, value)
        cfg.version = version
        cfg.game_exe = self._backend.get_exe_info_option(data, "game_exe", fallback="")

        self._config = cfg
        self.config_changed.emit(cfg)
        return cfg

    def save(self, section_updates: Mapping[str, Mapping[str, object]]) -> ConfigModel:
        self._backend.save(section_updates)
        cfg = self.reload()
        for section in section_updates:
            if section.lower() in self.OVERLAY_SECTIONS:
                self.overlay_setting_changed.emit(section.lower())
        return cfg

    def _apply_overlay_settings(self, cfg: ConfigModel, data: Mapping[str, Mapping[str, str]]) -> None:
        overlay = data.get("overlay", {})
        colors = data.get("colors", {})
        radar = data.get("radar", {})

        cfg.poll_ms = int(overlay.get("poll_ms", cfg.poll_ms))
        cfg.font_size = int(overlay.get("font_size", cfg.font_size))
        cfg.font_family = overlay.get("font_family", cfg.font_family)
        cfg.player_index = int(overlay.get("player_index", cfg.player_index))
        cfg.fudge_px = int(overlay.get("fudge_px", cfg.fudge_px))
        cfg.resize_throttle_ms = int(overlay.get("resize_throttle_ms", cfg.resize_throttle_ms))

        cfg.background_rgba = colors.get("background_rgba", cfg.background_rgba)
        cfg.text_color = colors.get("text_color", cfg.text_color)
        cfg.header_bg = colors.get("header_bg", cfg.header_bg)
        cfg.header_fg = colors.get("header_fg", cfg.header_fg)
        cfg.grid_color = colors.get("grid_color", cfg.grid_color)
        cfg.best_global = colors.get("best_global", cfg.best_global)
        cfg.best_personal = colors.get("best_personal", cfg.best_personal)
        cfg.pitting = colors.get("pitting", cfg.pitting)
        cfg.retired = colors.get("retired", cfg.retired)
        cfg.player_row = colors.get("player_row", cfg.player_row)

        cfg.radar_width = int(radar.get("width", cfg.radar_width))
        cfg.radar_height = int(radar.get("height", cfg.radar_height))
        cfg.radar_range_forward = int(radar.get("range_forward_lengths", cfg.radar_range_forward))
        cfg.radar_range_rear = int(radar.get("range_rear_lengths", cfg.radar_range_rear))
        cfg.radar_range_side = int(radar.get("range_side_widths", cfg.radar_range_side))
        cfg.radar_car_length_in = int(radar.get("car_length_in", cfg.radar_car_length_in))
        cfg.radar_car_width_in = int(radar.get("car_width_in", cfg.radar_car_width_in))
        cfg.radar_player_color = radar.get("player_color", cfg.radar_player_color)
        cfg.radar_ai_color = radar.get("ai_color", cfg.radar_ai_color)
        cfg.radar_background = radar.get("background", cfg.radar_background)
        cfg.radar_range_lengths = int(radar.get("range_lengths", cfg.radar_range_lengths))
        cfg.radar_range_widths = int(radar.get("range_widths", cfg.radar_range_widths))
        cfg.radar_ai_ahead_color = radar.get("ai_ahead_color", cfg.radar_ai_ahead_color)
        cfg.radar_ai_behind_color = radar.get("ai_behind_color", cfg.radar_ai_behind_color)
        cfg.radar_ai_alongside_color = radar.get("ai_alongside_color", cfg.radar_ai_alongside_color)
        cfg.radar_symbol = radar.get("symbol", cfg.radar_symbol)
        show_speeds = radar.get("show_speeds")
        if show_speeds is not None:
            cfg.radar_show_speeds = show_speeds.lower() in {"1", "true", "yes", "on"}


_CONFIG_STORE: Optional[ConfigStore] = None


def get_config_store() -> ConfigStore:
    global _CONFIG_STORE
    if _CONFIG_STORE is None:
        _CONFIG_STORE = ConfigStore()
    return _CONFIG_STORE


__all__ = [
    "ConfigModel",
    "ConfigStore",
    "EXE_INFO_SECTION",
    "EXE_VERSIONS",
    "VERSION_ALIASES",
    "OFFSETS",
    "get_config_store",
]
