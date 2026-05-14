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


def test_land_point_and_polygon_buttons_require_object_selection(qapp):
    window = SGViewerWindow()
    try:
        window.load_land_objects([])
        assert window._land_add_point_button.isEnabled() is False
        assert window._land_edit_point_button.isEnabled() is False
        assert window._land_add_polygon_button.isEnabled() is False
        assert window._land_delete_polygon_button.isEnabled() is False

        window.load_land_objects([{"name": "Object 1", "points": [], "polygons": []}])
        assert window._land_add_point_button.isEnabled() is True
        assert window._land_edit_point_button.isEnabled() is True
        assert window._land_add_polygon_button.isEnabled() is True
        assert window._land_delete_polygon_button.isEnabled() is True

        window._land_objects_table.clearSelection()
        window._load_selected_land_object()
        assert window._land_add_point_button.isEnabled() is False
        assert window._land_edit_point_button.isEnabled() is False
        assert window._land_add_polygon_button.isEnabled() is False
        assert window._land_delete_polygon_button.isEnabled() is False
    finally:
        window.close()


def test_draw_land_objects_tab_detection_is_widget_based(qapp):
    window = SGViewerWindow()
    try:
        tab_index = window._right_sidebar_tabs.indexOf(window._land_objects_sidebar)
        assert tab_index >= 0
        window._right_sidebar_tabs.setCurrentIndex(tab_index)
        window._right_sidebar_tabs.setTabText(tab_index, "Draw land Objects")
        assert window._draw_land_objects_tab_active() is True
    finally:
        window.close()


def test_land_object_rename_updates_list_and_save_does_not_duplicate(qapp):
    window = SGViewerWindow()
    try:
        window.load_land_objects([{"name": "Object 1", "points": [], "polygons": []}])
        window._land_object_name_edit.setText("Tree Line")
        assert window._land_objects_table.item(0, 0).text() == "Tree Line"

        window._save_current_land_object()
        serialized = window.serialize_land_objects()
        assert len(serialized) == 1
        assert serialized[0]["name"] == "Tree Line"
    finally:
        window.close()


def test_land_object_export_default_file_name_uses_underscores(qapp, monkeypatch):
    window = SGViewerWindow()
    try:
        window.load_land_objects([
            {
                "name": "My Object",
                "points": [("0", "0", "0"), ("1", "0", "0"), ("0", "1", "0")],
                "polygons": [("0,1,2", "0")],
            }
        ])
        captured = {}

        def _fake_get_save_file_name(*args, **kwargs):
            captured["default_path"] = args[2]
            return ("", "")

        monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", _fake_get_save_file_name)
        window._export_selected_land_object_to_3d()
        assert captured["default_path"] == "My_Object.3D"
    finally:
        window.close()


def test_land_polygon_move_up_down_reorders_rows(qapp):
    window = SGViewerWindow()
    try:
        window.load_land_objects([
            {
                "name": "Object 1",
                "points": [("0", "0", "0"), ("1", "0", "0"), ("0", "1", "0")],
                "polygons": [("0,1,2", "1"), ("0,2,1", "2")],
            }
        ])
        window._land_polygons_table.selectRow(1)
        window._move_selected_land_polygon_row(-1)
        assert window._land_polygons_table.item(0, 0).text() == "0,2,1"

        window._land_polygons_table.selectRow(0)
        window._move_selected_land_polygon_row(1)
        assert window._land_polygons_table.item(1, 0).text() == "0,2,1"
    finally:
        window.close()


def test_land_polygon_mode_is_combo_and_wall_mode_persists(qapp):
    window = SGViewerWindow()
    try:
        window.load_land_objects([{"name": "Object 1", "points": [], "polygons": []}])
        window._add_land_polygon_row()
        mode_widget = window._land_polygons_table.cellWidget(0, 2)
        assert isinstance(mode_widget, QtWidgets.QComboBox)
        assert mode_widget.count() == 2
        assert mode_widget.itemText(0) == "Land"
        assert mode_widget.itemText(1) == "Wall"
        mode_widget.setCurrentText("Wall")
        serialized = window.serialize_land_objects()
        assert serialized[0]["polygons"][0][2] == "Wall"
    finally:
        window.close()


def test_land_polygon_wall_mode_allows_two_points_but_land_needs_three(qapp):
    window = SGViewerWindow()
    try:
        window.load_land_objects([
            {
                "name": "Object 1",
                "points": [("0", "0", "0"), ("1", "0", "0"), ("0", "1", "0")],
                "polygons": [],
            }
        ])
        window._add_land_polygon_row()
        window._land_polygons_table.item(0, 0).setText("0,1")
        mode_widget = window._land_polygons_table.cellWidget(0, 2)
        mode_widget.setCurrentText("Wall")
        assert len(window._preview.land_object_polygons_overlay) == 1
        mode_widget.setCurrentText("Land")
        assert len(window._preview.land_object_polygons_overlay) == 0
    finally:
        window.close()


def test_land_object_name_table_edit_updates_editor_and_persists(qapp):
    window = SGViewerWindow()
    try:
        window.load_land_objects([{"name": "Object 1", "points": [], "polygons": []}])
        window._land_objects_table.item(0, 0).setText("Renamed")
        assert window._land_object_name_edit.text() == "Renamed"
        assert window.serialize_land_objects()[0]["name"] == "Renamed"
    finally:
        window.close()
