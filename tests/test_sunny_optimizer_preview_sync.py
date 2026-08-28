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


def _sample_rgb() -> np.ndarray:
    arr = np.zeros((64, 64, 3), dtype=np.uint8)
    arr[..., 0] = 128
    return arr


def test_sync_preview_views_copies_zoom_and_pan(qapp) -> None:
    _ = qapp
    window = MainWindow()
    pixmap = window._to_pixmap(_sample_rgb())
    window.orig_label.set_base_pixmap(pixmap)
    window.quant_label.set_base_pixmap(pixmap)

    source_view = window.orig_label._view
    target_view = window.quant_label._view

    source_view.scale(1.5, 1.5)
    source_view.horizontalScrollBar().setValue(12)
    source_view.verticalScrollBar().setValue(24)

    window._sync_preview_views(window.orig_label, window.quant_label)

    assert target_view.transform().m11() == pytest.approx(source_view.transform().m11())
    assert target_view.transform().m22() == pytest.approx(source_view.transform().m22())
    assert target_view.horizontalScrollBar().value() == source_view.horizontalScrollBar().value()
    assert target_view.verticalScrollBar().value() == source_view.verticalScrollBar().value()

def test_shared_preview_controls_apply_to_both_views(qapp) -> None:
    _ = qapp
    window = MainWindow()
    pixmap = window._to_pixmap(_sample_rgb())
    window.orig_label.set_base_pixmap(pixmap)
    window.quant_label.set_base_pixmap(pixmap)

    window.orig_label._view.scale(2.0, 2.0)
    window._reset_previews()

    assert window.fit_previews_btn.text() == "Fit"
    assert window.reset_previews_btn.text() == "Reset"
    assert window.quant_label._view.transform().m11() == pytest.approx(
        window.orig_label._view.transform().m11()
    )
    assert window.quant_label._view.transform().m22() == pytest.approx(
        window.orig_label._view.transform().m22()
    )


def test_highlight_control_is_inside_palette_section(qapp) -> None:
    _ = qapp
    window = MainWindow()

    palette_card = window.palette_label.parentWidget()
    assert palette_card is not None
    assert window.highlight_checkbox.parentWidget() is palette_card


def test_append_optimization_log_shows_elapsed_percent_and_message(qapp) -> None:
    _ = qapp
    window = MainWindow()

    assert window.optimization_log.toPlainText() == ""
    assert window.optimization_log.placeholderText() == "Optimization log will appear here"

    window._append_optimization_log("Preparing optimizer", 30, 1.25)

    visible_log = window.optimization_log.toPlainText()
    assert "Preparing optimizer" in visible_log
    assert "30%" in visible_log
    assert "1.2s" in visible_log


def test_optimization_palette_preview_fills_reserved_tiles(qapp) -> None:
    _ = qapp
    window = MainWindow()
    fixed_palette = np.zeros((256, 3), dtype=np.uint8)
    candidates = np.array([[255, 0, 0], [0, 128, 255]], dtype=np.uint8)

    window._show_optimization_palette_preview(fixed_palette, candidates, "Grouping colors")

    preview = window._optimization_preview_palette
    assert preview is not None
    np.testing.assert_array_equal(preview[176], candidates[0])
    np.testing.assert_array_equal(preview[177], candidates[1])
    np.testing.assert_array_equal(preview[178], candidates[0])
    assert window.palette_details_label.text() == "Optimizing: Grouping colors"
