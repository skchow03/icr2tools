"""Regression coverage for the opt-in combined-grip refinement objective."""
import numpy as np

from track_viewer.ai.combined_grip import combined_grip_profile, modeled_lap_seconds
from track_viewer.ai.indycar_speed_model import speed_profile_mph


def test_combined_grip_can_be_used_as_a_lap_objective():
    t = np.linspace(0.0, 2.0 * np.pi, 96, endpoint=False)
    xy = np.column_stack((260.0 * np.cos(t), 145.0 * np.sin(t)))
    # Both objectives must score identical geometry, without changing it.
    saved_xy = xy.copy()
    lateral_speeds = speed_profile_mph(xy)
    combined_speeds = combined_grip_profile(xy)
    lateral_time = modeled_lap_seconds(xy, lateral_speeds)
    combined_time = modeled_lap_seconds(xy, combined_speeds)
    assert np.array_equal(saved_xy, xy)
    assert np.isfinite(lateral_time) and np.isfinite(combined_time)
    assert combined_time >= lateral_time - 0.01
    assert np.max(combined_speeds) <= np.max(lateral_speeds) + 0.01


def test_combined_grip_respects_explicit_speed_cap():
    t = np.linspace(0.0, 2.0 * np.pi, 72, endpoint=False)
    xy = np.column_stack((300.0 * np.cos(t), 175.0 * np.sin(t)))
    speeds = combined_grip_profile(xy, max_speed_mph=100.0)
    assert np.all(np.isfinite(speeds))
    assert np.all(speeds <= 100.00001)
    assert np.all(speeds > 0.0)
