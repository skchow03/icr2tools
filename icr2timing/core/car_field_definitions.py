"""Shared metadata describing each raw car-state field."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional


@dataclass(frozen=True)
class CarFieldDefinition:
    """Descriptor for a single 4-byte value inside the car-state block."""

    index: int
    name: str
    description: str = ""


# Number of 32-bit integers that make up the raw car telemetry structure.
DEFAULT_FIELD_COUNT = 133


def _build_known_definitions() -> Dict[int, CarFieldDefinition]:
    """Definitions gathered from reverse engineering and documentation."""

    # Only a subset of the fields currently have friendly names/descriptions.
    # The rest fall back to a numbered placeholder (``value_000`` etc.).
    return {
        11: CarFieldDefinition(11, "dlat", "Signed lateral distance from track center."),
        18: CarFieldDefinition(18, "speed_raw", "Forward speed value used for overlays."),
        22: CarFieldDefinition(
            22,
            "lap_end_clock",
            "Clock value (ms) when the previous lap finished.",
        ),
        23: CarFieldDefinition(
            23,
            "lap_start_clock",
            "Clock value (ms) when the current lap started.",
        ),
        31: CarFieldDefinition(31, "dlong", "Signed distance along track from leader."),
        34: CarFieldDefinition(34, "qualifying_time", "Last qualifying lap time in ms."),
        35: CarFieldDefinition(35, "fuel_laps", "Estimated laps of fuel remaining."),
        36: CarFieldDefinition(36, "laps_lead", "Laps led during the current session."),
        38: CarFieldDefinition(38, "laps_since_yellow", "Laps since the previous yellow flag."),
        52: CarFieldDefinition(52, "lp_line", "Current LP line index."),
        98: CarFieldDefinition(
            98,
            "pit_release_timer",
            "Countdown timer before the car can leave the pits.",
        ),
    }


_KNOWN_DEFINITIONS = _build_known_definitions()


def _placeholder_definition(index: int) -> CarFieldDefinition:
    return CarFieldDefinition(index, f"value_{index:03d}")


def ensure_field_definitions(count: int = DEFAULT_FIELD_COUNT) -> List[CarFieldDefinition]:
    """Return a list of field definitions up to *count* entries."""

    return [
        _KNOWN_DEFINITIONS.get(index, _placeholder_definition(index))
        for index in range(count)
    ]


CAR_FIELD_DEFINITIONS: List[CarFieldDefinition] = ensure_field_definitions()
CAR_FIELD_DEFINITIONS_BY_INDEX: Dict[int, CarFieldDefinition] = {
    definition.index: definition for definition in CAR_FIELD_DEFINITIONS
}


def get_field_definition(index: int) -> Optional[CarFieldDefinition]:
    """Look up a field definition by index."""

    return CAR_FIELD_DEFINITIONS_BY_INDEX.get(index)


def iter_field_definitions(indices: Iterable[int]) -> List[CarFieldDefinition]:
    """Return definitions for the requested *indices* preserving order."""

    return [
        CAR_FIELD_DEFINITIONS_BY_INDEX.get(index, _placeholder_definition(index))
        for index in indices
    ]

