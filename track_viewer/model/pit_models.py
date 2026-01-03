"""Data models for track pit lane parameters."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

PIT_PARAMETER_DEFINITIONS: list[tuple[str, str, str, bool]] = [
    ("pitwall_dlat", "Pit wall DLAT", "DLAT position of the pitwall", True),
    (
        "pit_access_start_dlong",
        "Pit access start DLONG",
        "DLONG of the beginning of the pit access road",
        True,
    ),
    (
        "pit_access_end_dlong",
        "Pit access end DLONG",
        "DLONG of the end of pit access road",
        True,
    ),
    (
        "player_pit_stall_dlong",
        "Player pit stall DLONG",
        "DLONG of the back end of the first pit stall (player pit)",
        True,
    ),
    (
        "last_pit_stall_dlong",
        "Last pit stall DLONG",
        "DLONG of the back end of the final pit stall (15-30 feet before end of pit lane)",
        True,
    ),
    (
        "pit_stall_center_dlat",
        "Pit stall center DLAT",
        "DLAT of the middle of car when parked in pit stall",
        True,
    ),
    (
        "pit_to_race_transition_dlong",
        "Pit to race transition DLONG",
        "DLONG of the PIT to RACE transition point",
        True,
    ),
    (
        "pit_stall_count",
        "Pit stall count",
        "Number of pit stalls (number of cars this pits can hold)",
        True,
    ),
    (
        "unknown_dlong",
        "Unknown (usually 40-80 ft behind player stall)",
        "DLONG - Unknown - usually 40-80 ft behind player stall",
        True,
    ),
    (
        "pit_speed_limit_start_dlong",
        "Pit speed limit start DLONG",
        "DLONG of the pit speed limit start",
        True,
    ),
    (
        "pit_speed_limit_end_dlong",
        "Pit speed limit end DLONG",
        "DLONG of the pit speed limit end",
        True,
    ),
]

PIT_DLONG_LINE_INDICES: tuple[int, ...] = (1, 2, 3, 4, 6, 8, 9, 10)

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
