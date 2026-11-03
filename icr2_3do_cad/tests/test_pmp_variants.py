"""PMP extent-header and optional-footer regressions.

The first four PMP bytes are per-image extent metadata, not signatures.
Synthetic tests reproduce measured bounds for real tree1..tree4 artwork
without including the original proprietary image data in the repository.
"""
import struct
import tempfile
import unittest
from pathlib import Path

from pmp_preview import PMPError, load_pmp
from three_do import Model
from gpu_viewer.scene import build_scene, ordered_scene_indices
from gpu_viewer.mesh import make_mesh
from gpu_viewer.sprites import prepare_scene_sprites


PALETTE = [(i, i, i) for i in range(256)]
# Synthetic endpoints with the same extent headers as the uploaded sprites.
TREE_BOUNDS = {
    "tree1": ((7, 66, 67, 232), (127, 187, 188, 47)),
    "tree2": ((5, 81, 82, 232), (127, 171, 172, 47)),
    "tree3": ((10, 86, 87, 232), (131, 170, 171, 47)),
    "tree4": ((13, 76, 77, 232), (126, 183, 184, 47)),
}
TREE_HEADERS = {
    "tree1": bytes.fromhex("7a79bef9"),
    "tree2": bytes.fromhex("5b7baffb"),
    "tree3": bytes.fromhex("557aaaf6"),
    "tree4": bytes.fromhex("6c72b4f3"),
}
# Stock helmet PMP header is 4c38aaaf; its final 0xaf is a footer,
# unlike the scenery files where the final four bytes are image data.
HELMET_SPANS = ((81, 86, 87, 232), (136, 161, 162, 47))


def extent_header(spans):
    if not spans:
        return b"\0\0\0\0"
    min_x = min(s[1] for s in spans)
    max_x = max(s[2] for s in spans)
    min_y = min(s[0] for s in spans)
    max_y = max(s[0] for s in spans)
    return bytes((max_x-min_x, max_y-min_y+1,
                  (-min_x) & 0xff, (-min_y) & 0xff))


def pmp_bytes(spans=TREE_BOUNDS["tree2"], *, terminated=False):
    payload = b"".join(bytes(span) for span in spans)
    if terminated:
        payload += b"\xaf"
    return (extent_header(spans) + struct.pack("<II", len(payload), 30)
            + payload)


def tree_3do_bytes():
    # Real scenery 3DO structure: 60-byte model with root sprite and
    # vertex zero, 8-byte sprite name and PMP size 204000.
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

    def test_all_four_tree_extent_headers_vary_and_decode_without_footer(self):
        for name, spans in TREE_BOUNDS.items():
            with self.subTest(name=name):
                raw = pmp_bytes(spans)
                self.assertEqual(raw[:4], TREE_HEADERS[name])
                sprite = self.load_bytes(raw)
                x0 = min(row[1] for row in spans)
                y0 = min(row[0] for row in spans)
                x1 = max(row[2] for row in spans)
                y1 = max(row[0] for row in spans) + 1
                self.assertEqual(sprite.bounds, (x0, y0, x1, y1))
                self.assertEqual(sprite.rgba.size, (x1-x0, y1-y0))
                self.assertEqual(sprite.rgba.getpixel(
                    (x1-x0-1, y1-y0-1)), (47, 47, 47, 255))
                self.assertEqual(sprite.auxiliary, 30)

    def test_stock_helmet_header_and_footer_remain_supported(self):
        raw = pmp_bytes(HELMET_SPANS, terminated=True)
        self.assertEqual(raw[:4], bytes.fromhex("4c38aaaf"))
        self.assertEqual(raw[-1], 0xaf)
        sprite = self.load_bytes(raw)
        self.assertEqual(sprite.bounds, (86, 81, 162, 137))
        self.assertEqual(sprite.rgba.getpixel((75, 55)),
                         (47, 47, 47, 255))

    def test_scenery_may_also_have_footer_based_on_record_alignment(self):
        sprite = self.load_bytes(pmp_bytes(terminated=True))
        self.assertEqual(sprite.bounds, (81, 5, 172, 128))

    def test_reject_malformed_framing_extent_and_empty_data(self):
        sample = pmp_bytes()
        for raw in (
            sample + b"\xaf\0",
            sample + b"\x01",
            sample[:-1],
            sample[:-2],
            sample[:-3],
            b"invalid" + sample[7:],
            b"\0" * 16,
            pmp_bytes(spans=()),
        ):
            with self.subTest(raw=raw[:16].hex()), self.assertRaises(PMPError):
                self.load_bytes(raw)

        damaged = bytearray(sample)
        damaged[0] ^= 1
        with self.assertRaisesRegex(PMPError, "extent header"):
            self.load_bytes(bytes(damaged))
        # A structurally aligned but tampered last record must fail even
        # though its declared byte count and framing remain plausible.
        damaged = bytearray(sample)
        damaged[-2] = 170  # x1 less than x0=171
        with self.assertRaisesRegex(PMPError, "inverted"):
            self.load_bytes(bytes(damaged))

    def test_reject_bad_declared_size(self):
        raw = bytearray(pmp_bytes())
        struct.pack_into("<I", raw, 4, 123456)
        with self.assertRaisesRegex(PMPError, "size"):
            self.load_bytes(bytes(raw))

    def test_tree_style_3do_resolves_variable_header_and_traverses_sprite(self):
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
                scene.sprite_resources.placements[
                    (0, model.root_offset)].xyz, (0., 0., 0.))
            scene.geometry.sprite_bounds = scene.sprite_resources.bounds_points
            mesh = make_mesh(scene.geometry)
            self.assertEqual(mesh.polygon_count, 0)
            self.assertGreater(mesh.scale, 1000)
            indices, visible, info, sprite_events = ordered_scene_indices(
                scene, mesh, (10000, 0, 20000), 0, with_sprites=True)
            self.assertEqual(len(indices), 0)
            self.assertEqual(len(visible), 0)
            self.assertEqual(info["pmp_sprites"], 1)
            self.assertEqual(sprite_events,
                             ((0, (0, model.root_offset)),))
            bitmap = next(iter(scene.sprite_resources.images.values()))
            self.assertEqual(bitmap.shape, (123, 91, 2))
            self.assertEqual(tuple(bitmap[-1, -1]), (47, 255))


if __name__ == "__main__":
    unittest.main()
