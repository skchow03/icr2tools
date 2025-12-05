# sg_viewer/sg_geometry.py
from __future__ import annotations
import math
from typing import List, Tuple

from icr2_core.trk.sg_classes import SGFile


# ------------------------------------------------------------
# Helpers
# ------------------------------------------------------------
def vec_from_sincos(sin_val: float, cos_val: float) -> Tuple[float, float]:
    """Return unit vector (dx,dy) from raw SG sin/cos heading."""
    return float(cos_val), float(sin_val)


def heading_from_sincos(sin_val: float, cos_val: float) -> float:
    """Return heading angle θ from SG sin/cos fields."""
    return math.atan2(float(sin_val), float(cos_val))


def sincos_from_heading(theta: float) -> Tuple[int, int]:
    """Return SG-style sine/cosine stored as int32 approximations."""
    sinv = int(round(math.sin(theta)))
    cosv = int(round(math.cos(theta)))
    return sinv, cosv


def normalize_angle(phi: float) -> float:
    """Wrap angle to (-pi,pi]."""
    while phi <= -math.pi:
        phi += 2 * math.pi
    while phi > math.pi:
        phi -= 2 * math.pi
    return phi


# ------------------------------------------------------------
# Geometry for straight and curve sections
# ------------------------------------------------------------
def solve_straight(start_x: float, start_y: float, theta: float, length: float):
    """Solve end position for a straight section."""
    ex = start_x + length * math.cos(theta)
    ey = start_y + length * math.sin(theta)
    return ex, ey, theta


def solve_curve(start_x: float, start_y: float, theta: float,
                radius: float, length: float, center_x: float, center_y: float):
    """
    Solve end position for a curve using Papyrus SG parameters.

    radius > 0 : left turn
    radius < 0 : right turn
    angle phi = length / abs(radius)
    """
    if radius == 0:
        return solve_straight(start_x, start_y, theta, length)

    R = float(radius)
    phi = float(length) / abs(R)     # total turn angle
    phi = phi if R > 0 else -phi     # sign determines direction

    # Compute end heading
    theta_end = theta + phi

    # Papyrus curves use the explicit circle center:
    cx = float(center_x)
    cy = float(center_y)

    # Use geometric rotation around center
    # vector from center → start point
    vx = start_x - cx
    vy = start_y - cy

    cos_p = math.cos(phi)
    sin_p = math.sin(phi)

    # Rotate vector around center by phi
    rx = vx * cos_p - vy * sin_p
    ry = vx * sin_p + vy * cos_p

    ex = cx + rx
    ey = cy + ry
    return ex, ey, theta_end


# ------------------------------------------------------------
# Main chain solver
# ------------------------------------------------------------
def recompute_chain(sg: SGFile, start_index: int = 0) -> None:
    """
    Recompute SG section geometry from section[start_index] forward.
    Updates start_x,start_y,sang1,sang2,end_x,end_y,eang1,eang2.

    Exactly matches SGE behavior: an edit propagates through
    all remaining sections.
    """
    sections = sg.sects
    n = sg.num_sects
    if n <= 0:
        return

    # Find starting XY + heading
    if start_index == 0:
        # Use original file's starting geometry
        sx = float(sections[0].start_x)
        sy = float(sections[0].start_y)
        theta = heading_from_sincos(sections[0].sang1, sections[0].sang2)
    else:
        prev = sections[start_index - 1]
        sx = float(prev.end_x)
        sy = float(prev.end_y)
        theta = heading_from_sincos(prev.eang1, prev.eang2)

    # Compute downstream
    for i in range(start_index, n):
        sec = sections[i]

        sec.start_x = int(round(sx))
        sec.start_y = int(round(sy))
        sec.sang1, sec.sang2 = sincos_from_heading(theta)

        if sec.type == 1:
            ex, ey, theta_end = solve_straight(
                sx, sy, theta, float(sec.length)
            )
        else:
            ex, ey, theta_end = solve_curve(
                sx, sy, theta,
                float(sec.radius),
                float(sec.length),
                float(sec.center_x),
                float(sec.center_y),
            )

        sec.end_x = int(round(ex))
        sec.end_y = int(round(ey))
        sec.eang1, sec.eang2 = sincos_from_heading(theta_end)

        # next section starts from here
        sx, sy, theta = ex, ey, theta_end


# ------------------------------------------------------------
# Public utilities
# ------------------------------------------------------------
def update_section_length(sg: SGFile, index: int, new_length: float) -> None:
    """Set new length and recompute chain."""
    sg.sects[index].length = int(round(new_length))
    recompute_chain(sg, index)


def update_section_radius(sg: SGFile, index: int, new_radius: float) -> None:
    """Set new radius and recompute chain."""
    sg.sects[index].radius = int(round(new_radius))
    recompute_chain(sg, index)


def update_section_heading(sg: SGFile, index: int, new_heading_rad: float) -> None:
    """
    Force a new starting heading for section[index].
    SGE does this when the user manually edits angles.
    """
    sec = sg.sects[index]
    sec.sang1, sec.sang2 = sincos_from_heading(new_heading_rad)
    recompute_chain(sg, index)
