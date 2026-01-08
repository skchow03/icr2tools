"""Helpers for interpreting wind heading adjustments in the preview compass."""
from __future__ import annotations

import math

TURN_SCALE = 2_147_483_648.0
INT32_MIN = -2_147_483_648
INT32_MAX = 2_147_483_647


def heading_adjust_to_turns(adjust: int) -> float:
    """Convert heading adjust value to turns where 0 points up."""
    turns = (-adjust / TURN_SCALE) % 1.0
    return turns


def turns_to_heading_adjust(turns: float) -> int:
    """Convert turns (0 = up) into a heading adjust value."""
    value = int(round(-turns * TURN_SCALE))
    return max(INT32_MIN, min(INT32_MAX, value))


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
