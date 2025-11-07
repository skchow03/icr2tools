import unittest

from icr2_core.model import CarState, RaceState
from icr2timing.analysis.gap_utils import compute_intervals_display


class ComputeIntervalsDisplayTests(unittest.TestCase):
    def test_time_gap_when_laps_down_equal(self):
        ahead_state = CarState(
            struct_index=0,
            laps_left=0,
            laps_completed=101,
            last_lap_ms=60000,
            last_lap_valid=True,
            laps_down=0,
            lap_end_clock=100000,
            lap_start_clock=95000,
            car_status=0,
            current_lp=0,
            fuel_laps_remaining=0,
            dlat=0,
            dlong=0,
            values=[0] * 133,
        )
        car_state = CarState(
            struct_index=1,
            laps_left=0,
            laps_completed=100,
            last_lap_ms=60500,
            last_lap_valid=True,
            laps_down=0,
            lap_end_clock=100200,
            lap_start_clock=95200,
            car_status=0,
            current_lp=0,
            fuel_laps_remaining=0,
            dlat=0,
            dlong=0,
            values=[0] * 133,
        )

        race_state = RaceState(
            raw_count=2,
            display_count=2,
            total_laps=200,
            order=[0, 1],
            drivers={},
            car_states={
                0: ahead_state,
                1: car_state,
            },
        )

        intervals = compute_intervals_display(race_state)
        interval_text, _ = intervals[1]

        self.assertEqual(interval_text, "+0.200")
        self.assertNotIn("L", interval_text)

    def test_first_lap_down_shows_time_only(self):
        ahead_state = CarState(
            struct_index=0,
            laps_left=0,
            laps_completed=101,
            last_lap_ms=60000,
            last_lap_valid=True,
            laps_down=0,
            lap_end_clock=100000,
            lap_start_clock=95000,
            car_status=0,
            current_lp=0,
            fuel_laps_remaining=0,
            dlat=0,
            dlong=0,
            values=[0] * 133,
        )
        car_state = CarState(
            struct_index=1,
            laps_left=0,
            laps_completed=100,
            last_lap_ms=60500,
            last_lap_valid=True,
            laps_down=1,
            lap_end_clock=100500,
            lap_start_clock=95200,
            car_status=0,
            current_lp=0,
            fuel_laps_remaining=0,
            dlat=0,
            dlong=0,
            values=[0] * 133,
        )

        race_state = RaceState(
            raw_count=2,
            display_count=2,
            total_laps=200,
            order=[0, 1],
            drivers={},
            car_states={
                0: ahead_state,
                1: car_state,
            },
        )

        intervals = compute_intervals_display(race_state)
        interval_text, _ = intervals[1]

        self.assertEqual(interval_text, "+0.500")
        self.assertNotIn("L", interval_text)

    def test_subsequent_lapped_car_uses_previous_active_car(self):
        leader_state = CarState(
            struct_index=0,
            laps_left=0,
            laps_completed=101,
            last_lap_ms=60000,
            last_lap_valid=True,
            laps_down=0,
            lap_end_clock=100000,
            lap_start_clock=95000,
            car_status=0,
            current_lp=0,
            fuel_laps_remaining=0,
            dlat=0,
            dlong=0,
            values=[0] * 133,
        )

        first_lap_down = CarState(
            struct_index=1,
            laps_left=0,
            laps_completed=100,
            last_lap_ms=60500,
            last_lap_valid=True,
            laps_down=1,
            lap_end_clock=100500,
            lap_start_clock=95200,
            car_status=0,
            current_lp=0,
            fuel_laps_remaining=0,
            dlat=0,
            dlong=0,
            values=[0] * 133,
        )

        second_lap_down = CarState(
            struct_index=2,
            laps_left=0,
            laps_completed=100,
            last_lap_ms=60600,
            last_lap_valid=True,
            laps_down=1,
            lap_end_clock=100800,
            lap_start_clock=95300,
            car_status=0,
            current_lp=0,
            fuel_laps_remaining=0,
            dlat=0,
            dlong=0,
            values=[0] * 133,
        )

        race_state = RaceState(
            raw_count=3,
            display_count=3,
            total_laps=200,
            order=[0, 1, 2],
            drivers={},
            car_states={
                0: leader_state,
                1: first_lap_down,
                2: second_lap_down,
            },
        )

        intervals = compute_intervals_display(race_state)

        first_gap, _ = intervals[1]
        second_gap, _ = intervals[2]

        self.assertEqual(first_gap, "+0.500")
        self.assertEqual(second_gap, "+0.300")

    def test_gap_between_lapped_cars_uses_time_when_one_lap_apart(self):
        first_lap_down = CarState(
            struct_index=0,
            laps_left=0,
            laps_completed=150,
            last_lap_ms=60000,
            last_lap_valid=True,
            laps_down=1,
            lap_end_clock=200000,
            lap_start_clock=195000,
            car_status=0,
            current_lp=0,
            fuel_laps_remaining=0,
            dlat=0,
            dlong=0,
            values=[0] * 133,
        )

        second_lap_down = CarState(
            struct_index=1,
            laps_left=0,
            laps_completed=149,
            last_lap_ms=60250,
            last_lap_valid=True,
            laps_down=2,
            lap_end_clock=200400,
            lap_start_clock=195150,
            car_status=0,
            current_lp=0,
            fuel_laps_remaining=0,
            dlat=0,
            dlong=0,
            values=[0] * 133,
        )

        race_state = RaceState(
            raw_count=2,
            display_count=2,
            total_laps=200,
            order=[0, 1],
            drivers={},
            car_states={
                0: first_lap_down,
                1: second_lap_down,
            },
        )

        intervals = compute_intervals_display(race_state)

        gap_text, _ = intervals[1]

        self.assertEqual(gap_text, "+0.400")
        self.assertNotIn("L", gap_text)


if __name__ == "__main__":
    unittest.main()
