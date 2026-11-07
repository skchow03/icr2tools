"""Pure viewport gizmo math for ortho, perspective and screen-axis constraints."""
import math
import unittest

import numpy as np

from vertex_move import (
    move_handles, hit_move_handle, drag_raw_coordinate,
    connected_vertex_edges,
)


def ortho():
    return np.diag((.001, .001, .001, 1.))


def perspective_view():
    projection = np.zeros((4, 4), dtype=np.float64)
    projection[0, 0] = projection[1, 1] = 1.8
    projection[2, 2] = -1.01
    projection[2, 3] = -0.2
    projection[3, 2] = -1.
    view = np.identity(4)
    view[2, 3] = -5.
    return projection @ view


class VertexMoveMathTests(unittest.TestCase):
    def test_orthographic_gizmo_and_end_on_axis(self):
        h = move_handles((0,0,0), (0,0,0), 1,
                         ortho(), 1000, 1000)
        self.assertIn("X", h)
        self.assertIn("Y", h)
        self.assertNotIn("Z", h)  # Eye looks along the Z axis.
        self.assertAlmostEqual(h["X"].tip[0], 576, places=3)
        self.assertAlmostEqual(h["Y"].tip[1], 424, places=3)
        self.assertEqual(hit_move_handle(h, 550, 500), "X")
        self.assertEqual(hit_move_handle(h, 500, 450), "Y")
        self.assertIsNone(hit_move_handle(h, 500, 500))
        self.assertIsNone(hit_move_handle(h, 100, 100))

    def test_orthographic_drag_changes_one_axis_only(self):
        h = move_handles((0,0,0), (0,0,0), 1,
                         ortho(), 1000, 1000)
        changed = drag_raw_coordinate(
            h["X"], (550,500), (600,500), (0,0,0))
        self.assertEqual(changed, (100,0,0))
        changed = drag_raw_coordinate(
            h["Y"], (500,450), (500,400), (0,0,0), snap=10)
        self.assertEqual(changed, (0,100,0))
        backward = drag_raw_coordinate(
            h["X"], (550,500), (500,500), (0,0,0))
        self.assertEqual(backward, (-100,0,0))
        fine = drag_raw_coordinate(
            h["X"], (550,500), (600,500), (0,0,0), fine=True)
        self.assertEqual(fine, (10,0,0))

    def test_perspective_and_center_scaled_geometry(self):
        matrix = perspective_view()
        # Model raw coordinate (100000,8000,-1000) is normalized to origin.
        raw = (100_000, 8_000, -1_000)
        handles = move_handles(raw, raw, 1000, matrix, 800, 600)
        self.assertEqual(set(handles), {"X", "Y"})  # Z end-on
        hx = handles["X"]
        result = drag_raw_coordinate(
            hx, (440,300), (480,300), raw, snap=1)
        self.assertGreater(result[0], raw[0])
        self.assertEqual(result[1:], raw[1:])
        # 1 raw unit projects at 1.8*400/(5*1000) = .144 pixels
        self.assertAlmostEqual(result[0]-raw[0], 278, delta=2)

    def test_arbitrary_camera_rotation_preserves_constrained_axis(self):
        view = np.identity(4)
        angle = math.radians(40)
        view[0,0],view[0,1] = math.cos(angle), math.sin(angle)
        view[1,0],view[1,1] = -math.sin(angle), math.cos(angle)
        projection = ortho()
        handles = move_handles((45,55,65), (0,0,0), 1,
                               projection @ view, 1000, 1000)
        axis = handles["X"]
        result = drag_raw_coordinate(
            axis, axis.tip, (axis.tip[0]+35,axis.tip[1]-20),
            (45,55,65))
        self.assertNotEqual(result[0],45)
        self.assertEqual(result[1:],(55,65))

    def test_connected_edge_preview_only_tracks_incident_polygons(self):
        from types import SimpleNamespace
        model = SimpleNamespace(
            vertices={i: SimpleNamespace(xyz=(i, 0, 0))
                      for i in range(1, 7)},
            polygons={
                10: SimpleNamespace(unique_refs=(1,2,3)),
                20: SimpleNamespace(unique_refs=(1,3,4)),
                30: SimpleNamespace(unique_refs=(5,6,3)),
            })
        self.assertEqual(connected_vertex_edges(model,1),
                         ((2,(2,0,0)),(3,(3,0,0)),(4,(4,0,0))))
        self.assertEqual(connected_vertex_edges(model,1,max_neighbors=2),())
        self.assertEqual(connected_vertex_edges(model,999),())

    def test_clip_rejection_and_near_edge_safety(self):
        h = move_handles((1_000_000,0,0), (0,0,0), 1,
                         ortho(), 800, 600)
        self.assertFalse(h)
        h = move_handles((0,0,0), (0,0,0), 1,
                         perspective_view(), 800, 600)
        self.assertNotIn("Z", h)
        with self.assertRaises(ValueError):
            drag_raw_coordinate(h["X"],(400,300),(430,300),
                                (0,0,0),snap=0)


if __name__ == "__main__":
    unittest.main()
