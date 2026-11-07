"""A driver's RECOLOR/MIP can preview on any open car-part geometry.

The wrapper's EXTERN geometry reference is informational only for overlays.
No source, binary, external part, or texture file is modified by the preview.
"""
from pathlib import Path
import shutil
import tempfile
import unittest

from car_appearance import read_car_appearance, AppearanceError
from scene import load_car_or_model
from textures import build_atlas
from three_do import Model

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "fixtures"


class CarAppearanceOverlayTests(unittest.TestCase):
    def setUp(self):
        self.model = Model(FIX / "roadcar.3do", associate_planes=False)
        self.raw = self.model.raw
        self.wrapper = read_car_appearance(FIX / "cit74.3do")

    def test_reference_is_ignored_and_original_model_is_preserved(self):
        # Real CIT74 references INDYCAR even when ROADCAR is the editor root.
        self.assertEqual(self.wrapper.geometry_name.casefold(), "indycar")
        self.assertEqual(self.wrapper.texture_name.casefold(), "cit74")
        model, scene, chosen = load_car_or_model(
            self.model.path, existing_model=self.model,
            appearance_override=self.wrapper)
        self.assertIs(model, self.model)
        self.assertIs(scene.root, self.model)
        self.assertIs(scene.instances[0].model, self.model)
        self.assertEqual(chosen, self.wrapper)
        self.assertEqual(scene.appearance, self.wrapper)
        self.assertEqual(self.model.raw, self.raw)
        self.assertEqual(self.model.build_modified_bytes()[0], self.raw)
        self.assertFalse(self.model.dirty)
        self.assertEqual(scene.recolor_pairs, len(self.wrapper.mapping))
        for off, polygon in self.model.polygons.items():
            face = scene.geometry.polygons[scene.polygon_lookup[0, off]]
            self.assertEqual(face.color, self.wrapper.map_color(polygon.color))
            if polygon.kind == 2:
                pid = scene.polygon_lookup[0, off]
                self.assertEqual(scene.geometry.polygon_materials[pid], "cit74")
                self.assertEqual(scene.geometry.polygon_sources[pid],
                                 self.wrapper.path)

    def test_external_wheels_do_not_receive_body_recolor_or_livery(self):
        model, scene, _ = load_car_or_model(
            self.model.path, existing_model=self.model,
            appearance_override=self.wrapper)
        self.assertGreater(scene.loaded_instances, 0)
        for (instance, off), new_off in scene.polygon_lookup.items():
            original = scene.instances[instance].model.polygons[off]
            preview = scene.geometry.polygons[new_off]
            expected = (self.wrapper.map_color(original.color)
                        if instance == 0 else original.color)
            self.assertEqual(preview.color, expected)
            if instance != 0:
                self.assertNotEqual(scene.geometry.polygon_sources.get(new_off),
                                    self.wrapper.path)

    def test_body_livery_resolves_beside_wrapper_not_base_car(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            wrapper_path = folder / "cit74.3do"
            mip = folder / "cit74.mip"
            shutil.copyfile(self.wrapper.path, wrapper_path)
            shutil.copyfile(FIX / "ind96.mip", mip)
            app = read_car_appearance(wrapper_path)
            _, scene, _ = load_car_or_model(
                self.model.path, existing_model=self.model,
                appearance_override=app)
            atlas = build_atlas(scene.geometry, self.model.path)
            self.assertIn("cit74.mip", atlas.loaded_names)
            self.assertTrue(scene.geometry.body_polygons)
            self.assertTrue(
                scene.geometry.body_polygons.issubset(atlas.polygon_rects))
            self.assertNotIn("cit74", atlas.missing_names)
            self.assertEqual(self.model.raw, self.raw)

    def test_switch_and_clear_restore_original_preview_only(self):
        base_model, base_scene, _ = load_car_or_model(
            self.model.path, existing_model=self.model)
        _, with_wrapper, _ = load_car_or_model(
            self.model.path, existing_model=self.model,
            appearance_override=self.wrapper)
        self.assertIs(base_model, self.model)
        self.assertIsNone(base_scene.appearance)
        self.assertEqual(self.model.raw, self.raw)
        self.assertTrue(any(
            with_wrapper.geometry.polygons[with_wrapper.polygon_lookup[0, off]].color
            != base_scene.geometry.polygons[base_scene.polygon_lookup[0, off]].color
            for off in self.model.polygons))
        after_model, cleared, app = load_car_or_model(
            self.model.path, existing_model=self.model)
        self.assertIs(after_model, self.model)
        self.assertIsNone(app)
        self.assertEqual(
            {i:p.color for i,p in cleared.geometry.polygons.items()},
            {i:p.color for i,p in base_scene.geometry.polygons.items()})
        self.assertEqual(self.model.raw, self.raw)

    def test_overlay_accepts_indycar_and_individual_parts(self):
        for name in ("indycar.3do", "fwheel.3do"):
            with self.subTest(model=name):
                model = Model(FIX / name, associate_planes=False)
                original = model.raw
                loaded, scene, app = load_car_or_model(
                    model.path, existing_model=model,
                    appearance_override=self.wrapper)
                self.assertIs(loaded, model)
                self.assertEqual(scene.appearance, app)
                self.assertEqual(loaded.raw, original)

    def test_bad_wrapper_is_not_treated_as_car_appearance(self):
        with self.assertRaises(AppearanceError):
            read_car_appearance(self.model.path)
        with self.assertRaisesRegex(ValueError, "already-open"):
            load_car_or_model(self.model.path,
                              appearance_override=self.wrapper)


if __name__ == "__main__":
    unittest.main()
