from pathlib import Path

import pytest
from PIL import Image

try:  # pragma: no cover
    from PyQt5 import QtWidgets
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)

from texture_tools.main import ConvertTexturesWidget, TextureToolsWindow


@pytest.fixture
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _save_palette(path: Path) -> None:
    palette = Image.new("P", (1, 1))
    palette.putpalette([255, 0, 0, 0, 0, 255] + [0, 0, 0] * 254)
    palette.save(path)


def test_lists_supported_files_and_previews_selected_texture(qapp, tmp_path: Path) -> None:
    _ = qapp
    Image.new("RGB", (2, 1), "red").save(tmp_path / "b.BMP")
    Image.new("RGB", (1, 1), "blue").save(tmp_path / "a.png")
    _save_palette(tmp_path / "texture.pcx")
    (tmp_path / "ignored.jpg").write_bytes(b"not an image")
    palette_path = tmp_path / "sunny.pcx"
    _save_palette(palette_path)

    widget = ConvertTexturesWidget()
    try:
        widget.set_source_folder(tmp_path)
        assert [widget.file_list.item(row).text() for row in range(widget.file_list.count())] == [
            "a.png",
            "b.BMP",
            "sunny.pcx",
            "texture.pcx",
        ]
        widget.set_palette(palette_path)

        pixmap = widget.preview_pane._pixmap_item.pixmap()
        assert (pixmap.width(), pixmap.height()) == (1, 1)
        color = pixmap.toImage().pixelColor(0, 0)
        assert (color.red(), color.green(), color.blue()) == (0, 0, 255)
        assert "Palette: sunny.pcx" in widget.preview_pane.meta_label.text()
        assert widget.preview_pane.fit_btn.text() == "Fit to pane"
        assert widget.preview_pane.image_view.dragMode() == QtWidgets.QGraphicsView.ScrollHandDrag
    finally:
        widget.close()


def test_window_places_convert_textures_before_legacy_convert_formats(qapp, monkeypatch, tmp_path: Path) -> None:
    _ = qapp
    monkeypatch.setattr(
        "texture_tools.main.SunnyOptimizerSettings.default_path",
        staticmethod(lambda: tmp_path / "settings.ini"),
    )
    window = TextureToolsWindow()
    try:
        labels = [window.intent_tabs.tabText(index) for index in range(window.intent_tabs.count())]
        assert labels == [
            "Optimize palette",
            "Convert textures",
            "Convert formats",
            "Split/prepare textures",
        ]
    finally:
        window.close()
