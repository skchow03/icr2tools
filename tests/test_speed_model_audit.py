"""Audit catches real grip-limit excess without flagging permitted high-g laps."""
import numpy as np

from track_viewer.ai.indycar_speed_model import (
    CarPerformance, _corner_speed_mph, _curvature,
)
from track_viewer.ai.speed_model_audit import audit_paths, format_audit


def test_audit_uses_same_corner_limit_as_speed_model():
    n = 64
    angle = np.linspace(0, 2 * np.pi, n, endpoint=False)
    xy = np.column_stack((100 * np.cos(angle), 100 * np.sin(angle)))
    k = _curvature(xy)
    limit = _corner_speed_mph(float(k[0]), CarPerformance())
    baseline = np.full(n, limit * 0.85)
    refined = np.full(n, limit * 0.95)
    audit = audit_paths(
        np.arange(n) * 6000, xy, baseline, xy, refined,
        performance=CarPerformance(),
    )
    assert audit["violations_over_0_1_mph"] == 0
    assert audit["peak_refined_lateral_g"] > 0
    assert audit["rows"][0]["refined_lateral_g"] > audit["rows"][0]["baseline_lateral_g"]
    assert "SPEED MODEL AUDIT" in format_audit(audit)


def test_audit_detects_speed_above_lateral_limit():
    n = 64
    angle = np.linspace(0, 2 * np.pi, n, endpoint=False)
    xy = np.column_stack((100 * np.cos(angle), 100 * np.sin(angle)))
    limit = _corner_speed_mph(float(_curvature(xy)[0]), CarPerformance())
    audit = audit_paths(
        np.arange(n) * 6000, xy, np.full(n, limit * 0.9),
        xy, np.full(n, limit + 2),
    )
    assert audit["violations_over_0_1_mph"] == n
    assert audit["max_speed_limit_excess_mph"] > 1.9
