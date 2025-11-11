import configparser

import pytest

from icr2timing.core import config as cfg


def _set_version(monkeypatch, version: str) -> None:
    parser = configparser.ConfigParser()
    parser.add_section(cfg.EXE_INFO_SECTION)
    parser.set(cfg.EXE_INFO_SECTION, "version", version)
    monkeypatch.setattr(cfg, "_parser", parser)


def test_config_accepts_matching_executable(tmp_path, monkeypatch):
    exe_path = tmp_path / "cart.exe"
    exe_path.write_bytes(b"\0" * 1109095)
    _set_version(monkeypatch, "REND32A")

    cfg.Config(game_exe=str(exe_path))


def test_config_rejects_mismatched_executable(tmp_path, monkeypatch):
    exe_path = tmp_path / "cart.exe"
    exe_path.write_bytes(b"\0" * 1142387)
    _set_version(monkeypatch, "REND32A")

    with pytest.raises(ValueError, match="does not match executable"):
        cfg.Config(game_exe=str(exe_path))


def test_config_rejects_unknown_executable_size(tmp_path, monkeypatch):
    exe_path = tmp_path / "cart.exe"
    exe_path.write_bytes(b"\0" * 123)
    _set_version(monkeypatch, "DOS")

    with pytest.raises(ValueError, match="Unrecognized game_exe"):
        cfg.Config(game_exe=str(exe_path))
