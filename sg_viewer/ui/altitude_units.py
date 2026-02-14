from __future__ import annotations

ALTITUDE_UNITS_PER_FOOT = 6000
ALTITUDE_SLIDER_SCALE = 10
INCHES_PER_FOOT = 12.0
METERS_PER_FOOT = 0.3048

DEFAULT_ALTITUDE_MIN_FEET = -20
DEFAULT_ALTITUDE_MAX_FEET = 100
MIN_ELEVATION_Y_RANGE_FEET = 1.0
MIN_ELEVATION_Y_RANGE_UNITS = int(round(MIN_ELEVATION_Y_RANGE_FEET * ALTITUDE_UNITS_PER_FOOT))


def feet_to_500ths(value: float) -> int:
    return int(round(value * ALTITUDE_UNITS_PER_FOOT))


def feet_from_500ths(value: float) -> float:
    return value / ALTITUDE_UNITS_PER_FOOT


def feet_to_slider_units(value: float) -> int:
    return int(round(value * ALTITUDE_SLIDER_SCALE))


def feet_from_slider_units(value: int) -> float:
    return value / ALTITUDE_SLIDER_SCALE


def units_from_500ths(value: float, unit: str) -> float:
    feet = feet_from_500ths(value)
    if unit == "feet":
        return feet
    if unit == "meter":
        return feet * METERS_PER_FOOT
    if unit == "inch":
        return feet * INCHES_PER_FOOT
    return float(value)


def units_to_500ths(value: float, unit: str) -> int:
    if unit == "feet":
        return feet_to_500ths(value)
    if unit == "meter":
        return feet_to_500ths(value / METERS_PER_FOOT)
    if unit == "inch":
        return feet_to_500ths(value / INCHES_PER_FOOT)
    return int(round(value))
