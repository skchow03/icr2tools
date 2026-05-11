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
