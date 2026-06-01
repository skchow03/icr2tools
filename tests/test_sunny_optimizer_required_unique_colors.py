from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_settings_class():
    path = Path(__file__).resolve().parents[1] / "texture_tools" / "sunny_optimizer" / "ui" / "settings.py"
    spec = importlib.util.spec_from_file_location("sunny_optimizer_settings_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SunnyOptimizerSettings


def test_optimizer_prioritizes_required_unique_colors() -> None:
    np = pytest.importorskip("numpy")
    from sunny_optimizer.model import SunnyPaletteOptimizer

    image = np.array(
        [
            [(255, 0, 0), (0, 255, 0)],
            [(0, 0, 255), (255, 255, 0)],
        ],
        dtype=np.uint8,
    )
    fixed_palette = np.zeros((256, 3), dtype=np.uint8)
    optimizer = SunnyPaletteOptimizer(
        rgb_images={"test.png": image},
        per_texture_color_budget={"test.png": 1},
        fixed_palette=fixed_palette,
        dirt_present=True,
        per_texture_required_unique_colors={"test.png": 4},
        random_state=1,
    )

    palette = optimizer.compute_palette()
    indexed_images, _quantized_images = optimizer.compute_quantized_images(palette)

    assert np.unique(indexed_images["test.png"]).shape[0] >= 4


def test_settings_persist_required_unique_colors(tmp_path: Path) -> None:
    SunnyOptimizerSettings = _load_settings_class()
    folder = tmp_path / "textures"
    settings_path = tmp_path / "texture_tools.ini"
    settings = SunnyOptimizerSettings(settings_path)

    settings.set_required_unique_colors_for_folder(folder, {"a.png": 12, "b.png": 0})
    settings.save()

    loaded = SunnyOptimizerSettings(settings_path)
    loaded.load()

    assert loaded.required_unique_colors_for_folder(folder) == {"a.png": 12}
