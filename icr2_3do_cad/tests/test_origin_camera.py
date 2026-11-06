"""Configurable Fixed Camera eye tests in raw Papyrus coordinate space.

The camera defaults to raw XYZ (0,0,5000), which is not
generally at the GPU mesh center. Confirm both the perspective matrix's
eye and the BSP/RES raw eye remain stationary while looking around.
"""
import math
import unittest
import numpy as np

from visibility import (
    FIXED_CAMERA_DEFAULT_EYE, camera_in_model_units,
    fixed_eye_view_target, origin_view_target,
)


class FixedCameraTests(unittest.TestCase):
    def test_fixed_eye_for_offcentered_and_large_models(self):
        self.assertEqual(FIXED_CAMERA_DEFAULT_EYE, (0.0, 0.0, 5000.0))
        cases = (
            ((0, 0, 5000), 10000.0),
            ((750_000, -6_000_000, 450_000), 250_000.0),
            ((-32500, 10500, -65000), 23000.0),
        )
        for center, scale in cases:
            for azimuth, elevation in ((0, 0), (0.7, 0.2),
                                       (math.pi, -0.3), (1.9, 1.1)):
                target = fixed_eye_view_target(
                    center, scale, FIXED_CAMERA_DEFAULT_EYE, azimuth, elevation, 4.0)
                actual = camera_in_model_units(
                    center, scale, target, azimuth, elevation, 4.0)
                with self.subTest(center=center, azimuth=azimuth,
                                  elevation=elevation):
                    np.testing.assert_allclose(
                        actual, FIXED_CAMERA_DEFAULT_EYE, atol=1e-8, rtol=0)

    def test_fixed_eye_while_looking_around_and_changing_orbit_distance(self):
        center = (100000, -50000, 40000)
        scale = 45000.0
        expected_eye = ((np.asarray(FIXED_CAMERA_DEFAULT_EYE)
                         - np.asarray(center)) / scale)
        for distance in (0.1, 4.0, 15.0, 200.0):
            for azimuth in (-3, -0.5, 0, 0.7, 2.5):
                target = fixed_eye_view_target(
                    center, scale, FIXED_CAMERA_DEFAULT_EYE,
                    azimuth, -0.31, distance)
                direction = np.array((
                    math.cos(-0.31) * math.sin(azimuth),
                    -math.cos(-0.31) * math.cos(azimuth),
                    math.sin(-0.31)))
                np.testing.assert_allclose(
                    target + direction * distance,
                    expected_eye, rtol=0, atol=1e-13)

    def test_changing_xyz_repositions_camera_exactly(self):
        """User-entered values must not be restricted to the initial preset."""
        centers = ((0, 0, 15000), (49000, -175000, -5000))
        eyes = ((0, 0, 5000), (0, 0, 10000),
                (12500, -8000, 1500), (-225000, 450000, -12000))
        for center in centers:
            for eye in eyes:
                for azimuth in (0, 0.3, 2.1):
                    target = fixed_eye_view_target(
                        center, 100000, eye, azimuth, -0.2, 4)
                    actual = camera_in_model_units(
                        center, 100000, target, azimuth, -0.2, 4)
                    with self.subTest(center=center, eye=eye, azimuth=azimuth):
                        np.testing.assert_allclose(actual, eye, rtol=0, atol=1e-9)

    def test_generic_fixed_eye_and_legacy_origin_compatibility(self):
        center = (750, -400, 200)
        target = origin_view_target(center, 5000, 0.9, 0.4, 4.0)
        raw = camera_in_model_units(center, 5000, target, 0.9, 0.4, 4.0)
        np.testing.assert_allclose(raw, (0, 0, 0), rtol=0, atol=1e-10)
        arbitrary = (800, -500, 12000)
        target = fixed_eye_view_target(center, 5000, arbitrary, 0.9, 0.4, 4.0)
        raw = camera_in_model_units(center, 5000, target, 0.9, 0.4, 4.0)
        np.testing.assert_allclose(raw, arbitrary, rtol=0, atol=1e-10)

    def test_invalid_normalization_or_eye_is_rejected(self):
        for scale in (0, -1, float('nan')):
            with self.assertRaises(ValueError):
                fixed_eye_view_target((0,0,0), scale,
                                      FIXED_CAMERA_DEFAULT_EYE, 0, 0, 4.0)
        for distance in (0, -1, float('inf')):
            with self.assertRaises(ValueError):
                fixed_eye_view_target((0,0,0), 1,
                                      FIXED_CAMERA_DEFAULT_EYE, 0, 0, distance)
        for eye in ((1, 2), (1, 2, float('nan')), (1, 2, float('inf'))):
            with self.assertRaises(ValueError):
                fixed_eye_view_target((0,0,0), 1, eye, 0, 0, 4.0)


if __name__ == '__main__':
    unittest.main()
