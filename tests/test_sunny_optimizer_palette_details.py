import numpy as np
import pytest

try:  # pragma: no cover
    from PyQt5 import QtCore, QtWidgets
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)

from sunny_optimizer.ui.main_window import MainWindow


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_update_palette_details_displays_expected_fields(qapp) -> None:
    _ = qapp
    window = MainWindow()
    window.current_palette = np.zeros((256, 3), dtype=np.uint8)
    window.current_palette[42] = np.array([255, 0, 0], dtype=np.uint8)

    window._update_palette_details(42)

    text = window.palette_details_label.text()
    assert "Palette index: 42" in text
    assert "Hex: #FF0000" in text
    assert "RGB: (255, 0, 0)" in text


def test_palette_click_selects_tile_and_updates_details(qapp) -> None:
    _ = qapp
    window = MainWindow()
    window.resize(1400, 800)
    window.current_palette = np.zeros((256, 3), dtype=np.uint8)
    window.current_palette[17] = np.array([0, 255, 0], dtype=np.uint8)
    window._refresh_palette_view()

    click_point = QtCore.QPoint(22, 22)
    window._on_palette_clicked(click_point)

    assert window.selected_palette_index == 17
    assert "Palette index: 17" in window.palette_details_label.text()


def test_update_palette_details_displays_usage_when_indexed_images_exist(qapp) -> None:
    _ = qapp
    window = MainWindow()
    window.current_palette = np.zeros((256, 3), dtype=np.uint8)
    window.current_palette[42] = np.array([255, 0, 0], dtype=np.uint8)
    window.indexed_images = {
        "road.bmp": np.array([[42, 1], [42, 2]], dtype=np.uint8),
        "grass.bmp": np.array([[42, 3]], dtype=np.uint8),
    }

    window._update_palette_details(42)

    text = window.palette_details_label.text()
    assert "Usage: 3 pixels" in text
    assert "60.00% of indexed pixels" in text


def test_update_preview_displays_per_texture_diagnostics(qapp) -> None:
    _ = qapp
    window = MainWindow()
    texture_name = "road.bmp"
    rgb = np.zeros((2, 4, 3), dtype=np.uint8)
    indexed = np.array(
        [
            [176, 176, 177, 12],
            [245, 12, 12, 3],
        ],
        dtype=np.uint8,
    )
    window.texture_images = {texture_name: rgb}
    window.quantized_images = {texture_name: rgb.copy()}
    window.indexed_images = {texture_name: indexed}
    window.per_texture_budget = {texture_name: 5}
    window.current_palette = np.zeros((256, 3), dtype=np.uint8)
    window.current_palette[12] = np.array([1, 2, 3], dtype=np.uint8)
    window.current_palette[176] = np.array([176, 0, 0], dtype=np.uint8)
    window.current_palette[177] = np.array([177, 0, 0], dtype=np.uint8)
    window.current_palette[245] = np.array([245, 0, 0], dtype=np.uint8)

    window._update_preview(texture_name)

    text = window.texture_diagnostics_label.text()
    assert "Diagnostics for road.bmp" in text
    assert "Configured budget: 5" in text
    assert "Unique palette indices used: 5" in text
    assert "Optimized range 176-245: 3 indices, 4 pixels" in text
    assert "palette-index:12" in text
    assert "12" in text
    assert "3 px" in text


def test_diagnostics_index_link_selects_palette_index(qapp) -> None:
    _ = qapp
    window = MainWindow()
    texture_name = "road.bmp"
    rgb = np.zeros((2, 2, 3), dtype=np.uint8)
    window.texture_images = {texture_name: rgb}
    window.quantized_images = {texture_name: rgb.copy()}
    window.indexed_images = {texture_name: np.array([[42, 42], [1, 2]], dtype=np.uint8)}
    window.per_texture_budget = {texture_name: 4}
    window.current_palette = np.zeros((256, 3), dtype=np.uint8)
    window.current_palette[42] = np.array([255, 0, 0], dtype=np.uint8)

    window._on_diagnostics_index_clicked("palette-index:42")

    assert window.selected_palette_index == 42
    assert "Palette index: 42" in window.palette_details_label.text()
