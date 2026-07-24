import pytest

QtWidgets = pytest.importorskip("PyQt5.QtWidgets")

from sg_viewer.ui.app import SGViewerWindow


def test_elevation_range_inputs_accept_large_values() -> None:
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    window = SGViewerWindow()
    try:
        window.altitude_min_spin.setValue(-1_234_567.8)
        window.altitude_max_spin.setValue(1_234_567.8)

        assert window.altitude_min_spin.value() == -1_234_567.8
        assert window.altitude_max_spin.value() == 1_234_567.8
    finally:
        window.close()
        app.processEvents()
