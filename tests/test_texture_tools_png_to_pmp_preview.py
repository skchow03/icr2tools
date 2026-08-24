from pathlib import Path

import pytest
from PIL import Image

try:  # pragma: no cover
    from PyQt5 import QtWidgets
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)

from texture_tools.main import PmpConversionWidget
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


def test_preview_paints_threshold_transparency_bright_green(qapp, tmp_path: Path) -> None:
    _ = qapp
    source = tmp_path / "sprite.png"
    Image.new("RGBA", (2, 1), (200, 10, 20, 51)).save(source)
    widget = PmpConversionWidget(SunnyOptimizerSettings(tmp_path / "settings.ini"))
    try:
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
