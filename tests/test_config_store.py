import pytest

from icr2timing.core import config as config_facade
from icr2timing.core import config_store as store_mod
from icr2timing.core.config_backend import ConfigBackend
from icr2timing.core.config_store import ConfigStore


def _create_store(tmp_path) -> ConfigStore:
    ini_path = tmp_path / "settings.ini"
    ini_path.write_text("[exe_info]\nversion=REND32A\n", encoding="utf-8")
    backend = ConfigBackend(str(ini_path))
    return ConfigStore(backend=backend)


def test_config_facade_returns_shared_instance(tmp_path, monkeypatch):
    store = _create_store(tmp_path)
    monkeypatch.setattr(store_mod, "_CONFIG_STORE", store)

    first = config_facade.Config()
    second = config_facade.Config.current()

    assert first is second is store.config


def test_store_emits_signals_on_save(tmp_path, monkeypatch):
    store = _create_store(tmp_path)
    monkeypatch.setattr(store_mod, "_CONFIG_STORE", store)

    config_events = []
    overlay_events = []

    store.config_changed.connect(lambda cfg: config_events.append(cfg))
    store.overlay_setting_changed.connect(lambda section: overlay_events.append(section))

    store.save({"radar": {"width": 450}})

    assert len(config_events) == 1
    assert overlay_events == ["radar"]
    assert store.config.radar_width == 450


def test_config_constructor_still_returns_store_instance(tmp_path, monkeypatch):
    store = _create_store(tmp_path)
    monkeypatch.setattr(store_mod, "_CONFIG_STORE", store)

    cfg = config_facade.Config()
    assert cfg is store.config
