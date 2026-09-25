"""Data models for track pit lane parameters."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

PIT_PARAMETER_DEFINITIONS: list[tuple[str, str, str, bool]] = [
    ("pitwall_dlat", "Pit wall DLAT", "DLAT of the pit wall separating the pit lane from the track. If two walls define the median, use the inner wall facing the pit lane.", True),
    ("pit_access_start_dlong", "Pit lane start DLONG", "Pit lane entrance begins here, possibly before the physical pit wall. At this point, PIT.LP should still be within the PANIC lines.", True),
    ("pit_access_end_dlong", "Pit lane end DLONG", "Position where the pit lane wall ends. PIT.LP should still be outside the PANIC lines: PIT.LP is exiting pit lane while PANIC is on the racing portion of the track.", True),
    ("player_pit_stall_dlong", "Player pit stall DLONG", "Beginning of the player's pit stall, aligned with the back of the player's car.", True),
    ("last_pit_stall_dlong", "Last pit stall DLONG", "Beginning of the final AI opponent's pit stall. The pace car occupies a stall after this one, so leave adequate room.", True),
    ("pit_stall_center_dlat", "Pit stall center DLAT", "Lateral positioning of all cars in the pit lane.", True),
    ("pit_to_race_transition_dlong", "PIT.LP to RACE.LP transition DLONG", "Usually farther down the road from the pit exit to ensure a smooth pit exit.", True),
    ("pit_stall_count", "Pit stall count", "Number of pit stalls for the player and AI opponents. Do not include the pace car's stall.", True),
    ("unknown_dlong", "Unknown", "This line is placed somewhere before the player's pit stall start; it may be before or after value 10 (pit lane start). Its exact purpose is unknown.", True),
    ("pit_speed_limit_start_dlong", "Pit lane start", "Point where PIT.LP is now outside the PANIC zone. PANIC will have just transitioned from the outside pit lane entrance wall to the pit median.", True),
    ("pit_speed_limit_end_dlong", "Pit speed limit end", "End of the pit speed limit, usually close to value 3 (pit lane end DLONG).", True),
]

PIT_DLONG_LINE_INDICES: tuple[int, ...] = (1, 2, 3, 4, 6, 8, 9, 10)
PIT_DLAT_LINE_INDICES: tuple[int, ...] = (0, 5)

PIT_DLONG_LINE_COLORS: dict[int, str] = {
    1: "#f44336",
    2: "#ff9800",
    3: "#ffeb3b",
    4: "#4caf50",
    6: "#009688",
    8: "#2196f3",
    9: "#3f51b5",
    10: "#00ffe5",
}

PIT_DLAT_LINE_COLORS: dict[int, str] = {
    0: "#ffeb3b",
    5: "#00ff00",
}


@dataclass
class PitParameters:
    """Editable PIT lane parameters from the track TXT file."""

    pitwall_dlat: float
    pit_access_start_dlong: float
    pit_access_end_dlong: float
    player_pit_stall_dlong: float
    last_pit_stall_dlong: float
    pit_stall_center_dlat: float
    pit_to_race_transition_dlong: float
    pit_stall_count: int
    unknown_dlong: float
    pit_speed_limit_start_dlong: float
    pit_speed_limit_end_dlong: float

    @classmethod
    def from_values(cls, values: Sequence[float]) -> "PitParameters":
        expected = len(PIT_PARAMETER_DEFINITIONS)
        if len(values) < expected:
            raise ValueError(f"Expected {expected} PIT parameter values.")
        coerced: list[float] = []
        for value, definition in zip(values, PIT_PARAMETER_DEFINITIONS):
            is_integer = definition[3]
            if is_integer:
                coerced.append(int(round(value)))
            else:
                coerced.append(float(value))
        return cls(
            pitwall_dlat=coerced[0],
            pit_access_start_dlong=coerced[1],
            pit_access_end_dlong=coerced[2],
            player_pit_stall_dlong=coerced[3],
            last_pit_stall_dlong=coerced[4],
            pit_stall_center_dlat=coerced[5],
            pit_to_race_transition_dlong=coerced[6],
            pit_stall_count=int(coerced[7]),
            unknown_dlong=coerced[8],
            pit_speed_limit_start_dlong=coerced[9],
            pit_speed_limit_end_dlong=coerced[10],
        )

    @classmethod
    def empty(cls) -> "PitParameters":
        return cls.from_values([0.0] * len(PIT_PARAMETER_DEFINITIONS))

    def values(self) -> list[float]:
        return [
            self.pitwall_dlat,
            self.pit_access_start_dlong,
            self.pit_access_end_dlong,
            self.player_pit_stall_dlong,
            self.last_pit_stall_dlong,
            self.pit_stall_center_dlat,
            self.pit_to_race_transition_dlong,
            float(self.pit_stall_count),
            self.unknown_dlong,
            self.pit_speed_limit_start_dlong,
            self.pit_speed_limit_end_dlong,
        ]
