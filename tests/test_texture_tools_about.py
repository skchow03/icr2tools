import pytest

try:  # pragma: no cover
    from PyQt5 import QtWidgets
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)

from texture_tools.main import ABOUT_TEXT, APP_TITLE, TextureToolsWindow, __version__


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_texture_tools_window_title_includes_version(qapp) -> None:
    _ = qapp
    window = TextureToolsWindow()
    try:
        assert __version__ == "0.1.0"
        assert window.windowTitle() == APP_TITLE == "Texture Tools v0.1.0"
    finally:
        window.close()


def test_texture_tools_about_dialog_text(qapp, monkeypatch) -> None:
    _ = qapp
    captured = {}

    def fake_about(parent, title, text):
        captured["parent"] = parent
        captured["title"] = title
        captured["text"] = text

    monkeypatch.setattr(QtWidgets.QMessageBox, "about", fake_about)
    window = TextureToolsWindow()
    try:
        window._show_about_dialog()
    finally:
        window.close()

    assert captured["parent"] is window
    assert captured["title"] == "About ICR2 Texture Tools"
    assert captured["text"] == ABOUT_TEXT
    assert captured["text"] == 'ICR2 Texture Tools v0.1.0\nby SK Chow ("checkpoint10" on the icr2.net forums)'
