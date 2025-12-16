# sg_viewer/geometry/connect.py

import math
from typing import Tuple

EPS = 1e-6


# ---------------------------
# Basic vector helpers
# ---------------------------

def unit_from_angle(theta: float) -> Tuple[float, float]:
    return math.cos(theta), math.sin(theta)


def rotate(v: Tuple[float, float], angle: float) -> Tuple[float, float]:
    x, y = v
    c = math.cos(angle)
    s = math.sin(angle)
    return (c * x - s * y, s * x + c * y)


def wrap_angle(theta: float) -> float:
    """Wrap to (-pi, pi]."""
    while theta <= -math.pi:
        theta += 2 * math.pi
    while theta > math.pi:
        theta -= 2 * math.pi
    return theta


# ---------------------------
# Straight helpers
# ---------------------------

def straight_from_start_and_heading(
    start: Tuple[float, float],
    heading: float,
    length: float
) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """
    Returns (start, end) for a straight given start, heading, and length.
    """
    if length <= EPS:
        raise ValueError("Straight length must be positive")

    hx, hy = unit_from_angle(heading)
    end = (
        start[0] + hx * length,
        start[1] + hy * length
    )
    return start, end


# ---------------------------
# Curve helpers
# ---------------------------

def curve_from_start_and_headings(
    start: Tuple[float, float],
    start_heading: float,
    end_heading: float,
    arc_length: float,
    left: bool
) -> dict:
    """
    Construct a circular arc preserving:
      - start point
      - start heading
    Forcing:
      - end heading

    Free:
      - radius
      - center
      - end point

    Returns a dict with:
      center, radius, end, sweep
    """

    delta = wrap_angle(end_heading - start_heading)

    if abs(delta) < EPS:
        raise ValueError("Heading change too small for a curve")

    if arc_length <= EPS:
        raise ValueError("Arc length must be positive")

    R = arc_length / abs(delta)

    # Start normal
    if left:
        nx = -math.sin(start_heading)
        ny =  math.cos(start_heading)
    else:
        nx =  math.sin(start_heading)
        ny = -math.cos(start_heading)

    center = (
        start[0] + nx * R,
        start[1] + ny * R
    )

    # Vector from center to start
    v0 = (-nx * R, -ny * R)

    # Rotate by sweep angle
    v1 = rotate(v0, delta)

    end = (
        center[0] + v1[0],
        center[1] + v1[1]
    )

    return {
        "center": center,
        "radius": R,
        "end": end,
        "sweep": delta
    }
