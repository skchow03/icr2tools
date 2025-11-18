import types

import pytest

from icr2timing.ui.services import (
    LapLoggerController,
    PitCommandService,
    SessionPersistence,
    SessionSnapshot,
)


class DummySignal:
    def __init__(self):
        self._callbacks = []

    def connect(self, cb):
        self._callbacks.append(cb)

    def disconnect(self, cb):
        self._callbacks.remove(cb)


class DummyUpdater:
    def __init__(self):
        self.state_updated = DummySignal()


class DummyLogger:
    def __init__(self):
        self.connected = False
        self.closed = False

    def on_state_updated(self, *_):  # pragma: no cover - not invoked in unit tests
        self.connected = True

    def get_filename(self):
        return "telemetry_laps/test.csv"

    def close(self):
        self.closed = True


def test_lap_logger_controller_toggle():
    updater = DummyUpdater()
    messages = []
    created = []

    def factory():
        logger = DummyLogger()
        created.append(logger)
        return logger

    controller = LapLoggerController(
        updater=updater,
        status_callback=lambda msg, timeout=0: messages.append((msg, timeout)),
        logger_factory=factory,
    )

    assert controller.toggle() is True
    assert controller.enabled is True
    assert controller.recording_file.endswith("test.csv")
    assert len(updater.state_updated._callbacks) == 1

    assert controller.toggle() is False
    assert controller.enabled is False
    assert controller.recording_file is None
    assert updater.state_updated._callbacks == []
    assert len(messages) >= 2
    assert created and created[0].closed is True


def test_lap_logger_controller_handles_factory_errors():
    updater = DummyUpdater()
    messages = []

    def failing_factory():
        raise RuntimeError("boom")

    controller = LapLoggerController(
        updater=updater,
        status_callback=lambda msg, timeout=0: messages.append(msg),
        logger_factory=failing_factory,
    )

    assert controller.enable() is False
    assert controller.enabled is False
    assert controller.recording_file is None
    assert any("Failed" in msg for msg in messages)


class FakeMem:
    def __init__(self):
        self.writes_enabled = False
        self.writes = []

    def enable_writes(self):
        self.writes_enabled = True

    def write(self, offset, fmt, value):
        self.writes.append((offset, fmt, value))


class DummyCfg:
    car_state_base = 0x1000
    car_state_size = 4
    fuel_laps_remaining = 40


def make_state(num_cars=2, values_len=120):
    car_states = {}
    for idx in range(num_cars):
        car_states[idx] = types.SimpleNamespace(values=[0] * values_len)
    return types.SimpleNamespace(car_states=car_states)


def test_pit_command_service_release_all_cars_enables_writes():
    mem = FakeMem()
    mem.writes_enabled = False
    cfg = DummyCfg()
    state = make_state()
    messages = []

    service = PitCommandService(
        mem=mem,
        cfg=cfg,
        state_provider=lambda: state,
        confirm_enable_writes=lambda purpose: True,
        status_callback=lambda msg, timeout=0: messages.append(msg),
    )

    updated = service.release_all_cars()
    assert updated == len(state.car_states)
    assert mem.writes_enabled is True
    assert len(mem.writes) == len(state.car_states)
    assert any("Pit release" in msg for msg in messages)


def test_pit_command_service_force_pit_honors_confirmation():
    mem = FakeMem()
    cfg = DummyCfg()
    state = make_state()
    messages = []

    service = PitCommandService(
        mem=mem,
        cfg=cfg,
        state_provider=lambda: state,
        confirm_enable_writes=lambda purpose: False,
        status_callback=lambda msg, timeout=0: messages.append(msg),
    )

    updated = service.force_all_cars_to_pit()
    assert updated == 0
    assert mem.writes == []
    assert mem.writes_enabled is False
    assert any("remain disabled" in msg for msg in messages)


class FakeProfiles:
    def __init__(self):
        self.saved = None

    def save_last_session(self, profile):
        self.saved = profile


class DummyField:
    def __init__(self, key, label):
        self.key = key
        self.label = label
        self.tooltip = ""


def test_session_persistence_builds_profile():
    profiles = FakeProfiles()
    persistence = SessionPersistence(profiles)

    snapshot = SessionSnapshot(
        ordered_field_keys=["pos", "spd", "position_indicator"],
        custom_fields=[("Boost", 12)],
        n_columns=3,
        display_mode="speed",
        sort_by_best=True,
        use_abbrev=True,
        ro_window_x=10,
        ro_window_y=20,
        radar_x=30,
        radar_y=40,
        radar_visible=True,
        radar_width=200,
        radar_height=150,
        radar_range_forward=3,
        radar_range_rear=2,
        radar_range_side=4,
        radar_symbol="circle",
        radar_show_speeds=True,
        radar_player_color="1,1,1,255",
        radar_ai_ahead_color="2,2,2,255",
        radar_ai_behind_color="3,3,3,255",
        radar_ai_alongside_color="4,4,4,255",
        position_indicator_duration=7.5,
        position_indicator_enabled=True,
        available_fields=[
            DummyField("pos", "Pos"),
            DummyField("spd", "Speed"),
            DummyField("position_indicator", "SincePit"),
        ],
    )

    profile = persistence.save_last_session(snapshot)
    assert profiles.saved is profile
    assert profile.columns == ["Pos", "Speed", "SincePit"]
    assert profile.custom_fields == [("Boost", 12)]
    assert profile.n_columns == 3
    assert profile.display_mode == "speed"
    assert profile.radar_visible is True
    assert profile.position_indicator_duration == pytest.approx(7.5)
