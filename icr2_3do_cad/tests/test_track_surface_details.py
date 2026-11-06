"""Track Surface Detail structural detection and EBO regressions.

Synthetic original binary and N3 fixtures (no proprietary track files).
"""
import struct
import unittest

import numpy as np

from mesh import make_mesh
from scene import build_scene, ordered_scene_indices
from track_surface_details import detect_track_surface_details
from n3_compile import compile_n3_text
from three_do import Model


TRACK_SOURCE = """3D VERSION 3.0;
a: [<-100000,-100000,0>];
b: [<100000,-100000,0>];
c: [<100000,100000,0>];
d: [<-100000,100000,0>];
e: [<-20000,-40000,0>];
f: [<20000,-40000,0>];
g: [<20000,40000,0>];
h: [<-20000,40000,0>];
road: POLY <20> {a,b,c,d};
mark: POLY <178> {e,f,g,h};
mark_line: LINE <178> {e,g};
other_mark: POLY <179> {e,f,g,h};
other_line: LINE <179> {f,h};
decals: LIST {mark, mark_line, other_mark, other_line};
not_decal: POLY <179> {a,b,c,d};
ordinary: LIST {not_decal, road};
hi: LIST {road, decals, ordinary};
lo: LIST {road};
section: LIST {hi, nil, nil, nil, nil, nil, lo,
               DATA {0, 25000, 50000, 75000}};
hash: DATA {0};
root: LIST {hash, section};
"""


class SurfaceDetailsTests(unittest.TestCase):
    def setUp(self):
        self.source, _ = compile_n3_text(
            TRACK_SOURCE, "track.3d", associate_planes=False)
        self.s = self.source.n3_label_offsets

    def test_n3_detail_list_does_not_bias_ordinary_untextured_polygons(self):
        found = detect_track_surface_details(self.source)
        self.assertEqual(found, frozenset({
            self.s["mark"], self.s["other_mark"]}))
        scene = build_scene(self.source)
        self.assertEqual(scene.track_surface_details, found)
        self.assertNotIn(self.s["road"], found)
        self.assertNotIn(self.s["not_decal"], found)
        self.assertNotIn(self.s["mark_line"], found)

    def test_compiled_detail_list_with_flavor_zero_nil_and_dynamics(self):
        raw = bytearray(self.source.raw)
        # In compiled originals, each LINE becomes flavor-zero NIL. It
        # still occupies its slot in the DetailList, but is not a marking.
        for line in ("mark_line", "other_line"):
            off = self.s[line]
            struct.pack_into("<i", raw, self.source.body_start + off, 0)
        binary = Model("track.3do", raw_data=raw, associate_planes=False)
        found = detect_track_surface_details(binary)
        self.assertEqual(found, frozenset({
            self.s["mark"], self.s["other_mark"]}))
        scene = build_scene(binary)
        self.assertEqual(scene.track_surface_details, found)

    def test_only_visible_details_enter_overlay_and_order_remains_unchanged(self):
        scene = build_scene(self.source)
        mesh = make_mesh(scene.geometry)
        regular = ordered_scene_indices(
            scene, mesh, (0,0,100000), bsp_mode="off", track_detail="hi")
        selected = ordered_scene_indices(
            scene, mesh, (0,0,100000), bsp_mode="off", track_detail="hi",
            with_sprites=True, with_surface_details=True)
        indices, visible, stats, sprites, overlays = selected
        self.assertTrue(np.array_equal(regular[0], indices))
        self.assertEqual(regular[1], visible)
        self.assertEqual(sprites, ())
        self.assertEqual(stats["surface_detail_polygons"], 2)
        expected = []
        for label in ("mark", "other_mark"):
            poly = scene.polygon_lookup[(0, self.s[label])]
            start, count = mesh.polygon_ranges[poly]
            expected.extend(range(start, start+count))
        np.testing.assert_array_equal(overlays, np.array(expected, dtype=np.uint32))
        low = ordered_scene_indices(
            scene, mesh, (0,0,100000), bsp_mode="off", track_detail="lo",
            with_surface_details=True)
        self.assertEqual(low[3].size, 0)
        self.assertEqual(low[2]["surface_detail_polygons"], 0)

    def test_invalid_pair_and_standalone_nontrack_are_not_selected(self):
        standalone, _ = compile_n3_text(
            TRACK_SOURCE.replace("root: LIST {hash, section};",
                                 "root: LIST {hi};"),
            "standalone.3d", associate_planes=False)
        self.assertFalse(build_scene(standalone).track_surface_details)
        invalid, _ = compile_n3_text(
            TRACK_SOURCE.replace(
                "decals: LIST {mark, mark_line, other_mark, other_line};",
                "decals: LIST {mark, road, other_mark, other_line};"),
            "invalid.3d", associate_planes=False)
        found = detect_track_surface_details(invalid)
        self.assertFalse(found)


if __name__ == "__main__":
    unittest.main()
