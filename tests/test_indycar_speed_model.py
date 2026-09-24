"""Tests for the compact 1995 CART speed-envelope model."""

import math
import unittest

import numpy as np

from track_viewer.ai.indycar_speed_model import (
    MAX_SPEED_MPH,
    _corner_speed_mph,
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


if __name__ == "__main__":
    unittest.main()
