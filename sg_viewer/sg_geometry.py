# sg_viewer/sg_geometry.py
from __future__ import annotations

import math
from typing import Tuple

from icr2_core.trk.sg_classes import SGFile


def _heading_from_sincos(sin_val: float, cos_val: float) -> float:
    """
    Convert SG sine/cosine heading pair to an angle in radians.

    SG stores heading as (sang, eang) = (sinθ, cosθ) in fixed-point-ish form
    that we treat as integer approximations of -1..1.
    """
    return math.atan2(float(sin_val), float(cos_val))


def _sincos_from_heading(theta: float) -> Tuple[int, int]:
    """
    Convert angle in radians to SG-style (sine, cosine) integer pair.
    We round to nearest int, which matches the original SG integer fields.
    """
    sin_val = int(round(math.sin(theta)))
    cos_val = int(round(math.cos(theta)))
    return sin_val, cos_val


def _solve_straight(start_x: float, start_y: float, theta: float, length: float):
    """
    Solve straight section end point and heading.

    start_x, start_y: world coordinates of start point
    theta: heading angle in radians
    length: centerline length of the straight
    """
    ex = start_x + length * math.cos(theta)
    ey = start_y + length * math.sin(theta)
    return ex, ey, theta


def _solve_curve(
    start_x: float,
    start_y: float,
    theta: float,
    radius: float,
    length: float,
    center_x: float,
    center_y: float,
):
    """
    Solve curve section end point and heading using SG parameters.

    radius > 0 : left-hand turn
    radius < 0 : right-hand turn
    total turn angle φ = length / |radius|
    """
    if radius == 0:
        return _solve_straight(start_x, start_y, theta, length)

    R = float(radius)
    phi = float(length) / abs(R)          # magnitude of turn angle
    phi = phi if R > 0 else -phi          # sign determines direction

    # Update heading
    theta_end = theta + phi

    # Rotate start point around SG's stored circle center
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


def recompute_chain(sg: SGFile, start_index: int = 0) -> None:
    """
    Recompute SG section geometry from section[start_index] onwards.

    For each section i >= start_index:

    - set start_x/start_y to the previous section's end
    - set sang1/sang2 from the incoming heading
    - compute end_x/end_y/eang1/eang2 from type/length/radius/center
    - propagate end point + heading to next section

    This mimics SGE's "edit one section, everything downstream moves" behavior.
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


def update_section_length(sg: SGFile, index: int, new_length: float) -> None:
    """
    Change the length of a section and recompute geometry from that section onward.
    """
    if index < 0 or index >= sg.num_sects:
        return
    sec = sg.sects[index]
    sec.length = int(round(new_length))
    recompute_chain(sg, start_index=index)


def update_section_radius(sg: SGFile, index: int, new_radius: float) -> None:
    """
    Change the radius of a curve section and recompute geometry.

    For straights (type == 1), this has no effect.
    """
    if index < 0 or index >= sg.num_sects:
        return
    sec = sg.sects[index]
    if getattr(sec, "type", 1) != 2:
        return
    sec.radius = int(round(new_radius))
    recompute_chain(sg, start_index=index)


def update_curve_center(
    sg: SGFile, index: int, new_center_x: float, new_center_y: float
) -> None:
    """
    Change the stored curve centre for a section and recompute geometry.

    Only applies to curve sections (type == 2).
    """
    if index < 0 or index >= sg.num_sects:
        return

    sec = sg.sects[index]
    if getattr(sec, "type", 1) != 2:
        return

    sec.center_x = int(round(new_center_x))
    sec.center_y = int(round(new_center_y))
    recompute_chain(sg, start_index=index)


def update_section_start_heading(sg: SGFile, index: int, new_heading_rad: float) -> None:
    """
    Force a new starting heading for section[index] and recompute downstream.

    This is similar to SGE's "edit start angle" behavior.
    """
    if index < 0 or index >= sg.num_sects:
        return

    sec = sg.sects[index]
    sec.sang1, sec.sang2 = _sincos_from_heading(new_heading_rad)
    recompute_chain(sg, start_index=index)
