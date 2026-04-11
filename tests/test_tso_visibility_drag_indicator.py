import pytest

pytest.importorskip("PyQt5")

from PyQt5 import QtCore, QtWidgets

from sg_viewer.ui.tabs.tso_visibility_tab import TSOVisibilityListWidget


def _app() -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def _make_widget() -> TSOVisibilityListWidget:
    _app()
    widget = TSOVisibilityListWidget()
    widget.setFixedSize(220, 180)
    widget.show()
    for index in range(3):
        widget.addItem(f"__TSO{index}")
    widget.update_item_widths()
    QtWidgets.QApplication.processEvents()
    return widget


def test_drop_indicator_tracks_top_insertion_point() -> None:
    widget = _make_widget()
    first_rect = widget.visualItemRect(widget.item(0))

    indicator_y = widget._calculate_drop_indicator_y(QtCore.QPoint(8, first_rect.top()))

    assert indicator_y == first_rect.top()


def test_drop_indicator_tracks_middle_insertion_point() -> None:
    widget = _make_widget()
    second_rect = widget.visualItemRect(widget.item(1))

    indicator_y = widget._calculate_drop_indicator_y(QtCore.QPoint(8, second_rect.top()))

    assert indicator_y == second_rect.top()


def test_drop_indicator_tracks_bottom_insertion_point() -> None:
    widget = _make_widget()
    last_rect = widget.visualItemRect(widget.item(widget.count() - 1))

    indicator_y = widget._calculate_drop_indicator_y(QtCore.QPoint(8, widget.viewport().height() - 1))

    assert indicator_y == last_rect.bottom() + 1
