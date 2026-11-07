"""Pure tracing calibration math: no Qt, GL or source edits."""
from dataclasses import replace
from math import hypot
from pathlib import Path
import unittest
from types import SimpleNamespace

import numpy as np

from tracing_reference import (
    TracingReference, calibrate_two_points, image_point_to_world,
    initial_reference, plane_vertices,
)


class ReferenceCalibrationTests(unittest.TestCase):
    def setUp(self):
        self.mesh = SimpleNamespace(
            center=np.array([1000.0, 2000.0, 3000.0]),
            scale=1000.0)

    def test_default_centered_to_model_with_normalized_scale(self):
        ref = initial_reference(
            "a profile.jpg", 200, 100, self.mesh, plane="Front")
        self.assertEqual(ref.anchor_pixel, (100.0, 50.0))
        self.assertEqual(ref.world_anchor, (1000.0, 3000.0))
        self.assertEqual(ref.units_per_pixel, 10.0)
        self.assertEqual(image_point_to_world(ref, 100, 50),
                         (1000.0, 3000.0))
        self.assertEqual(image_point_to_world(ref, 200, 0),
                         (2000.0, 3500.0))

    def test_two_calibration_points_in_raw_units(self):
        units, angle = calibrate_two_points((10, 20), (210, 20), 30000)
        self.assertEqual(units, 150.0)
        self.assertEqual(angle, 0)
        ref = replace(initial_reference(
            "car.png", 300, 100, self.mesh, plane="Side"),
            anchor_pixel=(10, 20), units_per_pixel=units,
            rotation_degrees=angle, world_anchor=(0, 5000))
        self.assertEqual(image_point_to_world(ref, 10, 20), (0.0, 5000.0))
        self.assertEqual(image_point_to_world(ref, 210, 20), (30000.0, 5000.0))

    def test_diagonal_photo_calibration_corrects_rotation(self):
        a, b = (20, 20), (120, 120)
        scale, angle = calibrate_two_points(a, b, 5000)
        self.assertAlmostEqual(angle, 45)
        ref = replace(initial_reference(
            "photo.png", 200, 200, self.mesh, plane="Side"),
            anchor_pixel=a, world_anchor=(600, 1000),
            units_per_pixel=scale, rotation_degrees=angle)
        u, v = image_point_to_world(ref, *b)
        self.assertAlmostEqual(u, 5600)
        self.assertAlmostEqual(v, 1000)

    def test_reference_quad_projection_all_three_planes(self):
        for plane, axes, fixed, sign in (
                ("Front", (0, 2), 1, 1),
                ("Side", (1, 2), 0, -1),
                ("Top", (0, 1), 2, -1)):
            with self.subTest(plane=plane):
                ref = initial_reference(
                    "blueprint.png", 200, 100, self.mesh, plane=plane)
                v = plane_vertices(ref, self.mesh.center, self.mesh.scale)
                self.assertEqual(v.shape, (6, 5))
                self.assertEqual(v.dtype, np.float32)
                self.assertTrue(np.isfinite(v).all())
                self.assertTrue(np.allclose(v[:, fixed], sign * 1.25))
                self.assertTrue(np.allclose(v[:, 3:], [
                    (0,0), (1,0), (1,1), (0,0), (1,1), (0,1)]))
                self.assertAlmostEqual(v[0, axes[0]], -1)
                self.assertAlmostEqual(v[0, axes[1]], +0.5)

    def test_calibration_rejects_invalid_values(self):
        for a, b, distance in (
                ((0,0),(0,0),100),
                ((0,0),(1,1),0),
                ((0,0),(1,1),-5),
                ((0,0),(float("nan"),1),100)):
            with self.subTest(a=a,b=b,d=distance):
                with self.assertRaises(ValueError):
                    calibrate_two_points(a,b,distance)
        with self.assertRaises(ValueError):
            TracingReference(Path("x"), 10, 20, "Diagonal",
                             (0,0), (0,0), 1)
        with self.assertRaises(ValueError):
            TracingReference(Path("x"), 10, 20, "Side",
                             (0,0), (0,0), 0)
        with self.assertRaises(ValueError):
            TracingReference(Path("x"), 10, 20, "Side",
                             (0,0), (0,0), 1, opacity=2)

    def test_image_reference_does_not_change_model_binary(self):
        from three_do import Model
        model = Model(Path(__file__).resolve().parents[1]
                      / "fixtures" / "roadcar.3do", associate_planes=False)
        raw = model.raw
        for plane in ("Front", "Side", "Top"):
            ref = initial_reference("photo.png", 640, 480, self.mesh,
                                    plane=plane)
            plane_vertices(ref, self.mesh.center, self.mesh.scale)
        self.assertEqual(model.raw, raw)
        self.assertFalse(model.dirty)


if __name__ == "__main__":
    unittest.main()
