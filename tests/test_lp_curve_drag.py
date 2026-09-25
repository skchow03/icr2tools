"""Regression tests for periodic, wall-constrained LP curve dragging."""

import numpy as np

from track_viewer.ai.lp_curve_drag import smooth_lateral_drag


def _drag(stations, selected, delta, radius, track_length, lower=None, upper=None):
    original = np.zeros(len(stations), dtype=float)
    lo = np.full(len(stations), -1e6) if lower is None else np.asarray(lower)
    hi = np.full(len(stations), 1e6) if upper is None else np.asarray(upper)
    return smooth_lateral_drag(
        original, np.asarray(stations, dtype=float), selected, delta,
        radius, track_length, lo, hi,
    )


def test_selected_point_moves_fully_and_nearby_points_follow_smoothly():
    stations = np.arange(0, 500, 10, dtype=float) * 6000
    result = _drag(stations, 25, 4 * 6000, 100, 500 * 6000)
    assert np.isclose(result[25], 4 * 6000)
    assert result[25] > result[24] > result[20] > 0
    assert result[15] == 0
    assert result[35] == 0
    np.testing.assert_allclose(result[25-10:25], result[26:36][::-1], atol=1e-6)


def test_drag_wraps_across_start_finish_without_a_kink():
    stations = np.arange(0, 100, 10, dtype=float) * 6000
    result = _drag(stations, 0, 6000, 30, 100 * 6000)
    assert np.isclose(result[0], 6000)
    assert result[1] > 0 and np.isclose(result[1], result[-1])
    assert result[3] == 0 and result[-3] == 0


def test_legal_corridor_scales_whole_bump_instead_of_clipping_a_spike():
    stations = np.arange(0, 100, 10, dtype=float) * 6000
    upper = np.full(len(stations), 1e6)
    upper[4] = 1000  # An LP near the brush center is near a wall.
    result = _drag(
        stations, 5, 6000, 30, 100 * 6000, upper=upper
    )
    assert result[4] <= upper[4] + 1e-8
    assert result[5] < 6000
    assert np.all(result <= upper)


def test_negative_drag_and_out_of_range_index():
    stations = np.arange(0, 100, 10, dtype=float) * 6000
    lower = np.full(len(stations), -3000)
    result = _drag(stations, 5, -6000, 30, 100 * 6000, lower=lower)
    assert result[5] == -3000
    assert np.all(result >= lower)
    try:
        _drag(stations, len(stations), 6000, 30, 100 * 6000)
    except IndexError:
        pass
    else:
        raise AssertionError("Expected index validation")
