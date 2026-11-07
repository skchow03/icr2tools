"""Driver RECOLOR applies to all 8 helmet PMP/PMP2 angles, not wheel MIPs.

The GPU retains indexed sprites, selecting an angle through the helmet
3DO BSP as before. Recolor the per-appearance GPU index image, not the PMP
file, its alpha channel, the current PCX palette, or unrelated scenery.
"""
from pathlib import Path
import unittest

import numpy as np

from car_appearance import read_car_appearance
from scene import build_scene, ordered_scene_indices
from mesh import make_mesh
from sprites import prepare_scene_sprites
from three_do import Model

FIX = Path(__file__).resolve().parents[1] / "fixtures"


class CarHelmetRecolorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wrapper = read_car_appearance(FIX / "cit74.3do")
        cls.base = Model(FIX / "indycar.3do", associate_planes=False)

    def load(self, *, appearance=None, helmet_file=None):
        overrides = {"helmet": FIX / helmet_file} if helmet_file else None
        scene = build_scene(
            self.base, objects_folder=FIX, object_overrides=overrides,
            appearance=appearance)
        scene.sprite_resources = prepare_scene_sprites(
            scene, objects_folder=FIX)
        self.assertFalse(scene.sprite_resources.warnings,
                         scene.sprite_resources.warnings)
        return scene

    @staticmethod
    def helmet_placements(scene):
        return {
            offset: (instance_id, placement)
            for (instance_id, offset), placement
            in scene.sprite_resources.placements.items()
            if scene.instances[instance_id].model.path.stem.casefold().startswith("helmet")
        }

    def assert_helmet_palette(self, helmet_file):
        plain = self.load(helmet_file=helmet_file)
        painted = self.load(appearance=self.wrapper, helmet_file=helmet_file)
        source = self.helmet_placements(plain)
        target = self.helmet_placements(painted)
        self.assertEqual(len(source), 8)
        self.assertEqual(len(target), 8)
        self.assertEqual(set(source), set(target))
        self.assertEqual(len(plain.sprite_resources.images), 8)
        self.assertEqual(len(painted.sprite_resources.images), 8)
        indices = np.asarray(
            [self.wrapper.map_color(index) for index in range(256)],
            dtype=np.uint8)
        changed = 0
        for offset in source:
            original_id, original_placement = source[offset]
            painted_id, painted_placement = target[offset]
            original = plain.sprite_resources.images[original_placement.image_key]
            recolored = painted.sprite_resources.images[painted_placement.image_key]
            np.testing.assert_array_equal(recolored[..., 0],
                                          indices[original[..., 0]])
            np.testing.assert_array_equal(recolored[..., 1],
                                          original[..., 1])
            self.assertEqual(original_placement.xyz, painted_placement.xyz)
            self.assertEqual(original_placement.bounds, painted_placement.bounds)
            self.assertNotEqual(original_placement.image_key,
                                painted_placement.image_key)
            changed += np.count_nonzero(original[..., 0] != recolored[..., 0])
            self.assertTrue(painted.sprite_resources.placements[
                (painted_id, offset)].image_key)
        self.assertGreater(changed, 100)
        # The existing helmet BSP still selects one angle, not all eight.
        mesh = make_mesh(painted.geometry)
        _, _, stats, events = ordered_scene_indices(
            painted, mesh, (10000, 10000, 50000), 0, with_sprites=True)
        self.assertEqual(stats["pmp_sprites"], 1)
        self.assertEqual(len(events), 1)

    def test_regular_helmet_pmp_recolored_for_every_angle(self):
        self.assert_helmet_palette("helmet.3do")

    def test_pit_helmet_pmp2_recolored_for_every_angle(self):
        self.assert_helmet_palette("helmetp.3do")

    def test_helmet_inherits_recolor_but_not_body_mip(self):
        scene = self.load(appearance=self.wrapper)
        self.assertEqual(scene.appearance, self.wrapper)
        for instance in scene.instances:
            stem = instance.model.path.stem.casefold()
            if stem.startswith("helmet"):
                self.assertEqual(instance.recolor_layers,
                                 (self.wrapper.mapping,))
                self.assertFalse(instance.car_body)
                self.assertIsNone(instance.texture_override)
            elif stem in {"sfront", "srear", "fwheel", "rwheel"}:
                self.assertFalse(instance.recolor_layers)
                if stem in {"sfront", "srear"}:
                    self.assertIsNone(instance.texture_override)
                else:
                    self.assertEqual(instance.texture_override, "wheel1")

    def test_plain_standalone_helmet_keeps_original_pmp_indices(self):
        helmet = Model(FIX / "helmet.3do", associate_planes=False)
        scene = build_scene(helmet, objects_folder=FIX)
        resources = prepare_scene_sprites(scene, objects_folder=FIX)
        self.assertFalse(resources.warnings)
        self.assertEqual(len(resources.images), 8)
        self.assertTrue(all("#recolor-" not in key for key in resources.images))


if __name__ == "__main__":
    unittest.main()
