import pytest

pytest.importorskip("PyQt5")

from PyQt5 import QtWidgets

from sg_viewer.io.track3d_parser import Track3DObjectList
from sg_viewer.ui.main_window import SGViewerWindow
from sg_viewer.ui.viewer_controller import SGViewerController


@pytest.fixture
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_confirm_close_prompts_for_unsaved_tso_visibility_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    controller = SGViewerController.__new__(SGViewerController)
    controller._window = type("Window", (), {"preview": type("Preview", (), {"has_unsaved_changes": False})()})()
    controller._elevation_grade_is_dirty = False
    controller._fsects_is_dirty = False
    controller._mrk_is_dirty = False
    controller._tsd_is_dirty = False
    controller._trackside_objects_is_dirty = False
    controller._tso_visibility_is_dirty = True

    prompts: list[tuple[str, str, str]] = []

    def _fake_confirm_discard_dialog(*, title: str, message: str, confirm_text: str) -> bool:
        prompts.append((title, message, confirm_text))
        return False

    monkeypatch.setattr(controller, "_confirm_discard_dialog", _fake_confirm_discard_dialog)

    assert controller.confirm_close() is False
    assert prompts == [
        (
            "Close SG Viewer?",
            "You have unsaved changes in:\n• TSO visibility\n\nContinue and close sg viewer without saving?",
            "Close without saving",
        )
    ]


def test_tso_visibility_sidebar_marks_tab_dirty_and_save_clears_it(qapp) -> None:
    _ = qapp
    window = SGViewerWindow()
    try:
        tab = window.tso_visibility_sidebar
        tab.set_object_lists([Track3DObjectList(side="L", section=1, sub_index=0, tso_ids=[1, 2])])
        assert window.right_sidebar_tabs.tabText(4) == "TSO Visibility"

        tab.section_list.setCurrentRow(0)
        tab.available_tso_ids = [1, 2, 3]
        tab.object_lists[0].tso_ids.append(3)
        tab.objectListsChanged.emit()

        assert window.right_sidebar_tabs.tabText(4) == "TSO Visibility*"

        tab.objectListsSaved.emit()

        assert window.right_sidebar_tabs.tabText(4) == "TSO Visibility"
    finally:
        window.close()
