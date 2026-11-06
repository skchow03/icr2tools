"""Unit tests for root-model pointer-name labels and homogeneous projection."""
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from n3_compile import compile_n3_text
from three_do import Model
from gpu_viewer.appearance import DARK_COLORS, LIGHT_COLORS
from gpu_viewer.vertex_label_data import (
    include_source_vertex_declarations, project_vertex_labels, vertex_pointer_names,
)
from gpu_viewer.source_inspection import VertexPicker, index_source_targets

SOURCE = """3D VERSION 3.0;
front_left: [<0,0,0>];
nose_tip: [<100,0,0>];
rear_right: [<0,100,0>];
panel: POLY <30> {front_left,nose_tip,rear_right};
root: LIST {panel};
"""


class VertexLabelDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model, _ = compile_n3_text(
            SOURCE, Path("vertex_labels.3d"), associate_planes=False)

    def test_authored_pointer_names_and_binary_offset_fallback(self):
        names = vertex_pointer_names(self.model)
        for label in ("front_left", "nose_tip", "rear_right"):
            self.assertEqual(
                names[self.model.n3_label_offsets[label]], label)
        # .3DO does not store authored pointer names; its N3 exporter names
        # declarations _<body offset>. All vertices still get labels.
        binary = Model(Path("vertex_labels.3do"), raw_data=self.model.raw)
        fallback = vertex_pointer_names(binary)
        self.assertEqual(set(fallback), set(binary.vertices))
        self.assertTrue(all(name == f"_{offset}"
                            for offset, name in fallback.items()))

    def test_plane_only_source_vertex_is_labeled_even_without_polygon_ref(self):
        source = """3D VERSION 3.0;
a: [<0,0,0>];
b: [<100,0,0>];
c: [<0,100,0>];
plane_point: [<0,0,100>];
panel: POLY <30> {a,b,c};
face: FACE (a,b,plane_point), panel;
root: LIST {face};
"""
        model, _ = compile_n3_text(source, Path("plane_vertex.3d"),
                                   associate_planes=False)
        offset = model.n3_label_offsets["plane_point"]
        self.assertNotIn(offset, model.vertices)
        mesh = SimpleNamespace(center=(0, 0, 0), scale=100)
        picker = VertexPicker.from_model(model, mesh)
        names = vertex_pointer_names(model)
        expanded, renamed = include_source_vertex_declarations(
            model, mesh, picker, names, index_source_targets(source))
        self.assertEqual(len(expanded.offsets), len(picker.offsets) + 1)
        self.assertEqual(renamed[offset], "plane_point")
        entry = list(zip(expanded.offsets, expanded.normalized))
        self.assertTrue(any(int(off) == offset and np.allclose(pos, [0, 0, 1])
                            for off, pos in entry))

    def test_all_visible_vertices_including_overlaps_are_projected(self):
        picker = SimpleNamespace(
            offsets=np.array([10, 20, 30, 40, 50], dtype=np.int64),
            normalized=np.array([
                [0, 0, 0], [0, 0, 0], [0.7, -0.5, 0],
                [2, 0, 0], [0, 0, -2],
            ], dtype=np.float64))
        entries = project_vertex_labels(
            picker, {10: "one", 20: "two", 30: "three"},
            np.eye(4), 640, 480)
        self.assertEqual([row[0] for row in entries], [10, 20, 30])
        self.assertEqual(entries[0][1:3], (320, 240))
        self.assertEqual(entries[1][1:3], (320, 240))
        self.assertEqual(entries[2][3], "three")

    def test_behind_camera_and_nonfinite_are_rejected(self):
        picker = SimpleNamespace(
            offsets=np.array([3, 4, 5], dtype=np.int64),
            normalized=np.array([
                [0, 0, -2], [0, 0, 1], [np.nan, 0, 0],
            ], dtype=np.float64))
        perspective = np.zeros((4, 4), dtype=np.float64)
        perspective[0, 0] = perspective[1, 1] = 1
        perspective[2, 2] = -0.5
        perspective[3, 2] = -1  # positive W only for negative eye Z
        entries = project_vertex_labels(
            picker, {3: "ahead", 4: "behind"}, perspective, 640, 480)
        self.assertEqual([e[3] for e in entries], ["ahead"])

    def test_empty_model_and_invalid_dimensions(self):
        self.assertEqual(vertex_pointer_names(None), {})
        picker = SimpleNamespace(offsets=np.array([], dtype=np.int64),
                                 normalized=np.zeros((0, 3)))
        self.assertEqual(project_vertex_labels(
            picker, {}, np.eye(4), 640, 480), [])
        self.assertEqual(project_vertex_labels(
            picker, {}, np.eye(4), 0, 480), [])

    def test_regular_vertex_colors_differ_from_selected_marker(self):
        for colors in (DARK_COLORS, LIGHT_COLORS):
            self.assertNotEqual(
                colors["viewport_all_vertex_dot"],
                colors["viewport_vertex_dot"])
            self.assertNotEqual(
                colors["viewport_all_vertex_label"],
                colors["viewport_vertex_dot"])


if __name__ == "__main__":
    unittest.main()
