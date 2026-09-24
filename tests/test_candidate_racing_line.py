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

    def _generate(self, radius, width=20, margin=5, **options):
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
                self.track, [], self.dlongs, margin_feet=margin, **options
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
            centers, np.full(len(centers), -10.0), np.full(len(centers), 10.0),
            lookahead_feet=15,
        )
        self.assertLess(target[70], -4)  # outside just before right turn
        self.assertGreater(target[115], 9.2)  # near the usable inside edge
        self.assertLess(target[151], -3)  # outside after the turn
        self.assertGreater(weight[115], weight[30])

        centered, _ = optimizer._apex_targets(
            centers, np.full(len(centers), -10.0), np.full(len(centers), 10.0),
            lookahead_feet=15, corner_width_pct=0,
        )
        wider, _ = optimizer._apex_targets(
            centers, np.full(len(centers), -10.0), np.full(len(centers), 10.0),
            lookahead_feet=15, corner_width_pct=100,
        )
        self.assertAlmostEqual(centered[115], 0, delta=0.1)
        self.assertGreater(wider[115], target[115])
        early, _ = optimizer._apex_targets(
            centers, np.full(len(centers), -10.0), np.full(len(centers), 10.0),
            lookahead_feet=15, apex_position_pct=40,
        )
        late, _ = optimizer._apex_targets(
            centers, np.full(len(centers), -10.0), np.full(len(centers), 10.0),
            lookahead_feet=15, apex_position_pct=80,
        )
        self.assertLess(np.argmax(early[85:145]), np.argmax(late[85:145]))

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
                margin_feet=3, reference_dlats=[0] * len(centers),
                lookahead_feet=15,
            )) / 6000
        self.assertLess(path[70], -4)
        self.assertGreater(path[115], 8)
        self.assertLess(path[151], -4)
        self.assertTrue(np.all(np.abs(path) <= 9.00001))

    def test_linked_turns_share_handoff_and_straights_transition_once(self):
        lower, upper = np.full(300, -10.0), np.full(300, 10.0)
        # The first two corners form a close S bend. The third is separated
        # by a straight, with another long straight across the lap seam.
        corners = [(20, 60, 40, 1, 12, 1.0),
                   (68, 108, 88, -1, 12, 1.0),
                   (180, 210, 195, 1, 12, 1.0)]
        target, weight = optimizer._linked_corner_targets(
            corners, lower, upper, 75
        )
        self.assertGreater(target[40], 7)
        self.assertLess(target[88], -7)
        self.assertLess(abs(target[64]), 2)  # one shared S-bend handoff
        self.assertEqual(weight[40], 10)

        # One smooth move across the long straight prepares for the next
        # outside entry; the other straight stays on the same side.
        self.assertTrue(np.all(np.diff(target[120:169]) <= 1e-10))
        self.assertTrue(np.allclose(target[222:], target[222]))
        self.assertTrue(np.allclose(target[:9], target[222]))
        self.assertLess(abs(target[299] - target[0]), 1e-10)

        # A changing corridor still keeps every planned target in pavement.
        variable_upper = upper + 2 * np.sin(np.arange(300) * 2 * np.pi / 300)
        varied, _ = optimizer._linked_corner_targets(
            corners, lower, variable_upper, 75
        )
        self.assertTrue(np.all(varied >= lower))
        self.assertTrue(np.all(varied <= variable_upper))

    def test_adjacent_same_direction_turns_keep_shared_outside_setup(self):
        lower, upper = np.full(200, -10.0), np.full(200, 10.0)
        corners = [(15, 55, 35, 1, 10, 1.0),
                   (61, 100, 80, 1, 10, 1.0)]
        target, _ = optimizer._linked_corner_targets(corners, lower, upper, 75)
        self.assertAlmostEqual(target[58], -7.5)
        self.assertGreater(target[35], 7)
        self.assertGreater(target[80], 7)

    def test_apex_transition_begins_early_without_flattening_road_curvature(self):
        lower, upper = np.full(200, -10.0), np.full(200, 10.0)
        target, _ = optimizer._linked_corner_targets(
            [(20, 80, 55, 1, 18, 1.0)], lower, upper, 75
        )
        self.assertGreater(target[5], -7.49)  # starts upstream of turn index 20
        self.assertAlmostEqual(target[55], 7.5)
        near_apex_bend = abs(target[54] - 2 * target[55] + target[56])
        approach_bend = abs(target[37] - 2 * target[38] + target[39])
        self.assertLess(near_apex_bend, approach_bend * 0.2)

    def test_exit_unwinds_without_a_countersteer_to_reach_outside(self):
        radius = 45.0
        straight = np.column_stack((np.linspace(0, 160, 81),
                                    np.full(81, -radius)))
        a = np.linspace(-math.pi / 2, math.pi / 2, 61)[1:]
        turn = np.column_stack((160 + radius * np.cos(a), radius * np.sin(a)))
        back = np.column_stack((np.linspace(160, 0, 81)[1:],
                                np.full(80, radius)))
        a = np.linspace(math.pi / 2, 3 * math.pi / 2, 61)[1:-1]
        other = np.column_stack((radius * np.cos(a), radius * np.sin(a)))
        centers = np.concatenate((straight, turn, back, other))
        tangent = np.roll(centers, -1, axis=0) - np.roll(centers, 1, axis=0)
        tangent /= np.linalg.norm(tangent, axis=1)[:, None]
        normals = np.column_stack((-tangent[:, 1], tangent[:, 0]))

        def xyz(_trk, dlong, dlat, _cline):
            i = int(round(dlong / 65536)) % len(centers)
            point = centers[i] + normals[i] * dlat / 6000
            return point[0] * 6000, point[1] * 6000, 0

        with patch.object(optimizer, "dlong2sect", return_value=(0, 0)), \
             patch.object(optimizer, "getbounddlat",
                          side_effect=lambda _t, _s, _f, i: (-15 if i == 0 else 15) * 6000), \
             patch.object(optimizer, "getgrounddlat",
                          side_effect=lambda _t, _s, _f, i: [-15, -12, 12][i] * 6000), \
             patch.object(optimizer, "getxyz", side_effect=xyz):
            offsets = np.array(optimizer.optimize_race_line(
                self.track, [], [i * 65536 for i in range(len(centers))],
                margin_feet=3, reference_dlats=[0] * len(centers),
                lookahead_feet=40, corner_width_pct=90, apex_position_pct=65,
            )) / 6000
        points = centers + normals * offsets[:, None]
        incoming = points - np.roll(points, 1, axis=0)
        outgoing = np.roll(points, -1, axis=0) - points
        heading_change = np.arctan2(
            incoming[:, 0] * outgoing[:, 1] - incoming[:, 1] * outgoing[:, 0],
            np.sum(incoming * outgoing, axis=1),
        )
        self.assertGreaterEqual(np.min(heading_change[140:180]), -0.001)
        self.assertTrue(np.all(np.abs(offsets) <= 9.00001))

    def test_opposite_corner_allows_steering_transition_between_turns(self):
        corners = [(10, 40, 25, 1, 12, 1.0),
                   (48, 78, 63, -1, 12, 1.0),
                   (160, 190, 175, 1, 12, 1.0)]
        signs = optimizer._exit_turn_signs(corners, 220)
        self.assertEqual(signs[30], 1)
        self.assertEqual(signs[40], 0)  # release before the next entry
        self.assertEqual(signs[70], -1)

    def test_explicit_pit_side_clips_continuous_pavement_at_extra_wall(self):
        self.track.sects[0].num_bounds = 3
        self.track.sects[0].ground_fsects = 1
        self.track.sects[0].ground_type = [40]
        with patch.object(optimizer, "dlong2sect", return_value=(0, 0)), \
             patch.object(optimizer, "getbounddlat",
                          side_effect=lambda _t, _s, _f, i: [-20, 0, 20][i] * 6000), \
             patch.object(optimizer, "getgrounddlat", return_value=-20 * 6000):
            auto = optimizer._paved_corridor(
                self.track, self.dlongs, [-10 * 6000] * len(self.dlongs), 2
            )
            pit_left = optimizer._paved_corridor(self.track, self.dlongs, None, 2,
                                                  "left")
            pit_right = optimizer._paved_corridor(self.track, self.dlongs, None, 2,
                                                   "right")
        self.assertEqual((auto[0][0], auto[1][0]), (-18, -2))
        self.assertEqual((pit_left[0][0], pit_left[1][0]), (-18, -2))
        self.assertEqual((pit_right[0][0], pit_right[1][0]), (2, 18))

    def test_curved_pit_wall_stays_between_segments_and_at_section_edge(self):
        class Section:
            def __init__(self, start):
                self.start_dlong = start
                self.num_bounds = 3
                self.ground_fsects = 1
                self.ground_type = [40]  # paved across the internal wall

        track = _Track()
        track.sects = [Section(0), Section(450_000)]
        track.trklength = 1_000_000
        dlongs = [i * 100_000 for i in range(10)]

        def section_at(_trk, dlong):
            if dlong < 450_000:
                return 0, dlong / 450_000
            return 1, (dlong - 450_000) / 550_000

        def boundary(_trk, section, fraction, index):
            if index == 1:
                return (6 * fraction if section == 0 else 6 * (1 - fraction)) * 6000
            return (-20 if index == 0 else 20) * 6000

        def xyz(_trk, dlong, dlat, _cline):
            angle = 2 * math.pi * dlong / track.trklength
            radius = 80 - dlat / 6000  # positive DLAT is inside this turn
            return radius * math.cos(angle) * 6000, radius * math.sin(angle) * 6000, 0

        with patch.object(optimizer, "dlong2sect", side_effect=section_at), \
             patch.object(optimizer, "getbounddlat", side_effect=boundary), \
             patch.object(optimizer, "getgrounddlat", return_value=-20 * 6000), \
             patch.object(optimizer, "getxyz", side_effect=xyz):
            lo, hi = optimizer._paved_corridor(
                track, dlongs, [-10 * 6000] * len(dlongs), 2, "left"
            )
            centers = np.array([xyz(track, x, 0, [])[0:2] for x in dlongs]) / 6000
            normals = np.array([
                (np.array(xyz(track, x, 6000, [])[0:2]) / 6000 - center)
                for x, center in zip(dlongs, centers)
            ])
            checks = optimizer._between_record_constraints(
                track, [], dlongs, [-10 * 6000] * len(dlongs), 2,
                "left", centers, normals,
            )
            # At the sample points this path is legal, but its chords cut
            # inside the curved wall, including near the section boundary.
            self.assertTrue(any(a * hi[i] + b * hi[j] + c > upper
                                for i, j, a, b, c, lower, upper, _ in checks))
            corrected = optimizer._enforce_between_record_constraints(
                hi, lo, hi, checks
            )
            self.assertTrue(np.all(corrected >= lo - 1e-5))
            self.assertTrue(all(lower - 1e-4 <= a * corrected[i] +
                                b * corrected[j] + c <= upper + 1e-4
                                for i, j, a, b, c, lower, upper, _ in checks))
            generated = np.array(optimizer.optimize_race_line(
                track, [], dlongs, margin_feet=2,
                reference_dlats=[-10 * 6000] * len(dlongs),
                pit_side="left", lookahead_feet=15,
            )) / 6000
            self.assertTrue(np.all(generated >= lo - 1e-4))
            self.assertTrue(np.all(generated <= hi + 1e-4))
            self.assertTrue(all(lower - 1e-4 <= a * generated[i] +
                                b * generated[j] + c <= upper + 1e-4
                                for i, j, a, b, c, lower, upper, _ in checks))

    def test_auto_split_requires_an_unambiguous_existing_line(self):
        self.track.sects[0].num_bounds = 3
        self.track.sects[0].ground_fsects = 1
        self.track.sects[0].ground_type = [40]
        with patch.object(optimizer, "dlong2sect", return_value=(0, 0)), \
             patch.object(optimizer, "getbounddlat",
                          side_effect=lambda _t, _s, _f, i: [-20, 0, 20][i] * 6000), \
             patch.object(optimizer, "getgrounddlat", return_value=-20 * 6000):
            with self.assertRaisesRegex(ValueError, "choose the pit side"):
                optimizer._paved_corridor(self.track, self.dlongs, None, 2)

    def test_rejects_unusable_width(self):
        with self.assertRaisesRegex(ValueError, "No paved corridor wide enough"):
            self._generate(lambda _angle: 100, width=4, margin=5)



    def test_side_preference_moves_line_but_respects_margin(self):
        neutral = self._generate(
            lambda _angle: 300, width=30, margin=5,
            side_preference="none", side_preference_pct=0,
        )
        left = self._generate(
            lambda _angle: 300, width=30, margin=5,
            side_preference="left", side_preference_pct=100,
        )
        neutral_feet = np.asarray(neutral)
        left_feet = np.asarray(left)
        # A 100% preference must be visually/materially distinct, not just
        # numerically different by a tiny optimizer penalty.
        self.assertGreater(
            float(np.mean(left_feet - neutral_feet)), 5.0
        )
        self.assertGreater(float(np.percentile(left_feet, 25)), 10.0)
        self.assertTrue(np.all(left_feet <= 25.0 + 1e-6))
        self.assertTrue(np.all(left_feet >= -25.0 - 1e-6))

    def test_left_and_right_preferences_create_distinct_passing_lanes(self):
        left = self._generate(
            lambda _angle: 300, width=30, margin=5,
            side_preference="left", side_preference_pct=75,
        )
        right = self._generate(
            lambda _angle: 300, width=30, margin=5,
            side_preference="right", side_preference_pct=75,
        )
        self.assertGreater(float(np.mean(left - right)), 10.0)
        self.assertTrue(np.all(np.abs(left) <= 25.0 + 1e-6))
        self.assertTrue(np.all(np.abs(right) <= 25.0 + 1e-6))


if __name__ == "__main__":
    unittest.main()
