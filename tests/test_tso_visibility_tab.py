import pytest

pytest.importorskip("PyQt5")

from PyQt5 import QtWidgets

from sg_viewer.io.track3d_parser import Track3DObjectList
from sg_viewer.ui.tabs.tso_visibility_tab import TSOVisibilityReconcileDialog, TSOVisibilityTab


def _app() -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_pills_include_filename_and_description_metadata() -> None:
    _app()
    tab = TSOVisibilityTab()
    tab.set_tso_display_metadata({1: ("tree", "oak"), 2: ("house", "")})
    tab.set_object_lists([Track3DObjectList(side="L", section=1, sub_index=0, tso_ids=[1, 2, 3])])

    assert tab.tso_list.item(0).text() == "__TSO1 (tree — oak)"
    assert tab.tso_list.item(1).text() == "__TSO2 (house)"
    assert tab.tso_list.item(2).text() == "__TSO3"


def test_row_selection_emits_track_section_and_order() -> None:
    _app()
    tab = TSOVisibilityTab()
    tab.set_object_lists([Track3DObjectList(side="L", section=4, sub_index=0, tso_ids=[7, 2, 7])])

    sections: list[object] = []
    orders: list[object] = []
    tab.selectedTrackSectionChanged.connect(sections.append)
    tab.selectedTSOOrderChanged.connect(orders.append)

    tab.section_list.setCurrentRow(0)

    assert sections[-1]["section"] == 4
    assert sections[-1]["sub_index"] == 0
    assert orders[-1] == {7: 3, 2: 2}


def test_assigned_tso_ids_and_add_dialog_asterisk_labels() -> None:
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


def test_add_selected_tso_uses_tso_filter_list_selection() -> None:
    _app()
    tab = TSOVisibilityTab()
    tab.set_tso_display_metadata({1: ("tree", "oak"), 2: ("house", "")})
    tab.set_available_tso_ids([1, 2, 3])
    tab.set_object_lists([Track3DObjectList(side="L", section=1, sub_index=0, tso_ids=[1])])
    tab.section_list.setCurrentRow(0)
    tab.tso_filter_list.setCurrentRow(1)

    tab.add_tso_button.click()

    assert tab.object_lists[0].tso_ids == [1, 2]
    assert tab.tso_list.count() == 2
    assert tab.tso_list.item(1).text() == "__TSO2 (house)"


def test_reconcile_dialog_can_copy_matching_rows_and_add_missing_rows() -> None:
    _app()
    dialog = TSOVisibilityReconcileDialog(
        current_lists=[
            Track3DObjectList(side="L", section=1, sub_index=0, tso_ids=[1, 2]),
            Track3DObjectList(side="R", section=1, sub_index=0, tso_ids=[9]),
        ],
        track3d_lists=[
            Track3DObjectList(side="L", section=1, sub_index=0, tso_ids=[4, 5]),
            Track3DObjectList(side="R", section=2, sub_index=1, tso_ids=[6]),
        ],
    )

    dialog.copy_all_matching_button.click()
    dialog.add_missing_button.click()

    reconciled = dialog.reconciled_object_lists()
    assert reconciled[0].tso_ids == [4, 5]
    assert any((entry.side, entry.section, entry.sub_index, entry.tso_ids) == ("R", 2, 1, [6]) for entry in reconciled)



def test_reconcile_dialog_highlights_rows_missing_from_opposite_list_in_red() -> None:
    _app()
    dialog = TSOVisibilityReconcileDialog(
        current_lists=[
            Track3DObjectList(side="L", section=1, sub_index=0, tso_ids=[1]),
            Track3DObjectList(side="R", section=3, sub_index=0, tso_ids=[2]),
        ],
        track3d_lists=[
            Track3DObjectList(side="L", section=1, sub_index=0, tso_ids=[1]),
            Track3DObjectList(side="R", section=4, sub_index=0, tso_ids=[3]),
        ],
    )

    current_missing = dialog.current_list_widget.item(1)
    track3d_missing = dialog.track3d_list_widget.item(1)

    assert current_missing is not None
    assert track3d_missing is not None
    assert "[missing in .3D]" in current_missing.text()
    assert current_missing.foreground().color().name() == "#ff0000"
    assert "[missing in project]" in track3d_missing.text()
    assert track3d_missing.foreground().color().name() == "#ff0000"


def test_reconcile_dialog_can_sort_both_lists_by_side_then_section_then_subindex() -> None:
    _app()
    dialog = TSOVisibilityReconcileDialog(
        current_lists=[
            Track3DObjectList(side="R", section=2, sub_index=2, tso_ids=[8]),
            Track3DObjectList(side="L", section=3, sub_index=1, tso_ids=[4]),
            Track3DObjectList(side="L", section=2, sub_index=0, tso_ids=[5]),
        ],
        track3d_lists=[
            Track3DObjectList(side="R", section=1, sub_index=1, tso_ids=[7]),
            Track3DObjectList(side="L", section=5, sub_index=0, tso_ids=[6]),
            Track3DObjectList(side="R", section=1, sub_index=0, tso_ids=[9]),
        ],
    )

    dialog.sort_lists_button.click()

    assert [
        (entry.side, entry.section, entry.sub_index) for entry in dialog.reconciled_object_lists()
    ] == [("L", 2, 0), ("L", 3, 1), ("R", 2, 2)]
    assert [
        dialog.track3d_list_widget.item(row).text().split(" — ", 1)[0]
        for row in range(dialog.track3d_list_widget.count())
    ] == ["L / 5 / 0", "R / 1 / 0", "R / 1 / 1"]
