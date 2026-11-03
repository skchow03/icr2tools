"""GPU vertex editing contracts: text fidelity, projection, axis motion and picking."""
import unittest

import numpy as np

from gpu_viewer.vertex_tools import (
    check_values, source_vertex_text, patch_vertex_source,
    project_vertices, pick_vertex, drag_along_axis,
)


class GPUVertexToolsTests(unittest.TestCase):
    def test_patch_one_declaration_without_changing_other_source_or_comments(self):
        source = ("3D VERSION 3.0;\n% note\n% ICR2_OFFSET: 4\n"
                  "nose: [<10, 20, 30>, T=<4, 6>]; % original\n"
                  "tail: [<-5, 0, 20>];\nroot: LIST { nose, tail };\n")
        changed = patch_vertex_source(source, "nose", (100, -200, 300), (5, 9))
        self.assertIn("nose: [<100, -200, 300>, T=<5, 9>]; % original", changed)
        self.assertIn("tail: [<-5, 0, 20>];", changed)
        self.assertEqual(patch_vertex_source(
            changed, "nose", (10, 20, 30), (4, 6)), source)

    def test_patch_rejects_wrong_record_type_or_texcoord_shape(self):
        source = "3D VERSION 3.0;\nnose: [<1,2,3>];\nroot: POLY <12> {nose,nose};"
        with self.assertRaises(ValueError):
            patch_vertex_source(source, "root", (1, 2, 3))
        with self.assertRaises(ValueError):
            patch_vertex_source(source, "nose", (1, 2, 3), (1, 2))
        with self.assertRaises(ValueError):
            patch_vertex_source(source, "absent", (1, 2, 3))
        with self.assertRaises(ValueError):
            check_values((2**31, 0, 0))
        with self.assertRaises(ValueError):
            check_values((0, 0, 0), (-1, 2))
        with self.assertRaises(ValueError):
            check_values((0, 0, 0), (10, 65536))

    def test_coordinate_scale_preserves_raw_integer_roundtrip(self):
        src = "v1: [<0, 0, 0>];\n"
        edited = patch_vertex_source(src, "v1", (6000, 12000, -3000),
                                     coordinate_scale=6000)
        self.assertIn("[<1, 2, -0.5>]", edited)
        self.assertIn("[<0, 0, 0>]", source_vertex_text((0, 0, 0)))

    def test_orthographic_projection_and_front_clip(self):
        mvp = np.eye(4)
        pixels, visible = project_vertices(
            [(0, 0, 0), (1, 1, 0), (0, 0, -2)],
            (0, 0, 0), 1, mvp, 200, 100)
        self.assertTrue(np.allclose(pixels[0, :2], (100, 50)))
        self.assertTrue(visible[0])
        self.assertTrue(visible[1])
        self.assertFalse(visible[2])

    def test_perspective_rejects_behind_camera(self):
        proj = np.eye(4)
        proj[3, 3] = 0
        proj[3, 2] = -1
        pixels, visible = project_vertices(
            [(0, 0, -2), (0, 0, 2)], (0, 0, 0), 1, proj, 100, 100)
        self.assertTrue(visible[0])
        self.assertFalse(visible[1])

    def test_nearest_pick_and_depth_ties(self):
        points = np.array([[20., 20., -.3], [20., 20., .3], [30., 35., 0.]])
        self.assertEqual(pick_vertex([7, 8, 9], points, [1, 1, 1], 20, 20), 7)
        self.assertEqual(pick_vertex([7, 8, 9], points, [0, 1, 1], 20, 20), 8)
        self.assertIsNone(pick_vertex([7, 8, 9], points, [1, 1, 1], 90, 90))

    def test_drag_along_axis_and_edge_on_rejection(self):
        xyz = (0, 0, 0)
        kwargs = dict(center=(0, 0, 0), scale=100,
                      mvp=np.eye(4), width=200, height=100)
        result = drag_along_axis(xyz, "X", 20, 0, 10, **kwargs)
        self.assertEqual(result, (20, 0, 0))
        with self.assertRaisesRegex(ValueError, "edge-on"):
            # Z is depth-only if the view is looking straight down Z.
            drag_along_axis(xyz, "Z", 10, 10, 10, **kwargs)


if __name__ == "__main__":
    unittest.main()
