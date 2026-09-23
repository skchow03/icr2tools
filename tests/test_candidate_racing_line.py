"""Geometry checks for the preview-only candidate race path."""

import math
import unittest
from unittest.mock import patch

import numpy as np

from track_viewer.ai import racing_line_optimizer as optimizer


class _Section:
    def __init__(self):
        self.num_bounds = 2
        self.ground_fsects = 3
        self.ground_type = [0, 40, 0]


class _Track:
    def __init__(self):
        self.sects = [_Section()]


class CandidateRaceLineTest(unittest.TestCase):
    def setUp(self):
        self.dlongs = [i * 2500 for i in range(400)]
        self.track = _Track()

    def _generate(self, radius, width=20, margin=5):
        def xyz(_trk, dlong, dlat, _cline):
            angle = 2 * math.pi * dlong / 1_000_000
            r = radius(angle) + dlat / 6000
            return 6000 * r * math.cos(angle), 6000 * r * math.sin(angle), 0

        def boundary(_trk, _section, _fraction, index):
            return (-width if index == 0 else width) * 6000

        def ground(_trk, _section, _fraction, index):
            return [-width, -width + 3, width - 3][index] * 6000

        with patch.object(optimizer, "dlong2sect", return_value=(0, 0)), \
             patch.object(optimizer, "getbounddlat", side_effect=boundary), \
             patch.object(optimizer, "getgrounddlat", side_effect=ground), \
             patch.object(optimizer, "getxyz", side_effect=xyz):
            return np.array(optimizer.optimize_race_line(
                self.track, [], self.dlongs, margin_feet=margin
            )) / 6000

    def test_constant_radius_moves_outward_to_margin_and_closes(self):
        offsets = self._generate(lambda _angle: 100)
        self.assertTrue(np.allclose(offsets, 12, atol=0.1))
        self.assertAlmostEqual(offsets[0], offsets[-1], delta=0.1)

    def test_varying_radius_stays_smooth_within_pavement(self):
        offsets = self._generate(lambda angle: 100 + 15 * math.cos(3 * angle),
                                 width=12, margin=3)
        self.assertTrue(np.all(np.abs(offsets) <= 6.00001))
        self.assertLess(np.max(np.abs(np.diff(np.r_[offsets, offsets[0]]))), 1)

    def test_selects_main_pavement_not_separated_pit_strip(self):
        self.track.sects[0].ground_fsects = 4
        self.track.sects[0].ground_type = [40, 0, 40, 0]
        with patch.object(optimizer, "dlong2sect", return_value=(0, 0)), \
             patch.object(optimizer, "getbounddlat",
                          side_effect=lambda _t, _s, _f, i: (-20 if i == 0 else 20) * 6000), \
             patch.object(optimizer, "getgrounddlat",
                          side_effect=lambda _t, _s, _f, i: [-20, -14, -12, 12][i] * 6000):
            lower, upper = optimizer._paved_corridor(
                self.track, self.dlongs, [0] * len(self.dlongs), 3
            )
        self.assertTrue(np.all(lower == -9))
        self.assertTrue(np.all(upper == 9))

    def test_corner_targets_choose_outside_entry_and_inside_apex(self):
        straight = np.column_stack((np.linspace(0, 200, 81), np.full(81, -30)))
        a = np.linspace(-math.pi / 2, math.pi / 2, 61)[1:]
        right_turn = np.column_stack((200 + 30 * np.cos(a), 30 * np.sin(a)))
        back = np.column_stack((np.linspace(200, 0, 81)[1:], np.full(80, 30)))
        a = np.linspace(math.pi / 2, 3 * math.pi / 2, 61)[1:-1]
        left_turn = np.column_stack((30 * np.cos(a), 30 * np.sin(a)))
        centers = np.concatenate((straight, right_turn, back, left_turn))
        target, weight = optimizer._apex_targets(
            centers, np.full(len(centers), -10.0), np.full(len(centers), 10.0)
        )
        self.assertLess(target[70], -4)  # outside just before right turn
        self.assertGreater(target[115], 6)  # inside at right-turn apex
        self.assertLess(target[151], -3)  # outside after the turn
        self.assertGreater(weight[115], weight[30])

        tangent = np.roll(centers, -1, axis=0) - np.roll(centers, 1, axis=0)
        tangent /= np.linalg.norm(tangent, axis=1)[:, None]
        normals = np.column_stack((-tangent[:, 1], tangent[:, 0]))

        def xyz(_trk, dlong, dlat, _cline):
            i = int(round(dlong / 65536)) % len(centers)
            point = centers[i] + normals[i] * (dlat / 6000)
            return point[0] * 6000, point[1] * 6000, 0

        with patch.object(optimizer, "dlong2sect", return_value=(0, 0)), \
             patch.object(optimizer, "getbounddlat",
                          side_effect=lambda _t, _s, _f, i: (-15 if i == 0 else 15) * 6000), \
             patch.object(optimizer, "getgrounddlat",
                          side_effect=lambda _t, _s, _f, i: [-15, -12, 12][i] * 6000), \
             patch.object(optimizer, "getxyz", side_effect=xyz):
            path = np.array(optimizer.optimize_race_line(
                self.track, [], [i * 65536 for i in range(len(centers))],
                margin_feet=3, reference_dlats=[0] * len(centers)
            )) / 6000
        self.assertLess(path[70], -4)
        self.assertGreater(path[115], 6)
        self.assertLess(path[151], -4)
        self.assertTrue(np.all(np.abs(path) <= 9.00001))

    def test_rejects_unusable_width(self):
        with self.assertRaisesRegex(ValueError, "No paved corridor wide enough"):
            self._generate(lambda _angle: 100, width=4, margin=5)


if __name__ == "__main__":
    unittest.main()
