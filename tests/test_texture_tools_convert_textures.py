import json
from pathlib import Path

import pytest
from PIL import Image

try:  # pragma: no cover
    from PyQt5 import QtWidgets
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)

from texture_tools.main import ConvertGameTexturesWidget, ConvertTexturesWidget, TextureToolsWindow


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
        assert widget.sprite_button.text() == "Flag/unflag selected as sprite (PMP)"
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
            "Convert from source",
            "Convert from mip/pmp",
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


def test_convert_game_textures_scans_previews_and_exports_pngs(
    qapp, tmp_path: Path, monkeypatch
) -> None:
    _ = qapp
    source_dir = tmp_path / "game"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    output_dir.mkdir()
    (source_dir / "z.PMP").write_bytes(b"pmp")
    (source_dir / "a.mip").write_bytes(b"mip")
    (source_dir / "ignored.png").write_bytes(b"png")
    palette_path = tmp_path / "sunny.pcx"
    _save_palette(palette_path)
    decoded = Image.new("RGBA", (3, 2), "red")
    monkeypatch.setattr(
        ConvertGameTexturesWidget, "_decode", lambda _self, _path: decoded.copy()
    )
    messages = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "information",
        lambda _parent, title, message: messages.append((title, message)),
    )

    widget = ConvertGameTexturesWidget()
    try:
        widget.set_palette(palette_path)
        widget.set_output_folder(output_dir)
        widget.set_source_folder(source_dir)

        assert [widget.file_list.item(row).text() for row in range(widget.file_list.count())] == [
            "a.mip",
            "z.PMP",
        ]
        assert widget.file_list.selectionMode() == QtWidgets.QAbstractItemView.ExtendedSelection
        assert widget.preview_pane._pixmap_item.pixmap().size().width() == 3

        widget._convert_all()

        assert (output_dir / "a.png").is_file()
        assert (output_dir / "z.png").is_file()
        assert messages == [
            ("Conversion complete", f"Converted 2 of 2 texture(s) to:\n{output_dir}")
        ]
    finally:
        widget.close()


def test_supports_extended_selection_and_converts_selected_formats(
    qapp, tmp_path: Path, monkeypatch
) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    output_dir.mkdir()
    Image.new("RGB", (2, 2), "red").save(source_dir / "track.png")
    Image.new("RGBA", (256, 256), (0, 0, 0, 0)).save(source_dir / "sprite.png")
    palette_path = tmp_path / "sunny.pcx"
    _save_palette(palette_path)
    mip_calls = []
    pmp_calls = []
    messages = []
    monkeypatch.setattr(
        "texture_tools.main.img_to_mip",
        lambda image, output, palette, mode: mip_calls.append(
            (Path(output), Path(palette), mode)
        ),
    )
    monkeypatch.setattr(
        "texture_tools.main.png_to_pmp",
        lambda source, output, **kwargs: pmp_calls.append((Path(source), Path(output), kwargs)),
    )
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "information",
        lambda _parent, title, message: messages.append((title, message)),
    )

    widget = ConvertTexturesWidget()
    try:
        widget.set_source_folder(source_dir)
        widget.set_palette(palette_path)
        widget.set_output_folder(output_dir)
        assert widget.file_list.selectionMode() == QtWidgets.QAbstractItemView.ExtendedSelection

        widget.file_list.clearSelection()
        for row in range(widget.file_list.count()):
            widget.file_list.item(row).setSelected(True)
        widget._convert_selected()

        assert mip_calls == [(output_dir / "track.mip", palette_path, "track")]
        assert pmp_calls[0][0:2] == (source_dir / "sprite.png", output_dir / "sprite.pmp")
        assert pmp_calls[0][2]["size_field"] == 0
        assert pmp_calls[0][2]["alpha_transparent_threshold"] == 84
        assert messages == [("Conversion complete", f"Converted 2 of 2 texture(s) to:\n{output_dir}")]
    finally:
        widget.close()


def test_sprite_preview_updates_for_alpha_threshold(qapp, tmp_path: Path) -> None:
    _ = qapp
    sprite = Image.new("RGBA", (2, 1))
    sprite.putdata(((255, 0, 0, 84), (0, 0, 255, 85)))
    sprite.save(tmp_path / "sprite.png")
    palette_path = tmp_path / "sunny.pcx"
    _save_palette(palette_path)

    widget = ConvertTexturesWidget()
    try:
        widget.set_source_folder(tmp_path)
        widget.set_palette(palette_path)
        widget.sprite_button.setChecked(True)

        assert widget.alpha_threshold_slider.minimum() == 0
        assert widget.alpha_threshold_slider.maximum() == 100
        assert widget.alpha_threshold_slider.value() == 33
        assert widget.alpha_threshold_value_label.text() == "33%"
        image = widget.preview_pane._pixmap_item.pixmap().toImage()
        assert image.pixelColor(0, 0).alpha() == 0
        assert image.pixelColor(1, 0).alpha() == 255
        assert "PMP alpha ≤ 33% transparent" in widget.preview_pane.meta_label.text()

        widget.alpha_threshold_slider.setValue(32)
        image = widget.preview_pane._pixmap_item.pixmap().toImage()
        assert image.pixelColor(0, 0).alpha() == 255
        assert image.pixelColor(1, 0).alpha() == 255
    finally:
        widget.close()


def test_conversion_rejects_invalid_output_folder(qapp, tmp_path: Path, monkeypatch) -> None:
    _ = qapp
    Image.new("RGB", (1, 1), "blue").save(tmp_path / "track.png")
    errors = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "critical",
        lambda _parent, title, message: errors.append((title, message)),
    )
    widget = ConvertTexturesWidget()
    try:
        widget.set_source_folder(tmp_path)
        widget.set_output_folder(tmp_path / "missing")
        widget._convert_all()
        assert errors == [
            ("Invalid Output folder", "Select a valid Output folder before converting textures.")
        ]
    finally:
        widget.close()


@pytest.mark.parametrize("convert_action", ["_convert_selected", "_convert_all"])
def test_conversion_lists_overwrites_and_requires_confirmation(
    qapp, tmp_path: Path, monkeypatch, convert_action: str
) -> None:
    _ = qapp
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    output_dir.mkdir()
    Image.new("RGB", (1, 1), "blue").save(source_dir / "track.png")
    existing_output = output_dir / "track.mip"
    existing_output.write_bytes(b"existing")
    palette_path = tmp_path / "sunny.pcx"
    _save_palette(palette_path)
    warnings = []
    conversions = []

    def decline_overwrite(_parent, title, message, buttons, default_button):
        warnings.append((title, message, buttons, default_button))
        return QtWidgets.QMessageBox.No

    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", decline_overwrite)
    monkeypatch.setattr(
        "texture_tools.main.img_to_mip",
        lambda *args: conversions.append(args),
    )

    widget = ConvertTexturesWidget()
    try:
        widget.set_source_folder(source_dir)
        widget.set_palette(palette_path)
        widget.set_output_folder(output_dir)
        widget.file_list.item(0).setSelected(True)

        getattr(widget, convert_action)()

        assert conversions == []
        assert warnings == [
            (
                "Overwrite existing textures?",
                "The following files will be overwritten:\n\n"
                f"• {existing_output}\n\nContinue with conversion?",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
        ]
        assert existing_output.read_bytes() == b"existing"
    finally:
        widget.close()
