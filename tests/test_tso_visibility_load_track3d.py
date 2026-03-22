from pathlib import Path

import pytest

pytest.importorskip("PyQt5")

from PyQt5 import QtWidgets

from sg_viewer.io.track3d_parser import Track3DObjectList
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
