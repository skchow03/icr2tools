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
