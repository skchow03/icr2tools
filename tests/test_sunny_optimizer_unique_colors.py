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



def test_texture_table_shows_color_counts_and_editable_budgets(qapp) -> None:
    _ = qapp
    window = MainWindow()
    window.texture_images = {
        "tex.png": np.zeros((2, 2, 3), dtype=np.uint8),
    }
    window.texture_color_counts = {"tex.png": 2}
    window.per_texture_budget = {"tex.png": 1}
    window.indexed_images = {"tex.png": np.array([[1, 2], [2, 3]], dtype=np.uint8)}

    window._refresh_texture_list()

    assert window.texture_list.horizontalHeaderItem(0).text() == "File name"
    assert window.texture_list.item(0, 0).text() == "tex.png"
    assert window.texture_list.item(0, 1).text() == "2"
    assert window.texture_list.item(0, 4).text() == "3"
    assert "Paletted unique colors: 3" in window.texture_list.item(0, 0).toolTip()

    budget_edit = window.texture_list.cellWidget(0, 2)
    required_edit = window.texture_list.cellWidget(0, 3)
    assert isinstance(budget_edit, QtWidgets.QLineEdit)
    assert isinstance(required_edit, QtWidgets.QLineEdit)
    budget_edit.setText("12")
    budget_edit.editingFinished.emit()
    required_edit.setText("2")
    required_edit.editingFinished.emit()
    assert window.per_texture_budget["tex.png"] == 12
    assert window.per_texture_required_unique_colors["tex.png"] == 2


def test_optimization_progress_uses_separate_label_not_bar_text(qapp) -> None:
    _ = qapp
    window = MainWindow()

    assert window.compute_progress.isTextVisible() is False
    assert window.compute_progress_label.text() == "Idle"
