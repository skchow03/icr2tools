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

# Attribute name used on SGFile to store detached joints.
# A "joint" is the connection between section i and section i+1.
_DETACHED_ATTR = "_sg_detached_joints"


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
# Detached joint helpers (Option A)
# ---------------------------------------------------------------------------

def _get_detached_joints_mutable(sg: SGFile) -> set[int]:
    """
    Return the mutable set of detached joint indices stored on the SGFile.

    Creates the set on first use.
    """
    dj = getattr(sg, _DETACHED_ATTR, None)
    if dj is None:
        dj = set()
        setattr(sg, _DETACHED_ATTR, dj)
    return dj


def get_detached_joints(sg: SGFile) -> set[int]:
    """
    Return a copy of the indices of detached joints on *sg*.

    A value i in this set means the joint between section i and section i+1
    is currently detached.
    """
    dj = getattr(sg, _DETACHED_ATTR, None)
    return set(dj) if dj is not None else set()


def clear_detached_joints(sg: SGFile) -> None:
    """
    Clear all detached joints from *sg*.
    """
    setattr(sg, _DETACHED_ATTR, set())


def detach_endpoint(sg: SGFile, section_index: int) -> None:
    """
    Detach the joint between section_index and section_index + 1.

    This matches SGE's behavior: right-clicking the *end* of section i
    detaches it from the next section. Once detached:

    - Edits to section i (length, heading, moving its end point) will not
      automatically drag section i+1.
    - recompute_chain() will stop propagation before section i+1 when it
      reaches the detached joint.
    """
    if section_index < 0 or section_index >= sg.num_sects:
        return
    joints = _get_detached_joints_mutable(sg)
    joints.add(int(section_index))


def move_detached_endpoint(sg: SGFile, section_index: int, new_x: float, new_y: float) -> None:
    """
    Move the *end* point of a detached section to (new_x, new_y).

    This only updates the geometry of section_index itself; it does not modify
    section_index+1 or any other section. It is intended to be used while the
    joint after section_index is detached.

    Notes:

    - For straights (type == 1), we update both the length and headings so the
      section becomes a straight between its start and the new end.
    - For curves (type != 1), we update the end point and end heading only.
      Radius/center are left untouched for now; a more advanced solver can
      replace this later.
    """
    if section_index < 0 or section_index >= sg.num_sects:
        return

    sec = sg.sects[section_index]
    sx = float(sec.start_x)
    sy = float(sec.start_y)
    ex = float(new_x)
    ey = float(new_y)

    sec.end_x = int(round(ex))
    sec.end_y = int(round(ey))

    dx = ex - sx
    dy = ey - sy
    if dx == 0.0 and dy == 0.0:
        # Degenerate; leave headings and length as-is
        return

    theta_end = math.atan2(dy, dx)
    sec.eang1, sec.eang2 = _sincos_from_heading(theta_end)

    if getattr(sec, "type", 1) == 1:
        # Straight: treat it as a straight between start and new end.
        sec.length = int(round(math.hypot(dx, dy)))
        # Keep the start heading aligned with the section.
        sec.sang1, sec.sang2 = _sincos_from_heading(theta_end)


def reconnect_endpoint(sg: SGFile, section_index: int) -> None:
    """
    Reattach the joint between section_index and section_index + 1.

    After reconnecting, we recompute geometry from section_index + 1 onward
    so that the following sections follow the new end pose of section_index.
    """
    if section_index < 0 or section_index >= sg.num_sects:
        return

    joints = _get_detached_joints_mutable(sg)
    if section_index not in joints:
        return

    joints.remove(section_index)

    # If there is a next section, recompute from it using the current
    # end pose of section_index as the new starting pose.
    if section_index + 1 < sg.num_sects:
        recompute_chain(sg, section_index + 1)


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

    Detach-aware behavior:

    If the joint between section k and k+1 is detached, then when the loop
    finishes processing section k, propagation stops before k+1. This lets
    you edit section k without pulling the rest of the chain.

    This mimics SGE's "edit one section, everything downstream moves"
    behavior, with detach points acting as hard stops.
    """
    sections = sg.sects
    n = sg.num_sects
    if n <= 0:
        return

    if start_index < 0:
        start_index = 0
    if start_index >= n:
        return

    detached = getattr(sg, _DETACHED_ATTR, None)
    detached_joints = detached if isinstance(detached, set) else set()

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
        # If the joint between i-1 and i is detached, stop before touching i.
        if i > start_index and (i - 1) in detached_joints:
            break

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

    Detach-aware: if the joint after this section is detached, only this section
    is recomputed; propagation stops before the next section.
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
