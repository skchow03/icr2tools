# sg_viewer/sg_geometry.py
from __future__ import annotations

import math
from typing import Iterable

from icr2_core.trk.sg_classes import SGFile

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

# SG stores headings as (sin, cos) integer pair.
# Use a fixed scale factor to convert to/from radians.
_ANGLE_SCALE = 32768.0

def _heading_from_sincos(sin_val, cos_val) -> float:
    """
    Convert SG (sin, cos) values to a heading angle in radians.

    We treat the stored values as scaled by _ANGLE_SCALE.
    """
    s = float(sin_val) / _ANGLE_SCALE
    c = float(cos_val) / _ANGLE_SCALE
    return math.atan2(s, c)


def _sincos_from_heading(theta: float) -> tuple[int, int]:
    """
    Convert a heading angle in radians to SG (sin, cos) integer values.
    """
    s = math.sin(theta)
    c = math.cos(theta)
    return int(round(s * _ANGLE_SCALE)), int(round(c * _ANGLE_SCALE))


def _solve_straight(start_x: float, start_y: float, theta: float, length: float) -> tuple[float, float, float]:
    """
    Given a start point (x, y), heading theta [rad] and length, return:

        (end_x, end_y, end_heading)

    For a straight, the heading is unchanged.
    """
    dx = float(length) * math.cos(theta)
    dy = float(length) * math.sin(theta)
    return start_x + dx, start_y + dy, theta


def _solve_curve(
    start_x: float,
    start_y: float,
    theta: float,
    radius: float,
    length: float,
    center_x: float,
    center_y: float,
) -> tuple[float, float, float]:
    """
    Given curve parameters, compute:

        (end_x, end_y, end_heading)

    radius: signed radius (sign = direction of turn)
    length: arc length along the centerline
    center_x/center_y: stored SG circle center (global coordinates)
    """
    # Normalize inputs
    start_x = float(start_x)
    start_y = float(start_y)
    R = float(radius)
    L = float(length)

    if R == 0.0:
        # Degenerate: treat as straight
        return _solve_straight(start_x, start_y, theta, L)

    # Turn angle magnitude
    phi = L / abs(R)
    # Direction: sign of radius
    if R < 0:
        phi = -phi

    # End heading
    theta_end = theta + phi

    # Rotate the start point around the stored circle center
    cx = float(center_x)
    cy = float(center_y)

    vx = start_x - cx
    vy = start_y - cy

    cos_p = math.cos(phi)
    sin_p = math.sin(phi)

    rx = vx * cos_p - vy * sin_p
    ry = vx * sin_p + vy * cos_p

    ex = cx + rx
    ey = cy + ry
    return ex, ey, theta_end


# ---------------------------------------------------------------------------
# Main chain recomputation
# ---------------------------------------------------------------------------

def recompute_chain(sg: SGFile, start_index: int = 0) -> None:
    """
    Recompute SG section geometry from section[start_index] onwards.

    For each section i >= start_index:

    - set start_x/start_y to the previous section's end
    - set sang1/sang2 from the incoming heading
    - compute end_x/end_y/eang1/eang2 from type/length/radius/center
    - propagate end point + heading to next section

    """
    sections = sg.sects
    n = sg.num_sects
    if n <= 0:
        return

    if start_index < 0:
        start_index = 0
    if start_index >= n:
        return

    # Determine starting pose (x,y,θ)
    if start_index == 0:
        first = sections[0]
        sx = float(first.start_x)
        sy = float(first.start_y)
        theta = _heading_from_sincos(first.sang1, first.sang2)
    else:
        prev = sections[start_index - 1]
        sx = float(prev.end_x)
        sy = float(prev.end_y)
        theta = _heading_from_sincos(prev.eang1, prev.eang2)

    # Propagate through the chain
    for i in range(start_index, n):
        sec = sections[i]

        # Set start position + heading for this section
        sec.start_x = int(round(sx))
        sec.start_y = int(round(sy))
        sec.sang1, sec.sang2 = _sincos_from_heading(theta)

        length = float(sec.length)

        if getattr(sec, "type", 1) == 1:
            # Straight
            ex, ey, theta_end = _solve_straight(sx, sy, theta, length)
        else:
            # Curve
            ex, ey, theta_end = _solve_curve(
                sx,
                sy,
                theta,
                float(sec.radius),
                length,
                float(sec.center_x),
                float(sec.center_y),
            )

        sec.end_x = int(round(ex))
        sec.end_y = int(round(ey))
        sec.eang1, sec.eang2 = _sincos_from_heading(theta_end)

        # Next section starts here
        sx, sy, theta = ex, ey, theta_end


# ---------------------------------------------------------------------------
# Property edit helpers
# ---------------------------------------------------------------------------

def update_section_length(sg: SGFile, index: int, new_length: float) -> None:
    """
    Change the length of a section and recompute geometry from that section onward.
    """
    if index < 0 or index >= sg.num_sects:
        return

    sec = sg.sects[index]
    sec.length = int(round(float(new_length)))
    recompute_chain(sg, index)


def update_section_radius(sg: SGFile, index: int, new_radius: float) -> None:
    """
    Change the radius of a curve section and recompute geometry from that section onward.

    For a straight (type == 1), this is a no-op.
    """
    if index < 0 or index >= sg.num_sects:
        return

    sec = sg.sects[index]
    if getattr(sec, "type", 1) != 2:
        # Not a curve; ignore radius edits for now.
        return

    sec.radius = int(round(float(new_radius)))
    recompute_chain(sg, index)


def update_curve_center(sg: SGFile, index: int, new_center_x: float, new_center_y: float) -> None:
    """
    Change the center of a curve section and recompute geometry from that section onward.

    For a straight (type == 1), this is a no-op.
    """
    if index < 0 or index >= sg.num_sects:
        return

    sec = sg.sects[index]
    if getattr(sec, "type", 1) != 2:
        return

    sec.center_x = int(round(float(new_center_x)))
    sec.center_y = int(round(float(new_center_y)))
    recompute_chain(sg, index)


def update_section_start_heading(sg: SGFile, index: int, new_heading_deg: float) -> None:
    """
    Set the start heading (in degrees) of a section and recompute downstream.

    The starting (x, y) of the section is preserved; we only modify the heading
    and then re-run the chain from this section onward.
    """
    if index < 0 or index >= sg.num_sects:
        return

    theta = math.radians(float(new_heading_deg))
    sec = sg.sects[index]
    sec.sang1, sec.sang2 = _sincos_from_heading(theta)
    recompute_chain(sg, index)
