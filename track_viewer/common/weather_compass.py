"""Helpers for interpreting wind heading adjustments in the preview compass."""
from __future__ import annotations

import math

TURN_SCALE = 4_294_967_296.0
TURN_SCALE_INT = 4_294_967_296
HALF_TURN_SCALE = TURN_SCALE_INT // 2
TURN_OFFSET = 0.25
INT32_MIN = -2_147_483_648
WIND_DIRECTION_SCALE = HALF_TURN_SCALE


def heading_adjust_to_turns(adjust: int) -> float:
    """Convert heading adjust value to turns where 0 points up."""
    turns = (TURN_OFFSET - adjust / TURN_SCALE) % 1.0
    return turns


def turns_to_heading_adjust(turns: float) -> int:
    """Convert turns (0 = up) into a heading adjust value."""
    normalized_turns = turns % 1.0
    value = int(round((TURN_OFFSET - normalized_turns) * TURN_SCALE))
    if value <= -HALF_TURN_SCALE:
        value += TURN_SCALE_INT
    elif value > HALF_TURN_SCALE:
        value -= TURN_SCALE_INT
    if value == INT32_MIN:
        return HALF_TURN_SCALE
    return value


def wind_direction_to_turns(direction: int) -> float:
    """Convert wind direction value into turns (0 = up)."""
    return (direction / WIND_DIRECTION_SCALE) % 1.0


def turns_to_wind_direction(turns: float) -> int:
    """Convert turns (0 = up) into wind direction units."""
    normalized_turns = turns % 1.0
    value = int(round(normalized_turns * WIND_DIRECTION_SCALE))
    if value == WIND_DIRECTION_SCALE:
        return 0
    return value


def turns_to_unit_vector(turns: float) -> tuple[float, float]:
    """Convert turns (0 = up) into a unit vector in screen coordinates."""
    angle = turns * math.tau
    return math.sin(angle), -math.cos(angle)


def turns_from_vector(dx: float, dy: float) -> float:
    """Convert a screen-space vector into turns (0 = up)."""
    if dx == 0 and dy == 0:
        return 0.0
    angle = math.atan2(dx, -dy)
    turns = angle / math.tau
    if turns < 0:
        turns += 1.0
    return turns


def degrees_to_turns(degrees: float) -> float:
    """Convert degrees (0 = up) into turns."""
    return (degrees / 360.0) % 1.0


def turns_to_degrees(turns: float) -> int:
    """Convert turns (0 = up) into degrees."""
    return int(round((turns % 1.0) * 360.0)) % 360
