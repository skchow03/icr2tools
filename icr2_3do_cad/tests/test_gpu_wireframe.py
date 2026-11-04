"""Wireframe outlines must follow original polygon boundaries, not tessellation."""
import unittest
from types import SimpleNamespace

import numpy as np

from gpu_viewer.mesh import make_mesh
from gpu_viewer.wireframe import make_wireframe


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
