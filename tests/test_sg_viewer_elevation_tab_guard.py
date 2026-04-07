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
        window.xsect_elevation_table.setItem(0, 2, QtWidgets.QTableWidgetItem("123"))

        controller._elevation_panel_controller.on_xsect_table_cell_changed(0, 2)

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
        window.xsect_elevation_table.setItem(0, 3, QtWidgets.QTableWidgetItem("4"))

        controller._elevation_panel_controller.on_xsect_table_cell_changed(0, 3)

        assert called["value"] is False
        assert refreshed["count"] == 1
    finally:
        window.close()


def test_xsect_table_dlat_edit_updates_xsect_definitions(qapp, monkeypatch):
    window = SGViewerWindow()
    try:
        controller = window.controller
        assert controller is not None

        called_payload: list[list[tuple[int, float]]] = []
        synced = {"count": 0}

        monkeypatch.setattr(controller, "_is_elevation_tab_active", lambda: True)
        monkeypatch.setattr(window.preview, "get_xsect_metadata", lambda: [(0, -100.0), (1, 100.0)])

        def _set_xsect_definitions(payload):
            called_payload.append(payload)
            return True

        monkeypatch.setattr(window.preview, "set_xsect_definitions", _set_xsect_definitions)
        monkeypatch.setattr(
            controller,
            "_sync_after_xsect_value_change",
            lambda: synced.__setitem__("count", synced["count"] + 1),
        )

        controller._active_selection = type("Selection", (), {"index": 0})()
        window.xsect_elevation_table.setRowCount(2)
        window.xsect_elevation_table.setItem(1, 1, QtWidgets.QTableWidgetItem("3.0"))

        controller._elevation_panel_controller.on_xsect_table_cell_changed(1, 1)

        assert called_payload == [[(0, -100.0), (1, 1500.0)]]
        assert synced["count"] == 1
    finally:
        window.close()


def test_xsect_table_selection_updates_active_xsect(qapp):
    window = SGViewerWindow()
    try:
        controller = window.controller
        assert controller is not None
        assert window.xsect_combo.currentData() == 0

        window.xsect_elevation_table.setRowCount(2)
        window.xsect_elevation_table.setItem(0, 0, QtWidgets.QTableWidgetItem("0"))
        window.xsect_elevation_table.setItem(1, 0, QtWidgets.QTableWidgetItem("1"))
        window.xsect_elevation_table.setCurrentCell(1, 0)

        controller._on_xsect_table_selection_changed()

        assert window.xsect_combo.currentData() == 1
    finally:
        window.close()


def test_xsect_table_selection_ignores_programmatic_table_refresh(qapp, monkeypatch):
    window = SGViewerWindow()
    try:
        controller = window.controller
        assert controller is not None
        window.xsect_combo.setCurrentIndex(0)

        called = {"value": False}

        def _on_xsect_node_clicked(_xsect_index: int) -> None:
            called["value"] = True

        monkeypatch.setattr(controller, "_on_xsect_node_clicked", _on_xsect_node_clicked)
        window._updating_xsect_table = True
        window.xsect_elevation_table.setRowCount(2)
        window.xsect_elevation_table.setItem(0, 0, QtWidgets.QTableWidgetItem("0"))
        window.xsect_elevation_table.setItem(1, 0, QtWidgets.QTableWidgetItem("1"))
        window.xsect_elevation_table.setCurrentCell(1, 0)

        controller._on_xsect_table_selection_changed()

        assert called["value"] is False
    finally:
        window._updating_xsect_table = False
        window.close()
