"""Regression tests for LP polyline picking and periodic, constrained dragging."""

import numpy as np

from track_viewer.ai.lp_curve_drag import (
    nearest_lp_line_anchor,
    smooth_lateral_drag,
)


def _drag(stations, selected, delta, radius, track_length, lower=None, upper=None):
    original = np.zeros(len(stations), dtype=float)
    lo = np.full(len(stations), -1e6) if lower is None else np.asarray(lower)
    hi = np.full(len(stations), 1e6) if upper is None else np.asarray(upper)
    return smooth_lateral_drag(
        original, np.asarray(stations, dtype=float), selected, delta,
        radius, track_length, lo, hi,
    )


def test_clicking_the_middle_of_a_visible_segment_selects_an_anchor():
    # Old vertex-only picking rejected this click: endpoints are 100 px away.
    points = [[0, 0], [200, 0], [200, 80]]
    assert nearest_lp_line_anchor(points, (70, 3)) == 0
    assert nearest_lp_line_anchor(points, (170, 3)) == 1
    assert nearest_lp_line_anchor(points, (200, 48)) == 2


def test_polyline_picking_respects_distance_and_seam():
    points = [[0, 0], [200, 0], [200, 100], [0, 100]]
    assert nearest_lp_line_anchor(points, (0, 55)) == 3
    assert nearest_lp_line_anchor(points, (70, 35)) is None
    assert nearest_lp_line_anchor([[0, 0], [0, 0]], (0, 0)) is None


def test_selected_point_moves_fully_and_nearby_points_follow_smoothly():
    stations = np.arange(0, 500, 10, dtype=float) * 6000
    result = _drag(stations, 25, 4 * 6000, 100, 500 * 6000)
    assert np.isclose(result[25], 4 * 6000)
    assert result[25] > result[24] > result[20] > 0
    assert result[15] == 0
    assert result[35] == 0
    np.testing.assert_allclose(result[15:25], result[26:36][::-1], atol=1e-6)


def test_drag_wraps_across_start_finish_without_a_kink():
    stations = np.arange(0, 100, 10, dtype=float) * 6000
    result = _drag(stations, 0, 6000, 30, 100 * 6000)
    assert np.isclose(result[0], 6000)
    assert result[1] > 0 and np.isclose(result[1], result[-1])
    assert result[3] == 0 and result[-3] == 0


def test_nearby_point_at_wall_no_longer_freezes_the_entire_brush():
    stations = np.arange(0, 100, 10, dtype=float) * 6000
    upper = np.full(len(stations), 1e6)
    upper[4] = 0  # Previous all-or-nothing scaling made every offset zero.
    result = _drag(stations, 5, 6000, 30, 100 * 6000, upper=upper)
    assert np.isclose(result[5], 6000)
    assert result[4] == 0
    assert result[6] > 0  # The unconstrained side still follows the anchor.
    assert np.all(result <= upper)


def test_nearby_partial_wall_limit_shortens_only_the_blocked_side():
    stations = np.arange(0, 100, 10, dtype=float) * 6000
    upper = np.full(len(stations), 1e6)
    upper[4] = 1000
    result = _drag(stations, 5, 6000, 30, 100 * 6000, upper=upper)
    assert np.isclose(result[5], 6000)
    assert result[4] <= 1000
    assert result[6] > 0
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
