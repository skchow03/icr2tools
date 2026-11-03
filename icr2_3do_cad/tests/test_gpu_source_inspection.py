"""N3 source cursor inspection: declaration spans, model offsets and projection."""
import unittest
from types import SimpleNamespace

import numpy as np

from gpu_viewer.source_inspection import (
    index_source_targets, target_offset, polygon_mesh_range,
    vertex_screen_position,
)
from n3_compile import compile_n3_text


SOURCE = """3D VERSION 3.0;
% This is a comment, not a target.
front_left: [<0,0,0>];
front_right: [<1000,0,0>];
rear_left: [<0,1000,0>];
% ICR2_OFFSET: 999999
body_panel: POLY <44>
    {front_left, front_right,
     rear_left};
root: LIST {body_panel};
"""


class SourceInspectionTests(unittest.TestCase):
    def test_cursor_declarations_multiline_and_comments(self):
        idx = index_source_targets(SOURCE)
        self.assertIsNone(idx.at_line(0))
        self.assertIsNone(idx.at_line(1))
        self.assertEqual(idx.at_line(2), ("vertex", "front_left"))
        self.assertEqual(idx.at_line(3), ("vertex", "front_right"))
        self.assertEqual(idx.at_line(4), ("vertex", "rear_left"))
        self.assertIsNone(idx.at_line(5))
        for line in (6, 7, 8):
            self.assertEqual(idx.at_line(line), ("polygon", "body_panel"))
        self.assertIsNone(idx.at_line(9))
        self.assertIsNone(idx.at_line(100))
        self.assertEqual(
            index_source_targets("t: POLY [T] <1> {a,b,c};").at_line(0),
            ("polygon", "t"))
        self.assertEqual(
            index_source_targets("p: [<1,2,3>, T=<0,1>];").at_line(0),
            ("vertex", "p"))
        self.assertIsNone(
            index_source_targets("% x: POLY <2> {a,b,c};").at_line(0))
        self.assertIsNone(
            index_source_targets("p: POLY <2> {a,b,c}").at_line(0))

    def test_compiled_labels_track_current_geometry_not_old_offsets(self):
        model, doc = compile_n3_text(SOURCE, "example.3d",
                                     associate_planes=False)
        offsets = {stmt.label: stmt.offset for stmt in doc.statements}
        self.assertEqual(model.n3_label_offsets, offsets)
        self.assertNotEqual(offsets["body_panel"], 999999)
        self.assertEqual(target_offset(model, "polygon", "body_panel"),
                         offsets["body_panel"])
        self.assertEqual(target_offset(model, "vertex", "front_left"),
                         offsets["front_left"])
        self.assertIsNone(target_offset(model, "polygon", "front_left"))
        self.assertIsNone(target_offset(model, "vertex", "body_panel"))
        self.assertIsNone(target_offset(model, "polygon", "no_such_poly"))

    def test_generated_binary_labels_and_missing_record_handling(self):
        model = SimpleNamespace(n3_label_offsets={},
                                polygons={200: object()},
                                vertices={120: object()})
        self.assertEqual(target_offset(model, "polygon", "_200"), 200)
        self.assertEqual(target_offset(model, "vertex", "_120"), 120)
        self.assertIsNone(target_offset(model, "polygon", "_120"))
        self.assertIsNone(target_offset(model, "vertex", "malformed"))
        self.assertIsNone(target_offset(None, "vertex", "_120"))

    def test_only_root_polygon_range_is_selected(self):
        scene = SimpleNamespace(polygon_lookup={(0, 200): 11, (1, 200): 12})
        mesh = SimpleNamespace(polygon_ranges={11: (81, 6), 12: (120, 3)})
        self.assertEqual(polygon_mesh_range(scene, mesh, 200), (81, 6))
        self.assertIsNone(polygon_mesh_range(scene, mesh, 500))
        self.assertIsNone(polygon_mesh_range(None, mesh, 200))

    def test_vertex_projection_and_clipping(self):
        model = SimpleNamespace(vertices={
            1: SimpleNamespace(xyz=(50, 0, 0)),
            2: SimpleNamespace(xyz=(300, 0, 0)),
        })
        mesh = SimpleNamespace(center=(0, 0, 0), scale=100.0)
        self.assertEqual(
            vertex_screen_position(model, mesh, 1, np.eye(4), 800, 600),
            (600.0, 300.0))
        self.assertIsNone(vertex_screen_position(
            model, mesh, 2, np.eye(4), 800, 600))
        self.assertIsNone(vertex_screen_position(
            model, mesh, 9, np.eye(4), 800, 600))
        behind = np.diag([1.0, 1.0, 1.0, -1.0])
        self.assertIsNone(vertex_screen_position(
            model, mesh, 1, behind, 800, 600))


if __name__ == "__main__":
    unittest.main()
