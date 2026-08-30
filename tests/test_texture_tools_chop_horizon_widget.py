from pathlib import Path

import pytest
from PIL import Image

try:  # pragma: no cover
    from PyQt5 import QtWidgets
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)

from texture_tools.main import ChopHorizonWidget


@pytest.fixture
def qapp():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _source(path: Path) -> None:
    image = Image.new("RGB", (2048, 64))
    for panel in range(8):
        color = (panel * 30, 0, 0)
        image.paste(color, (panel * 256, 0, (panel + 1) * 256, 64))
    image.save(path)


def test_source_and_outputs_preview_and_follow_start_panel(qapp, tmp_path: Path) -> None:
    _ = qapp
    source = tmp_path / "horizon.png"
    _source(source)
    widget = ChopHorizonWidget()
    try:
        widget.input_edit.setText(str(source))
        assert widget.source_preview._pixmap_item.pixmap().width() == 2048
        assert widget.first_output_preview._pixmap_item.pixmap().size().width() == 256
        assert widget.second_output_preview._pixmap_item.pixmap().size().height() == 256
        assert widget.first_output_preview._pixmap_item.pixmap().toImage().pixelColor(0, 0).red() == 0

        widget.start_panel_spin.setValue(3)

        assert widget.first_output_preview._pixmap_item.pixmap().toImage().pixelColor(0, 0).red() == 60
    finally:
        widget.close()


def test_exports_default_mip_names_and_confirms_overwrite(qapp, tmp_path: Path, monkeypatch) -> None:
    _ = qapp
    source = tmp_path / "horizon.png"
    palette = tmp_path / "sunny.pcx"
    _source(source)
    Image.new("P", (1, 1)).save(palette)
    calls = []
    monkeypatch.setattr("texture_tools.main.img_to_mip", lambda _im, output, *_args, **_kwargs: calls.append(Path(output).name))
    warnings = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda *_args: warnings.append(_args[2]) or QtWidgets.QMessageBox.No,
    )
    widget = ChopHorizonWidget()
    try:
        widget.input_edit.setText(str(source))
        widget.palette_edit.setText(str(palette))
        widget.output_edit.setText(str(tmp_path))
        widget._run()
        assert calls == ["Page03.mip", "Page03b.mip"]

        (tmp_path / "Page03.mip").write_bytes(b"existing")
        widget._run()
        assert len(calls) == 2
        assert "Page03.mip" in warnings[0]
    finally:
        widget.close()
