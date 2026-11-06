"""Wireframe outlines must follow original polygon boundaries, not tessellation."""
import unittest
from types import SimpleNamespace

import numpy as np

from mesh import make_mesh
from wireframe import make_wireframe


def geometry(points, faces):
    vertices = {index: SimpleNamespace(xyz=xyz, uv=(0, 0))
                for index, xyz in enumerate(points, 1)}
    polygons = {index: SimpleNamespace(unique_refs=refs, color=44, kind=1)
                for index, refs in enumerate(faces, 1)}
    return SimpleNamespace(vertices=vertices, polygons=polygons)


class WireframeBoundaryTests(unittest.TestCase):
    def _edges(self, wire):
        data = wire.vertices.reshape(-1, 2, 3)
        return {frozenset((tuple(segment[0]), tuple(segment[1])))
                for segment in data}

    def test_quad_has_four_edges_and_no_triangulation_diagonal(self):
        model = geometry(
            [(0, 0, 0), (8, 0, 0), (8, 4, 0), (0, 4, 0)],
            [(1, 2, 3, 4)])
        filled = make_mesh(model)
        self.assertEqual(filled.triangle_count, 2)
        wire = make_wireframe(model, filled)
        self.assertEqual(wire.polygon_count, 1)
        self.assertEqual(wire.segment_count, 4)
        self.assertEqual(wire.polygon_ranges, {1: (0, 8)})
        self.assertEqual(wire.vertices.dtype, np.float32)
        self.assertEqual(wire.vertices.shape, (8, 3))
        edges = self._edges(wire)
        p = [tuple((np.asarray(model.vertices[i].xyz)
                    - filled.center) / filled.scale) for i in range(1, 5)]
        expected = {frozenset((p[i], p[(i + 1) % 4])) for i in range(4)}
        self.assertEqual(edges, expected)
        self.assertNotIn(frozenset((p[0], p[2])), edges)
        self.assertNotIn(frozenset((p[1], p[3])), edges)

    def test_concave_polygon_keeps_boundary_and_collinear_points(self):
        model = geometry(
            [(0, 0, 0), (4, 0, 0), (8, 0, 0),
             (8, 8, 0), (4, 4, 0), (0, 8, 0)],
            [(1, 2, 3, 4, 5, 6)])
        filled = make_mesh(model)
        self.assertGreater(filled.triangle_count, 1)
        wire = make_wireframe(model, filled)
        self.assertEqual(wire.segment_count, 6)
        self.assertEqual(wire.polygon_ranges[1], (0, 12))

    def test_duplicate_closing_pointer_and_zero_length_edges(self):
        model = geometry(
            [(0, 0, 0), (4, 0, 0), (4, 4, 0), (0, 4, 0)],
            [(1, 2, 2, 3, 4, 1)])
        filled = make_mesh(model)
        wire = make_wireframe(model, filled)
        self.assertEqual(wire.segment_count, 4)

    def test_skips_degenerate_unmeshed_polygons(self):
        model = geometry(
            [(0, 0, 0), (4, 0, 0), (4, 4, 0), (0, 4, 0)],
            [(1, 2, 3, 4), (1, 2)])
        filled = make_mesh(model)
        wire = make_wireframe(model, filled)
        self.assertEqual(wire.polygon_count, 1)
        self.assertNotIn(2, wire.polygon_ranges)

    def test_res_switch_changes_wireframe_edges_without_bsp_culling(self):
        from n3_compile import compile_n3_text
        from scene import build_scene, ordered_scene_indices

        source = """3D VERSION 3.0;
a: [<0,0,0>];
b: [<100,0,0>];
c: [<0,100,0>];
d: [<1000,0,0>];
e: [<1100,0,0>];
f: [<1000,100,0>];
near_poly: POLY <44> {a,b,c};
far_poly: POLY <55> {d,e,f};
res: SWITCH DISTANCE (a) > {(1200 ? far_poly), (0 ? near_poly)};
root: LIST {res};
"""
        model, _ = compile_n3_text(source, "wire_res.3d",
                                   associate_planes=False)
        scene = build_scene(model)
        filled = make_mesh(scene.geometry)
        wire = make_wireframe(scene.geometry, filled)
        self.assertEqual(wire.segment_count, 6)
        self.assertEqual(wire.polygon_count, 2)
        camera = (0.0, 0.0, 0.0)
        near_offset = model.n3_label_offsets["near_poly"]
        far_offset = model.n3_label_offsets["far_poly"]
        for distance, selected in ((0, near_offset), (1199, near_offset),
                                   (1200, far_offset), (1500, far_offset)):
            with self.subTest(distance=distance):
                indices, visible, info = ordered_scene_indices(
                    scene, wire, camera, distance, bsp_mode="off")
                self.assertEqual(visible, frozenset({selected}))
                self.assertEqual(info["mesh_polygons"], 1)
                self.assertEqual(indices.size, 6)
                flattened = scene.polygon_lookup[(0, selected)]
                start, count = wire.polygon_ranges[flattened]
                self.assertTrue(
                    np.array_equal(indices, np.arange(start, start + count)))
        expanded, visible, info = ordered_scene_indices(
            scene, wire, camera, None, bsp_mode="off")
        self.assertEqual(visible, frozenset({near_offset, far_offset}))
        self.assertEqual(info["mesh_polygons"], 2)
        self.assertEqual(expanded.size, 12)

        auto_near, visible_near, _ = ordered_scene_indices(
            scene, wire, camera, "auto", bsp_mode="off")
        auto_far, visible_far, _ = ordered_scene_indices(
            scene, wire, (0.0, 0.0, 2000.0), "auto", bsp_mode="off")
        self.assertEqual(auto_near.size, 6)
        self.assertEqual(auto_far.size, 6)
        self.assertEqual(visible_near, frozenset({near_offset}))
        self.assertEqual(visible_far, frozenset({far_offset}))

    def test_does_not_change_source_geometry(self):
        model = geometry(
            [(0, 0, 0), (4, 0, 0), (0, 4, 0)],
            [(1, 2, 3)])
        before = [model.vertices[i].xyz for i in model.vertices]
        wire = make_wireframe(model, make_mesh(model))
        self.assertEqual(wire.segment_count, 3)
        self.assertEqual(before, [model.vertices[i].xyz for i in model.vertices])


if __name__ == "__main__":
    unittest.main()
