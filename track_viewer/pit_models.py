"""Data models for track pit lane parameters."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

PIT_PARAMETER_DEFINITIONS: list[tuple[str, str, str, bool]] = [
    ("pitwall_dlat", "Pit wall DLAT", "DLAT position of the pitwall", False),
    (
        "pit_access_start_dlong",
        "Pit access start DLONG",
        "DLONG of the beginning of the pit access road",
        False,
    ),
    (
        "pit_access_end_dlong",
        "Pit access end DLONG",
        "DLONG of the end of pit access road",
        False,
    ),
    (
        "player_pit_stall_dlong",
        "Player pit stall DLONG",
        "DLONG of the back end of the first pit stall (player pit)",
        False,
    ),
    (
        "last_pit_stall_dlong",
        "Last pit stall DLONG",
        "DLONG of the back end of the final pit stall (15-30 feet before end of pit lane)",
        False,
    ),
    (
        "pit_stall_center_dlat",
        "Pit stall center DLAT",
        "DLAT of the middle of car when parked in pit stall",
        False,
    ),
    (
        "pit_merge_dlong",
        "Pit merge DLONG",
        "DLONG where AI cars merge from PIT.LP to RACE.LP after pitting",
        False,
    ),
    (
        "pit_stall_count",
        "Pit stall count",
        "Number of pit stalls (number of cars this pits can hold)",
        True,
    ),
    (
        "unknown_dlong",
        "Unknown DLONG",
        "DLONG - Unknown - usually same value as pit wall start or slightly lower",
        False,
    ),
    (
        "pit_wall_start_dlong",
        "Pit wall start DLONG",
        "DLONG of the beginning of pit wall",
        False,
    ),
    (
        "pit_wall_end_dlong",
        "Pit wall end DLONG",
        "DLONG of the end of pit wall",
        False,
    ),
]


@dataclass
class PitParameters:
    """Editable PIT lane parameters from the track TXT file."""

    pitwall_dlat: float
    pit_access_start_dlong: float
    pit_access_end_dlong: float
    player_pit_stall_dlong: float
    last_pit_stall_dlong: float
    pit_stall_center_dlat: float
    pit_merge_dlong: float
    pit_stall_count: int
    unknown_dlong: float
    pit_wall_start_dlong: float
    pit_wall_end_dlong: float

    @classmethod
    def from_values(cls, values: Sequence[float]) -> "PitParameters":
        if len(values) < len(PIT_PARAMETER_DEFINITIONS):
            raise ValueError("Expected 11 PIT parameter values.")
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
            pit_merge_dlong=coerced[6],
            pit_stall_count=int(coerced[7]),
            unknown_dlong=coerced[8],
            pit_wall_start_dlong=coerced[9],
            pit_wall_end_dlong=coerced[10],
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
            self.pit_merge_dlong,
            float(self.pit_stall_count),
            self.unknown_dlong,
            self.pit_wall_start_dlong,
            self.pit_wall_end_dlong,
        ]
