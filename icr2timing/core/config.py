"""
config.py — Centralized addresses and config dataclass with INI overrides.
Supports multiple ICR2 versions (REND32A, DOS).
"""

from dataclasses import dataclass, field
from typing import Dict
import configparser, os, sys

# Load INI file if present
_cfgdir = os.path.dirname(sys.argv[0])
_cfgfile = os.path.join(_cfgdir, "settings.ini")
_parser = configparser.ConfigParser()
_parser.read(_cfgfile)

EXE_INFO_SECTION = "exe_info"

# Known EXE file sizes and their associated ICR2 versions.
EXE_VERSIONS = {
    1142387: "DOS",
    1916928: "WINDY",
    1109095: "REND32A",
}


def _get_exe_info_option(option: str, fallback: str = "") -> str:
    """Return an option from the [exe_info] section with legacy fallbacks."""

    for section in (EXE_INFO_SECTION, "memory"):
        if _parser.has_option(section, option):
            return _parser.get(section, option)

    if option == "game_exe" and _parser.has_option("paths", option):
        return _parser.get("paths", option)

    return fallback

# --- Version-specific memory maps ---
OFFSETS = {
    "REND32A": {
        "run_order_base":   0x000EF638,
        "car_numbers_base": 0x000EDE88,
        "driver_names_base":0x000EDF3E,
        "cars_addr":        0x0E71A8,
        "laps_addr":        0xB8C98,
        "car_state_base":   0x000E1DC4,
        "track_length_addr":0x000F15BC,
        "current_track_addr":0x000F823D,
    },
    "DOS": {
        "run_order_base":   0xDAA1C,
        "car_numbers_base": 0xCB700,
        "driver_names_base":0xCAD8E,
        "cars_addr":        0xDAA18,
        "laps_addr":        0xAD578,
        "car_state_base":   0xD5638,
        "track_length_addr":0xDFFB4,
        "current_track_addr":0xE2EE9,
        "session_timer_addr":0xDC61C,
    },
    "WINDY": {
        "run_order_base":   0x50FD64,
        # "car_numbers_base": 0x51511C,
        # "driver_names_base":0x51539C,
        "car_numbers_base": 0x515120,
        "driver_names_base":0x5153B6,
        "cars_addr":        0x524664,
        "laps_addr":        0x4F1DBC,
        "car_state_base":   0x51DC5C,
        "track_length_addr":0x527C00,
        "current_track_addr":0x527D58,
    },
}


@dataclass
class Config:
    # These will be patched in __post_init__
    run_order_base: int = 0
    car_numbers_base: int = 0
    driver_names_base: int = 0
    cars_addr: int = 0
    laps_addr: int = 0
    car_state_base: int = 0
    track_length_addr: int = 0
    current_track_addr: int = 0
    session_timer_addr: int = 0
    version: str = ""

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
    poll_ms: int = _parser.getint("overlay", "poll_ms", fallback=250)
    font_size: int = _parser.getint("overlay", "font_size", fallback=8)
    font_family: str = _parser.get("overlay", "font_family", fallback="Arial")
    player_index: int = _parser.getint("overlay", "player_index", fallback=1)
    fudge_px: int = _parser.getint("overlay", "fudge_px", fallback=2)

    resize_throttle_ms: int = _parser.getint("overlay", "resize_throttle_ms", fallback=333)

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
    col_widths: Dict[str, int] = field(default_factory=lambda: {
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
    })

    # Colors
    background_rgba: str = _parser.get("colors", "background_rgba", fallback="0,0,0,180")
    text_color: str = _parser.get("colors", "text_color", fallback="white")
    header_bg: str = _parser.get("colors", "header_bg", fallback="#222")
    header_fg: str = _parser.get("colors", "header_fg", fallback="white")
    grid_color: str = _parser.get("colors", "grid_color", fallback="#333")

    best_global: str = _parser.get("colors", "best_global", fallback="#a0f")
    best_personal: str = _parser.get("colors", "best_personal", fallback="#0f0")
    pitting: str = _parser.get("colors", "pitting", fallback="#ffcc00")
    retired: str = _parser.get("colors", "retired", fallback="#ff8888")
    player_row: str = _parser.get("colors", "player_row", fallback="#444")
    
    # Radar overlay
    radar_width: int = _parser.getint("radar", "width", fallback=300)
    radar_height: int = _parser.getint("radar", "height", fallback=300)
    radar_range_lengths: int = _parser.getint("radar", "range_lengths", fallback=2)
    radar_range_widths: int = _parser.getint("radar", "range_widths", fallback=5)
    radar_car_length_in: int = _parser.getint("radar", "car_length_in", fallback=201)
    radar_car_width_in: int = _parser.getint("radar", "car_width_in", fallback=76)
    radar_player_color: str = _parser.get("radar", "player_color", fallback="0,255,0,255")
    radar_ai_color: str = _parser.get("radar", "ai_color", fallback="255,255,255,255")
    radar_background: str = _parser.get("radar", "background", fallback="0,0,0,128")
    radar_range_forward: int = _parser.getint("radar", "range_forward_lengths", fallback=2)
    radar_range_rear: int = _parser.getint("radar", "range_rear_lengths", fallback=1)
    radar_range_side: int = _parser.getint("radar", "range_side_widths", fallback=5)
    radar_ai_ahead_color: str = _parser.get("radar", "ai_ahead_color", fallback="0,128,255,255")
    radar_ai_behind_color: str = _parser.get("radar", "ai_behind_color", fallback="255,64,64,255")
    radar_ai_alongside_color: str = _parser.get("radar", "ai_alongside_color", fallback="255,255,0,255")
    radar_symbol: str = _parser.get("radar", "symbol", fallback="rectangle")
    radar_show_speeds: bool = _parser.getboolean("radar", "show_speeds", fallback=False)

    # Paths
    game_exe: str = _get_exe_info_option("game_exe", fallback="")

    def __post_init__(self):
        version = _get_exe_info_option("version", fallback="REND32A").upper()
        self.version = version
        if version not in OFFSETS:
            raise ValueError(f"Unsupported memory version: {version}")

        if self.game_exe:
            try:
                size = os.path.getsize(self.game_exe)
            except OSError as exc:
                raise ValueError(
                    f"Configured game_exe '{self.game_exe}' is not accessible: {exc.strerror or exc}"
                ) from exc

            exe_version = EXE_VERSIONS.get(size)
            if exe_version is None:
                known = ", ".join(
                    f"{name} ({bytes_} bytes)" for bytes_, name in sorted(EXE_VERSIONS.items())
                )
                raise ValueError(
                    f"Unrecognized game_exe '{self.game_exe}' size {size} bytes. Known versions: {known}"
                )

            if exe_version.upper() != version:
                raise ValueError(
                    "settings.ini version "
                    f"'{version}' does not match executable '{self.game_exe}' "
                    f"({exe_version} build, {size} bytes)"
                )

        for k, v in OFFSETS[version].items():
            object.__setattr__(self, k, v)
