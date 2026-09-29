import pytest

from tso_generator import tso_generator


QtWidgets = pytest.importorskip("PyQt5.QtWidgets")


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    yield app


def test_generator_window_has_live_3d_preview(monkeypatch, qapp):
    windows = []

    def capture_window(_app):
        windows.extend(
            widget
            for widget in QtWidgets.QApplication.topLevelWidgets()
            if widget.windowTitle() == "ICR2 Building Generator"
        )
        return 0

    monkeypatch.setattr(QtWidgets.QApplication, "exec_", capture_window)

    tso_generator.build_window()

    assert windows
    window = windows[-1]
    try:
        assert isinstance(window.preview, QtWidgets.QOpenGLWidget)
        assert window.preview.toolTip() == "Drag to rotate; use the mouse wheel to zoom"
        assert window.preview._verts
        original_vertex_count = len(window.preview._verts)

        window.shape_combo.setCurrentText("circular")
        window.sides_spin.setValue(7)
        window.refresh_preview()

        assert len(window.preview._verts) != original_vertex_count
        assert window.reset_preview_btn.text() == "Reset View"
    finally:
        window.close()
