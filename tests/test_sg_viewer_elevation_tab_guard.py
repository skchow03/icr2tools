from __future__ import annotations

import pytest

try:
    from PyQt5 import QtWidgets
    from sg_viewer.ui.app import SGViewerWindow
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


def test_switching_away_from_elevation_tab_cancels_live_edits(qapp, monkeypatch):
    window = SGViewerWindow()
    try:
        controller = window.controller
        assert controller is not None

        calls = {"count": 0}

        def _cancel_live_edits() -> None:
            calls["count"] += 1

        monkeypatch.setattr(
            controller._elevation_panel_controller,
            "cancel_live_edits",
            _cancel_live_edits,
        )

        walls_tab_index = next(
            index
            for index in range(window.right_sidebar_tabs.count())
            if window.right_sidebar_tabs.tabText(index) == "Walls"
        )
        window.right_sidebar_tabs.setCurrentIndex(walls_tab_index)

        assert calls["count"] == 1
    finally:
        window.close()


def test_altitude_edit_is_ignored_when_elevation_tab_not_active(qapp, monkeypatch):
    window = SGViewerWindow()
    try:
        controller = window.controller
        assert controller is not None

        called = {"value": False}

        def _set_section_xsect_altitude(*_args, **_kwargs):
            called["value"] = True
            return True

        monkeypatch.setattr(controller, "_is_elevation_tab_active", lambda: False)
        monkeypatch.setattr(
            window.preview,
            "set_section_xsect_altitude",
            _set_section_xsect_altitude,
        )

        controller._apply_altitude_edit(live=True, slider_value=0)

        assert called["value"] is False
    finally:
        window.close()


def test_grade_edit_is_ignored_when_elevation_tab_not_active(qapp, monkeypatch):
    window = SGViewerWindow()
    try:
        controller = window.controller
        assert controller is not None

        called = {"value": False}

        def _set_section_xsect_grade(*_args, **_kwargs):
            called["value"] = True
            return True

        monkeypatch.setattr(controller, "_is_elevation_tab_active", lambda: False)
        monkeypatch.setattr(
            window.preview,
            "set_section_xsect_grade",
            _set_section_xsect_grade,
        )

        controller._apply_grade_edit(live=True, grade_value=0)

        assert called["value"] is False
    finally:
        window.close()



def test_xsect_table_altitude_edit_is_ignored_when_elevation_tab_not_active(qapp, monkeypatch):
    window = SGViewerWindow()
    try:
        controller = window.controller
        assert controller is not None

        called = {"value": False}
        refreshed = {"count": 0}

        def _set_section_xsect_altitude(*_args, **_kwargs):
            called["value"] = True
            return True

        monkeypatch.setattr(controller, "_is_elevation_tab_active", lambda: False)
        monkeypatch.setattr(window.preview, "set_section_xsect_altitude", _set_section_xsect_altitude)
        monkeypatch.setattr(
            controller._elevation_panel_controller,
            "refresh_xsect_elevation_table",
            lambda: refreshed.__setitem__("count", refreshed["count"] + 1),
        )

        controller._active_selection = type("Selection", (), {"index": 0})()
        window.xsect_elevation_table.setRowCount(1)
        window.xsect_elevation_table.setItem(0, 1, QtWidgets.QTableWidgetItem("123"))

        controller._elevation_panel_controller.on_xsect_table_cell_changed(0, 1)

        assert called["value"] is False
        assert refreshed["count"] == 1
    finally:
        window.close()


def test_xsect_table_grade_edit_is_ignored_when_elevation_tab_not_active(qapp, monkeypatch):
    window = SGViewerWindow()
    try:
        controller = window.controller
        assert controller is not None

        called = {"value": False}
        refreshed = {"count": 0}

        def _set_section_xsect_grade(*_args, **_kwargs):
            called["value"] = True
            return True

        monkeypatch.setattr(controller, "_is_elevation_tab_active", lambda: False)
        monkeypatch.setattr(window.preview, "set_section_xsect_grade", _set_section_xsect_grade)
        monkeypatch.setattr(
            controller._elevation_panel_controller,
            "refresh_xsect_elevation_table",
            lambda: refreshed.__setitem__("count", refreshed["count"] + 1),
        )

        controller._active_selection = type("Selection", (), {"index": 0})()
        window.xsect_elevation_table.setRowCount(1)
        window.xsect_elevation_table.setItem(0, 2, QtWidgets.QTableWidgetItem("4"))

        controller._elevation_panel_controller.on_xsect_table_cell_changed(0, 2)

        assert called["value"] is False
        assert refreshed["count"] == 1
    finally:
        window.close()
