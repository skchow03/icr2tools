import pytest

pytest.importorskip("PyQt5")

from PyQt5 import QtCore, QtWidgets

from sg_viewer.io.track3d_parser import Track3DObjectList
from sg_viewer.ui.tabs.tso_visibility_tab import TSOVisibilityTab


def _app() -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_pills_include_filename_and_description_metadata():
    _app()
    tab = TSOVisibilityTab()
    tab.set_tso_display_metadata({1: ("tree", "oak"), 2: ("house", "")})
    tab.set_object_lists([Track3DObjectList(side="L", section=1, sub_index=0, tso_ids=[1, 2, 3])])

    widget = tab.table.cellWidget(0, 3)
    assert widget is not None

    assert widget.item(0).text() == "__TSO1 (tree — oak)"
    assert widget.item(1).text() == "__TSO2 (house)"
    assert widget.item(2).text() == "__TSO3"
    assert widget.item(0).data(QtCore.Qt.UserRole) == 1
