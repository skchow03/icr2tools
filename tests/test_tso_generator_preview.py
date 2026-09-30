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


def test_project_generator_uses_project_palette_without_palette_controls(
    monkeypatch, qapp, tmp_path
):
    monkeypatch.setattr(
        tso_generator, "INI_PATH", tmp_path / "missing-tso-generator.ini"
    )
    palette = bytes(value % 256 for value in range(768))
    palette_path = tmp_path / "SUNNY.PCX"
    palette_path.write_bytes(b"pcx data" + bytes([0x0C]) + palette)

    window = tso_generator.build_window(
        project_templates={},
        project_palette_path=palette_path,
        run_event_loop=False,
    )
    try:
        assert window.palette[0] == (0, 1, 2)
        assert window.palette[255] == (253, 254, 255)
        assert not hasattr(window, "sunny_edit")
        assert not hasattr(window, "sunny_browse")
        assert all(
            "sunny.pcx" not in action.text().lower()
            for action in window.findChildren(QtWidgets.QAction)
        )
        assert "sunny_pcx" not in window.collect_current_values()
    finally:
        window.close()
