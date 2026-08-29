from pathlib import Path

import numpy as np
import pytest

try:  # pragma: no cover
    from PIL import Image
    from PyQt5 import QtCore, QtWidgets
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 or Pillow not available", allow_module_level=True)

from sunny_optimizer.palette import save_palette
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
    assert manifest == {
        "sunny_palette": "",
        "images": [{"file": "a.png", "budget": 70, "required": 0}],
    }

    window.per_texture_budget["a.png"] = 23
    window.per_texture_required_unique_colors["a.png"] = 1
    window._persist_current_folder_budgets()
    window.refresh_folder()

    assert window.per_texture_budget == {"a.png": 23}
    assert window.per_texture_required_unique_colors == {"a.png": 1}
    assert window.folder_path_label.text() == str(tmp_path.resolve())


def test_folder_manifest_restores_its_sunny_palette(qapp, tmp_path: Path) -> None:
    import json

    _ = qapp
    texture_folder = tmp_path / "textures"
    texture_folder.mkdir()
    _write_png(texture_folder / "a.png", (255, 0, 0))
    palette_path = tmp_path / "palettes" / "sunny.pcx"
    palette_path.parent.mkdir()
    palette_path.write_bytes(b"palette placeholder")
    (texture_folder / MainWindow.FOLDER_SETTINGS_FILENAME).write_text(
        json.dumps(
            {
                "sunny_palette": "../palettes/sunny.pcx",
                "images": [{"file": "a.png", "budget": 12, "required": 0}],
            }
        ),
        encoding="utf-8",
    )

    window = MainWindow()
    window._load_folder(texture_folder)

    assert window._last_sunny_palette_path == palette_path.resolve()
    assert window.palette_path_label.text() == str(palette_path.resolve())
    saved = json.loads(
        (texture_folder / MainWindow.FOLDER_SETTINGS_FILENAME).read_text(encoding="utf-8")
    )
    assert saved["sunny_palette"] == str(palette_path.resolve())


def test_optimize_palette_uses_resizable_splitter_and_preview_titles(qapp) -> None:
    _ = qapp
    window = MainWindow()

    assert window.main_splitter.count() == 2
    assert not window.main_splitter.childrenCollapsible()
    assert window.preview_palette_splitter.orientation() == QtCore.Qt.Vertical
    assert window.preview_palette_splitter.count() == 2
    assert not window.preview_palette_splitter.childrenCollapsible()
    labels = {label.text() for label in window.findChildren(QtWidgets.QLabel)}
    assert "Files" in labels
    assert "Original" in labels
    assert "Paletted" in labels
    assert not any(text.startswith(("Step 2", "Step 3")) for text in labels)
    assert not any("Scroll to zoom" in text for text in labels)


def test_files_section_uses_select_buttons_without_recent_palette_dropdown(qapp) -> None:
    _ = qapp
    window = MainWindow()

    assert window.folder_btn.text() == "Browse…"
    assert window.refresh_folder_btn.text() == "Reload"
    assert window.palette_path_browse_btn.text() == "Browse…"
    assert window.apply_loaded_palette_btn.text() == "Apply"
    assert window.export_destination_btn.text() == "Browse…"
    assert not hasattr(window, "palette_recent_btn")
    assert not hasattr(window, "palette_path_recent_btn")


def test_file_selection_bar_is_one_row_with_read_only_elided_fields(qapp) -> None:
    _ = qapp
    window = MainWindow()
    window.show()
    qapp.processEvents()

    field_widgets = [
        window.folder_path_label,
        window.palette_path_label,
        window.export_destination_label,
    ]
    assert all(isinstance(field, QtWidgets.QLineEdit) for field in field_widgets)
    assert all(field.isReadOnly() for field in field_widgets)
    labels = {label.text() for label in window.files_card.findChildren(QtWidgets.QLabel)}
    assert {"Textures:", "Palette:", "Output:"} <= labels

    controls = [
        *field_widgets,
        window.folder_btn,
        window.refresh_folder_btn,
        window.palette_path_browse_btn,
        window.apply_loaded_palette_btn,
        window.export_destination_btn,
    ]
    centers = [
        control.mapTo(window.files_card, control.rect().center()).y()
        for control in controls
    ]
    assert max(centers) - min(centers) <= 2
    assert all(control.geometry().width() > 0 for control in controls)


def test_path_field_middle_elides_and_only_then_shows_full_path_tooltip(qapp) -> None:
    _ = qapp
    window = MainWindow()
    field = window.folder_path_label
    full_path = r"C:\Dosprogs\icr2\projects\goiania\art"

    field.resize(120, field.sizeHint().height())
    field.setText(full_path)
    assert "…" in field.text()
    assert field.text().startswith("C:")
    assert field.text().endswith("art")
    assert field.toolTip() == full_path
    assert field.fullText() == full_path

    field.resize(1000, field.height())
    assert field.text() == full_path
    assert field.toolTip() == ""


def test_apply_loaded_palette_updates_palette_and_all_texture_previews(
    qapp, tmp_path: Path
) -> None:
    _ = qapp
    texture_folder = tmp_path / "textures"
    texture_folder.mkdir()
    _write_png(texture_folder / "a.png", (255, 0, 0))
    _write_png(texture_folder / "b.png", (0, 255, 0))
    palette_path = tmp_path / "sunny.pcx"
    palette = np.zeros((256, 3), dtype=np.uint8)
    palette[7] = (255, 0, 0)
    palette[11] = (0, 255, 0)
    save_palette(palette_path, palette)

    window = MainWindow()
    window._load_folder(texture_folder)
    window._set_palette_path(str(palette_path))

    assert window.apply_loaded_palette_btn.isEnabled()
    window.apply_loaded_palette()

    np.testing.assert_array_equal(window.current_palette, palette)
    assert not window.apply_loaded_palette_btn.isEnabled()
    assert set(window.indexed_images) == {"a.png", "b.png"}
    assert set(window.quantized_images) == {"a.png", "b.png"}
    assert window.palette_preview_title.text() == "Palette from loaded sunny.pcx"
    assert window._apply_palette_dialog is not None
    assert window._apply_palette_dialog.windowTitle() == "Applying Loaded Palette"
    assert window._apply_palette_dialog.progress.value() == 100
    assert (
        "Applied sunny.pcx to 2 textures"
        in window._apply_palette_dialog.progress_label.text()
    )
    assert "Applying palette to a.png (1/2)" in window._apply_palette_dialog.log.toPlainText()


def test_successful_optimization_updates_palette_header(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    _ = qapp
    texture_folder = tmp_path / "textures"
    texture_folder.mkdir()
    _write_png(texture_folder / "a.png", (255, 0, 0))
    palette_path = tmp_path / "sunny.pcx"
    palette = np.zeros((256, 3), dtype=np.uint8)
    save_palette(palette_path, palette)

    class FakeOptimizer:
        def __init__(self, **kwargs):
            self.progress_callback = kwargs["progress_callback"]

        def compute_palette(self):
            return palette.copy()

        def compute_quantized_images(self, _palette):
            return (
                {"a.png": np.zeros((8, 8), dtype=np.uint8)},
                {"a.png": np.zeros((8, 8, 3), dtype=np.uint8)},
            )

    monkeypatch.setattr(
        "sunny_optimizer.ui.main_window._get_optimizer_class", lambda: FakeOptimizer
    )
    window = MainWindow()
    window._load_folder(texture_folder)
    window._set_palette_path(str(palette_path))

    window.compute_palette()

    assert window.palette_preview_title.text() == "Palette from optimization"
