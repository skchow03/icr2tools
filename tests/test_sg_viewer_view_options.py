import json
import math
from types import SimpleNamespace

import pytest

try:
    from PyQt5 import QtCore, QtGui, QtWidgets
    from sg_viewer.ui.app import SGViewerWindow
    from sg_viewer.model.preview_fsection import PreviewFSection
    from sg_viewer.model.selection import SectionSelection
    from sg_viewer.ui.about import ABOUT_DIALOG_TITLE, about_dialog_html
    from icr2_core.trk.sg_classes import SGFile
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


def test_measurement_units_are_global(qapp):
    window = SGViewerWindow()
    try:
        window.measurement_units_combo.setCurrentIndex(1)

        assert "m" in window.xsect_elevation_table.horizontalHeaderItem(1).text()
        assert "m" in window.fsect_table.horizontalHeaderItem(1).text()
        assert "m" in window.fsect_table.horizontalHeaderItem(3).text()

        window.update_elevation_inputs(6000, 0, True)
        assert window._altitude_value_label.text() == "0.305"

        window.measurement_units_combo.setCurrentIndex(2)

        assert "in" in window.xsect_elevation_table.horizontalHeaderItem(1).text()
        assert "in" in window.fsect_table.horizontalHeaderItem(1).text()
        assert "in" in window.fsect_table.horizontalHeaderItem(3).text()

        window.update_elevation_inputs(6000, 0, True)
        assert window._altitude_value_label.text() == "12.0"

        window.measurement_units_combo.setCurrentIndex(3)

        assert "500ths" in window.xsect_elevation_table.horizontalHeaderItem(1).text()
        assert "500ths" in window.fsect_table.horizontalHeaderItem(1).text()
        assert "500ths" in window.fsect_table.horizontalHeaderItem(3).text()

        window.update_elevation_inputs(6000, 0, True)
        assert window._altitude_value_label.text() == "6000"

        window.measurement_units_combo.setCurrentIndex(0)
        assert "ft" in window.xsect_elevation_table.horizontalHeaderItem(1).text()
        assert "ft" in window.fsect_table.horizontalHeaderItem(1).text()
        assert "ft" in window.fsect_table.horizontalHeaderItem(3).text()

        window.update_elevation_inputs(6000, 0, True)
        assert window._altitude_value_label.text() == "1.0"
    finally:
        window.close()


def test_fsect_delta_columns_follow_and_edit_next_fsect(qapp):
    window = SGViewerWindow()
    try:
        window._selected_section_index = 0
        window.preview._fsects_by_section = [
            [
                PreviewFSection(start_dlat=500.0, end_dlat=1500.0, surface_type=0, type2=0),
                PreviewFSection(start_dlat=750.0, end_dlat=1800.0, surface_type=0, type2=0),
            ]
        ]

        window._update_fsect_table(0)

        assert window.fsect_table.item(0, 3).text() == "0.1"
        assert window.fsect_table.item(0, 4).text() == "0.1"
        assert window.fsect_table.item(1, 3).text() == ""
        assert window.fsect_table.item(1, 4).text() == ""

        window.fsect_table.item(0, 3).setText("0.2")
        window._on_fsect_cell_changed(0, 3)

        assert window.preview.get_section_fsects(0)[1].start_dlat == 1500.0
        assert window.fsect_table.item(0, 3).text() == "0.2"
    finally:
        window.close()


def test_selection_and_track_length_show_secondary_units(qapp):
    window = SGViewerWindow()
    try:
        selection = SectionSelection(
            index=3,
            type_name="Straight",
            start_dlong=500.0 * 5280.0,
            end_dlong=500.0 * 6000.0,
            length=500.0 * 7200.0,
            previous_id=2,
            next_id=4,
        )

        window.measurement_units_combo.setCurrentIndex(0)
        window.update_selection_sidebar(selection)
        window.update_track_length_label(
            f"Track Length: {window.format_length_with_secondary(selection.length)}"
        )

        assert window._section_start_dlong_label.text() == "Starting DLONG: 5280.0 ft"
        assert window._section_end_dlong_label.text() == "Ending DLONG: 6000.0 ft"
        assert (
            window._section_length_label.text()
            == "Section Length: 7200.0 ft (1.364 miles)"
        )
        assert window._track_stats_label.text() == "Track Length: 7200.0 ft (1.364 miles)"

        window.measurement_units_combo.setCurrentIndex(1)
        window.update_selection_sidebar(selection)
        window.update_track_length_label(
            f"Track Length: {window.format_length_with_secondary(selection.length)}"
        )

        assert window._section_start_dlong_label.text() == "Starting DLONG: 1609.344 m"
        assert window._section_end_dlong_label.text() == "Ending DLONG: 1828.800 m"
        assert (
            window._section_length_label.text()
            == "Section Length: 2194.560 m (2.195 km)"
        )
        assert window._track_stats_label.text() == "Track Length: 2194.560 m (2.195 km)"
    finally:
        window.close()


def test_elevation_labels_and_help_about(qapp, monkeypatch):
    window = SGViewerWindow()
    try:
        assert window._right_sidebar_tabs.tabText(0) == "Elevation/Grade"
        assert window.xsect_elevation_table.horizontalHeaderItem(1).text().startswith(
            "Elevation ("
        )

        menu_titles = [action.text().replace("&", "") for action in window.menuBar().actions()]
        assert "Help" in menu_titles

        about_calls: list[tuple[str, str]] = []

        def _fake_about(_parent, title, text):
            about_calls.append((title, text))

        monkeypatch.setattr(QtWidgets.QMessageBox, "about", _fake_about)

        help_menu = next(
            menu for menu in window.menuBar().findChildren(QtWidgets.QMenu) if menu.title() == "Help"
        )
        about_action = next(
            action for action in help_menu.actions() if action.text() == "About SG Viewer"
        )
        about_action.trigger()

        assert about_calls == [(ABOUT_DIALOG_TITLE, about_dialog_html())]
    finally:
        window.close()


def test_view_options_expose_color_controls(qapp):
    window = SGViewerWindow()
    try:
        controls = window.preview_color_controls
        assert "background" in controls
        assert "centerline_unselected" in controls
        assert "centerline_selected" in controls
        assert "centerline_long_curve" in controls
        assert "nodes_connected" in controls
        assert "nodes_disconnected" in controls
        assert "radii_unselected" in controls
        assert "radii_selected" in controls
        assert "xsect_dlat_line" in controls
        assert "fsect_5" in controls

        background_edit, _ = controls["background"]
        assert background_edit.text().startswith("#")

        background_edit.setText("#123456")
        background_edit.editingFinished.emit()

        assert window.preview.preview_color("background").name().upper() == "#123456"

        xsect_edit, _ = controls["xsect_dlat_line"]
        xsect_edit.setText("#00AA11")
        xsect_edit.editingFinished.emit()

        assert window.preview.preview_color("xsect_dlat_line").name().upper() == "#00AA11"
    finally:
        window.close()


def test_tools_menu_exposes_background_calibrator(qapp, monkeypatch):
    window = SGViewerWindow()
    try:
        popen_calls: list[list[str]] = []

        class _DummyPopen:
            def __init__(self, args):
                popen_calls.append(args)

        monkeypatch.setattr("sg_viewer.ui.viewer_controller.subprocess.Popen", _DummyPopen)

        tools_menu = next(
            menu for menu in window.menuBar().findChildren(QtWidgets.QMenu) if menu.title() == "Tools"
        )
        calibrator_action = next(
            action for action in tools_menu.actions() if action.text() == "Open Background Calibrator"
        )

        calibrator_action.trigger()

        assert len(popen_calls) == 1
        assert popen_calls[0][0]
        assert popen_calls[0][1].endswith("bg_calibrator_minimal.py")
        assert len(popen_calls[0]) == 2
    finally:
        window.close()


def test_mrk_tab_enables_sg_fsects_and_mrk_notches(qapp):
    window = SGViewerWindow()
    try:
        assert window.preview.show_mrk_notches is False

        mrk_index = next(
            index
            for index in range(window.right_sidebar_tabs.count())
            if window.right_sidebar_tabs.tabText(index) == "MRK"
        )
        window.right_sidebar_tabs.setCurrentIndex(mrk_index)

        assert window.sg_fsects_checkbox.isChecked() is True
        assert window.preview.show_mrk_notches is True

        window.right_sidebar_tabs.setCurrentIndex(0)
        assert window.preview.show_mrk_notches is False
    finally:
        window.close()

def test_mrk_select_wall_highlights_full_entry_when_no_table_rows(qapp):
    window = SGViewerWindow()
    try:
        window.mrk_boundary_spin.setValue(2)
        window.mrk_track_section_spin.setValue(7)
        window.mrk_wall_index_spin.setValue(3)
        window.mrk_entry_count_spin.setValue(4)

        window.mrk_select_button.click()

        assert window.preview.highlighted_mrk_walls == ((2, 7, 3, 4),)
    finally:
        window.close()


def test_mrk_table_selection_restores_wall_count_spin(qapp):
    window = SGViewerWindow()
    try:
        table = window.mrk_entries_table
        table.setRowCount(1)
        values = [11, 5, 2, 6]
        for column, value in enumerate(values):
            table.setItem(0, column, QtWidgets.QTableWidgetItem(str(value)))

        table.selectRow(0)

        assert window.mrk_track_section_spin.value() == 11
        assert window.mrk_boundary_spin.value() == 5
        assert window.mrk_wall_index_spin.value() == 2
        assert window.mrk_entry_count_spin.value() == 6
    finally:
        window.close()


def test_mrk_add_entry_populates_repeating_texture_pattern(qapp):
    window = SGViewerWindow()
    try:
        from sg_viewer.ui.mrk_textures_dialog import MrkTextureDefinition

        window.controller._mrk_texture_definitions = (
            MrkTextureDefinition("brick01", "brick01", 0, 0, 63, 63, "#FF0000"),
            MrkTextureDefinition("stripe02", "stripe02", 8, 8, 56, 56, "#00FF00"),
        )
        window.mrk_track_section_spin.setValue(1)
        window.mrk_boundary_spin.setValue(2)
        window.mrk_wall_index_spin.setValue(3)
        window.mrk_entry_count_spin.setValue(5)

        window.mrk_add_entry_button.click()

        assert window.mrk_entries_table.item(0, 4).text() == "brick01,stripe02,brick01,stripe02,brick01"
    finally:
        window.close()



def test_mrk_highlights_repeat_texture_pattern_when_shorter_than_wall_count(qapp):
    window = SGViewerWindow()
    try:
        from sg_viewer.ui.mrk_textures_dialog import MrkTextureDefinition

        window.controller._mrk_texture_definitions = (
            MrkTextureDefinition("brick01", "brick01", 0, 0, 63, 63, "#FF0000"),
            MrkTextureDefinition("stripe02", "stripe02", 8, 8, 56, 56, "#00FF00"),
        )
        table = window.mrk_entries_table
        table.setRowCount(1)
        values = [1, 2, 3, 5]
        for column, value in enumerate(values):
            table.setItem(0, column, QtWidgets.QTableWidgetItem(str(value)))
        table.setItem(0, 4, QtWidgets.QTableWidgetItem("brick01,stripe02"))

        window.controller._update_mrk_highlights_from_table()

        assert window.preview.highlighted_mrk_walls == (
            (2, 1, 3, 1, "#FF0000"),
            (2, 1, 4, 1, "#00FF00"),
            (2, 1, 5, 1, "#FF0000"),
            (2, 1, 6, 1, "#00FF00"),
            (2, 1, 7, 1, "#FF0000"),
        )
    finally:
        window.close()


def test_mrk_textures_button_saves_texture_definitions(qapp, monkeypatch):
    window = SGViewerWindow()
    try:
        from sg_viewer.ui.mrk_textures_dialog import MrkTextureDefinition

        class _FakeDialog:
            Accepted = QtWidgets.QDialog.Accepted

            def __init__(self, _parent, _definitions):
                pass

            def exec_(self):
                return QtWidgets.QDialog.Accepted

            def texture_definitions(self):
                return (MrkTextureDefinition("stone03", "stone03", 1, 2, 3, 4),)

        monkeypatch.setattr("sg_viewer.ui.viewer_controller.MrkTexturesDialog", _FakeDialog)

        window.mrk_textures_button.click()

        assert window.controller._mrk_texture_definitions == (
            MrkTextureDefinition("stone03", "stone03", 1, 2, 3, 4),
        )
    finally:
        window.close()




def test_mrk_patterns_use_texture_names_not_mip_names(qapp):
    window = SGViewerWindow()
    try:
        from sg_viewer.ui.mrk_textures_dialog import MrkTextureDefinition

        window.controller._mrk_texture_definitions = (
            MrkTextureDefinition("brick_red", "walls01", 0, 0, 63, 63, "#FF0000"),
            MrkTextureDefinition("brick_blue", "walls01", 8, 8, 56, 56, "#0000FF"),
        )

        assert window.controller._default_texture_pattern_for_wall_count(3) == "brick_red,brick_blue,brick_red"
    finally:
        window.close()


def test_mrk_save_and_load_json_round_trip(qapp, tmp_path, monkeypatch):
    window = SGViewerWindow()
    try:
        from sg_viewer.ui.mrk_textures_dialog import MrkTextureDefinition

        json_path = tmp_path / "mrk_state.json"
        window.controller._mrk_texture_definitions = (
            MrkTextureDefinition("brick_red", "walls01", 0, 0, 63, 63, "#FF0000"),
        )
        table = window.mrk_entries_table
        table.setRowCount(1)
        table.setItem(0, 0, QtWidgets.QTableWidgetItem("10"))
        table.setItem(0, 1, QtWidgets.QTableWidgetItem("2"))
        table.setItem(0, 2, QtWidgets.QTableWidgetItem("5"))
        table.setItem(0, 3, QtWidgets.QTableWidgetItem("2"))
        table.setItem(0, 4, QtWidgets.QTableWidgetItem("brick_red"))

        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getSaveFileName",
            lambda *args, **kwargs: (str(json_path), "JSON Files (*.json)"),
        )
        window.controller._on_mrk_save_requested()

        payload = json.loads(json_path.read_text(encoding="utf-8"))
        assert payload["texture_definitions"][0]["texture_name"] == "brick_red"
        assert payload["texture_definitions"][0]["mip_filename"] == "walls01"

        table.setRowCount(0)
        window.controller._mrk_texture_definitions = ()

        monkeypatch.setattr(
            QtWidgets.QFileDialog,
            "getOpenFileName",
            lambda *args, **kwargs: (str(json_path), "JSON Files (*.json)"),
        )
        window.controller._on_mrk_load_requested()

        assert window.controller._mrk_texture_definitions == (
            MrkTextureDefinition("brick_red", "walls01", 0, 0, 63, 63, "#FF0000"),
        )
        assert window.mrk_entries_table.item(0, 4).text() == "brick_red"
    finally:
        window.close()

def test_mrk_divisions_follow_polyline_arc_length():
    from sg_viewer.services.preview_painter import _division_points_for_polyline

    radius = 24000.0
    total_angle = math.pi / 2
    points = [
        (radius * math.cos(total_angle * step / 32), radius * math.sin(total_angle * step / 32))
        for step in range(33)
    ]

    divisions = _division_points_for_polyline(points, target_length=14.0 * 6000.0)

    total_length = (math.pi / 2) * radius
    expected_segments = round(total_length / (14.0 * 6000.0))
    assert len(divisions) == max(0, expected_segments - 1)
    if divisions:
        spacing = total_length / expected_segments
        assert divisions[0] == pytest.approx(spacing, rel=0.03)


def test_mrk_highlight_lookup_accepts_one_based_section_boundary_ids():
    from sg_viewer.services.preview_painter import _resolve_mrk_highlight_indices

    one_based_lookup = {
        (2, 3): {
            4: "#FF00FF",
        }
    }

    resolved = _resolve_mrk_highlight_indices(
        one_based_lookup,
        section_index=1,
        boundary_index=2,
    )

    assert resolved == {4: "#FF00FF"}


def test_mrk_highlight_lookup_merges_zero_based_and_one_based_matches():
    from sg_viewer.services.preview_painter import _resolve_mrk_highlight_indices

    lookup = {
        (1, 2): {3: "#00FF00"},
        (2, 3): {4: "#FF0000"},
    }

    resolved = _resolve_mrk_highlight_indices(
        lookup,
        section_index=1,
        boundary_index=2,
    )

    assert resolved == {3: "#00FF00", 4: "#FF0000"}


def test_paint_preview_passes_mrk_highlight_walls_to_renderer(monkeypatch):
    from sg_viewer.services import preview_painter

    captured: dict[str, object] = {}

    def _fake_render_sg_preview(*args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(preview_painter, "render_sg_preview", _fake_render_sg_preview)

    image = QtGui.QImage(8, 8, QtGui.QImage.Format_ARGB32)
    painter = QtGui.QPainter(image)
    try:
        preview_painter.paint_preview(
            painter,
            preview_painter.BasePreviewState(
                rect=QtCore.QRect(0, 0, 8, 8),
                background_color=QtGui.QColor("black"),
                background_image=None,
                background_brightness=0,
                background_scale_500ths_per_px=None,
                background_origin=None,
                track_opacity=1.0,
                sampled_centerline=[(0.0, 0.0), (1.0, 0.0)],
                selected_section_points=(),
                section_endpoints=(),
                selected_section_index=None,
                show_curve_markers=False,
                show_axes=False,
                sections=(),
                selected_curve_index=None,
                start_finish_mapping=None,
                status_message="",
                split_section_mode=False,
                split_hover_point=None,
                xsect_dlat=None,
                show_xsect_dlat_line=False,
                centerline_unselected_color=QtGui.QColor("white"),
                centerline_selected_color=QtGui.QColor("white"),
                centerline_long_curve_color=QtGui.QColor("white"),
                radii_unselected_color=QtGui.QColor("white"),
                radii_selected_color=QtGui.QColor("white"),
                xsect_dlat_line_color=QtGui.QColor("white"),
                integrity_boundary_violation_points=(),
            ),
            preview_painter.CreationOverlayState(),
            node_state=None,
            drag_heading_state=None,
            sg_preview_state=preview_painter.SgPreviewState(
                model=SimpleNamespace(fsects=[]),
                transform=SimpleNamespace(world_to_view=lambda x, y, h: (x, y)),
                view_state=SimpleNamespace(show_surfaces=False, show_boundaries=False),
                enabled=True,
                show_mrk_notches=True,
                selected_mrk_wall=(0, 0, 0),
                highlighted_mrk_walls=((1, 2, 3, 1, "#ff00ff"),),
            ),
            transform=SimpleNamespace(world_to_view=lambda x, y, h: (x, y)),
            widget_height=8,
        )
    finally:
        painter.end()

    assert captured["highlighted_mrk_walls"] == ((1, 2, 3, 1, "#ff00ff"),)


def test_background_calibrator_receives_loaded_background_image_path(qapp, monkeypatch, tmp_path):
    window = SGViewerWindow()
    try:
        popen_calls: list[list[str]] = []

        class _DummyPopen:
            def __init__(self, args):
                popen_calls.append(args)

        monkeypatch.setattr("sg_viewer.ui.viewer_controller.subprocess.Popen", _DummyPopen)

        image_path = tmp_path / "background.png"
        image_path.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR"
            b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
            b"\x90wS\xde"
            b"\x00\x00\x00\x0cIDATx\x9cc``\x00\x00\x00\x04\x00\x01"
            b"\x0b\xe7\x02\x9d"
            b"\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        window.preview.load_background_image(image_path)

        tools_menu = next(
            menu for menu in window.menuBar().findChildren(QtWidgets.QMenu) if menu.title() == "Tools"
        )
        calibrator_action = next(
            action for action in tools_menu.actions() if action.text() == "Open Background Calibrator"
        )

        calibrator_action.trigger()

        assert len(popen_calls) == 1
        assert popen_calls[0][0]
        assert popen_calls[0][1].endswith("bg_calibrator_minimal.py")
        assert popen_calls[0][2] == str(image_path)
    finally:
        window.close()


def test_calibrator_receiver_loads_background_from_payload(qapp, monkeypatch, tmp_path):
    window = SGViewerWindow()
    try:
        image_path = tmp_path / "sent_background.png"
        image_path.write_bytes(b"placeholder")

        payload = {
            "units_per_pixel": 123.0,
            "upper_left": [10.0, 20.0],
            "image_path": str(image_path),
        }

        class _FakeSocket:
            def __init__(self, data):
                self._data = data

            def waitForReadyRead(self, _timeout):
                return True

            def readAll(self):
                return self._data

            def disconnectFromServer(self):
                return None

        class _FakeServer:
            def __init__(self, socket):
                self._socket = socket
                self._used = False

            def hasPendingConnections(self):
                return not self._used

            def nextPendingConnection(self):
                if self._used:
                    return None
                self._used = True
                return self._socket

        load_calls = []
        settings_calls = []

        def _load_background(path):
            load_calls.append(path)

        def _set_settings(scale, origin):
            settings_calls.append((scale, origin))

        monkeypatch.setattr(window.preview, "load_background_image", _load_background)
        monkeypatch.setattr(window.preview, "set_background_settings", _set_settings)
        monkeypatch.setattr(window.preview, "has_background_image", lambda: True)
        monkeypatch.setattr(window.controller, "_persist_background_state", lambda: None)
        monkeypatch.setattr(window, "show_status_message", lambda _msg: None)
        window.controller._calibrator_server = _FakeServer(
            _FakeSocket(json.dumps(payload).encode("utf-8"))
        )

        window.controller._on_calibrator_values_received()

        assert load_calls == [image_path]
        assert settings_calls == [(123.0, (10.0, 20.0))]
    finally:
        window.close()


def test_file_menu_exposes_save_action(qapp):
    window = SGViewerWindow()
    try:
        file_menu = next(
            menu for menu in window.menuBar().findChildren(QtWidgets.QMenu) if menu.title() == "&File"
        )
        save_action = next(
            action for action in file_menu.actions() if action.text() == "Save"
        )

        assert save_action.shortcut().toString() == "Ctrl+S"
    finally:
        window.close()


def test_save_action_saves_to_current_path(qapp, monkeypatch, tmp_path):
    window = SGViewerWindow()
    try:
        controller = window.controller
        target_path = tmp_path / "loaded.sg"
        controller._current_path = target_path
        controller._save_current_action.setEnabled(True)

        saved_paths = []

        def _fake_save(path):
            saved_paths.append(path)

        monkeypatch.setattr(window.preview, "save_sg", _fake_save)
        controller._document_controller.set_export_csv_on_save(False)

        controller._save_current_action.trigger()

        assert saved_paths == [target_path]
    finally:
        window.close()


def test_adjusted_dlong_labels_auto_update_without_toggle(qapp):
    window = SGViewerWindow()
    try:
        num_xsects = 2
        data = [0] * (58 + 2 * num_xsects)
        section = SGFile.Section(data, num_xsects)
        section.length = 1000
        section.alt = [0, 100]
        section.grade = [0, 0]
        sgfile = SGFile([0, 0, 0, 0, 1, num_xsects], 1, num_xsects, [-100, 100], [section])
        window.preview._sgfile = sgfile

        selection = SectionSelection(
            index=0,
            type_name="Straight",
            start_dlong=0,
            end_dlong=1000,
            length=1000,
            previous_id=-1,
            next_id=-1,
        )

        window.update_selection_sidebar(selection)
        assert window._adjusted_section_start_dlong_label.text() == "Adjusted Starting DLONG: 0.0 ft"
        assert window._adjusted_section_end_dlong_label.text() == "Adjusted Ending DLONG: 1001.2 ft"
        assert (
            window._adjusted_section_length_label.text()
            == "Adjusted Section Length: 1001.2 ft (0.190 miles)"
        )
    finally:
        window.close()


def test_file_menu_exposes_export_csv_on_save_toggle(qapp):
    window = SGViewerWindow()
    try:
        file_menu = next(
            menu for menu in window.menuBar().findChildren(QtWidgets.QMenu) if menu.title() == "&File"
        )
        export_action = next(
            action for action in file_menu.actions() if action.text() == "Export CSVs on Save"
        )

        assert export_action.isCheckable()
        assert export_action.isChecked()
    finally:
        window.close()


def test_export_csv_on_save_toggle_controls_csv_export(qapp, monkeypatch, tmp_path):
    window = SGViewerWindow()
    try:
        controller = window.controller
        target_path = tmp_path / "loaded.sg"

        save_calls = []
        csv_calls = []

        monkeypatch.setattr(window.preview, "save_sg", lambda path: save_calls.append(path))
        monkeypatch.setattr(
            controller._document_controller,
            "convert_sg_to_csv",
            lambda path: csv_calls.append(path),
        )

        controller._document_controller.save_to_path(target_path)
        controller._export_csv_on_save_action.setChecked(False)
        controller._document_controller.save_to_path(target_path)

        assert save_calls == [target_path, target_path]
        assert csv_calls == [target_path]
    finally:
        window.close()


def test_export_sg_to_trk_is_in_file_menu_not_tools_menu(qapp):
    window = SGViewerWindow()
    try:
        file_menu = next(
            menu for menu in window.menuBar().findChildren(QtWidgets.QMenu) if menu.title() == "&File"
        )
        tools_menu = next(
            menu for menu in window.menuBar().findChildren(QtWidgets.QMenu) if menu.title() == "Tools"
        )

        file_labels = [action.text() for action in file_menu.actions()]
        tools_labels = [action.text() for action in tools_menu.actions()]

        assert "Export SG to TRK…" in file_labels
        assert "Export SG to TRK…" not in tools_labels
    finally:
        window.close()
