import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt5 import QtWidgets

from sg_viewer.services.track3d_topo_tso_calls import SectionTopoTsoCalls
from sg_viewer.ui.tabs.topo_tso_calls_tab import TopoTsoCallsTab


def _app() -> QtWidgets.QApplication:
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_section_picker_adds_selected_section_to_either_side() -> None:
    _app()
    tab = TopoTsoCallsTab()
    tab.set_calls(
        [
            SectionTopoTsoCalls("sec0_s0_HI", ["LEFT"], []),
            SectionTopoTsoCalls("sec1_s0_MED", [], ["RIGHT"]),
            SectionTopoTsoCalls("sec2_s1_LO", [], []),
        ]
    )
    changes: list[bool] = []
    tab.changed.connect(lambda: changes.append(True))

    assert [
        tab.available_sections_list.item(row).text()
        for row in range(tab.available_sections_list.count())
    ] == ["sec0_s0_HI", "sec1_s0_MED", "sec2_s1_LO"]

    tab.available_sections_list.setCurrentRow(2)
    tab.add_section_left_button.click()
    tab.available_sections_list.setCurrentRow(1)
    tab.add_section_right_button.click()

    assert tab.calls()[0].left == ["LEFT", "sec2_s1_LO"]
    assert tab.calls()[0].right == ["sec1_s0_MED"]
    assert len(changes) == 2


def test_section_picker_does_nothing_without_a_selection() -> None:
    _app()
    tab = TopoTsoCallsTab()
    tab.set_calls([SectionTopoTsoCalls("sec0_s0_HI", [], [])])
    tab.available_sections_list.clearSelection()
    tab.available_sections_list.setCurrentItem(None)

    tab.add_section_left_button.click()

    assert tab.calls()[0].left == []
