"""N3 source cursor inspection: declaration spans, model offsets and projection."""
import unittest
from types import SimpleNamespace

import numpy as np

from source_inspection import (
    index_source_targets, target_offset, polygon_mesh_range,
    vertex_screen_position, polygon_inspection_notice, VertexPicker, PolygonPicker,
)
from workspaces import max_switch_distance
from scene import build_scene
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

    def test_inline_material_poly_is_indexed_and_compiled_polygon_resolved(self):
        # Real user case: the declaration label names the MATERIAL record;
        # the polygon is an anonymous child with its own body offset.
        source = (
            "3D VERSION 3.0;\n"
            "c1: [<0,0,0>, T=<0,0>];\n"
            "c0: [<100,0,0>, T=<127,0>];\n"
            "d0: [<100,100,0>, T=<127,127>];\n"
            "d1: [<0,100,0>, T=<0,127>];\n"
            'rs1: MATERIAL MIP="usag", GROUP=3, '
            'POLY [T] <208> {c1, c0, d0, d1};\n'
            'bk1: MATERIAL MIP="usag", GROUP=3, '
            'POLY [T] <26> {d1, d0, c0, c1};\n'
            "root: LIST {rs1, bk1};\n"
        )
        idx = index_source_targets(source)
        self.assertEqual(idx.at_line(5), ("polygon", "rs1"))
        self.assertEqual(idx.at_line(6), ("polygon", "bk1"))
        self.assertIsNone(idx.at_line(7))
        model, _ = compile_n3_text(source, "nested_material.3d",
                                   associate_planes=False)
        self.assertEqual(len(model.polygons), 2)
        resolved = []
        for label in ("rs1", "bk1"):
            wrapper = model.n3_label_offsets[label]
            self.assertEqual(model.records[wrapper], 4)
            offset = target_offset(model, "polygon", label)
            self.assertNotEqual(offset, wrapper)
            self.assertIn(offset, model.polygons)
            self.assertEqual(model.children[wrapper], [offset])
            resolved.append(offset)
        self.assertNotEqual(resolved[0], resolved[1])
        self.assertEqual([model.polygons[o].color for o in resolved],
                         [208, 26])
        scene = build_scene(model)
        self.assertTrue(all((0, offset) in scene.polygon_lookup
                            for offset in resolved))

    def test_material_wrapper_without_inline_poly_is_not_a_target(self):
        source = (
            "3D VERSION 3.0;\n"
            "a: [<0,0,0>];\n"
            "b: [<100,0,0>];\n"
            "c: [<0,100,0>];\n"
            "face: POLY <42> {a,b,c};\n"
            'ordinary: MATERIAL MIP="usag", GROUP=3, face;\n'
            "group: MATERIAL GROUP=3, LIST {face};\n"
            'quoted: MATERIAL MIP="POLY <2>", GROUP=3, face;\n'
            "root: LIST {ordinary, group, quoted};\n"
        )
        idx = index_source_targets(source)
        self.assertEqual(idx.at_line(4), ("polygon", "face"))
        for line in (5, 6, 7):
            self.assertIsNone(idx.at_line(line))
        model, _ = compile_n3_text(source, "ordinary_material.3d",
                                   associate_planes=False)
        self.assertEqual(target_offset(model, "polygon", "face"),
                         model.n3_label_offsets["face"])
        # Resolver can follow wrappers; only the source index decides
        # whether they actually contain an inline polygon statement.
        self.assertEqual(target_offset(model, "polygon", "ordinary"),
                         model.n3_label_offsets["face"])
        self.assertIsNone(target_offset(model, "polygon", "group"))

    def test_inline_poly_in_multiline_material_and_group_only(self):
        source = (
            "grouped: MATERIAL GROUP=3,\n"
            "    POLY <42> {a,b,c};\n"
            "tex: MATERIAL GROUP=4, MIP=\"usag\",\n"
            "    POLY [T] <208> {a,b,c};\n"
            "nested: MATERIAL GROUP=3, MATERIAL GROUP=4,\n"
            "    POLY <42> {a,b,c};\n"
        )
        idx = index_source_targets(source)
        for line, label in ((0, "grouped"), (1, "grouped"),
                            (2, "tex"), (3, "tex"),
                            (4, "nested"), (5, "nested")):
            self.assertEqual(idx.at_line(line), ("polygon", label))

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


    def test_viewport_vertex_picker_clips_and_limits_search_radius(self):
        model = SimpleNamespace(vertices={
            100: SimpleNamespace(xyz=(0, 0, 0)),
            200: SimpleNamespace(xyz=(50, 0, 0)),
            300: SimpleNamespace(xyz=(300, 0, 0)),  # beyond view
        })
        mesh = SimpleNamespace(center=(0, 0, 0), scale=100.)
        picker = VertexPicker.from_model(model, mesh)
        self.assertEqual(picker.nearest(np.eye(4), 402, 301, 800, 600), 100)
        self.assertEqual(picker.nearest(np.eye(4), 599, 299, 800, 600), 200)
        self.assertIsNone(picker.nearest(np.eye(4), 520, 300, 800, 600))
        self.assertIsNone(picker.nearest(
            np.diag([1., 1., 1., -1.]), 400, 300, 800, 600))
        self.assertIsNone(picker.nearest(np.eye(4), 400, 300, 0, 600))
        self.assertEqual(picker.nearest(
            np.eye(4), 400, 300, 800, 600, eligible_offsets={200}), None)

    def test_vertex_picker_prefers_nearest_depth_at_same_screen_position(self):
        model = SimpleNamespace(vertices={
            20: SimpleNamespace(xyz=(0, 0, 40)),
            10: SimpleNamespace(xyz=(0, 0, -40)),
            30: SimpleNamespace(xyz=(0, 0, 200)),
        })
        picker = VertexPicker.from_model(
            model, SimpleNamespace(center=(0, 0, 0), scale=100.))
        self.assertEqual(picker.nearest(np.eye(4), 400, 300, 800, 600), 10)
        self.assertEqual(picker.nearest(
            np.eye(4), 400, 300, 800, 600, eligible_offsets={20}), 20)
        self.assertEqual(VertexPicker.from_model(
            SimpleNamespace(vertices={}),
            SimpleNamespace(center=(0, 0, 0), scale=1)).nearest(
                np.eye(4), 0, 0, 800, 600), None)

    def test_max_switch_distance_includes_loaded_child_models(self):
        # No file needed for this deterministic traversal.
        local = SimpleNamespace(model=SimpleNamespace(switches={
            1: SimpleNamespace(branches=((100, 10), (0, 20))),
        }))
        child = SimpleNamespace(model=SimpleNamespace(switches={
            2: SimpleNamespace(branches=((450, 30), (125, 40), (0, 50))),
        }))
        scene = SimpleNamespace(instances=[local, child])
        self.assertEqual(max_switch_distance(scene), 450)
        self.assertEqual(max_switch_distance(None), 0)
        self.assertEqual(max_switch_distance(SimpleNamespace(instances=[])), 0)

    def test_hidden_polygon_report_uses_active_res_branch_not_forced_draw(self):
        source = """3D VERSION 3.0;
a: [<0,0,0>];
b: [<100,0,0>];
c: [<0,100,0>];
near_poly: POLY <44> {a,b,c};
far_poly: POLY <55> {a,c,b};
unreferenced: POLY <66> {a,b,c};
lod: SWITCH DISTANCE (a) > {(1200 ? far_poly), (0 ? near_poly)};
root: LIST {lod};
"""
        model, _ = compile_n3_text(source, "switch_inspect.3d",
                                   associate_planes=False)
        scene = build_scene(model)
        self.assertEqual(max_switch_distance(scene), 1200)
        near = model.n3_label_offsets["near_poly"]
        far = model.n3_label_offsets["far_poly"]
        unused = model.n3_label_offsets["unreferenced"]
        eye = (0, 0, 200)

        selected_near, _, _ = model.switched_polygons(0, eye, "original")
        self.assertIn(near, selected_near)
        self.assertNotIn(far, selected_near)
        notice = polygon_inspection_notice(
            model, far, set(selected_near), 0, eye, "painter")
        self.assertIn("SWITCH DISTANCE", notice)
        self.assertIn("distance 0", notice)
        self.assertIsNone(polygon_inspection_notice(
            model, near, set(selected_near), 0, eye, "painter"))
        self.assertIsNone(polygon_inspection_notice(
            model, far, set(), 0, eye, "all"))

        selected_far, _, _ = model.switched_polygons(1200, eye, "original")
        self.assertIn(far, selected_far)
        self.assertNotIn(near, selected_far)
        self.assertIn("distance 1,200", polygon_inspection_notice(
            model, near, set(selected_far), 1200, eye, "painter"))

        # Root polygon present in LOD traversal but excluded by camera BSP.
        self.assertIn("BSP", polygon_inspection_notice(
            model, far, set(), 1200, eye, "painter"))
        # Orphan source declarations are not parsed into renderable POLYs.
        # Inspection correctly returns no notice when the record is absent.
        self.assertNotIn(unused, model.polygons)
        self.assertIsNone(polygon_inspection_notice(
            model, unused, set(), 1200, eye, "painter"))


    def test_polygon_ray_picker_uses_rendered_triangles_and_front_depth(self):
        # Two root POLYs overlap in screen space, plus an external child.
        # Their coordinates match the normalized XYZ held in the GPU VBO.
        mesh_vertices = np.zeros((9, 13), dtype=np.float32)
        face_xy = np.asarray([(-0.6, -0.6), (0.6, -0.6), (0., 0.6)])
        for first, z in ((0, -0.3), (3, 0.3), (6, -0.7)):
            mesh_vertices[first:first+3, :2] = face_xy
            mesh_vertices[first:first+3, 2] = z
        mesh = SimpleNamespace(
            vertices=mesh_vertices, polygon_ranges={
                11: (0, 3), 12: (3, 3), 13: (6, 3)})
        scene = SimpleNamespace(polygon_lookup={
            (0, 100): 11, (0, 200): 12, (1, 300): 13})
        picker = PolygonPicker.from_scene(scene, mesh)
        self.assertEqual(picker.nearest(np.eye(4), 400, 300, 800, 600), 100)
        self.assertEqual(picker.nearest(
            np.eye(4), 400, 300, 800, 600, eligible_offsets={200}), 200)
        self.assertIsNone(picker.nearest(
            np.eye(4), 400, 300, 800, 600, eligible_offsets={300}))
        self.assertIsNone(picker.nearest(np.eye(4), 10, 10, 800, 600))
        self.assertIsNone(picker.nearest(np.eye(4), 400, 300, 0, 600))
        self.assertIsNone(picker.nearest(
            np.eye(4), 400, 300, 800, 600, eligible_offsets=set()))
        self.assertEqual(len(picker.triangle_starts), 2)

    def test_polygon_ray_picker_rejects_clipped_and_degenerate_faces(self):
        vertices = np.zeros((6, 13), dtype=np.float32)
        vertices[:3, :3] = [
            (-.4, -.4, 2), (.4, -.4, 2), (0, .4, 2)]
        vertices[3:, :3] = [(0, 0, 0)] * 3
        mesh = SimpleNamespace(vertices=vertices, polygon_ranges={
            1: (0, 3), 2: (3, 3)})
        scene = SimpleNamespace(polygon_lookup={(0, 100): 1, (0, 200): 2})
        picker = PolygonPicker.from_scene(scene, mesh)
        self.assertIsNone(picker.nearest(np.eye(4), 400, 300, 800, 600))
        self.assertIsNone(picker.nearest(
            np.zeros((4, 4)), 400, 300, 800, 600))
        self.assertIsNone(PolygonPicker.from_scene(
            None, mesh).nearest(np.eye(4), 400, 300, 800, 600))


if __name__ == "__main__":
    unittest.main()
