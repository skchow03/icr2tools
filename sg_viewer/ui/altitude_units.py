from __future__ import annotations

ALTITUDE_UNITS_PER_FOOT = 500

DEFAULT_ALTITUDE_MIN_FEET = -20
DEFAULT_ALTITUDE_MAX_FEET = 100


def feet_to_500ths(value: float) -> int:
    return int(round(value * ALTITUDE_UNITS_PER_FOOT))


def feet_from_500ths(value: float) -> int:
    return int(round(value / ALTITUDE_UNITS_PER_FOOT))
