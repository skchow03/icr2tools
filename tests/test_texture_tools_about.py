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
        assert __version__ == "1.0"
        assert window.windowTitle() == APP_TITLE == "Texture Tools v1.0"
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
    assert captured["title"] == "About PPG (Palette, Paint and Graphics) for ICR2"
    assert captured["text"] == ABOUT_TEXT
    assert captured["text"] == (
        'PPG (Palette, Paint and Graphics) for ICR2 v1.0\n'
        'by SK Chow ("checkpoint10" on the icr2.net forums)'
    )


def test_files_are_global_above_tabs_and_feed_compatible_tools(qapp, tmp_path) -> None:
    from PIL import Image

    texture_folder = tmp_path / "textures"
    texture_folder.mkdir()
    Image.new("RGB", (2, 2), (12, 34, 56)).save(texture_folder / "wall.png")
    palette_path = tmp_path / "SUNNY.PCX"
    palette_path.write_bytes(b"placeholder")

    window = TextureToolsWindow()
    try:
        central_layout = window.centralWidget().layout()
        assert central_layout.indexOf(window.sunny_optimizer.files_card) == 0
        assert central_layout.indexOf(window.intent_tabs) == 1

        window.sunny_optimizer._load_folder(texture_folder)
        window.sunny_optimizer._set_palette_path(str(palette_path))

        assert window.convert_textures._source_folder == texture_folder.resolve()
        assert window.convert_textures._palette_path == palette_path
        assert window.convert_game_textures._palette_path == palette_path
    finally:
        window.close()


def test_optimizer_palette_actions_use_normal_button_styling(qapp) -> None:
    window = TextureToolsWindow()
    try:
        assert window.sunny_optimizer.compute_btn.property("primary") is None
        assert window.sunny_optimizer.save_btn.property("secondary") is None
    finally:
        window.close()
