"""Origin-locked GPU camera tests using raw Papyrus coordinate space.

The scene's raw XYZ origin rarely coincides with its normalized mesh center.
An interior view must pin the actual perspective camera eye at raw 0,0,0
even when rotating, changing zoom/FOV, or recompiling meshes.
"""
import math
import unittest
import numpy as np

from gpu_viewer.visibility import (
    camera_in_model_units, origin_view_target,
)


class OriginCameraTests(unittest.TestCase):
    def test_origin_eye_for_offcentered_and_large_models(self):
        cases = (
            ((0, 0, 5000), 10000.0),
            ((750_000, -6_000_000, 450_000), 250_000.0),
            ((-32500, 10500, -65000), 23000.0),
        )
        for center, scale in cases:
            for azimuth, elevation in ((0, 0), (0.7, 0.2),
                                       (math.pi, -0.3), (1.9, 1.1)):
                target = origin_view_target(
                    center, scale, azimuth, elevation, 4.0)
                actual = camera_in_model_units(
                    center, scale, target, azimuth, elevation, 4.0)
                with self.subTest(center=center, azimuth=azimuth,
                                  elevation=elevation):
                    np.testing.assert_allclose(
                        actual, (0, 0, 0), atol=1e-8, rtol=0)

    def test_fixed_eye_while_turning_and_dolly_distance_changes(self):
        center = (100000, -50000, 40000)
        scale = 45000.0
        expected_eye = -np.asarray(center) / scale
        for distance in (0.1, 4.0, 15.0, 200.0):
            for azimuth in (-3, -0.5, 0, 0.7, 2.5):
                target = origin_view_target(
                    center, scale, azimuth, -0.31, distance)
                direction = np.array((
                    math.cos(-0.31) * math.sin(azimuth),
                    -math.cos(-0.31) * math.cos(azimuth),
                    math.sin(-0.31)))
                np.testing.assert_allclose(
                    target + direction * distance,
                    expected_eye, rtol=0, atol=1e-13)

    def test_invalid_normalization_is_rejected(self):
        for scale in (0, -1, float('nan')):
            with self.assertRaises(ValueError):
                origin_view_target((0,0,0), scale, 0, 0, 4.0)
        for distance in (0, -1, float('inf')):
            with self.assertRaises(ValueError):
                origin_view_target((0,0,0), 1, 0, 0, distance)


if __name__ == '__main__':
    unittest.main()
