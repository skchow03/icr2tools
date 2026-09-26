"""Common LP metrics remain comparable across generators."""
from types import SimpleNamespace

import numpy as np
import pytest

from track_viewer.ai.line_diagnostics import analyze_line, format_diagnostics


def circle(n=64, radius=100.0, mph=100.0):
    theta = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    records = [
        SimpleNamespace(
            x=radius * np.cos(t) * 6000.0,
            y=radius * np.sin(t) * 6000.0,
            dlong=i * 1000.0,
            dlat=0.0,
            speed_mph=mph,
        )
        for i, t in enumerate(theta)
    ]
    records.append(SimpleNamespace(
        x=records[0].x, y=records[0].y, dlong=n * 1000.0,
        dlat=0.0, speed_mph=mph,
    ))
    return records


def test_closed_circle_terminal_record_not_double_counted():
    stats = analyze_line(circle(), track_length=64000.0,
                         lower=np.full(64, -30000.0),
                         upper=np.full(64, 30000.0))
    assert stats["sample_count"] == 64
    assert stats["minimum_legal_clearance_ft"] == 5.0
    assert stats["thresholded_curvature_sign_changes"] == 0
    assert stats["accelerating_seconds_estimate"] == 0.0
    assert stats["decelerating_seconds_estimate"] == 0.0
    assert stats["near_constant_speed_seconds_estimate"] == pytest.approx(stats["lap_seconds"])
    assert stats["peak_abs_curvature_per_ft"] == pytest.approx(0.01, rel=0.02)
    assert "COMMON LP DIAGNOSTICS" in format_diagnostics(stats)


def test_invalid_speed_is_rejected():
    points = circle()
    points[4].speed_mph = float("nan")
    with pytest.raises(ValueError, match="nonfinite"):
        analyze_line(points, track_length=64000.0)
