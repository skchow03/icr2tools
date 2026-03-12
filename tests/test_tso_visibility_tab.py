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


def test_row_selection_emits_track_section_and_order():
    _app()
    tab = TSOVisibilityTab()
    tab.set_object_lists([
        Track3DObjectList(side="L", section=4, sub_index=0, tso_ids=[7, 2, 7]),
    ])

    sections: list[object] = []
    orders: list[object] = []
    tab.selectedTrackSectionChanged.connect(sections.append)
    tab.selectedTSOOrderChanged.connect(orders.append)

    tab.table.selectRow(0)

    assert sections[-1] == 4
    assert orders[-1] == {7: 3, 2: 2}


def test_assigned_tso_ids_and_add_dialog_asterisk_labels():
    _app()
    tab = TSOVisibilityTab()
    tab.set_tso_display_metadata({1: ("tree", "oak")})
    tab.set_object_lists(
        [
            Track3DObjectList(side="L", section=1, sub_index=0, tso_ids=[1, 3]),
            Track3DObjectList(side="R", section=2, sub_index=0, tso_ids=[3, 4]),
        ]
    )

    assigned = tab._assigned_tso_ids()
    assert assigned == {1, 3, 4}

    assert tab._build_add_tso_dialog_label(1, assigned) == "__TSO1 (tree — oak)"
    assert tab._build_add_tso_dialog_label(2, assigned) == "__TSO2 *"
