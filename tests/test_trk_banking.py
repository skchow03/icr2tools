"""Tests for TRK-derived banking and bank-aware speed envelopes."""

import math
import unittest
from types import SimpleNamespace

import numpy as np

from track_viewer.ai.indycar_speed_model import (
    _corner_speed_mph,
    speed_profile_mph,
)
from track_viewer.ai.trk_banking import build_trk_banking_profile


class TrkBankingTests(unittest.TestCase):
    @staticmethod
    def _track():
        # DLAT increases to the left; only the left half slopes inward.
        sect = SimpleNamespace(
            start_dlong=0.0,
            length=12000.0,
            alt=[6000.0, 6000.0, 3000.0],
            grade1=[0.0, 0.0, 0.0],
            grade2=[0.0, 0.0, 0.0],
            grade3=[0.0, 0.0, -1200.0],
        )
        return SimpleNamespace(
            num_xsects=3,
            xsect_dlats=[-6000.0, 0.0, 6000.0],
            num_sects=1,
            sects=[sect],
            trklength=12000.0,
        )

    def test_uses_trk_elevation_difference_at_actual_dlat(self):
        profile = build_trk_banking_profile(
            self._track(), [0.0, 6000.0, 11999.0],
        )
        angle = math.degrees(math.atan(0.5))
        sampled = profile.at_dlats([-3000.0, 3000.0, 3000.0])
        self.assertAlmostEqual(sampled[0], 0.0, places=6)
        self.assertAlmostEqual(sampled[1], math.degrees(math.atan(0.6)), places=6)
        self.assertGreater(sampled[2], angle)

    def test_dlat_selection_uses_local_cross_section_slope(self):
        profile = build_trk_banking_profile(self._track(), [0.0, 0.0, 0.0])
        sampled = profile.at_dlats([-3000, 1000, 6000])
        self.assertAlmostEqual(sampled[0], 0.0)
        self.assertAlmostEqual(sampled[1], math.degrees(math.atan(0.5)))
        self.assertAlmostEqual(sampled[2], math.degrees(math.atan(0.5)))

    def test_flat_or_missing_cross_sections_do_not_invent_banking(self):
        trk = self._track()
        trk.num_xsects = 1
        trk.xsect_dlats = [0]
        profile = build_trk_banking_profile(trk, [0, 6000])
        np.testing.assert_array_equal(profile.at_dlats([0, 0]), [0, 0])

    def test_dlats_must_match_station_count(self):
        profile = build_trk_banking_profile(self._track(), [0, 6000])
        with self.assertRaisesRegex(ValueError, "match"):
            profile.at_dlats([0])


class BankedSpeedTests(unittest.TestCase):
    def test_positive_bank_helps_left_turn_but_hurts_right_turn(self):
        curvature = 1.0 / 350.0
        flat = _corner_speed_mph(curvature)
        left_banked = _corner_speed_mph(curvature, banking_degrees=12)
        right_banked = _corner_speed_mph(-curvature, banking_degrees=12)
        self.assertGreater(left_banked, flat)
        self.assertLess(right_banked, flat)

    def test_bank_aware_speed_profile_and_flat_backwards_compatibility(self):
        angle = np.linspace(0, 2 * math.pi, 180, endpoint=False)
        xy = np.column_stack((350 * np.cos(angle), 350 * np.sin(angle)))
        flat = speed_profile_mph(xy)
        explicit_flat = speed_profile_mph(xy, banking_degrees=np.zeros(len(xy)))
        banked = speed_profile_mph(xy, banking_degrees=np.full(len(xy), 12.0))
        reverse = speed_profile_mph(xy[::-1], banking_degrees=np.full(len(xy), 12.0))
        np.testing.assert_allclose(flat, explicit_flat, rtol=0, atol=1e-9)
        self.assertGreater(float(np.mean(banked)), float(np.mean(flat)))
        self.assertLess(float(np.mean(reverse)), float(np.mean(flat)))

    def test_bad_banking_samples_rejected(self):
        angle = np.linspace(0, 2 * math.pi, 16, endpoint=False)
        xy = np.column_stack((350 * np.cos(angle), 350 * np.sin(angle)))
        for banks in ([12.0] * 15, [float("nan")] * 16):
            with self.assertRaisesRegex(ValueError, "Banking angles"):
                speed_profile_mph(xy, banking_degrees=banks)


if __name__ == "__main__":
    unittest.main()
