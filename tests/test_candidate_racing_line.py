"""Geometry checks for the preview-only candidate race path."""

import math
import unittest
from unittest.mock import patch

import numpy as np

from track_viewer.ai import racing_line_optimizer as optimizer


class _Section:
    num_bounds = 2


class _Track:
    sects = [_Section()]


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

        with patch.object(optimizer, "dlong2sect", return_value=(0, 0)), \
             patch.object(optimizer, "getbounddlat", side_effect=boundary), \
             patch.object(optimizer, "getxyz", side_effect=xyz):
            return np.array(optimizer.optimize_race_line(
                self.track, [], self.dlongs, margin_feet=margin
            )) / 6000

    def test_constant_radius_moves_outward_to_margin_and_closes(self):
        offsets = self._generate(lambda _angle: 100)
        self.assertTrue(np.allclose(offsets, 15, atol=0.1))
        self.assertAlmostEqual(offsets[0], offsets[-1], delta=0.1)

    def test_varying_radius_reduces_bending_within_walls(self):
        offsets = self._generate(lambda angle: 100 + 15 * math.cos(3 * angle),
                                 width=12, margin=3)
        angles = np.array(self.dlongs) * (2 * math.pi / 1_000_000)
        normals = np.column_stack((np.cos(angles), np.sin(angles)))
        center = (100 + 15 * np.cos(3 * angles))[:, None] * normals
        old_energy = optimizer._energy_and_gradient(center)[0]
        new_energy = optimizer._energy_and_gradient(
            center + offsets[:, None] * normals
        )[0]
        self.assertLess(new_energy, old_energy)
        self.assertTrue(np.all(np.abs(offsets) <= 9.00001))
        self.assertLess(np.max(np.abs(np.diff(np.r_[offsets, offsets[0]]))), 1)

    def test_rejects_unusable_width(self):
        with self.assertRaisesRegex(ValueError, "No usable width"):
            self._generate(lambda _angle: 100, width=4, margin=5)


if __name__ == "__main__":
    unittest.main()
