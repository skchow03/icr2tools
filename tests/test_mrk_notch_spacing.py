import math

import pytest

try:
    from sg_viewer.services.preview_painter import _division_points_for_polyline
except ImportError:  # pragma: no cover
    pytest.skip("PyQt5 not available", allow_module_level=True)


def test_divisions_follow_polyline_arc_length():
    radius = 24000.0
    total_angle = math.pi / 2
    points = [
        (
            radius * math.cos(total_angle * step / 32),
            radius * math.sin(total_angle * step / 32),
        )
        for step in range(33)
    ]

    target = 14.0 * 6000.0
    divisions = _division_points_for_polyline(points, target_length=target)

    total_length = (math.pi / 2) * radius
    expected_segments = round(total_length / target)
    assert len(divisions) == max(0, expected_segments - 1)
    if divisions:
        spacing = total_length / expected_segments
        assert divisions[0] == pytest.approx(spacing, rel=0.03)
