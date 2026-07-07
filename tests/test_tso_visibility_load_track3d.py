from pathlib import Path

import pytest

pytest.importorskip("PyQt5")

from PyQt5 import QtCore, QtWidgets

from sg_viewer.io.track3d_parser import Track3DDetailList, Track3DObjectList
from sg_viewer.ui.tabs.tso_visibility_tab import TSOVisibilityTab


def _app() -> QtWidgets.QApplication:
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


def test_load_track3d_warns_before_overwriting_existing_data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _app()
    tab = TSOVisibilityTab()
    tab.set_object_lists([Track3DObjectList(side="L", section=1, sub_index=0, tso_ids=[1])])

    path = tmp_path / "track.3d"
    path.write_text(
        "ObjectList_L0_0: LIST {__TSO0};\n"
        "sec0_l0: LIST { DATA { 0, 10, 20 } };\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(path), ""))
    warnings: list[tuple[str, str]] = []

    def _fake_warning(_parent, title, text, *args, **kwargs):
        warnings.append((title, text))
        return QtWidgets.QMessageBox.No

    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", _fake_warning)

    tab.load_file()

    assert warnings == [
        ("Load track.3D", "Loading track.3D will overwrite the current TSO Visibility data. Continue?"),
    ]
    assert tab.object_lists[0].tso_ids == [1]


def test_load_track3d_warns_when_section_count_does_not_match(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _app()
    tab = TSOVisibilityTab()
    tab.set_current_track_section_count(3)

    path = tmp_path / "track.3d"
    path.write_text(
        "ObjectList_L0_0: LIST {__TSO0};\n"
        "sec0_l0: LIST { DATA { 0, 10, 20 } };\n"
        "sec1_l0: LIST { DATA { 20, 30, 40 } };\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(path), ""))
    warnings: list[tuple[str, str]] = []

    def _fake_warning(_parent, title, text, *args, **kwargs):
        warnings.append((title, text))
        return QtWidgets.QMessageBox.Yes

    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", _fake_warning)

    tab.load_file()

    assert warnings == [
        (
            "Load track.3D",
            "The selected track.3D file has a different number of sections than the current track.\n\n"
            "Current track sections: 3\n"
            "track.3D sections: 2",
        )
    ]
    assert tab.object_lists == []


def test_load_track3d_warns_when_object_lists_are_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _app()
    tab = TSOVisibilityTab()

    path = tmp_path / "track.3d"
    path.write_text("sec0_l0: LIST { DATA { 0, 10, 20 } };\n", encoding="utf-8")

    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(path), ""))
    warnings: list[tuple[str, str]] = []

    def _fake_warning(_parent, title, text, *args, **kwargs):
        warnings.append((title, text))
        return QtWidgets.QMessageBox.Yes

    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", _fake_warning)

    tab.load_file()

    assert warnings == [
        ("Load track.3D", "The selected track.3D file does not contain any ObjectLists."),
    ]


def test_refresh_tso_filter_reports_detailed_progress() -> None:
    _app()
    tab = TSOVisibilityTab()
    tab.object_lists = [Track3DObjectList(side="L", section=0, sub_index=0, tso_ids=[1, 2])]
    tab.detail_lists = [Track3DDetailList(section=0, sub_index=0, lod_suffix="H", tso_ids=[3])]
    tab.set_detail_list_tso_ids({3})
    tab.available_tso_ids = [4]
    tab.set_tso_display_metadata({5: ("grandstand.3do", "Grandstand")})

    details: list[str] = []

    tab._refresh_tso_filter_list(details.append)

    assert tab.tso_filter_list.rowCount() == 5
    assert "Reading current TSO filter selections." in details
    assert "Collecting ObjectList and catalog TSO IDs." in details
    assert "Rebuilding filter rows for 5 available TSOs." in details
    assert "Building TSO filter row 1/5 for __TSO1." in details
    assert "Building TSO filter row 5/5 for __TSO5." in details
    assert "Highlighting unassigned TSOs." in details
    assert "Highlighting unassigned TSOs: starting row scan." in details
    assert (
        "Highlighting unassigned TSOs: "
        "2 ObjectList-assigned IDs, 1 DetailList IDs, 1 DetailList-only IDs, 5 filter rows."
    ) in details
    assert "Highlighting unassigned TSOs: checking row 1/5." in details
    assert "Highlighting unassigned TSOs: checking row 5/5." in details
    assert (
        "Highlighting unassigned TSOs: finished "
        "5 rows (2 ObjectList-assigned, 1 DetailList-only, 2 unassigned)."
    ) in details
    assert "Finished refreshing 5 available TSO filter rows." in details


def test_save_track3d_warns_when_layout_does_not_match(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _app()
    tab = TSOVisibilityTab()
    tab.set_object_lists([Track3DObjectList(side="L", section=1, sub_index=0, tso_ids=[1])])

    path = tmp_path / "track.3d"
    path.write_text(
        "ObjectList_L0_0: LIST {__TSO0};\n"
        "sec0_l0: LIST { DATA { 0, 10, 20 } };\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(path), ""))
    warnings: list[tuple[str, str]] = []

    def _fake_warning(_parent, title, text, *args, **kwargs):
        warnings.append((title, text))
        return QtWidgets.QMessageBox.Ok

    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", _fake_warning)

    tab._on_save_to_track3d_requested()

    assert warnings == [
        (
            "Save ObjectLists",
            "The selected track.3D file does not perfectly match the current app ObjectList layout.\n\n"
            "Use Reconcile .3D first so every Sections / Side / SubIndex row lines up before saving.",
        )
    ]


def test_load_detail_lists_button_imports_only_tso_items_from_detail_lists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _app()
    tab = TSOVisibilityTab()

    path = tmp_path / "track.3d"
    path.write_text(
        "__TSO1: DYNAMIC 1, 2, 3, 4, EXTERN \"tree\";\n"
        "__TSO2: DYNAMIC 1, 2, 3, 4, EXTERN \"sign\";\n"
        "DetailList_4-0H: LIST { DetailO_1-0, __TSO1, DetailN_1-0, __TSO2 };\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(path), ""))

    tab.load_detail_lists_file()

    assert [entry.tso_ids for entry in tab.detail_lists] == [[1, 2]]
    assert tab.visibility_mode_combo.currentData() == "detail"
    assert tab.tso_list.item(0).data(QtCore.Qt.UserRole) == 1
    assert tab.tso_list.item(1).data(QtCore.Qt.UserRole) == 2


def test_load_detail_lists_button_warns_before_overwriting_existing_detail_lists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _app()
    tab = TSOVisibilityTab()
    tab.set_detail_lists([Track3DDetailList(section=1, sub_index=0, lod_suffix="H", tso_ids=[7])])

    path = tmp_path / "track.3d"
    path.write_text("DetailList_4-0H: LIST { __TSO1 };\n", encoding="utf-8")
    monkeypatch.setattr(QtWidgets.QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(path), ""))
    warnings: list[tuple[str, str]] = []

    def _fake_warning(_parent, title, text, *args, **kwargs):
        warnings.append((title, text))
        return QtWidgets.QMessageBox.No

    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", _fake_warning)

    tab.load_detail_lists_file()

    assert warnings == [
        ("Load DetailLists", "Loading DetailLists will overwrite the current DetailList visibility data. Continue?"),
    ]
    assert tab.detail_lists[0].tso_ids == [7]
