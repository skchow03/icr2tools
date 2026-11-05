"""Authored BSP plane winding: cursor indexing, exact vertex resolution, projection."""
import unittest
from types import SimpleNamespace

import numpy as np

from gpu_viewer.source_inspection import (
    bsp_plane_points, bsp_winding_arrows, index_source_targets,
    raw_point_screen_position, target_offset,
)
from n3_compile import compile_n3_text


SOURCE = """3D VERSION 3.0;
a: [<0,0,0>];
b: [<1000,0,0>];
c: [<0,1000,0>];
plane_a: [<0,0,500>];
plane_b: [<1000,0,500>];
plane_c: [<0,1000,500>];
panel: POLY <44> {a,b,c};
partition: BSPF (plane_a, plane_b, plane_c), NIL, panel, NIL;
root: LIST {partition};
"""

INLINE_SOURCE = SOURCE.replace(
    "partition: BSPF (plane_a, plane_b, plane_c)",
    "partition: BSPA ([<0,0,500>], [<1000,0,500>], [<0,1000,500>])")

# Exact geometry and root BSP statement from the reported failure.
ROOT_BSP_SOURCE = """3D VERSION 3.0;
_0: [<1686000, 0, 1056000>];
_16: [<1686000, 0, 0>];
_32: [<0, 0, 0>];
_48: [<0, 0, 1056000>];
_64: [<1686000, -378000, 1056000>];
_80: [<1686000, -378000, 0>];
_96: [<0, -378000, 1056000>];
_112: [<0, -378000, 0>];
_128: NIL;
_132: POLY <41> {_0, _16, _32, _48};
_160: POLY <40> {_64, _80, _16, _0};
_188: POLY <41> {_96, _112, _80, _64};
_216: POLY <40> {_48, _32, _112, _96};
_244: BSPF (_48, _32, _112), _128, _216, _128;
_280: BSPF (_96, _112, _80), _128, _188, _244;
_316: BSPF (_64, _80, _16), _128, _160, _280;
root: BSPF (_0, _16, _32), _128, _132, _316;
"""


class BSPInspectionTests(unittest.TestCase):
    def test_indexes_bsp_and_multiline_continuations(self):
        for kind in ("BSPF", "BSPA", "BSP2", "BSPN"):
            with self.subTest(kind=kind):
                text = SOURCE.replace(
                    "partition: BSPF (plane_a, plane_b, plane_c)",
                    f"partition: {kind} (plane_a,\n"
                    "    plane_b, plane_c)")
                index = index_source_targets(text)
                self.assertEqual(index.at_line(8), ("bsp", "partition"))
                self.assertEqual(index.at_line(9), ("bsp", "partition"))
                target = index.target_at_line(9)
                self.assertEqual(target.plane_operands,
                                 ("plane_a", "plane_b", "plane_c"))
                self.assertIsNone(index.at_line(10))

    def test_plane_only_vertices_are_resolved_using_compiled_bytes(self):
        model, _ = compile_n3_text(
            SOURCE, "bsp_source.3d", associate_planes=False)
        self.assertNotIn(model.n3_label_offsets["plane_a"], model.vertices)
        self.assertEqual(
            target_offset(model, "bsp", "partition"),
            model.n3_label_offsets["partition"])
        self.assertEqual(
            bsp_plane_points(index_source_targets(SOURCE), model, 8),
            ((0, 0, 500), (1000, 0, 500), (0, 1000, 500)))
        self.assertIsNone(
            bsp_plane_points(index_source_targets(SOURCE), model, 9))

    def test_binary_export_root_bsp_resolves_to_header_root_offset(self):
        # On a freshly loaded .3do there is no n3_label_offsets map.
        # Its exporter renames the actual root plane to "root" instead
        # of "_<offset>", which formerly prevented cursor inspection.
        from three_do import Model
        from text_3d import export_compilable_text

        compiled, _ = compile_n3_text(
            ROOT_BSP_SOURCE, "bsp_root_example.3d",
            associate_planes=False)
        binary = Model("bsp_root_example.3do", raw_data=compiled.raw,
                       associate_planes=False)
        self.assertFalse(hasattr(binary, "n3_label_offsets"))
        self.assertIn(binary.root_offset, binary.planes)
        exported = export_compilable_text(binary)
        index = index_source_targets(exported)
        root_line = next(i for i, line in enumerate(exported.splitlines())
                         if line.startswith("root: BSPF "))
        self.assertEqual(index.at_line(root_line), ("bsp", "root"))
        self.assertEqual(
            target_offset(binary, "bsp", "root"), binary.root_offset)
        self.assertEqual(
            bsp_plane_points(index, binary, root_line),
            ((1686000, 0, 1056000),
             (1686000, 0, 0),
             (0, 0, 0)))
        # Other numeric-offset BSP declarations still resolve.
        other = next(i for i, line in enumerate(exported.splitlines())
                     if ": BSPF (" in line and not line.startswith("root:"))
        self.assertIsNotNone(bsp_plane_points(index, binary, other))

    def test_root_alias_requires_a_matching_record_kind(self):
        from types import SimpleNamespace
        binary = SimpleNamespace(
            root_offset=420, n3_label_offsets={},
            vertices={8: object()}, polygons={15: object()},
            planes={300: object()})
        self.assertIsNone(target_offset(binary, "bsp", "root"))
        binary.planes[420] = object()
        self.assertEqual(target_offset(binary, "bsp", "root"), 420)
        self.assertIsNone(target_offset(binary, "vertex", "root"))
        self.assertIsNone(target_offset(binary, "polygon", "root"))
        # Compiled authored-label mapping takes precedence over the fallback.
        binary.n3_label_offsets = {"root": 300}
        self.assertEqual(target_offset(binary, "bsp", "root"), 300)

    def test_inline_coords_and_compiler_scaling(self):
        model, _ = compile_n3_text(
            INLINE_SOURCE, "bsp_inline.3d", associate_planes=False)
        self.assertEqual(
            bsp_plane_points(index_source_targets(INLINE_SOURCE), model, 8),
            ((0, 0, 500), (1000, 0, 500), (0, 1000, 500)))
        scaled = INLINE_SOURCE.replace(
            "([<0,0,500>], [<1000,0,500>], [<0,1000,500>])",
            "([<0,0,0.5>], [<1,0,0.5>], [<0,1,0.5>])")
        updated, _ = compile_n3_text(
            scaled, "bsp_scaled.3d", associate_planes=False)
        self.assertEqual(
            bsp_plane_points(index_source_targets(scaled), updated, 8),
            ((0, 0, 3000), (6000, 0, 3000), (0, 6000, 3000)))

    def test_integer_coefficients_and_bogus_references_have_no_winding(self):
        coeff = SOURCE.replace(
            "(plane_a, plane_b, plane_c)", "(0, 0, 1, 0, -500)")
        self.assertIsNone(index_source_targets(coeff).at_line(8))
        unknown = SOURCE.replace("plane_b, plane_c", "wrong, plane_c")
        idx = index_source_targets(unknown)
        model, _ = compile_n3_text(
            SOURCE, "bsp_source.3d", associate_planes=False)
        self.assertIsNone(bsp_plane_points(idx, model, 8))
        self.assertIsNone(bsp_plane_points(idx, None, 8))

    def test_raw_xyz_projection_and_clip_for_independent_points(self):
        mesh = SimpleNamespace(center=(0, 0, 0), scale=100.)
        self.assertEqual(
            raw_point_screen_position(mesh, (50, 0, 0),
                                      np.eye(4), 800, 600),
            (600.0, 300.0))
        self.assertIsNone(raw_point_screen_position(
            mesh, (200, 0, 0), np.eye(4), 800, 600))
        self.assertIsNone(raw_point_screen_position(
            mesh, (0, 0, 0), np.diag([1, 1, 1, -1]), 800, 600))

    def test_screen_arrow_order_and_partial_clipping(self):
        points = ((80., 80.), (280., 80.), (80., 280.))
        arrows = bsp_winding_arrows(points)
        self.assertEqual(len(arrows), 3)
        # First edge goes right, then down-left, then straight up.
        self.assertGreater(arrows[0][1][0], arrows[0][0][0])
        self.assertGreater(arrows[1][1][1], arrows[1][0][1])
        self.assertLess(arrows[2][1][1], arrows[2][0][1])
        self.assertEqual(
            len(bsp_winding_arrows((points[0], points[1], None))), 1)
        self.assertEqual(len(bsp_winding_arrows(((1,1), (1,1), (1,1)))), 0)


if __name__ == "__main__":
    unittest.main()
