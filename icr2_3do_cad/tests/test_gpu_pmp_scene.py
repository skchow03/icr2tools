"""PMP/PMP2 sprite preparation and BSP event regressions (no Qt/GL)."""
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from three_do import Model
from pmp_preview import load_pmp
from gpu_viewer.scene import build_scene, ordered_scene_indices
from gpu_viewer.mesh import make_mesh
from gpu_viewer.sprites import prepare_scene_sprites, draw_runs


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
GREY = [(i, i, i) for i in range(256)]


class PMPGPUSceneTests(unittest.TestCase):
    def _prepare(self, model_name, **opts):
        model = Model(FIXTURES / model_name, associate_planes=False)
        scene = build_scene(model, objects_folder=FIXTURES)
        resources = prepare_scene_sprites(
            scene, objects_folder=FIXTURES, **opts)
        scene.sprite_resources = resources
        scene.geometry.sprite_bounds = resources.bounds_points
        return model, scene, resources

    def test_real_helmet_pmp_and_pmp2_decode_palette_and_alpha(self):
        for name in ("helmet.3do", "helmetp.3do"):
            with self.subTest(name=name):
                model, scene, resources = self._prepare(name)
                self.assertEqual(len(resources.placements), 8)
                self.assertEqual(len(resources.images), 8)
                self.assertFalse(resources.warnings)
                self.assertEqual(len(resources.bounds_points), 16)
                self.assertGreater(resources.decoded_bytes, 0)
                self.assertTrue(all(x.shape[2] == 2 and x.dtype == np.uint8
                                    for x in resources.images.values()))
                sprite = next(iter(resources.placements.values()))
                self.assertIn(sprite.image_key, resources.images)
                actual = resources.images[sprite.image_key]
                rgba = np.asarray(load_pmp(
                    FIXTURES / (model.pmp_sprites[sprite.offset].name + ".pmp"),
                    GREY).rgba)
                self.assertTrue(np.array_equal(actual[..., 0], rgba[..., 0]))
                self.assertTrue(np.array_equal(actual[..., 1], rgba[..., 3]))
                self.assertTrue(np.any(actual[..., 1] == 0))
                self.assertTrue(np.any(actual[..., 1] == 255))
                self.assertGreater(sprite.normalized_pixel_size, 0)

    def test_root_only_sprite_model_has_useful_mesh_bounds(self):
        _, scene, resources = self._prepare("helmet.3do")
        mesh = make_mesh(scene.geometry)
        self.assertEqual(mesh.triangle_count, 0)
        self.assertEqual(mesh.polygon_count, 0)
        self.assertGreater(mesh.scale, 1.0)
        self.assertTrue(np.isfinite(mesh.center).all())
        for eye in ((10000, 0, 1500), (10000, 10000, 1500),
                    (-10000, 0, 1500), (0, -10000, 1500)):
            indices, visible, info, sprite_events = ordered_scene_indices(
                scene, mesh, eye, 0, with_sprites=True)
            self.assertEqual(len(indices), 0)
            self.assertEqual(len(visible), 0)
            self.assertEqual(info["pmp_sprites"], 1)
            self.assertEqual(len(sprite_events), 1)
            self.assertEqual(sprite_events[0][0], 0)
            self.assertEqual(
                sprite_events[0][1][0], 0)
            self.assertEqual(
                [x[0] for x in draw_runs(0, sprite_events)], ["pmp"])

    def test_referenced_helmet_transform_bsp_and_painter_insertion(self):
        model, scene, resources = self._prepare("indycar.3do")
        self.assertGreater(scene.loaded_instances, 0)
        self.assertEqual(len(resources.placements), 8)
        self.assertEqual(len(resources.images), 8)
        self.assertFalse(resources.warnings)
        helmet_id = next(i for i, x in enumerate(scene.instances)
                         if x.model.path.name.casefold() == "helmet.3do")
        self.assertEqual(len([
            key for key in resources.placements if key[0] == helmet_id]), 8)
        for x, y in ((0, -100000), (100000, 30000), (-100000, 30000)):
            mesh = make_mesh(scene.geometry)
            indices, visible, stats, sprite_events = ordered_scene_indices(
                scene, mesh, (x, y, 50000), 0, with_sprites=True)
            self.assertGreater(len(indices), 0)
            self.assertEqual(stats["pmp_sprites"], 1)
            self.assertEqual(len(sprite_events), 1)
            position, key = sprite_events[0]
            self.assertEqual(key[0], helmet_id)
            self.assertTrue(0 <= position <= len(indices))
            sprite = resources.placements[key]
            self.assertEqual(sprite.xyz, (10761., 0., 4035.))
            commands = draw_runs(len(indices), sprite_events)
            self.assertEqual(sum(c[2] for c in commands
                                 if c[0] == "polygons"), len(indices))
            self.assertEqual(sum(c[0] == "pmp" for c in commands), 1)

    def test_no_sprite_scene_keeps_original_three_value_api(self):
        model = Model(FIXTURES / "roadcar.3do", associate_planes=False)
        scene = build_scene(model)
        mesh = make_mesh(scene.geometry)
        old = ordered_scene_indices(
            scene, mesh, (-36000, -80000, 7000), 0)
        self.assertEqual(len(old), 3)
        self.assertGreater(old[0].size, 0)

    def test_missing_pmp_is_nonfatal_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "helmet.3do"
            shutil.copyfile(FIXTURES / "helmet.3do", path)
            scene = build_scene(Model(path, associate_planes=False))
            sprites = prepare_scene_sprites(scene)
            self.assertEqual(sprites.placements, {})
            self.assertEqual(sprites.images, {})
            self.assertTrue(sprites.warnings)
            mesh = make_mesh(scene.geometry)
            scene.sprite_resources = sprites
            _, _, info, events = ordered_scene_indices(
                scene, mesh, (10000, 0, 1500), 0, with_sprites=True)
            self.assertFalse(events)
            self.assertEqual(info["pmp_sprites"], 0)

    def test_memory_budget_skips_pmp_without_crash(self):
        _, _, resources = self._prepare("helmet.3do", max_bytes=1)
        self.assertFalse(resources.images)
        self.assertFalse(resources.placements)
        self.assertTrue(any("memory budget" in x for x in resources.warnings))

    def test_draw_runs_include_zero_geometry_and_consecutive_sprites(self):
        self.assertEqual(draw_runs(0, ((0, (0, 20)), (0, (0, 30)))), [
            ("pmp", (0, 20)), ("pmp", (0, 30))])
        self.assertEqual(draw_runs(12, ((3, (0, 20)), (9, (1, 30)))), [
            ("polygons", 0, 3), ("pmp", (0, 20)),
            ("polygons", 3, 6), ("pmp", (1, 30)),
            ("polygons", 9, 3)])
        with self.assertRaises(ValueError):
            draw_runs(8, ((9, (0, 20)),))


if __name__ == "__main__":
    unittest.main()
