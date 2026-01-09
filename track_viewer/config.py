"""Configuration helpers for Track Viewer settings persistence."""
from __future__ import annotations

from configparser import ConfigParser, Error
import os
from pathlib import Path
import sys
from typing import Optional

CONFIG_FILENAME = "track_viewer.ini"
_SECTION = "paths"
_KEY = "installation_path"
_LP_SECTION = "lp_colors"
_PIT_DLONG_SECTION = "pit_dlong_colors"
_PIT_DLAT_SECTION = "pit_dlat_colors"


def _config_dir(main_script_path: Optional[Path]) -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    if main_script_path is not None:
        return main_script_path.resolve().parent
    main_module = sys.modules.get("__main__")
    if main_module and getattr(main_module, "__file__", None):
        return Path(main_module.__file__).resolve().parent
    return Path.cwd()


def config_path(main_script_path: Optional[Path]) -> Path:
    return _config_dir(main_script_path) / CONFIG_FILENAME


def load_installation_path(main_script_path: Optional[Path]) -> Optional[Path]:
    ini_path = config_path(main_script_path)
    if not ini_path.exists():
        return None
    parser = ConfigParser()
    try:
        with ini_path.open("r", encoding="utf-8") as handle:
            parser.read_file(handle)
        stored_path = parser.get(_SECTION, _KEY, fallback=None)
    except (OSError, Error):
        return None
    if not stored_path:
        return None
    candidate = Path(stored_path)
    return candidate if candidate.is_dir() else None


def load_lp_colors(main_script_path: Optional[Path]) -> dict[str, str]:
    ini_path = config_path(main_script_path)
    if not ini_path.exists():
        return {}
    parser = ConfigParser()
    parser.optionxform = str
    try:
        with ini_path.open("r", encoding="utf-8") as handle:
            parser.read_file(handle)
    except (OSError, Error):
        return {}
    if not parser.has_section(_LP_SECTION):
        return {}
    return {key: value for key, value in parser.items(_LP_SECTION)}


def load_pit_colors(
    main_script_path: Optional[Path],
) -> tuple[dict[int, str], dict[int, str]]:
    ini_path = config_path(main_script_path)
    if not ini_path.exists():
        return {}, {}
    parser = ConfigParser()
    parser.optionxform = str
    try:
        with ini_path.open("r", encoding="utf-8") as handle:
            parser.read_file(handle)
    except (OSError, Error):
        return {}, {}
    dlong_colors: dict[int, str] = {}
    dlat_colors: dict[int, str] = {}
    if parser.has_section(_PIT_DLONG_SECTION):
        for key, value in parser.items(_PIT_DLONG_SECTION):
            try:
                index = int(key)
            except ValueError:
                continue
            dlong_colors[index] = value
    if parser.has_section(_PIT_DLAT_SECTION):
        for key, value in parser.items(_PIT_DLAT_SECTION):
            try:
                index = int(key)
            except ValueError:
                continue
            dlat_colors[index] = value
    return dlong_colors, dlat_colors


def save_installation_path(
    installation_path: Path, main_script_path: Optional[Path]
) -> None:
    config = ConfigParser()
    config.optionxform = str
    config[_SECTION] = {_KEY: str(installation_path)}
    ini_path = config_path(main_script_path)
    try:
        with ini_path.open("w", encoding="utf-8") as handle:
            config.write(handle)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        return


def save_lp_colors(lp_colors: dict[str, str], main_script_path: Optional[Path]) -> None:
    config = ConfigParser()
    config.optionxform = str
    ini_path = config_path(main_script_path)
    if ini_path.exists():
        try:
            with ini_path.open("r", encoding="utf-8") as handle:
                config.read_file(handle)
        except (OSError, Error):
            return
    if lp_colors:
        config[_LP_SECTION] = {str(key): str(value) for key, value in lp_colors.items()}
    elif config.has_section(_LP_SECTION):
        config.remove_section(_LP_SECTION)
    try:
        with ini_path.open("w", encoding="utf-8") as handle:
            config.write(handle)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        return


def save_pit_colors(
    dlong_colors: dict[int, str],
    dlat_colors: dict[int, str],
    main_script_path: Optional[Path],
) -> None:
    config = ConfigParser()
    config.optionxform = str
    ini_path = config_path(main_script_path)
    if ini_path.exists():
        try:
            with ini_path.open("r", encoding="utf-8") as handle:
                config.read_file(handle)
        except (OSError, Error):
            return
    if dlong_colors:
        config[_PIT_DLONG_SECTION] = {
            str(key): str(value) for key, value in dlong_colors.items()
        }
    elif config.has_section(_PIT_DLONG_SECTION):
        config.remove_section(_PIT_DLONG_SECTION)
    if dlat_colors:
        config[_PIT_DLAT_SECTION] = {
            str(key): str(value) for key, value in dlat_colors.items()
        }
    elif config.has_section(_PIT_DLAT_SECTION):
        config.remove_section(_PIT_DLAT_SECTION)
    try:
        with ini_path.open("w", encoding="utf-8") as handle:
            config.write(handle)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        return
