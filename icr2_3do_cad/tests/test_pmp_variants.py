"""PMP variant regression: helmet terminator vs terminator-free scenery.

tree2.pmp reported from a real scenery 3DO uses marker 5b7baffb,
a 19488-byte payload of four-byte spans, auxiliary=30, and no footer.
Use tiny deterministic fixtures with the same framing, rather than storing
user-provided third-party sprite artwork in the repository.
"""
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from pmp_preview import PMPError, load_pmp
from three_do import Model
from gpu_viewer.scene import build_scene, ordered_scene_indices
from gpu_viewer.mesh import make_mesh
from gpu_viewer.sprites import prepare_scene_sprites


HELMET = bytes.fromhex("4c38aaaf")
SCENERY = bytes.fromhex("5b7baffb")
PALETTE = [(i, i, i) for i in range(256)]
SPANS = ((5, 126, 128, 232), (6, 125, 127, 44), (127, 131, 132, 47))


def pmp_bytes(marker=SCENERY, spans=SPANS):
    payload = b"".join(bytes(span) for span in spans)
    if marker == HELMET:
        payload += b"\xaf"
    return marker + struct.pack("<II", len(payload), 30) + payload


def tree_3do_bytes():
    # Matches the uploaded tree2.3do record layout: one PMP at root offset
    # 16 referencing vertex 0, name table entry 0 and size 204000.
    return (
        struct.pack("<5i", 32, 16, 0, 1, 0) + b"tree2\0\0\0" +
        struct.pack("<8i", 0, 0, 0, 0, -(1 << 31) + 3, 0, 204000, 0)
    )


class PMPVariantsTests(unittest.TestCase):
    def load_bytes(self, raw):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "sample.pmp"
            file.write_bytes(raw)
            return load_pmp(file, PALETTE)

    def test_scenery_no_terminator_last_record_is_image_data(self):
        sprite = self.load_bytes(pmp_bytes())
        self.assertEqual(sprite.auxiliary, 30)
        self.assertEqual(sprite.bounds, (125, 5, 132, 128))
        self.assertEqual(sprite.rgba.size, (7, 123))
        self.assertEqual(sprite.rgba.getpixel((6, 122)), (47, 47, 47, 255))
        self.assertEqual(sprite.rgba.getpixel((0, 0)), (0, 0, 0, 0))
        self.assertEqual(sprite.rgba.getpixel((1, 0)), (232, 232, 232, 255))

    def test_helmet_original_terminator_is_still_supported(self):
        sprite = self.load_bytes(pmp_bytes(HELMET))
        self.assertEqual(sprite.auxiliary, 30)
        self.assertEqual(sprite.bounds, (125, 5, 132, 128))
        self.assertEqual(sprite.rgba.getpixel((6, 122)), (47, 47, 47, 255))

    def test_reject_mismatched_framing_in_both_directions(self):
        for data in (
            SCENERY + pmp_bytes(HELMET)[4:],
            HELMET + pmp_bytes(SCENERY)[4:],
            pmp_bytes(SCENERY) + b"\xaf",
            pmp_bytes(HELMET)[:-1],
            pmp_bytes(SCENERY)[:-1],
            pmp_bytes(SCENERY)[:-2],
            b"invalid" + pmp_bytes(SCENERY)[7:],
            pmp_bytes(SCENERY, spans=()),
            pmp_bytes(HELMET, spans=()),
        ):
            with self.subTest(raw=data[:16].hex()), self.assertRaises(PMPError):
                self.load_bytes(data)

    def test_reject_bad_declared_size_or_inverted_span(self):
        data = bytearray(pmp_bytes(SCENERY))
        struct.pack_into("<I", data, 4, 123456)
        with self.assertRaisesRegex(PMPError, "size"):
            self.load_bytes(bytes(data))
        with self.assertRaisesRegex(PMPError, "inverted"):
            self.load_bytes(pmp_bytes(
                SCENERY, spans=((5, 150, 149, 20),)))

    def test_tree_style_3do_resolves_and_traverses_real_sprite_path(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "tree2.3do").write_bytes(tree_3do_bytes())
            (folder / "TREE2.PMP").write_bytes(pmp_bytes())
            model = Model(folder / "tree2.3do", associate_planes=False)
            self.assertEqual(len(model.pmp_sprites), 1)
            sprite = next(iter(model.pmp_sprites.values()))
            self.assertEqual(sprite.name.casefold(), "tree2")
            self.assertEqual(sprite.kind, 3)
            self.assertEqual(sprite.size, 204000)
            scene = build_scene(model)
            scene.sprite_resources = prepare_scene_sprites(scene)
            self.assertFalse(scene.sprite_resources.warnings)
            self.assertEqual(len(scene.sprite_resources.images), 1)
            self.assertEqual(len(scene.sprite_resources.placements), 1)
            self.assertEqual(
                scene.sprite_resources.placements[(0, model.root_offset)].xyz,
                (0., 0., 0.))
            scene.geometry.sprite_bounds = scene.sprite_resources.bounds_points
            mesh = make_mesh(scene.geometry)
            self.assertEqual(mesh.polygon_count, 0)
            self.assertGreater(mesh.scale, 1000)
            indices, visible, info, sprite_events = ordered_scene_indices(
                scene, mesh, (10000, 0, 20000), 0, with_sprites=True)
            self.assertEqual(len(indices), 0)
            self.assertEqual(len(visible), 0)
            self.assertEqual(info["pmp_sprites"], 1)
            self.assertEqual(sprite_events, ((0, (0, model.root_offset)),))
            bitmap = next(iter(scene.sprite_resources.images.values()))
            self.assertEqual(bitmap.shape, (123, 7, 2))
            self.assertEqual(tuple(bitmap[-1, -1]), (47, 255))


if __name__ == "__main__":
    unittest.main()
