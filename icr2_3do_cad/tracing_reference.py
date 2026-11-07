"""Model-space tracing image placement, calibration and projection.

All coordinates are raw Papyrus units until the final GPU normalization.
This module intentionally has no Qt or OpenGL dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import atan2, cos, degrees, hypot, isfinite, radians, sin
from pathlib import Path

import numpy as np


# Horizontal (screen-right), vertical (screen-up), fixed axis, fixed direction.
# Fixed coordinates sit behind the model in the matching canonical view.
PLANES = {
    "Front": (0, 2, 1, +1),
    "Side": (1, 2, 0, -1),
    "Top": (0, 1, 2, -1),
}


@dataclass(frozen=True)
class TracingReference:
    path: Path
    width: int
    height: int
    plane: str
    anchor_pixel: tuple[float, float]
    world_anchor: tuple[float, float]
    units_per_pixel: float
    rotation_degrees: float = 0.0
    opacity: float = 0.45
    visible: bool = True
    point_a: tuple[float, float] | None = None
    point_b: tuple[float, float] | None = None
    calibration_distance: float | None = None

    def __post_init__(self):
        if self.plane not in PLANES:
            raise ValueError("Reference plane must be Front, Side or Top")
        if not (self.width > 0 and self.height > 0):
            raise ValueError("Reference image dimensions must be positive")
        if not (isfinite(self.units_per_pixel) and self.units_per_pixel > 0):
            raise ValueError("Reference scale must be positive and finite")
        if not (isfinite(self.rotation_degrees) and
                0 <= self.opacity <= 1 and isfinite(self.opacity)):
            raise ValueError("Invalid reference rotation or opacity")
        if not all(isfinite(v) for v in (*self.anchor_pixel, *self.world_anchor)):
            raise ValueError("Non-finite reference origin")
        for pt in (self.point_a, self.point_b):
            if pt is not None and (len(pt) != 2 or not all(isfinite(v) for v in pt)):
                raise ValueError("Invalid calibration marker")


def calibrate_two_points(a, b, known_distance):
    """Return raw-model-units/pixel and rotation aligning A->B with +U.

    Y in image pixel coordinates points downward. In the model plane, +V
    points upward, so the positive correction angle is atan2(dy, dx).
    A and B must be distinct; the user supplies the *real* distance AB.
    """
    if not all(isfinite(float(v)) for v in (*a, *b, known_distance)):
        raise ValueError("Calibration coordinates and distance must be finite")
    pixels = hypot(b[0] - a[0], b[1] - a[1])
    if pixels <= 1e-6 or known_distance <= 0:
        raise ValueError("Pick two different image points and a positive distance")
    return float(known_distance / pixels), degrees(atan2(
        b[1] - a[1], b[0] - a[0]))


def image_point_to_world(ref, x, y):
    """Pixel point (top-left origin) -> U,V on selected 3D reference plane."""
    theta = radians(ref.rotation_degrees)
    dx = x - ref.anchor_pixel[0]
    dy = ref.anchor_pixel[1] - y
    u = ref.world_anchor[0] + ref.units_per_pixel * (
        cos(theta) * dx - sin(theta) * dy)
    v = ref.world_anchor[1] + ref.units_per_pixel * (
        sin(theta) * dx + cos(theta) * dy)
    return u, v


def plane_vertices(ref, mesh_center, mesh_scale):
    """Six GL triangle vertices, each with normalized XYZ and top-down UV.

    Texture samples use UV(0,0) at the QImage's top-left: the RGBA upload
    is deliberately not vertically flipped. The plane sits behind the
    model bounding box, but never participates in model depth picking.
    """
    if not isfinite(mesh_scale) or mesh_scale <= 0:
        raise ValueError("Mesh scale must be positive and finite")
    center = np.asarray(mesh_center, dtype=np.float64)
    if center.shape != (3,) or not np.isfinite(center).all():
        raise ValueError("Invalid mesh center")
    h_axis, v_axis, fixed_axis, sign = PLANES[ref.plane]
    fixed = center[fixed_axis] + sign * mesh_scale * 1.25
    corners = []
    for x, y, tu, tv in ((0, 0, 0, 0),
                         (ref.width, 0, 1, 0),
                         (ref.width, ref.height, 1, 1),
                         (0, ref.height, 0, 1)):
        u, v = image_point_to_world(ref, x, y)
        p = center.copy()
        p[h_axis] = u
        p[v_axis] = v
        p[fixed_axis] = fixed
        xyz = (p - center) / mesh_scale
        corners.append((*xyz, tu, tv))
    return np.ascontiguousarray(
        [corners[i] for i in (0, 1, 2, 0, 2, 3)], dtype=np.float32)


def initial_reference(path, width, height, mesh, *, plane="Side"):
    """Initial placement is centered on the loaded model's actual bounds."""
    center = np.asarray(mesh.center, dtype=np.float64)
    u_axis, v_axis, _, _ = PLANES[plane]
    return TracingReference(
        Path(path), width, height, plane,
        (width / 2.0, height / 2.0),
        (float(center[u_axis]), float(center[v_axis])),
        max(float(mesh.scale) * 2.0 / width, 1e-9))
