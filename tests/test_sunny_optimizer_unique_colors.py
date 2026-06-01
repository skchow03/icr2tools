import numpy as np
import pytest

try:  # pragma: no cover
    from PyQt5 import QtWidgets
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)

from sunny_optimizer.ui.main_window import MainWindow


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_update_preview_shows_unique_color_counts(qapp) -> None:
    _ = qapp
    window = MainWindow()

    rgb = np.array(
        [
            [[0, 0, 0], [255, 0, 0]],
            [[255, 0, 0], [0, 255, 0]],
        ],
        dtype=np.uint8,
    )
    quant = np.array(
        [
            [[0, 0, 0], [128, 128, 128]],
            [[128, 128, 128], [255, 255, 255]],
        ],
        dtype=np.uint8,
    )
    indexed = np.array([[1, 2], [2, 3]], dtype=np.uint8)

    window.texture_images = {"tex.png": rgb}
    window.quantized_images = {"tex.png": quant}
    window.indexed_images = {"tex.png": indexed}

    window._update_preview("tex.png")

    assert window.orig_unique_colors_label.text() == "Original unique colors: 3"
    assert window.paletted_unique_colors_label.text() == "Paletted unique colors: 3"


def test_update_preview_shows_placeholder_for_missing_paletted_preview(qapp) -> None:
    _ = qapp
    window = MainWindow()
    window.texture_images = {"tex.png": np.zeros((2, 2, 3), dtype=np.uint8)}

    window._update_preview("tex.png")

    assert window.paletted_unique_colors_label.text() == "Paletted unique colors: —"



def test_texture_list_shows_paletted_unique_color_counts(qapp) -> None:
    _ = qapp
    window = MainWindow()
    window.texture_images = {
        "tex.png": np.zeros((2, 2, 3), dtype=np.uint8),
    }
    window.texture_color_counts = {"tex.png": 2}
    window.per_texture_budget = {"tex.png": 1}
    window.indexed_images = {"tex.png": np.array([[1, 2], [2, 3]], dtype=np.uint8)}

    window._refresh_texture_list()

    item = window.texture_list.item(0)
    widget = window.texture_list.itemWidget(item)
    assert widget.original_color_count_label.text() == "Original: 2 colors"
    assert widget.paletted_color_count_label.text() == "Paletted: 3 colors"
    assert "Paletted unique colors: 3" in item.toolTip()


def test_optimization_progress_uses_separate_label_not_bar_text(qapp) -> None:
    _ = qapp
    window = MainWindow()

    assert window.compute_progress.isTextVisible() is False
    assert window.compute_progress_label.text() == "Idle"
