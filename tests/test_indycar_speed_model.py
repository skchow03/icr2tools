"""Tests for the compact 1995 CART speed-envelope model."""

import json
import math
import tempfile
import unittest
from pathlib import Path

import numpy as np

from track_viewer.ai.indycar_speed_model import (
    MAX_SPEED_MPH,
    CarPerformance,
    _corner_speed_mph,
    load_performance_model,
    speed_profile_mph,
)


class IndyCarSpeedModelTest(unittest.TestCase):
    def test_corner_speed_increases_with_radius(self):
        radii = [50, 100, 200, 400, 800]
        speeds = [_corner_speed_mph(1.0 / radius) for radius in radii]
        self.assertTrue(all(b > a for a, b in zip(speeds, speeds[1:])))
        self.assertGreater(speeds[-1], 180)

    def test_constant_radius_lap_is_curvature_limited(self):
        radius = 200.0
        angle = np.linspace(0, 2 * math.pi, 240, endpoint=False)
        points = np.column_stack((radius * np.cos(angle), radius * np.sin(angle)))
        speeds = speed_profile_mph(points)
        self.assertLess(np.ptp(speeds), 0.25)
        self.assertLess(float(np.mean(speeds)), MAX_SPEED_MPH)
        self.assertGreater(float(np.mean(speeds)), 60)

    def test_braking_starts_before_tight_corner(self):
        # Stadium-shaped lap: long straights joined by tight semicircles.
        radius = 55.0
        top = np.column_stack((np.linspace(-250, 250, 120), np.full(120, radius)))
        a = np.linspace(math.pi / 2, -math.pi / 2, 80, endpoint=False)[1:]
        right = np.column_stack((250 + radius * np.cos(a), radius * np.sin(a)))
        bottom = np.column_stack((np.linspace(250, -250, 120), np.full(120, -radius)))[1:]
        a = np.linspace(-math.pi / 2, math.pi / 2, 80, endpoint=False)[1:]
        left = np.column_stack((-250 + radius * np.cos(a), radius * np.sin(a)))
        points = np.concatenate((top, right, bottom, left))
        speeds = speed_profile_mph(points)
        # The end of the first straight must already be slowing for the bend.
        self.assertGreater(speeds[60], speeds[115])
        self.assertGreater(speeds[60], speeds[125])

    def test_tuning_changes_corner_speed(self):
        baseline = _corner_speed_mph(1.0 / 250.0)
        more_grip = _corner_speed_mph(
            1.0 / 250.0, CarPerformance(cornering_pct=120.0)
        )
        less_aero = _corner_speed_mph(
            1.0 / 250.0, CarPerformance(aero_pct=50.0)
        )
        self.assertGreater(more_grip, baseline)
        self.assertLess(less_aero, baseline)

    def test_acceleration_and_braking_tuning_change_profile(self):
        radius = 55.0
        top = np.column_stack((np.linspace(-250, 250, 120), np.full(120, radius)))
        a = np.linspace(math.pi / 2, -math.pi / 2, 80, endpoint=False)[1:]
        right = np.column_stack((250 + radius * np.cos(a), radius * np.sin(a)))
        bottom = np.column_stack((np.linspace(250, -250, 120), np.full(120, -radius)))[1:]
        a = np.linspace(-math.pi / 2, math.pi / 2, 80, endpoint=False)[1:]
        left = np.column_stack((-250 + radius * np.cos(a), radius * np.sin(a)))
        points = np.concatenate((top, right, bottom, left))
        baseline = speed_profile_mph(points)
        slower = speed_profile_mph(
            points, CarPerformance(acceleration_pct=70.0, braking_pct=70.0)
        )
        self.assertLess(float(np.mean(slower)), float(np.mean(baseline)))

    def test_performance_model_json_loads_and_validates(self):
        data = {
            "max_speed_mph": 200,
            "lateral_g": [[0, 1.0], [200, 3.0]],
            "acceleration_g": [[0, 0.8], [200, 0.0]],
            "braking_g": [[0, 1.0], [200, 3.0]],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            loaded = load_performance_model(path)
        self.assertEqual(loaded["max_speed_mph"], 200.0)
        self.assertEqual(loaded["lateral_g"].shape, (2, 2))



if __name__ == "__main__":
    unittest.main()
