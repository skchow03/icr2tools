"""Camera-consistent, GL-independent vertex move gizmo geometry.

All positions supplied/returned are *raw Papyrus* XYZ; mesh.center/scale
are only a viewport projection normalization. Dragging follows one world
axis, preserving both other coordinates. No GPU or N3 source mutation.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

AXIS_COLORS = {"X": "#f15b57", "Y": "#5bd985", "Z": "#6da7ff"}
AXIS_INDEX = {"X": 0, "Y": 1, "Z": 2}
HANDLE_LENGTH = 76.0


@dataclass(frozen=True)
class MoveHandle:
    axis: str
    center: tuple[float, float]
    tip: tuple[float, float]
    direction: tuple[float, float]
    # Clip-space 4-vectors for the raw anchor and one raw unit of axis motion.
    clip_origin: tuple[float, float, float, float]
    clip_unit: tuple[float, float, float, float]
    width: int
    height: int


def _project_raw(raw, center, scale, matrix, width, height):
    if scale <= 0 or not np.isfinite(scale):
        return None
    normalized = (np.asarray(raw, dtype=np.float64) -
                  np.asarray(center, dtype=np.float64)) / float(scale)
    clip = np.asarray(matrix, dtype=np.float64) @ np.array(
        [*normalized, 1.0], dtype=np.float64)
    if not np.isfinite(clip).all() or clip[3] <= 0:
        return None
    if (np.abs(clip[:3]) > clip[3]).any():
        return None
    ndc = clip[:2] / clip[3]
    return (clip, (float((ndc[0]+1.0)*width/2),
                   float((1.0-ndc[1])*height/2)))


def move_handles(raw, center, scale, matrix, width, height,
                 *, length=HANDLE_LENGTH):
    """Project constant-size XYZ arrows from the selected vertex.

    Handle direction is the derivative of the *actual* perspective/ortho
    projection, not an arbitrary screen-space axis. End-on axes whose
    projected derivative is effectively zero have no draggable handle.
    """
    if width <= 0 or height <= 0:
        return {}
    matrix = np.asarray(matrix, dtype=np.float64)
    projected = _project_raw(raw, center, scale, matrix, width, height)
    if projected is None:
        return {}
    clip, (cx, cy) = projected
    handles = {}
    for axis, index in AXIS_INDEX.items():
        raw_basis = np.zeros(4, dtype=np.float64)
        raw_basis[index] = 1.0 / float(scale)
        unit = matrix @ raw_basis
        derivative = ((unit[:2] * clip[3] - clip[:2] * unit[3]) /
                      (clip[3] ** 2))
        pixel_dx = derivative[0] * width / 2
        pixel_dy = -derivative[1] * height / 2
        norm = math.hypot(pixel_dx, pixel_dy)
        # An axis pointing exactly toward the eye cannot be moved using
        # mouse motion in the screen plane: do not advertise a bogus handle.
        if not math.isfinite(norm) or norm < 1e-10:
            continue
        ux, uy = pixel_dx / norm, pixel_dy / norm
        handles[axis] = MoveHandle(
            axis, (cx, cy), (cx+ux*length, cy+uy*length), (ux, uy),
            tuple(map(float, clip)), tuple(map(float, unit)),
            int(width), int(height))
    return handles


def hit_move_handle(handles, mouse_x, mouse_y, *, radius=11.0):
    """Accept the arrow *shaft*, not the center vertex's selection dot."""
    choices = []
    for axis, h in handles.items():
        ux, uy = h.direction
        along = ((mouse_x-h.center[0])*ux +
                 (mouse_y-h.center[1])*uy)
        if along < 16 or along > HANDLE_LENGTH + 8:
            continue
        perp = abs((mouse_x-h.center[0])*uy -
                   (mouse_y-h.center[1])*ux)
        if perp <= radius:
            choices.append((perp, axis))
    if not choices:
        return None
    choices.sort()
    # Two near-identical overlapping axes cannot be distinguished reliably.
    if len(choices) > 1 and abs(choices[0][0]-choices[1][0]) < 1.5:
        return None
    return choices[0][1]


def drag_raw_coordinate(handle, press, mouse, original_xyz, *, snap=1,
                        fine=False):
    """Unproject mouse displacement onto the picked raw model-space axis.

    For perspective, solve the selected axis' homogeneous projection for
    its signed world displacement. Unlike a fixed pixels-to-units factor,
    this remains correct as the point changes camera depth. Orthographic
    is the same formula with clip-unit.w = 0.
    """
    if snap <= 0 or not isinstance(snap, int):
        raise ValueError("Snap must be a positive integer raw coordinate step")
    cx, cy = handle.center
    ux, uy = handle.direction
    advance = ((mouse[0]-press[0])*ux + (mouse[1]-press[1])*uy)
    if fine:
        advance *= .1
    screen_x = cx + advance*ux
    screen_y = cy + advance*uy
    ndc = (2*screen_x/handle.width-1,
           1-2*screen_y/handle.height)
    clip = handle.clip_origin
    unit = handle.clip_unit
    # Use the coordinate with the greater screen response to minimize
    # numerical instability (and avoid division by a near-zero derivative).
    index = 0 if abs(ux) >= abs(uy) else 1
    numerator = ndc[index]*clip[3] - clip[index]
    denominator = unit[index] - ndc[index]*unit[3]
    if abs(denominator) < 1e-14:
        return tuple(int(v) for v in original_xyz)
    delta = numerator / denominator
    if not math.isfinite(delta):
        return tuple(int(v) for v in original_xyz)
    # Prevent the ray/axis perspective singularity from producing a giant
    # jump. A short drag must never place a vertex beyond Papyrus i32 limits.
    limit = max(abs(v) for v in original_xyz) * 4 + 100_000
    delta = max(-limit, min(limit, delta))
    result = list(map(int, original_xyz))
    idx = AXIS_INDEX[handle.axis]
    target = result[idx] + round(delta/snap)*snap
    target = max(-2_147_483_648, min(2_147_483_647, target))
    result[idx] = target
    return tuple(result)
