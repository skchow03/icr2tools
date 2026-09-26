"""Combined-grip re-scoring leaves the source geometry and speed data intact."""
import numpy as np

from track_viewer.ai.combined_grip import (
    combined_grip_profile, compare_combined_grip, modeled_lap_seconds,
)
from track_viewer.ai.indycar_speed_model import speed_profile_mph


def test_combined_grip_never_faster_than_separate_envelopes():
    t = np.linspace(0, 2 * np.pi, 48, endpoint=False)
    xy = np.column_stack((220 * np.cos(t), 130 * np.sin(t)))
    original = speed_profile_mph(xy)
    combined = combined_grip_profile(xy)
    assert np.all(np.isfinite(combined))
    assert np.all(combined <= original + 0.02)
    assert modeled_lap_seconds(xy, combined) >= modeled_lap_seconds(xy, original) - 0.01


def test_comparison_does_not_modify_input_geometry_or_speeds():
    t = np.linspace(0, 2 * np.pi, 32, endpoint=False)
    xy = np.column_stack((180 * np.cos(t), 140 * np.sin(t)))
    before = xy.copy()
    result = compare_combined_grip(xy, xy.copy())
    assert np.array_equal(xy, before)
    assert abs(result["refined_minus_baseline_seconds"]) < 0.001
    assert len(result["baseline"]["speeds_mph"]) == len(xy)
