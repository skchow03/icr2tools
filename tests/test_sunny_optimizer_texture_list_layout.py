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
