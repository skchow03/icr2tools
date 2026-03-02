from pathlib import Path

import pytest

try:  # pragma: no cover
    from PIL import Image
    from PyQt5 import QtWidgets
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 or Pillow not available", allow_module_level=True)

from sunny_optimizer.ui.main_window import MainWindow


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _write_png(path: Path, rgb: tuple[int, int, int]) -> None:
    Image.new("RGB", (8, 8), rgb).save(path)


def _listed_texture_names(window: MainWindow) -> list[str]:
    names: list[str] = []
    for i in range(window.texture_list.count()):
        item = window.texture_list.item(i)
        widget = window.texture_list.itemWidget(item)
        if widget is not None:
            names.append(widget.texture_name)
    return names


def test_refresh_folder_rescans_texture_list(qapp, tmp_path: Path) -> None:
    _ = qapp
    window = MainWindow()

    _write_png(tmp_path / "a.png", (255, 0, 0))
    window._load_folder(tmp_path)
    assert _listed_texture_names(window) == ["a.png"]

    (tmp_path / "a.png").unlink()
    _write_png(tmp_path / "b.png", (0, 255, 0))

    window.refresh_folder()

    assert _listed_texture_names(window) == ["b.png"]
