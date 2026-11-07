"""Saved tracing image profiles survive restarts and adapt to other models."""
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import unittest

import numpy as np

from tracing_reference import initial_reference
from tracing_profiles import TracingProfileStore, ProfileError


class TracingProfileStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.library = Path(self.temp.name) / "config" / "tracing_profiles.json"
        self.store = TracingProfileStore(self.library)
        self.image = Path(self.temp.name) / "photo.png"
        self.image.write_bytes(b"immutable image bytes")
        self.original = self.image.read_bytes()
        self.mesh_a = SimpleNamespace(
            center=np.array((1000.0, 2000.0, 3000.0)), scale=500)
        self.mesh_b = SimpleNamespace(
            center=np.array((11000.0, -8000.0, 23000.0)), scale=900)
        self.ref = replace(initial_reference(
            self.image, 800, 400, self.mesh_a, plane="Side"),
            anchor_pixel=(150., 270.), world_anchor=(2400., 3200.),
            units_per_pixel=23.456, rotation_degrees=-15.25, opacity=0.37,
            visible=False, point_a=(150., 270.), point_b=(350., 260.),
            calibration_distance=4700.0)

    def test_full_roundtrip_and_new_store_instance_survives_restart(self):
        self.assertEqual(self.store.names(), [])
        self.store.save("Vintage IndyCar profile", self.ref, self.mesh_a)
        self.assertTrue(self.library.exists())
        rebuilt_store = TracingProfileStore(self.library)
        self.assertEqual(rebuilt_store.names(), ["Vintage IndyCar profile"])
        restored = rebuilt_store.load("Vintage IndyCar profile", self.mesh_a)
        self.assertEqual(restored, self.ref)
        self.assertEqual(self.image.read_bytes(), self.original)
        payload = json.loads(self.library.read_text())
        self.assertEqual(payload["version"], 1)
        self.assertEqual(len(payload["profiles"]), 1)
        self.assertEqual(payload["profiles"][0]["point_a"], [150., 270.])
        self.assertNotIn("pixels", payload["profiles"][0])

    def test_reapply_to_different_model_uses_center_offset_not_rescale(self):
        self.store.save("A profile", self.ref, self.mesh_a)
        relative = self.store.load("A profile", self.mesh_b)
        # Side plane is Y/Z; original model center (2000,3000),
        # new center (-8000,23000). Anchor offset (400,200).
        self.assertEqual(relative.world_anchor, (-7600., 23200.))
        self.assertEqual(relative.units_per_pixel, self.ref.units_per_pixel)
        self.assertEqual(relative.rotation_degrees, self.ref.rotation_degrees)
        self.assertEqual(relative.anchor_pixel, self.ref.anchor_pixel)
        self.assertEqual(relative.point_a, self.ref.point_a)
        self.assertEqual(relative.point_b, self.ref.point_b)
        self.assertEqual(relative.calibration_distance,
                         self.ref.calibration_distance)
        self.assertEqual(relative.opacity, self.ref.opacity)
        self.assertFalse(relative.visible)
        absolute = self.store.load(
            "A profile", self.mesh_b, placement="absolute")
        self.assertEqual(absolute.world_anchor, (2400., 3200.))

    def test_all_planes_translate_only_the_correct_axes(self):
        for plane, shift in (("Side", (-10000, 20000)),
                             ("Front", (10000, 20000)),
                             ("Top", (10000, -10000))):
            with self.subTest(plane=plane):
                name = plane + " test"
                ref = initial_reference(
                    self.image, 800, 400, self.mesh_a, plane=plane)
                self.store.save(name, ref, self.mesh_a)
                new = self.store.load(name, self.mesh_b)
                self.assertEqual(
                    new.world_anchor,
                    tuple(ref.world_anchor[i]+shift[i] for i in (0,1)))

    def test_save_overwrite_case_insensitive_and_delete(self):
        self.store.save("Profile One", self.ref, self.mesh_a)
        with self.assertRaisesRegex(ProfileError, "already exists"):
            self.store.save("profile one", self.ref, self.mesh_a)
        changed = replace(self.ref, opacity=0.91)
        self.store.save("profile one", changed, self.mesh_a, overwrite=True)
        self.assertEqual(self.store.names(), ["Profile One"])
        self.assertAlmostEqual(
            self.store.load("PROFILE ONE", self.mesh_a).opacity, .91)
        self.store.delete("pRoFiLe OnE")
        self.assertEqual(self.store.names(), [])
        self.assertEqual(self.image.read_bytes(), self.original)
        with self.assertRaises(ProfileError):
            self.store.delete("Profile One")

    def test_bad_profile_and_corrupted_library_do_not_overwrite(self):
        with self.assertRaises(ProfileError):
            self.store.save("  ", self.ref, self.mesh_a)
        self.store.save("Safe", self.ref, self.mesh_a)
        before = self.library.read_bytes()
        with self.assertRaises(ProfileError):
            self.store.save("SAFE", self.ref, self.mesh_a)
        self.assertEqual(before, self.library.read_bytes())
        self.assertEqual(self.image.read_bytes(), self.original)
        self.library.write_text("{invalid JSON")
        with self.assertRaisesRegex(ProfileError, "Cannot read"):
            self.store.load("Safe", self.mesh_a)
        with self.assertRaisesRegex(ProfileError, "Cannot read"):
            self.store.save("New", self.ref, self.mesh_a)
        self.assertEqual(self.library.read_text(), "{invalid JSON")

    def test_invalid_serialized_values_rejected_before_rendering(self):
        self.store.save("Bad", self.ref, self.mesh_a)
        original = json.loads(self.library.read_text())
        for field, value in (
                ("units_per_pixel", 0),
                ("plane", "Depth"),
                ("opacity", 5),
                ("anchor_pixel", [1]),
                ("world_anchor", [float("inf"), 0]),
                ("image_path", "../relative.png"),
                ("width", -1),
                ("point_a", [float("nan"), 1]),
                ("visible", "true")):
            with self.subTest(field=field):
                broken = json.loads(json.dumps(original))
                broken["profiles"][0][field] = value
                self.library.write_text(json.dumps(broken))
                with self.assertRaises(ProfileError):
                    self.store.load("Bad", self.mesh_a)
        self.assertEqual(self.image.read_bytes(), self.original)

    def test_all_models_are_independent_of_profile_file_operations(self):
        from three_do import Model
        model = Model(Path(__file__).resolve().parents[1] /
                      "fixtures" / "roadcar.3do", associate_planes=False)
        raw = model.raw
        self.store.save("test", self.ref, self.mesh_a)
        self.store.load("test", self.mesh_b)
        self.store.delete("test")
        self.assertEqual(model.raw, raw)
        self.assertFalse(model.dirty)


if __name__ == "__main__":
    unittest.main()
