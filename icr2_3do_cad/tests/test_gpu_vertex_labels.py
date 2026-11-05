"""All-vertex pointer inventory and fast viewport projection regressions."""
import unittest
from types import SimpleNamespace

import numpy as np

from gpu_viewer.source_inspection import index_source_targets
from gpu_viewer.vertex_labels import (
    labelled_model_vertices, project_labelled_vertices,
)
from n3_compile import compile_n3_text
from three_do import Model


SOURCE = """3D VERSION 3.0;
a: [<-100, -100, 0>];
b: [<100, -100, 0>];
c: [<100, 100, 0>];
plane_only: [<0,0,500>];
p: POLY <44> {a,b,c};
root: BSPF (a,b,plane_only), NIL,p,NIL;
"""


class VertexLabelsTests(unittest.TestCase):
    def setUp(self):
        self.model, _ = compile_n3_text(
            SOURCE, "label_source.3d", associate_planes=False)

    def test_authored_labels_map_to_binary_vertex_offsets(self):
        inventory = labelled_model_vertices(self.model)
        by_offset = {point.offset: point for point in inventory}
        for label in ("a", "b", "c"):
            offset = self.model.n3_label_offsets[label]
            self.assertIn(offset, by_offset)
            self.assertEqual(by_offset[offset].label, label)
            self.assertEqual(by_offset[offset].xyz,
                             self.model.vertices[offset].xyz)
        self.assertEqual(len(inventory), len(self.model.vertices))

    def test_validated_source_only_plane_vertex_is_included(self):
        extra = "plane_only"
        offset = self.model.n3_label_offsets[extra]
        self.assertNotIn(offset, self.model.vertices)
        names = index_source_targets(SOURCE).vertex_labels
        inventory = labelled_model_vertices(self.model, names)
        matching = [point for point in inventory if point.label == extra]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].offset, offset)
        self.assertEqual(matching[0].xyz, (0, 0, 500))
        self.assertEqual(len(inventory), len(self.model.vertices) + 1)
        self.assertEqual(len({p.offset for p in inventory}), len(inventory))
        self.assertNotIn("root", {p.label for p in inventory})

    def test_raw_3do_uses_generated_offset_labels(self):
        binary = Model(
            "label_source.3do", raw_data=self.model.raw,
            associate_planes=False)
        self.assertFalse(hasattr(binary, "n3_label_offsets"))
        inventory = labelled_model_vertices(binary)
        self.assertEqual(len(inventory), len(binary.vertices))
        self.assertTrue(all(point.label == f"_{point.offset}"
                            for point in inventory))
        self.assertTrue(all(point.xyz == binary.vertices[point.offset].xyz
                            for point in inventory))

    def test_vectorized_projection_and_clipping(self):
        from gpu_viewer.vertex_labels import LabelledVertex
        vertices = (
            LabelledVertex(0, "front", (50, 0, 0)),
            LabelledVertex(16, "left", (-50, 0, 0)),
            LabelledVertex(32, "clipped", (500, 0, 0)),
        )
        mesh = SimpleNamespace(center=(0, 0, 0), scale=100)
        screen = project_labelled_vertices(
            vertices, mesh, np.eye(4), 800, 600)
        self.assertEqual({p.label for p in screen}, {"front", "left"})
        coords = {p.label: (p.x, p.y) for p in screen}
        self.assertEqual(coords["front"], (600, 300))
        self.assertEqual(coords["left"], (200, 300))
        self.assertEqual(
            project_labelled_vertices(
                vertices, mesh, np.diag([1, 1, 1, -1]), 800, 600),
            ())
        self.assertEqual(
            project_labelled_vertices(vertices, None, np.eye(4), 800, 600),
            ())

    def test_projected_vertex_order_uses_depth_and_no_duplicate_offsets(self):
        from gpu_viewer.vertex_labels import LabelledVertex
        vertices = (
            LabelledVertex(16, "near", (0, 0, -40)),
            LabelledVertex(32, "far", (0, 0, 40)),
        )
        screen = project_labelled_vertices(
            vertices, SimpleNamespace(center=(0,0,0), scale=100),
            np.eye(4), 500, 300)
        self.assertEqual([v.label for v in screen], ["far", "near"])
        self.assertEqual((screen[0].x, screen[0].y),
                         (screen[1].x, screen[1].y))


if __name__ == "__main__":
    unittest.main()
