from pathlib import Path

import pytest

try:  # pragma: no cover
    from PyQt5 import QtWidgets
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)

from texture_tools import main as texture_tools_main
from texture_tools.main import PmpToPngWidget
from texture_tools.sunny_optimizer.ui.settings import SunnyOptimizerSettings


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_pmp_to_png_batch_converts_folder(qapp, tmp_path: Path, monkeypatch) -> None:
    _ = qapp
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    source_dir.mkdir()
    target_dir.mkdir()
    (source_dir / "car.pmp").write_bytes(b"pmp")
    (source_dir / "helmet.PMP").write_bytes(b"pmp")
    (source_dir / "ignore.txt").write_text("not a sprite")
    palette = tmp_path / "SUNNY.PCX"
    palette.write_bytes(b"palette")

    calls = []

    def fake_convert(input_path, output_path, palette_path, crop=False):
        calls.append((Path(input_path), Path(output_path), Path(palette_path), crop))

    monkeypatch.setattr(texture_tools_main, "convert_pmp_to_png", fake_convert)
    widget = PmpToPngWidget(SunnyOptimizerSettings(tmp_path / "settings.ini"))
    try:
        widget.source_folder_edit.setText(str(source_dir))
        widget.target_folder_edit.setText(str(target_dir))
        widget.palette_edit.setText(str(palette))
        widget.crop_checkbox.setChecked(True)

        assert widget.batch_btn.isEnabled()
        widget._convert_folder_to_png()

        assert calls == [
            (source_dir / "car.pmp", target_dir / "car.png", palette, True),
            (source_dir / "helmet.PMP", target_dir / "helmet.png", palette, True),
        ]
        assert "Converted 2 file(s) to PNG" in widget.status_label.text()
    finally:
        widget.close()
