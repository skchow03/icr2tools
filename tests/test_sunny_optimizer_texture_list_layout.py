import pytest

try:  # pragma: no cover
    from PyQt5 import QtCore, QtWidgets
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)

from sunny_optimizer.ui.main_window import MainWindow


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_texture_list_columns_fit_left_pane(qapp) -> None:
    _ = qapp
    window = MainWindow()

    header = window.texture_list.horizontalHeader()

    assert all(
        header.sectionResizeMode(column) == QtWidgets.QHeaderView.Stretch
        for column in range(window.texture_list.columnCount())
    )
    assert window.texture_list.horizontalScrollBarPolicy() == QtCore.Qt.ScrollBarAlwaysOff


def test_file_controls_share_one_row_without_title(qapp) -> None:
    _ = qapp
    window = MainWindow()

    card_layout = window.files_card.layout()
    assert card_layout.count() == 1
    controls = card_layout.itemAt(0).layout()
    assert controls is not None
    assert controls.indexOf(window.folder_path_label) >= 0
    assert controls.indexOf(window.folder_btn) >= 0
    assert controls.indexOf(window.refresh_folder_btn) >= 0
    assert controls.indexOf(window.palette_path_label) >= 0
    assert controls.indexOf(window.palette_path_browse_btn) >= 0
    assert controls.indexOf(window.apply_loaded_palette_btn) >= 0
    assert controls.indexOf(window.export_destination_label) >= 0
    assert controls.indexOf(window.export_destination_btn) >= 0
    assert window.files_card.findChildren(QtWidgets.QLabel, "sectionTitle") == []


def test_select_export_destination_updates_label_and_settings(qapp, monkeypatch, tmp_path) -> None:
    _ = qapp
    window = MainWindow()
    monkeypatch.setattr(window.settings, "save", lambda: None)
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(tmp_path),
    )

    window.select_export_destination()

    assert window.export_destination == tmp_path.resolve()
    assert window.export_destination_label.text() == str(tmp_path.resolve())
    assert window.settings.last_export_destination == str(tmp_path.resolve())
