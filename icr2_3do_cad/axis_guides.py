"""Screen-space CAD axis guides and camera-aligned XYZ orientation math.

All camera matrices use the viewport's existing row-major, normalized
Papyrus XYZ convention. The overlay is a drawing aid: never add axes to
the mesh, BSP, model selection, or exported .3D/.3DO.
"""
from __future__ import annotations

from math import isfinite

import numpy as np


AXIS_COLORS = {
    "X": "#ff7474",
    "Y": "#67d99a",
    "Z": "#67b6ff",
}
AXIS_UNITS = {
    "X": np.array((1., 0., 0.), dtype=np.float64),
    "Y": np.array((0., 1., 0.), dtype=np.float64),
    "Z": np.array((0., 0., 1.), dtype=np.float64),
}
GUIDE_ANCHORS = ("focus", "model", "origin")


def camera_focus(view, distance):
    """Recover the camera's current view target (including fixed/TRK modes)."""
    view = np.asarray(view, dtype=np.float64)
    if view.shape != (4, 4) or not np.isfinite(view).all():
        raise ValueError("Camera view matrix must be a finite 4x4 matrix")
    if not isfinite(float(distance)) or distance <= 0:
        raise ValueError("Camera distance must be positive and finite")
    rotation = view[:3, :3]
    eye = -rotation.T @ view[:3, 3]
    return eye - rotation[2, :] * distance


def guide_anchor(mode, view, distance, mesh_center, mesh_scale):
    """Select anchor in *normalized* world XYZ, not 2D/screen coordinates.

    focus: active camera's target, always in the viewport and follows pans.
    model: bounding-box center (local XYZ guide, not Papyrus raw origin).
    origin: true raw Papyrus (0,0,0), potentially far off screen.
    """
    if mode not in GUIDE_ANCHORS:
        raise ValueError(f"Unknown axis anchor: {mode}")
    if mode == "focus":
        return camera_focus(view, distance)
    if mode == "model":
        return np.zeros(3, dtype=np.float64)
    center = np.asarray(mesh_center, dtype=np.float64)
    if (center.shape != (3,) or not np.isfinite(center).all()
            or not isfinite(float(mesh_scale)) or mesh_scale <= 0):
        raise ValueError("Invalid model center or scale")
    return -center / float(mesh_scale)


def _clip_segment(a, b):
    """Clip homogeneous endpoints against all 6 OpenGL frustum planes.

    Clip in 4D *before perspective divide*. This avoids huge guides or
    inverted lines when an axis crosses the near plane/behind the camera.
    """
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    if not (np.isfinite(a).all() and np.isfinite(b).all()):
        return None
    lo, hi = 0., 1.
    constraints = (
        lambda p: p[3] + p[0], lambda p: p[3] - p[0],
        lambda p: p[3] + p[1], lambda p: p[3] - p[1],
        lambda p: p[3] + p[2], lambda p: p[3] - p[2],
        lambda p: p[3] - 1e-7,
    )
    for f in constraints:
        fa, fb = float(f(a)), float(f(b))
        if fa < 0. and fb < 0.:
            return None
        if fa >= 0. and fb >= 0.:
            continue
        cross = fa / (fa - fb)
        if fa < 0.:
            lo = max(lo, cross)
        else:
            hi = min(hi, cross)
        if lo > hi:
            return None
    start = a + (b-a)*lo
    end = a + (b-a)*hi
    if min(start[3], end[3]) <= 0.:
        return None
    return start, end


def _screen(clip, width, height):
    return (
        float((clip[0] / clip[3] + 1.) * width / 2.),
        float((1. - clip[1] / clip[3]) * height / 2.),
    )


def projected_axis_guides(projection, view, anchor, span, width, height):
    """Clipped, visible + and - world-axis segments in logical Qt pixels.

    Produces {axis: {"positive": (p0,p1)|None,
                     "negative": (p0,p1)|None}}, positive drawn solid,
    negative drawn dashed. No scene depth/picking or GPU state changes.
    """
    if (span <= 0 or not isfinite(float(span))
            or width <= 0 or height <= 0):
        raise ValueError("Invalid axis guide span or viewport size")
    view = np.asarray(view, dtype=np.float64)
    projection = np.asarray(projection, dtype=np.float64)
    anchor = np.asarray(anchor, dtype=np.float64)
    if (view.shape != (4,4) or projection.shape != (4,4)
            or anchor.shape != (3,)
            or not np.isfinite(view).all()
            or not np.isfinite(projection).all()
            or not np.isfinite(anchor).all()):
        raise ValueError("Invalid guide transform")
    mvp = projection @ view
    origin = np.append(anchor, 1.)
    mid = mvp @ origin
    result = {}
    for name, axis in AXIS_UNITS.items():
        halves = {}
        for direction, sign in (("positive", 1), ("negative", -1)):
            endpoint = mvp @ np.append(anchor + axis * span * sign, 1.)
            clipped = _clip_segment(mid, endpoint)
            halves[direction] = (
                (_screen(clipped[0], width, height),
                 _screen(clipped[1], width, height))
                if clipped is not None else None)
        result[name] = halves
    return result


def orientation_axes(view, *, center=(70., 70.), radius=38.):
    """Project fixed-length XYZ triad using the same world-to-view rotation.

    Screen Y is inverted; 3D depth provides back-to-front painter order.
    The gizmo is independent of mesh bounds, translation, and zoom.
    """
    view = np.asarray(view, dtype=np.float64)
    if view.shape != (4, 4) or not np.isfinite(view).all():
        raise ValueError("Invalid camera view")
    rotation = view[:3, :3]
    if (radius <= 0 or not isfinite(radius)):
        raise ValueError("Gizmo radius must be positive")
    cx, cy = (float(center[0]), float(center[1]))
    return {
        label: (cx + radius * float(rotation[0, index]),
                cy - radius * float(rotation[1, index]),
                float(rotation[2, index]))
        for index, label in enumerate("XYZ")
    }
