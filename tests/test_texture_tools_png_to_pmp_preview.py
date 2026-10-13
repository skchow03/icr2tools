from pathlib import Path

import pytest
from PIL import Image

try:  # pragma: no cover
    from PyQt5 import QtWidgets
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)

from texture_tools.main import PmpConversionWidget
from texture_tools.pmp_to_png import pmp_to_image
from texture_tools.sunny_optimizer.ui.settings import SunnyOptimizerSettings


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _pixmap_pixel(widget: PmpConversionWidget, x: int = 0, y: int = 0) -> tuple[int, int, int, int]:
    color = widget.preview_pane._pixmap_item.pixmap().toImage().pixelColor(x, y)
    return color.red(), color.green(), color.blue(), color.alpha()


def _save_palette(tmp_path: Path) -> Path:
    path = tmp_path / "SUNNY.PCX"
    palette = Image.new("P", (1, 1))
    palette.putpalette([200, 10, 20, 10, 20, 200, 255, 0, 0, 0, 0, 255] + [0, 0, 0] * 252)
    palette.save(path)
    return path


def test_preview_paints_threshold_transparency_bright_green(qapp, tmp_path: Path) -> None:
    _ = qapp
    source = tmp_path / "sprite.png"
    Image.new("RGBA", (2, 1), (200, 10, 20, 51)).save(source)
    widget = PmpConversionWidget(SunnyOptimizerSettings(tmp_path / "settings.ini"))
    try:
        widget.palette_edit.setText(str(_save_palette(tmp_path)))
        widget.input_edit.setText(str(source))
        assert _pixmap_pixel(widget) == (0, 255, 0, 255)

        widget.alpha_threshold_spin.setValue(50)
        assert _pixmap_pixel(widget) == (200, 10, 20, 255)
        assert "alpha ≤ 50 transparent" in widget.preview_pane.meta_label.text()
    finally:
        widget.close()


def test_preview_makes_every_pixel_fully_opaque_or_transparent(qapp, tmp_path: Path) -> None:
    _ = qapp
    source = tmp_path / "sprite.png"
    image = Image.new("RGBA", (2, 1))
    image.putdata(((200, 10, 20, 52), (10, 20, 200, 51)))
    image.save(source)
    widget = PmpConversionWidget(SunnyOptimizerSettings(tmp_path / "settings.ini"))
    try:
        widget.palette_edit.setText(str(_save_palette(tmp_path)))
        widget.transparency_checkbox.setChecked(False)
        widget.input_edit.setText(str(source))

        assert _pixmap_pixel(widget, 0, 0) == (200, 10, 20, 255)
        assert _pixmap_pixel(widget, 1, 0)[3] == 0
    finally:
        widget.close()


def test_output_preview_panel_is_to_the_right_of_controls(qapp, tmp_path: Path) -> None:
    _ = qapp
    widget = PmpConversionWidget(SunnyOptimizerSettings(tmp_path / "settings.ini"))
    try:
        root_layout = widget.layout()
        assert root_layout.itemAt(0).widget() is widget.controls_panel
        assert root_layout.itemAt(1).widget() is widget.preview_panel
    finally:
        widget.close()


def test_folder_preview_can_cycle_png_outputs(qapp, tmp_path: Path) -> None:
    _ = qapp
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    Image.new("RGBA", (1, 1), (255, 0, 0, 255)).save(source_dir / "a.png")
    Image.new("RGBA", (1, 1), (0, 0, 255, 255)).save(source_dir / "b.PNG")
    widget = PmpConversionWidget(SunnyOptimizerSettings(tmp_path / "settings.ini"))
    try:
        widget.palette_edit.setText(str(_save_palette(tmp_path)))
        widget.source_folder_edit.setText(str(source_dir))
        assert widget.preview_position_label.text() == "1 of 2"
        assert "a.png" in widget.preview_pane.meta_label.text()

        widget._step_preview(1)
        assert widget.preview_position_label.text() == "2 of 2"
        assert "b.PNG" in widget.preview_pane.meta_label.text()

        widget._step_preview(1)
        assert "a.png" in widget.preview_pane.meta_label.text()
    finally:
        widget.close()


@pytest.mark.parametrize("dither", [False, True])
@pytest.mark.parametrize("paint_transparency", [False, True])
@pytest.mark.parametrize("batch", [False, True])
def test_preview_matches_decoded_export_with_palette_and_dither(
    qapp, tmp_path: Path, monkeypatch, dither: bool, paint_transparency: bool, batch: bool
) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "output"
    source_dir.mkdir()
    output_dir.mkdir()
    source = source_dir / "sprite.png"
    image = Image.new("RGBA", (16, 4))
    image.putdata([
        (100 + x * 5, 100 + x * 5, 100 + x * 5, (0, 51, 52, 128)[y])
        for y in range(4) for x in range(16)
    ])
    image.save(source)
    palette_path = tmp_path / "SUNNY.PCX"
    palette = Image.new("P", (1, 1))
    palette.putpalette([0, 0, 0, 255, 255, 255] + [0, 0, 0] * 254)
    palette.save(palette_path)
    monkeypatch.setattr("texture_tools.main._confirm_summary", lambda *_args, **_kwargs: True)
    widget = PmpConversionWidget(SunnyOptimizerSettings(tmp_path / "settings.ini"))
    try:
        widget.palette_edit.setText(str(palette_path))
        widget.transparency_checkbox.setChecked(paint_transparency)
        widget.input_edit.setText(str(source))
        undithered = [_pixmap_pixel(widget, x, y) for y in range(4) for x in range(16)]
        widget.dither_checkbox.setChecked(dither)
        preview_pixels = [_pixmap_pixel(widget, x, y) for y in range(4) for x in range(16)]
        if dither:
            assert preview_pixels != undithered
        output = output_dir / "sprite.pmp"
        if batch:
            widget.source_folder_edit.setText(str(source_dir))
            widget.target_folder_edit.setText(str(output_dir))
            widget._convert_folder_to_pmp()
        else:
            widget.output_edit.setText(str(output))
            widget._convert()
        decoded = pmp_to_image(output, palette_path).crop((0, 0, 16, 4))
        assert list(decoded.getchannel("A").tobytes()) == [0] * 32 + [255] * 32
        if paint_transparency:
            decoded = Image.alpha_composite(Image.new("RGBA", decoded.size, (0, 255, 0, 255)), decoded)
        assert preview_pixels == [decoded.getpixel((x, y)) for y in range(4) for x in range(16)]
    finally:
        widget.close()


def test_preview_refreshes_when_palette_changes(qapp, tmp_path: Path) -> None:
    source = tmp_path / "sprite.png"
    Image.new("RGBA", (1, 1), (200, 10, 20, 128)).save(source)
    palette_path = _save_palette(tmp_path)
    other_path = tmp_path / "other.pcx"
    other = Image.new("P", (1, 1))
    other.putpalette([255, 255, 255] * 256)
    other.save(other_path)
    widget = PmpConversionWidget(SunnyOptimizerSettings(tmp_path / "settings.ini"))
    try:
        widget.palette_edit.setText(str(palette_path))
        widget.input_edit.setText(str(source))
        assert _pixmap_pixel(widget) == (200, 10, 20, 255)
        widget.palette_edit.setText(str(other_path))
        assert _pixmap_pixel(widget) == (255, 255, 255, 255)
        widget.palette_edit.setText(str(tmp_path / "missing.pcx"))
        assert widget.preview_pane._pixmap_item.pixmap().isNull()
        assert "Preview unavailable" in widget.preview_pane.image_label.text()
    finally:
        widget.close()
