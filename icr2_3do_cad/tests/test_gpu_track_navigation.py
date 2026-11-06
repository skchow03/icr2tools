"""TRK-guided camera tests using the shared icr2_core.trk interpolation.

No commercial TRK file, GUI, or OpenGL context is required.
"""
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from gpu_viewer.track_navigation import (
    TrackNavigation, UNITS_PER_FOOT, DEFAULT_EYE_HEIGHT_FT,
    DEFAULT_EYE_HEIGHT_UNITS,
    find_matching_trk,
)


def flat_trk():
    """A 200-foot out-and-back closed lap along the X axis."""
    def section(start, heading, x, right_y, left_y):
        return SimpleNamespace(
            type=1, start_dlong=start, length=600000,
            heading=heading, pos1=[x, x], pos2=[right_y, left_y],
        )
    sec0 = section(0, 0, 0, -60000, 60000)
    sec1 = section(600000, -(2**31), 600000, 60000, -60000)
    return SimpleNamespace(
        num_sects=2, num_xsects=2, trklength=1200000,
        xsect_dlats=[-60000, 60000],
        sects=[sec0, sec1],
        xsect_data=[[0, 0, 0, 12345, 0, 0, 0, 0]] * 4,
    )


def curved_trk():
    """A quarter-circle section followed by a straight back to start."""
    radius = 300000
    curve = SimpleNamespace(
        type=2, start_dlong=0, length=900000, heading=0,
        pos1=[radius + 60000, radius - 60000],
        pos2=[0, 0], ang1=0, ang2=0,
    )
    straight = SimpleNamespace(
        type=1, start_dlong=900000, length=900000,
        heading=2**30,
        pos1=[radius + 60000, radius - 60000],
        pos2=[0, 0],
    )
    return SimpleNamespace(
        num_sects=2, num_xsects=2, trklength=1800000,
        xsect_dlats=[-60000, 60000],
        sects=[curve, straight],
        xsect_data=[[0, 0, 0, 0, 0, 0, 0, 0]] * 4,
    )


class TrackCameraGeometryTests(unittest.TestCase):
    def test_origin_is_ten_thousand_units_above_surface_and_looks_forward(self):
        nav = TrackNavigation("course.trk", flat_trk())
        pose = nav.pose()
        self.assertEqual((pose.dlong, pose.dlat, pose.section), (0, 0, 0))
        self.assertEqual(pose.ground, (0.0, 0.0, 12345.0))
        self.assertEqual(DEFAULT_EYE_HEIGHT_UNITS, 10000.0)
        self.assertEqual(DEFAULT_EYE_HEIGHT_FT * UNITS_PER_FOOT, 10000.0)
        self.assertEqual(pose.eye, (0.0, 0.0, 22345.0))
        self.assertAlmostEqual(pose.azimuth, -math.pi/2, places=7)
        self.assertAlmostEqual(pose.elevation, 0.0, places=7)

    def test_wasd_forward_backward_and_signed_lateral_motion(self):
        nav = TrackNavigation("course.trk", flat_trk())
        pose = nav.move(forward_feet=10)
        self.assertEqual(pose.dlong, 60000)
        self.assertAlmostEqual(pose.eye[0], 60000)
        left = nav.move(left_feet=2)
        self.assertEqual(left.dlat, 12000)
        self.assertAlmostEqual(left.eye[1], 12000)
        right = nav.move(left_feet=-4)
        self.assertEqual(right.dlat, -12000)
        self.assertAlmostEqual(right.eye[1], -12000)
        back = nav.move(forward_feet=-10)
        self.assertEqual(back.dlong, 0)
        self.assertEqual(back.dlat, -12000)

    def test_dlong_wraps_at_start_and_finish(self):
        nav = TrackNavigation("course.trk", flat_trk())
        back = nav.move(forward_feet=-10)
        self.assertEqual(back.dlong, 1140000)
        self.assertEqual(back.section, 1)
        self.assertAlmostEqual(back.eye[0], 60000, places=5)
        self.assertAlmostEqual(abs(back.azimuth), math.pi/2, places=5)
        self.assertEqual(nav.move(forward_feet=10).dlong, 0)

    def test_curve_follows_trk_tangent_and_left_is_inward(self):
        nav = TrackNavigation("curve.trk", curved_trk())
        nav.set_coordinates(450000, 0)
        mid = nav.pose()
        self.assertEqual(mid.section, 0)
        self.assertAlmostEqual(mid.azimuth, -math.pi/4, places=5)
        self.assertAlmostEqual(mid.ground[0], 300000 / math.sqrt(2), places=4)
        self.assertAlmostEqual(mid.ground[1], -300000 / math.sqrt(2), places=4)
        inward = nav.move(left_feet=2)
        self.assertLess(math.hypot(*inward.ground[:2]),
                        math.hypot(*mid.ground[:2]))
        self.assertAlmostEqual(inward.azimuth, mid.azimuth, places=5)

    def test_only_same_stem_trk_is_discovered_case_insensitively(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            model = folder/"STPETE24.3DO"
            model.touch()
            (folder/"unrelated.trk").write_bytes(b"elsewhere")
            self.assertIsNone(find_matching_trk(model))
            trk = folder/"stpete24.TRK"
            trk.write_bytes(b"matching")
            self.assertEqual(find_matching_trk(model), trk)
            self.assertIsNone(find_matching_trk(folder/"washdc.3d"))
            with patch("gpu_viewer.track_navigation.TRKFile.from_trk",
                       return_value=flat_trk()) as parser:
                nav = TrackNavigation.from_file(trk)
                self.assertEqual(nav.path, trk)
                parser.assert_called_once_with(trk)

    def test_invalid_geometry_and_inputs_report_errors(self):
        bad = flat_trk()
        bad.trklength = 0
        with self.assertRaises(ValueError):
            TrackNavigation("broken.trk", bad)
        nav = TrackNavigation("course.trk", flat_trk())
        for a, b in ((float("nan"), 0), (0, float("inf"))):
            with self.assertRaises(ValueError):
                nav.set_coordinates(a, b)
        with self.assertRaises(ValueError):
            nav.move(forward_feet=float("inf"))


if __name__ == "__main__":
    unittest.main()
