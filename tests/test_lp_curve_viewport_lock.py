"""Regression tests for locked preview navigation in Smooth Drag LP mode."""

from types import SimpleNamespace

import numpy as np
from PyQt5 import QtCore

from track_viewer.model.lp_editing_session import LPChange
from track_viewer.widget.interaction import mouse_controller

from track_viewer.widget.interaction.mouse_controller import TrackPreviewMouseController


def _controller():
    """Build a controller without live Qt drawing or a track database."""
    controller = TrackPreviewMouseController.__new__(TrackPreviewMouseController)
    controller.curve_edit_enabled = True
    controller._curve_drag = None
    controller._state = SimpleNamespace(
        is_panning=True,
        last_mouse_pos=QtCore.QPoint(10, 10),
        left_press_pos=QtCore.QPoint(10, 10),
        dragged_during_press=True,
    )
    return controller


def test_enabling_curve_drag_clears_an_existing_pan():
    controller = _controller()
    controller._clear_lp_hover_update = lambda: None
    controller.cancel_view_pan()
    assert controller._state.is_panning is False
    assert controller._state.last_mouse_pos is None
    assert controller._state.left_press_pos is None
    assert controller._state.dragged_during_press is False


def test_missed_curve_drag_click_never_starts_panning():
    controller = _controller()
    controller._state.is_panning = False
    calls = []
    controller.begin_curve_drag = lambda point, size: calls.append(point) or False
    event = SimpleNamespace(
        button=lambda: QtCore.Qt.LeftButton,
        pos=lambda: QtCore.QPoint(20, 20),
    )
    assert controller.handle_mouse_press(event, QtCore.QSize(320, 240))
    assert len(calls) == 1
    assert controller._state.is_panning is False


def test_curve_edit_ignores_map_wheel_and_unrelated_right_click():
    controller = _controller()
    wheel = SimpleNamespace(angleDelta=lambda: QtCore.QPoint(0, 120))
    assert controller.handle_wheel(wheel, QtCore.QSize(320, 240))
    right = SimpleNamespace(button=lambda: QtCore.Qt.RightButton)
    assert controller.handle_mouse_press(right, QtCore.QSize(320, 240))
    assert controller._state.last_mouse_pos == QtCore.QPoint(10, 10)


def test_moving_and_releasing_with_no_drag_never_pan():
    controller = _controller()
    controller._state.is_panning = False
    event = SimpleNamespace(
        button=lambda: QtCore.Qt.LeftButton,
        pos=lambda: QtCore.QPoint(30, 40),
    )
    assert controller.handle_mouse_move(event, QtCore.QSize(320, 240))
    assert controller.handle_mouse_release(event, QtCore.QSize(320, 240))
    assert controller._state.is_panning is False


def test_click_on_long_lp_segment_starts_drag_and_updates_curve(monkeypatch):
    """Regression: the old NumPy reference triggered a silent truth-value error.

    LP points can also be >14px apart at high zoom, so click between them.
    """
    controller = _controller()
    controller.curve_drag_error = None
    controller.curve_influence_feet = 180.0
    controller._curve_drag_changed = False
    controller._clear_lp_hover_update = lambda: None
    lp_name = "RACE"
    records = [
        SimpleNamespace(x=x, y=0.0, dlong=x * 6000.0, dlat=0.0)
        for x in (0.0, 150.0, 250.0)
    ]
    updated = []
    def save_offsets(name, offsets):
        assert name == lp_name
        updated.append(np.asarray(offsets).copy())
        return True

    controller._model = SimpleNamespace(
        trk=SimpleNamespace(trklength=300.0 * 6000.0),
        visible_lp_files={lp_name},
        centerline=[(0.0, 0.0)],
        ai_line_records=lambda name: records,
        set_lp_curve_offsets=save_offsets,
        bounds=(-10.0, 300.0, -10.0, 10.0),
    )
    controller._lp_session = SimpleNamespace(
        active_lp_line=lp_name,
        set_selected_lp_record=lambda name, index: {LPChange.SELECTION},
    )
    controller._state.current_transform = lambda bounds, size: (
        1.0, (0.0, 0.0)
    )
    size = QtCore.QSize(320, 240)
    controller._state.map_to_track = lambda point, bounds, size: (
        float(point.x()), float(240 - point.y())
    )
    selection = []
    controller._callbacks = SimpleNamespace(
        lp_record_selected=lambda name, idx: selection.append((name, idx)),
        state_changed=lambda intent: None,
    )

    def fake_corridor(trk, centerline, dlongs, reference_dlats, **kwargs):
        # Matches the real _paved_corridor's truthiness check. Passing the
        # original NumPy array instead of a list raises ValueError here.
        assert bool(reference_dlats)
        assert isinstance(reference_dlats, list)
        return (
            np.full(len(dlongs), -1e6),
            np.full(len(dlongs), 1e6),
        )
    monkeypatch.setattr(mouse_controller, "build_legal_dlat_envelope", fake_corridor)
    monkeypatch.setattr(
        mouse_controller, "getxyz",
        lambda trk, dlong, dlat, centerline: (dlong / 6000.0, dlat, 0.0),
    )

    # The visible segment runs across x=0..150 at viewport y=240.
    click = QtCore.QPointF(75, 240)
    assert controller.begin_curve_drag(click, size)
    assert selection == [("RACE", 0)]
    assert controller.curve_drag_error is None
    assert controller.curve_drag_active

    # The first motion at the click position must not cause a positional jump.
    assert controller.update_curve_drag(click, size)
    np.testing.assert_array_equal(updated[-1], [0, 0, 0])

    # Drag 5000 native units upward, perpendicular to the selected line.
    assert controller.update_curve_drag(QtCore.QPointF(75, 235), size)
    assert updated[-1][0] == 5.0
    assert updated[-1][1] > 0.0
    assert controller.end_curve_drag() == "RACE"


def test_begin_curve_drag_exposes_corridor_rejection(monkeypatch):
    """Problems determining pavement no longer masquerade as missed clicks."""
    controller = _controller()
    controller.curve_drag_error = None
    controller._curve_drag_changed = False
    controller._clear_lp_hover_update = lambda: None
    controller._model = SimpleNamespace(
        trk=SimpleNamespace(trklength=300.0 * 6000.0),
        visible_lp_files={"RACE"},
        centerline=[(0, 0)],
        ai_line_records=lambda name: [
            SimpleNamespace(x=x, y=0.0, dlong=x * 6000, dlat=0.0)
            for x in (0, 150, 250)
        ],
        bounds=(0, 250, -5, 5),
    )
    controller._lp_session = SimpleNamespace(active_lp_line="RACE")
    controller._state.current_transform = lambda bounds, size: (
        1.0, (0.0, 0.0)
    )
    controller._state.map_to_track = lambda point, bounds, size: (
        point.x(), 240 - point.y()
    )
    monkeypatch.setattr(
        mouse_controller, "build_legal_dlat_envelope",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ValueError("No paved corridor")
        ),
    )
    assert not controller.begin_curve_drag(
        QtCore.QPointF(75, 240), QtCore.QSize(320, 240)
    )
    assert "No paved corridor" in controller.curve_drag_error
