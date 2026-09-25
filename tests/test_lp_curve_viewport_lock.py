"""Regression tests for locked preview navigation in Smooth Drag LP mode."""

from types import SimpleNamespace

from PyQt5 import QtCore

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
