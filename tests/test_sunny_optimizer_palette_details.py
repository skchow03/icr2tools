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
    assert "Nearest XKCD color:" in text


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
