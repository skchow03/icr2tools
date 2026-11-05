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
