from pathlib import Path

import numpy as np
import pytest

from sunny_optimizer.ui.settings import SunnyOptimizerSettings

try:  # pragma: no cover
    from PyQt5 import QtWidgets
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)

from sunny_optimizer.ui import main_window as mw


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_settings_round_trip(tmp_path: Path) -> None:
    settings_path = tmp_path / "sunny_optimizer.ini"
    settings = SunnyOptimizerSettings(settings_path)
    settings.last_texture_folder = str((tmp_path / "textures").resolve())
    settings.last_sunny_palette = str((tmp_path / "sunny.pcx").resolve())
    settings.set_budgets_for_folder(tmp_path / "textures", {"a.png": 12, "b.png": 45})
    settings.save()

    loaded = SunnyOptimizerSettings(settings_path)
    loaded.load()

    assert loaded.last_texture_folder == settings.last_texture_folder
    assert loaded.last_sunny_palette == settings.last_sunny_palette
    assert loaded.budgets_for_folder(tmp_path / "textures") == {"a.png": 12, "b.png": 45}


def test_compute_palette_uses_remembered_sunny_pcx(monkeypatch: pytest.MonkeyPatch, qapp, tmp_path: Path) -> None:
    _ = qapp
    remembered = tmp_path / "sunny.pcx"
    remembered.write_bytes(b"x")

    class DummySettings:
        def __init__(self, _path):
            self.last_texture_folder = ""
            self.last_sunny_palette = str(remembered)

        @staticmethod
        def default_path():
            return tmp_path / "dummy.ini"

        def load(self):
            return None

        def save(self):
            return None

        def budgets_for_folder(self, _folder):
            return {}

        def set_budgets_for_folder(self, _folder, _budgets):
            return None

    class FakeOptimizer:
        def __init__(self, **_kwargs):
            pass

        def compute_palette(self):
            return np.zeros((256, 3), dtype=np.uint8)

        def compute_quantized_images(self, _palette):
            return {}, {}

    seen: dict[str, str] = {}

    def fake_load_sunny_palette(path):
        seen["path"] = path
        return np.zeros((256, 3), dtype=np.uint8)

    def fail_dialog(*_args, **_kwargs):
        raise AssertionError("File dialog should not be opened when palette path is remembered")

    monkeypatch.setattr(mw, "SunnyOptimizerSettings", DummySettings)
    monkeypatch.setattr(mw, "SunnyPaletteOptimizer", FakeOptimizer)
    monkeypatch.setattr(mw, "load_sunny_palette", fake_load_sunny_palette)
    monkeypatch.setattr(mw.QtWidgets.QFileDialog, "getOpenFileName", fail_dialog)

    window = mw.MainWindow()
    window.texture_images = {"tex.png": np.zeros((2, 2, 3), dtype=np.uint8)}
    window.per_texture_budget = {"tex.png": 1}

    window.compute_palette()

    assert seen["path"] == str(remembered)
