import json
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


def test_detects_and_persists_pmp_sprites_and_allows_manual_override(qapp, tmp_path: Path) -> None:
    _ = qapp
    sprite = Image.new("RGBA", (256, 256), (255, 0, 0, 255))
    # 6,554 pixels is the smallest whole-pixel count that is at least 10%.
    for index in range(6554):
        sprite.putpixel((index % 256, index // 256), (255, 0, 0, 0))
    sprite.save(tmp_path / "sprite.png")
    Image.new("RGBA", (256, 256), (0, 0, 255, 255)).save(tmp_path / "opaque.png")
    Image.new("RGBA", (255, 256), (0, 255, 0, 0)).save(tmp_path / "wrong-size.png")

    widget = ConvertTexturesWidget()
    try:
        widget.set_source_folder(tmp_path)
        assert [widget.file_list.item(row).text() for row in range(widget.file_list.count())] == [
            "opaque.png",
            "sprite.png (PMP)",
            "wrong-size.png",
        ]
        manifest_path = tmp_path / "sunny_optimizer.json"
        images = {
            item["file"]: item["sprite"]
            for item in json.loads(manifest_path.read_text(encoding="utf-8"))["images"]
        }
        assert images == {"opaque.png": False, "sprite.png": True, "wrong-size.png": False}

        widget.file_list.setCurrentRow(1)
        assert widget.sprite_button.isChecked()
        widget.sprite_button.click()
        assert widget.file_list.currentItem().text() == "sprite.png"
        images = {
            item["file"]: item["sprite"]
            for item in json.loads(manifest_path.read_text(encoding="utf-8"))["images"]
        }
        assert images["sprite.png"] is False

        widget.set_source_folder(tmp_path)
        assert widget.file_list.item(1).text() == "sprite.png"
    finally:
        widget.close()
