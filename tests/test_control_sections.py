import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from types import SimpleNamespace

import pytest

try:  # pragma: no cover - allows tests to be skipped in headless CI without PyQt5
    from PyQt5 import QtWidgets, QtTest, QtCore
    from icr2timing.ui.control_sections import (
        OverlayControlsSection,
        RadarSettingsSection,
        TelemetryControlsSection,
    )
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)


@pytest.fixture(scope="module")
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    yield app


def test_overlay_controls_signal_emission(qapp):
    btn_toggle = QtWidgets.QPushButton()
    btn_reset = QtWidgets.QPushButton()
    btn_quit = QtWidgets.QPushButton()
    btn_radar = QtWidgets.QPushButton()
    btn_track = QtWidgets.QPushButton()
    btn_surface = QtWidgets.QPushButton()

    section = OverlayControlsSection(
        btn_toggle_overlay=btn_toggle,
        btn_reset=btn_reset,
        btn_quit=btn_quit,
        btn_radar=btn_radar,
        btn_track_map=btn_track,
        btn_surface_overlay=btn_surface,
    )

    toggle_spy = QtTest.QSignalSpy(section.toggle_overlay_requested)
    btn_toggle.click()
    assert toggle_spy.count() == 1

    section.set_overlay_visible(True)
    assert btn_toggle.text() == "Hide Overlay"
    section.set_overlay_visible(False)
    assert btn_toggle.text() == "Show Overlay"


def test_radar_settings_updates_overlay(qapp):
    class DummyOverlay:
        def __init__(self):
            self.size = None
            self.range = {}
            self.symbol = None

        def set_size(self, w, h):
            self.size = (w, h)

        def set_range(self, forward=None, rear=None, side=None):
            self.range = {"forward": forward, "rear": rear, "side": side}

        def set_symbol(self, symbol):
            self.symbol = symbol

        def set_show_speeds(self, enabled):
            self.show_speeds = enabled

        def set_colors(self, **colors):
            self.colors = colors

        def move(self, *_):
            pass

        def resize(self, *_):
            pass

    class DummyConfig:
        radar_width = 200
        radar_height = 150
        radar_range_forward = 2
        radar_range_rear = 1
        radar_range_side = 3
        radar_symbol = "rectangle"
        radar_player_color = "1,2,3,4"
        radar_ai_ahead_color = "2,3,4,5"
        radar_ai_behind_color = "3,4,5,6"
        radar_ai_alongside_color = "4,5,6,7"

    class DummyStore(QtCore.QObject):
        overlay_setting_changed = QtCore.pyqtSignal(str)

        def __init__(self, config):
            super().__init__()
            self.config = config

    overlay = DummyOverlay()
    store = DummyStore(DummyConfig())

    spin_width = QtWidgets.QSpinBox()
    spin_height = QtWidgets.QSpinBox()
    spin_forward = QtWidgets.QSpinBox()
    spin_rear = QtWidgets.QSpinBox()
    spin_side = QtWidgets.QSpinBox()

    section = RadarSettingsSection(
        overlay=overlay,
        config_store=store,
        parent=QtWidgets.QWidget(),
        spin_width=spin_width,
        spin_height=spin_height,
        spin_forward=spin_forward,
        spin_rear=spin_rear,
        spin_side=spin_side,
        combo_symbol=QtWidgets.QComboBox(),
        btn_player_color=QtWidgets.QPushButton(),
        btn_ahead_color=QtWidgets.QPushButton(),
        btn_behind_color=QtWidgets.QPushButton(),
        btn_along_color=QtWidgets.QPushButton(),
        color_button_setter=lambda *_: None,
    )

    spin_width.setValue(250)
    assert overlay.size == (250, spin_height.value())

    spin_forward.setValue(5)
    assert overlay.range["forward"] == 5

    store.overlay_setting_changed.emit("radar")
    # ensure sync refreshes spin boxes
    assert spin_width.value() == store.config.radar_width


def test_telemetry_controls_updates_and_signals(qapp):
    btn_lap = QtWidgets.QPushButton()
    btn_release = QtWidgets.QPushButton()
    btn_force = QtWidgets.QPushButton()
    btn_toggle = QtWidgets.QPushButton()
    combo = QtWidgets.QComboBox()

    section = TelemetryControlsSection(
        btn_lap_logger=btn_lap,
        btn_release_all=btn_release,
        btn_force_pits=btn_force,
        btn_toggle_individual=btn_toggle,
        select_individual_car=combo,
    )

    spy = QtTest.QSignalSpy(section.lap_logger_toggle_requested)
    btn_lap.click()
    assert spy.count() == 1

    driver = SimpleNamespace(car_number=7, name="Tester")
    state = SimpleNamespace(drivers={3: driver})
    section.update_car_list(state)
    combo.setCurrentIndex(0)
    car_spy = QtTest.QSignalSpy(section.individual_car_selected)
    combo.setCurrentIndex(0)
    assert car_spy.count() == 1
    assert car_spy[0][0] == 3

    section.set_individual_overlay_visible(True)
    assert "Hide" in btn_toggle.text()
    section.set_lap_logger_enabled(True)
    assert "Disable" in btn_lap.text()
