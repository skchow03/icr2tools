import pytest

from sg_viewer.preview.trackside_drag import quantize_trackside_drag_delta


def test_quantize_trackside_drag_delta_accumulates_subunit_motion() -> None:
    step_x, step_y, remainder = quantize_trackside_drag_delta(0.4, 0.0, (0.0, 0.0))

    assert (step_x, step_y) == (0, 0)
    assert remainder == (0.4, 0.0)

    step_x, step_y, remainder = quantize_trackside_drag_delta(0.6, 0.0, remainder)

    assert (step_x, step_y) == (1, 0)
    assert remainder == (0.0, 0.0)


def test_quantize_trackside_drag_delta_waits_for_full_unit_without_rounding_up() -> None:
    step_x, step_y, remainder = quantize_trackside_drag_delta(0.6, 0.0, (0.0, 0.0))

    assert (step_x, step_y) == (0, 0)
    assert remainder == (0.6, 0.0)

    step_x, step_y, remainder = quantize_trackside_drag_delta(0.39, 0.0, remainder)

    assert (step_x, step_y) == (0, 0)
    assert remainder == (0.99, 0.0)

    step_x, step_y, remainder = quantize_trackside_drag_delta(0.01, 0.0, remainder)

    assert (step_x, step_y) == (1, 0)
    assert remainder == (0.0, 0.0)


def test_quantize_trackside_drag_delta_accumulates_negative_motion_without_bias() -> None:
    step_x, step_y, remainder = quantize_trackside_drag_delta(-0.4, 0.0, (0.0, 0.0))

    assert (step_x, step_y) == (0, 0)
    assert remainder == (-0.4, 0.0)

    step_x, step_y, remainder = quantize_trackside_drag_delta(-0.61, 0.0, remainder)

    assert (step_x, step_y) == (-1, 0)
    assert remainder == pytest.approx((-0.01, 0.0))


def test_quantize_trackside_drag_delta_does_not_oscillate_around_zero() -> None:
    step_x, step_y, remainder = quantize_trackside_drag_delta(0.75, 0.0, (0.0, 0.0))

    assert (step_x, step_y) == (0, 0)
    assert remainder == (0.75, 0.0)

    step_x, step_y, remainder = quantize_trackside_drag_delta(-0.5, 0.0, remainder)

    assert (step_x, step_y) == (0, 0)
    assert remainder == (0.25, 0.0)
