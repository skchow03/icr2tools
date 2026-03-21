from sg_viewer.preview.trackside_drag import quantize_trackside_drag_delta


def test_quantize_trackside_drag_delta_accumulates_subunit_motion() -> None:
    step_x, step_y, remainder = quantize_trackside_drag_delta(0.4, 0.0, (0.0, 0.0))

    assert (step_x, step_y) == (0, 0)
    assert remainder == (0.4, 0.0)

    step_x, step_y, remainder = quantize_trackside_drag_delta(0.6, 0.0, remainder)

    assert (step_x, step_y) == (1, 0)
    assert remainder == (0.0, 0.0)
