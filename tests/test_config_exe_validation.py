import configparser

import pytest

from icr2timing.core.config_backend import ConfigBackend
from icr2timing.core.config_store import ConfigStore


def _write_ini(tmp_path, version: str, exe_path: str) -> str:
    ini_path = tmp_path / "settings.ini"
    ini_path.write_text(
        "[exe_info]\n" f"version={version}\n" f"game_exe={exe_path}\n",
        encoding="utf-8",
    )
    return str(ini_path)


def _load_store(tmp_path, version: str, exe_size: int) -> ConfigStore:
    exe_path = tmp_path / "cart.exe"
    exe_path.write_bytes(b"\0" * exe_size)
    ini_path = _write_ini(tmp_path, version, str(exe_path))
    backend = ConfigBackend(ini_path)
    return ConfigStore(backend=backend)


def test_config_accepts_matching_executable(tmp_path):
    store = _load_store(tmp_path, "REND32A", 1109095)
    assert store.config.game_exe.endswith("cart.exe")


def test_config_rejects_mismatched_executable(tmp_path):
    with pytest.raises(ValueError, match="does not match executable"):
        _load_store(tmp_path, "REND32A", 1142387)


def test_config_rejects_unknown_executable_size(tmp_path):
    with pytest.raises(ValueError, match="Unrecognized game_exe"):
        _load_store(tmp_path, "REND32A", 123)


def test_config_accepts_windy101_alias(tmp_path):
    store = _load_store(tmp_path, "WINDY101", 1916928)
    assert store.config.version == "WINDY101"
