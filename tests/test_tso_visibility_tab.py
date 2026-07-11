import pytest

pytest.importorskip("PyQt5")

from PyQt5 import QtCore, QtWidgets

from sg_viewer.io.track3d_parser import Track3DObjectList
from sg_viewer.ui.tabs.tso_visibility_tab import (
    TSOVisibilityReconcileDialog,
    TSOVisibilityTab,
    UNASSIGNED_TSO_MEMO_FLAVOR_MESSAGES,
)


def _app() -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_pills_include_filename_and_description_metadata() -> None:
    _app()
    tab = TSOVisibilityTab()
    tab.set_tso_display_metadata({1: ("tree", "oak"), 2: ("house", "")})
    tab.set_object_lists(
        [Track3DObjectList(side="L", section=1, sub_index=0, tso_ids=[1, 2, 3])]
    )

    assert tab.tso_list.item(0).text() == "__TSO1 (tree — oak)"
    assert tab.tso_list.item(1).text() == "__TSO2 (house)"
    assert tab.tso_list.item(2).text() == "__TSO3"


def test_row_selection_emits_track_section_and_order() -> None:
    _app()
    tab = TSOVisibilityTab()
    tab.set_object_lists(
        [Track3DObjectList(side="L", section=4, sub_index=0, tso_ids=[7, 2, 7])]
    )

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


def test_tso_filter_selection_emits_highlighted_tso() -> None:
    _app()
    tab = TSOVisibilityTab()
    tab.set_available_tso_ids([1, 2, 3])
    tab.set_object_lists(
        [Track3DObjectList(side="L", section=1, sub_index=0, tso_ids=[1])]
    )
    highlighted: list[object] = []
    tab.selectedTSOPillChanged.connect(highlighted.append)

    tab.tso_filter_list.setCurrentRow(1)

    assert highlighted[-1] == 2


def test_add_selected_tso_uses_tso_filter_list_selection() -> None:
    _app()
    tab = TSOVisibilityTab()
    tab.set_tso_display_metadata({1: ("tree", "oak"), 2: ("house", "")})
    tab.set_available_tso_ids([1, 2, 3])
    tab.set_object_lists(
        [Track3DObjectList(side="L", section=1, sub_index=0, tso_ids=[1])]
    )
    tab.section_list.setCurrentRow(0)
    tab.tso_filter_list.setCurrentRow(1)

    tab.add_tso_button.click()

    assert tab.object_lists[0].tso_ids == [1, 2]
    assert tab.tso_list.count() == 2
    assert tab.tso_list.item(1).text() == "__TSO2 (house)"
    assert tab.tso_list.currentRow() == 1


def test_add_selected_tso_inserts_after_selected_visible_tso() -> None:
    _app()
    tab = TSOVisibilityTab()
    tab.set_available_tso_ids([1, 2, 3, 4])
    tab.set_object_lists(
        [Track3DObjectList(side="L", section=1, sub_index=0, tso_ids=[1, 3, 4])]
    )
    tab.section_list.setCurrentRow(0)
    tab.tso_list.setCurrentRow(0)
    tab.tso_filter_list.setCurrentRow(1)

    tab.add_tso_button.click()

    assert tab.object_lists[0].tso_ids == [1, 2, 3, 4]
    assert tab.tso_list.currentRow() == 1
    assert tab.tso_list.item(1).text() == "__TSO2"


def test_unassigned_tso_filter_rows_are_highlighted_light_blue() -> None:
    _app()
    tab = TSOVisibilityTab()
    tab.set_available_tso_ids([1, 2, 3])
    tab.set_object_lists(
        [Track3DObjectList(side="L", section=1, sub_index=0, tso_ids=[2])]
    )

    unassigned_filter_item = tab.tso_filter_list.item(0, 0)
    unassigned_tso_item = tab.tso_filter_list.item(0, 1)
    assigned_filter_item = tab.tso_filter_list.item(1, 0)
    assigned_tso_item = tab.tso_filter_list.item(1, 1)

    assert unassigned_filter_item is not None
    assert unassigned_tso_item is not None
    assert assigned_filter_item is not None
    assert assigned_tso_item is not None

    assert unassigned_filter_item.background().color().name() == "#dbeeff"
    assert unassigned_tso_item.background().color().name() == "#dbeeff"
    assert assigned_filter_item.background().style() == 0
    assert assigned_tso_item.background().style() == 0


def test_detail_list_tso_filter_rows_are_not_highlighted_blue() -> None:
    _app()
    tab = TSOVisibilityTab()
    tab.set_available_tso_ids([1, 2])
    tab.set_object_lists(
        [Track3DObjectList(side="L", section=1, sub_index=0, tso_ids=[1])]
    )
    tab.set_detail_list_tso_ids({1, 2})

    assigned_filter_item = tab.tso_filter_list.item(0, 0)
    assigned_tso_item = tab.tso_filter_list.item(0, 1)
    unassigned_filter_item = tab.tso_filter_list.item(1, 0)
    unassigned_tso_item = tab.tso_filter_list.item(1, 1)

    assert assigned_filter_item is not None
    assert assigned_tso_item is not None
    assert unassigned_filter_item is not None
    assert unassigned_tso_item is not None

    assert assigned_filter_item.background().style() == 0
    assert assigned_tso_item.background().style() == 0
    assert assigned_tso_item.toolTip() == ""
    assert unassigned_filter_item.background().style() == 0
    assert unassigned_tso_item.background().style() == 0
    assert unassigned_tso_item.toolTip() == ""


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
    assert any(
        (entry.side, entry.section, entry.sub_index, entry.tso_ids) == ("R", 2, 1, [6])
        for entry in reconciled
    )


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


def test_reconcile_dialog_can_sort_both_lists_by_side_then_section_then_subindex() -> (
    None
):
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
        (entry.side, entry.section, entry.sub_index)
        for entry in dialog.reconciled_object_lists()
    ] == [("L", 2, 0), ("L", 3, 1), ("R", 2, 2)]
    assert [
        dialog.track3d_list_widget.item(row).text().split(" — ", 1)[0]
        for row in range(dialog.track3d_list_widget.count())
    ] == ["L / 5 / 0", "R / 1 / 0", "R / 1 / 1"]


from sg_viewer.io.track3d_parser import Track3DDetailList


def test_clear_all_object_lists_removes_tsos_but_keeps_lists() -> None:
    _app()
    tab = TSOVisibilityTab()
    tab.set_available_tso_ids([1, 2, 3])
    tab.set_object_lists(
        [
            Track3DObjectList(side="L", section=1, sub_index=0, tso_ids=[1, 2]),
            Track3DObjectList(side="R", section=2, sub_index=1, tso_ids=[3]),
        ]
    )
    tab._subsection_dlong_ranges[(1, 0)] = (10, 20)
    tab._section_subindex_starts[1] = (0,)

    tab.clear_all_object_lists()

    assert [
        (entry.side, entry.section, entry.sub_index) for entry in tab.object_lists
    ] == [
        ("L", 1, 0),
        ("R", 2, 1),
    ]
    assert [entry.tso_ids for entry in tab.object_lists] == [[], []]
    assert tab._subsection_dlong_ranges == {(1, 0): (10, 20)}
    assert tab._section_subindex_starts == {1: (0,)}
    assert tab.section_list.count() == 2
    tab.section_list.setCurrentRow(0)
    assert tab.tso_list.count() == 0


def test_clear_all_detail_lists_removes_tsos_but_keeps_lists() -> None:
    _app()
    tab = TSOVisibilityTab()
    tab.set_available_tso_ids([1, 2, 3])
    tab.set_detail_lists(
        [
            Track3DDetailList(section=3, sub_index=0, lod_suffix="H", tso_ids=[1, 2]),
            Track3DDetailList(section=4, sub_index=1, lod_suffix="M", tso_ids=[3]),
        ]
    )
    tab._detail_list_dlong_ranges[(3, 0, "H")] = (30, 40)

    tab.clear_all_detail_lists()

    assert [
        (entry.section, entry.sub_index, entry.lod_suffix) for entry in tab.detail_lists
    ] == [(3, 0, "H"), (4, 1, "M")]
    assert [entry.tso_ids for entry in tab.detail_lists] == [[], []]
    assert tab._detail_list_tso_ids == set()
    assert tab._detail_list_dlong_ranges == {(3, 0, "H"): (30, 40)}
    assert tab.section_list.count() == 2
    tab.section_list.setCurrentRow(0)
    assert tab.tso_list.count() == 0


def test_object_and_detail_lists_show_in_parallel_section_table() -> None:
    _app()
    tab = TSOVisibilityTab()
    tab.set_object_lists(
        [
            Track3DObjectList(side="L", section=4, sub_index=0, tso_ids=[7]),
            Track3DObjectList(side="R", section=5, sub_index=1, tso_ids=[8]),
        ]
    )
    tab.set_detail_lists(
        [
            Track3DDetailList(section=1, sub_index=0, lod_suffix="H", tso_ids=[1]),
            Track3DDetailList(section=1, sub_index=0, lod_suffix="M", tso_ids=[2]),
            Track3DDetailList(section=2, sub_index=0, lod_suffix="H", tso_ids=[3]),
        ]
    )

    assert tab.section_list.columnCount() == 3
    assert tab.section_list.horizontalHeaderItem(0).text() == "ObjectLists L sections"
    assert tab.section_list.horizontalHeaderItem(1).text() == "ObjectLists R sections"
    assert tab.section_list.horizontalHeaderItem(2).text() == "DetailLists"
    assert tab.section_list.count() == 4
    assert [
        tab.section_list.item(row).text() for row in range(tab.section_list.count())
    ] == [
        "4 / 0",
        "5 / 1",
        "1 / 0H",
        "2 / 0H",
    ]
    assert [
        tab.section_list.item(row).data(QtCore.Qt.UserRole)
        for row in range(tab.section_list.count())
    ] == [("object", 0), ("object", 1), ("detail", 0), ("detail", 2)]


def test_detail_list_mode_disables_copy_previous_and_emits_dlong_range() -> None:
    _app()
    tab = TSOVisibilityTab()
    tab.set_detail_lists(
        [Track3DDetailList(section=2, sub_index=1, lod_suffix="H", tso_ids=[4])]
    )
    tab._detail_list_dlong_ranges[(2, 1, "H")] = (100, 200)
    sections: list[object] = []
    tab.selectedTrackSectionChanged.connect(sections.append)

    tab.section_list.setCurrentRow(0)

    assert not tab.copy_prev_button.isEnabled()
    assert sections[-1]["section"] == 2
    assert sections[-1]["sub_index"] == 1
    assert sections[-1]["start_dlong"] == 100
    assert sections[-1]["end_dlong"] == 200


def test_unassigned_tso_memo_reports_tsos_missing_from_object_and_detail_lists() -> (
    None
):
    _app()
    tab = TSOVisibilityTab()
    tab.set_tso_display_metadata(
        {1: ("tree", "oak"), 4: ("marshal", ""), 5: ("sign", "brake")}
    )
    tab.set_available_tso_ids([1, 2, 3, 4, 5])
    tab.set_object_lists(
        [Track3DObjectList(side="L", section=1, sub_index=0, tso_ids=[1])]
    )
    tab.set_detail_lists(
        [Track3DDetailList(section=1, sub_index=0, lod_suffix="H", tso_ids=[3])]
    )

    memo = tab.build_unassigned_tso_memo()

    assert "Subject: TSO Visibility Assignment Review" in memo
    assert "Unassigned TSOs: 3" in memo
    assert "__TSO2" in memo
    assert "__TSO4 (marshal)" in memo
    assert "__TSO5 (sign — brake)" in memo
    assert "__TSO1 (tree — oak)" not in memo.split("Findings:", 1)[1]
    assert "__TSO3" not in memo.split("Findings:", 1)[1]


def test_unassigned_tso_memo_reports_clean_assignment() -> None:
    _app()
    tab = TSOVisibilityTab()
    tab.set_available_tso_ids([1, 2])
    tab.set_object_lists(
        [Track3DObjectList(side="L", section=1, sub_index=0, tso_ids=[1])]
    )
    tab.set_detail_lists(
        [Track3DDetailList(section=1, sub_index=0, lod_suffix="H", tso_ids=[2])]
    )

    memo = tab.build_unassigned_tso_memo()

    assert "Unassigned TSOs: 0" in memo
    assert "No unassigned TSOs found." in memo


def test_unassigned_tso_memo_has_twenty_random_flavor_messages() -> None:
    _app()
    tab = TSOVisibilityTab()
    tab.set_available_tso_ids([1])

    memo = tab.build_unassigned_tso_memo()

    assert len(UNASSIGNED_TSO_MEMO_FLAVOR_MESSAGES) == 20
    assert "Department note:" in memo
    assert any(
        message in memo for message in UNASSIGNED_TSO_MEMO_FLAVOR_MESSAGES
    )
