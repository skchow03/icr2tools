"""Pure camera/guide math tests: no Qt, OpenGL context or game file required."""
import math
import unittest

import numpy as np

from axis_guides import (
    AXIS_COLORS, GUIDE_ANCHORS, camera_focus, guide_anchor,
    orientation_axes, projected_axis_guides,
)


def front_view():
    # Papyrus Front view: screen right +X, screen up +Z, eye at -Y.
    # Row 3 points toward the eye; this matches camera_view(az=0,el=0).
    return np.array(((1., 0., 0., 0.),
                     (0., 0., 1., 0.),
                     (0.,-1., 0.,-4.),
                     (0., 0., 0., 1.)))


def ortho():
    return np.diag((.5, .5, -.02, 1.))


class AxisGuideGeometryTests(unittest.TestCase):
    def test_camera_focus_recovers_target_when_eye_moves(self):
        view = front_view()
        self.assertTrue(np.allclose(camera_focus(view, 4.), (0., 0., 0.)))
        view2 = view.copy()
        # translate view origin by -5 screen X = camera moved +5 world X
        view2[0, 3] = -5.
        self.assertTrue(np.allclose(
            camera_focus(view2, 4.), (5., 0., 0.)))

    def test_three_anchor_modes_are_physically_distinct(self):
        center = (1000., 2000., 3000.)
        view = front_view()
        self.assertEqual(GUIDE_ANCHORS, ("focus", "model", "origin"))
        self.assertTrue(np.array_equal(
            guide_anchor("focus", view, 4., center, 1000.),
            (0., 0., 0.)))
        self.assertTrue(np.array_equal(
            guide_anchor("model", view, 4., center, 1000.),
            (0., 0., 0.)))
        self.assertTrue(np.array_equal(
            guide_anchor("origin", view, 4., center, 1000.),
            (-1., -2., -3.)))
        with self.assertRaises(ValueError):
            guide_anchor("view_zero", view, 4., center, 1000.)

    def test_canonical_front_orientation_matches_Papyrus_XZ(self):
        d = orientation_axes(front_view(), center=(90., 90.), radius=30.)
        self.assertEqual(tuple(AXIS_COLORS), ("X", "Y", "Z"))
        self.assertAlmostEqual(d["X"][0], 120.)
        self.assertAlmostEqual(d["X"][1], 90.)
        self.assertAlmostEqual(d["Z"][0], 90.)
        self.assertAlmostEqual(d["Z"][1], 60.)
        self.assertAlmostEqual(d["Y"][0], 90.)
        self.assertAlmostEqual(d["Y"][1], 90.)
        # Y direction is end-on, never mislabeled as X or Z.
        self.assertLess(d["Y"][2], 0.)

    def test_side_top_views_use_consistent_xyz_gizmo(self):
        # Side view camera at +X looking -X: +Y is screen-right.
        side = np.array(((0., 1., 0., 0.),
                         (0., 0., 1., 0.),
                         (1., 0., 0.,-4.),
                         (0., 0., 0., 1.)))
        s = orientation_axes(side, center=(0,0), radius=40.)
        self.assertAlmostEqual(s["Y"][0], 40.)
        self.assertAlmostEqual(s["Z"][1], -40.)
        self.assertAlmostEqual(s["X"][0], 0.)
        # Top view screen right +X, up +Y, positive Z end-on.
        top = np.array(((1.,0.,0.,0.),
                        (0.,1.,0.,0.),
                        (0.,0.,1.,-4.),
                        (0.,0.,0.,1.)))
        t = orientation_axes(top, center=(0,0), radius=40.)
        self.assertAlmostEqual(t["X"][0], 40.)
        self.assertAlmostEqual(t["Y"][1], -40.)
        self.assertAlmostEqual(t["Z"][0], 0.)

    def test_axes_clip_to_viewport_without_z_fighting(self):
        # Independent screen-only guides extend in +/- X and +/- Y.
        # Orthographic view looks down -Z, target at world origin.
        view = np.eye(4, dtype=float)
        guides = projected_axis_guides(
            np.eye(4), view, (0., 0., 0.), 50., 400, 200)
        self.assertEqual(guides["X"]["positive"],
                         ((200., 100.), (400., 100.)))
        self.assertEqual(guides["X"]["negative"],
                         ((200., 100.), (0., 100.)))
        self.assertEqual(guides["Y"]["positive"],
                         ((200., 100.), (200., 0.)))
        self.assertEqual(guides["Y"]["negative"],
                         ((200., 100.), (200., 200.)))
        for halves in guides.values():
            for segment in halves.values():
                if segment:
                    for p in segment:
                        self.assertTrue(all(math.isfinite(x) for x in p))
                        self.assertTrue(0 <= p[0] <= 400)
                        self.assertTrue(0 <= p[1] <= 200)

    def test_perspective_near_camera_axes_never_invert(self):
        # Classic OpenGL projection with near=.1, far=100.
        near, far = .1, 100.
        proj = np.zeros((4,4))
        proj[0,0] = 1.
        proj[1,1] = 1.
        proj[2,2] = -(far+near)/(far-near)
        proj[2,3] = -2*far*near/(far-near)
        proj[3,2] = -1.
        view = np.eye(4)
        view[2,3] = -4.
        data = projected_axis_guides(
            proj, view, (0.,0.,0.), 100., 640, 480)
        self.assertIsNotNone(data["Z"]["positive"])
        for pair in data.values():
            for segment in pair.values():
                if segment:
                    for point in segment:
                        self.assertTrue(all(math.isfinite(v) for v in point))
                        self.assertGreaterEqual(point[0], -1e-6)
                        self.assertLessEqual(point[0], 640+1e-6)
                        self.assertGreaterEqual(point[1], -1e-6)
                        self.assertLessEqual(point[1], 480+1e-6)

    def test_reject_invalid_guide_inputs_without_corrupting_scene(self):
        with self.assertRaises(ValueError):
            projected_axis_guides(
                np.eye(4), np.eye(4), (0,0,0), -1, 800, 600)
        with self.assertRaises(ValueError):
            projected_axis_guides(
                np.eye(4), np.eye(4), (0,0,float("nan")), 10, 800, 600)
        with self.assertRaises(ValueError):
            camera_focus(np.zeros((3,3)), 3)
        with self.assertRaises(ValueError):
            orientation_axes(np.eye(4), radius=0)


if __name__ == "__main__":
    unittest.main()
