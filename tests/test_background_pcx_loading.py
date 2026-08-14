from pathlib import Path

import pytest

try:
    from PyQt5 import QtWidgets

    from sg_viewer.services.preview_background import PreviewBackground
    from sg_viewer.ui.bg_calibrator_minimal import Calibrator
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


def _write_pcx(path: Path) -> None:
    header = bytearray(128)
    header[0:4] = bytes((0x0A, 5, 1, 8))
    header[8:12] = bytes((2, 0, 1, 0))  # xmax=2, ymax=1
    header[65] = 1
    header[66:68] = (4).to_bytes(2, "little")  # padded scanlines
    palette = bytearray(768)
    palette[3:6] = bytes((12, 34, 56))
    pixels = bytes((1, 0, 0, 0, 0, 0, 0, 0))
    path.write_bytes(header + pixels + bytes((0x0C,)) + palette)


def test_preview_background_loads_pcx(qapp, tmp_path) -> None:
    path = tmp_path / "BACKGROUND.PCX"
    _write_pcx(path)

    background = PreviewBackground()
    background.load_image(path)

    assert background.image is not None
    assert (background.image.width(), background.image.height()) == (3, 2)
    assert background.image.pixelColor(0, 0).getRgb()[:3] == (12, 34, 56)


def test_calibrator_loads_pcx(qapp, tmp_path) -> None:
    path = tmp_path / "background.pcx"
    _write_pcx(path)

    calibrator = Calibrator()
    try:
        assert calibrator._load_image(str(path))
        assert calibrator.image_size == (3, 2)
        assert calibrator.current_image_path == str(path)
    finally:
        calibrator.close()
