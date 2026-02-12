import json

import pytest

try:
    from PyQt5 import QtWidgets
    from sg_viewer.ui.app import SGViewerWindow
    from sg_viewer.models.preview_fsection import PreviewFSection
    from sg_viewer.models.selection import SectionSelection
    from sg_viewer.ui.about import ABOUT_DIALOG_TITLE, about_dialog_html
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
        assert "fsect_5" in controls

        background_edit, _ = controls["background"]
        assert background_edit.text().startswith("#")

        background_edit.setText("#123456")
        background_edit.editingFinished.emit()

        assert window.preview.preview_color("background").name().upper() == "#123456"
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
