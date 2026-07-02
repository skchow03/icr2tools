from __future__ import annotations

import pytest

try:
    from PyQt5 import QtCore, QtGui, QtWidgets
    from sg_viewer.services.preview_painter import _draw_land_object_polygons_overlay
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


def test_land_polygon_wall_mode_draws_two_point_segment(qapp):
    image = QtGui.QImage(32, 32, QtGui.QImage.Format_ARGB32)
    image.fill(QtCore.Qt.transparent)
    painter = QtGui.QPainter(image)
    try:
        _draw_land_object_polygons_overlay(
            painter=painter,
            points=((2.0, 2.0), (28.0, 2.0)),
            polygons=(((0, 1), 255, True),),
            palette=(),
            transform=(1.0, (0.0, 0.0)),
            widget_height=32,
        )
    finally:
        painter.end()

    opaque_pixels = 0
    for y in range(image.height()):
        for x in range(image.width()):
            if QtGui.QColor(image.pixel(x, y)).alpha() > 0:
                opaque_pixels += 1
    assert opaque_pixels > 0

def test_land_polygon_export_applies_height_to_land_mode_vertices(qapp):
    window = SGViewerWindow()
    try:
        points, polygons, error = window._parse_land_object_export_data(
            {
                "points": [("0", "0", "1"), ("10", "0", "2"), ("0", "10", "3")],
                "polygons": [("0,1,2", "7", "Land", "5")],
            }
        )
        assert error is None
        assert polygons == [((3, 4, 5), 7)]
        assert points[3:] == [(0.0, 0.0, 6.0), (10.0, 0.0, 7.0), (0.0, 10.0, 8.0)]
    finally:
        window.close()


def test_paint_preview_draws_land_objects_before_tsos(qapp, monkeypatch):
    from sg_viewer.services import preview_painter

    calls = []

    def record(name):
        def _inner(*args, **kwargs):
            calls.append(name)
        return _inner

    for name in (
        "_draw_background",
        "_draw_axes",
        "render_sg_preview",
        "_draw_tsd_lines",
        "_draw_centerlines",
        "_draw_start_finish_line",
        "_draw_creation_overlays",
        "_draw_drag_heading_guide",
        "_draw_nodes",
        "_draw_center_crosshair",
        "_draw_query_track_overlay",
        "_draw_status_overlay",
    ):
        monkeypatch.setattr(preview_painter, name, record(name))
    monkeypatch.setattr(
        preview_painter, "_draw_land_object_polygons_overlay", record("land_polygons")
    )
    monkeypatch.setattr(
        preview_painter, "_draw_land_object_points_overlay", record("land_points")
    )
    monkeypatch.setattr(preview_painter, "_draw_trackside_objects", record("tsos"))

    image = QtGui.QImage(16, 16, QtGui.QImage.Format_ARGB32)
    painter = QtGui.QPainter(image)
    try:
        preview_painter.paint_preview(
            painter,
            preview_painter.BasePreviewState(
                rect=QtCore.QRect(0, 0, 16, 16),
                background_color=QtGui.QColor("black"),
                background_image=None,
                background_brightness=1.0,
                background_scale_500ths_per_px=None,
                background_origin=None,
                track_opacity=1.0,
                sampled_centerline=[(0.0, 0.0)],
                selected_section_points=[],
                section_endpoints=[],
                selected_section_index=None,
                show_curve_markers=False,
                show_axes=False,
                show_crosshair=False,
                sections=[],
                selected_curve_index=None,
                start_finish_mapping=None,
                status_message="",
                split_section_mode=False,
                split_hover_point=None,
                query_track_hover_point=None,
                query_track_overlay_message="",
                ruler_start_point=None,
                ruler_end_point=None,
                ruler_label="",
                land_object_points=((1.0, 1.0), (2.0, 1.0), (1.0, 2.0)),
                land_object_polygons=(((0, 1, 2), 1, False),),
                xsect_dlat=None,
                show_xsect_dlat_line=False,
                centerline_unselected_color=QtGui.QColor("white"),
                centerline_selected_color=QtGui.QColor("yellow"),
                centerline_long_curve_color=QtGui.QColor("red"),
                radii_unselected_color=QtGui.QColor("gray"),
                radii_selected_color=QtGui.QColor("magenta"),
                xsect_dlat_line_color=QtGui.QColor("green"),
                integrity_boundary_violation_points=(),
            ),
            preview_painter.CreationOverlayState(
                False, None, None, False, None, None, None
            ),
            None,
            None,
            preview_painter.SgPreviewState(
                model=None,
                transform=None,
                view_state=None,
                enabled=False,
                trackside_objects=(object(),),
            ),
            (1.0, (0.0, 0.0)),
            16,
        )
    finally:
        painter.end()

    assert calls.index("land_polygons") < calls.index("tsos")
    assert calls.index("land_points") < calls.index("tsos")
