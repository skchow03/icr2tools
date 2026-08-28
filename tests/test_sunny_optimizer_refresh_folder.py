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
    return [
        window.texture_list.item(row, 0).text()
        for row in range(window.texture_list.rowCount())
    ]


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


def test_folder_manifest_is_created_and_refreshed(qapp, tmp_path: Path) -> None:
    import json

    _ = qapp
    window = MainWindow()
    _write_png(tmp_path / "a.png", (255, 0, 0))
    window._load_folder(tmp_path)

    manifest_path = tmp_path / window.FOLDER_SETTINGS_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest == {"images": [{"file": "a.png", "budget": 70, "required": 0}]}

    window.per_texture_budget["a.png"] = 23
    window.per_texture_required_unique_colors["a.png"] = 1
    window._persist_current_folder_budgets()
    window.refresh_folder()

    assert window.per_texture_budget == {"a.png": 23}
    assert window.per_texture_required_unique_colors == {"a.png": 1}
    assert window.folder_path_label.text() == str(tmp_path.resolve())
