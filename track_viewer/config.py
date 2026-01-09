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


def save_installation_path(installation_path: Path, main_script_path: Optional[Path]) -> None:
    config = ConfigParser()
    config[_SECTION] = {_KEY: str(installation_path)}
    ini_path = config_path(main_script_path)
    try:
        with ini_path.open("w", encoding="utf-8") as handle:
            config.write(handle)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError:
        return
