"""CPU-only bridge between Papyrus BSP traversal and the GPU index buffer.

Keep triangles/vertex colors uploaded once. Camera motion reevaluates the
original 3DO tree and uploads *only* a compact index list in painter order.
This is a visibility/debugging approximation of the Papyrus renderer, not a
claim of bit-exact rasterization, clipping, or game-specific LOD behavior.
"""
from __future__ import annotations

import math

import numpy as np


def camera_in_model_units(center, scale, target, azimuth, elevation, distance):
    """Convert the actual GPU eye into raw Papyrus model coordinates.

    The GPU's vertices are (raw - center) / scale. target and distance are
    already in those normalized coordinates; BSP equations are *not*.
    """
    direction = (
        math.cos(elevation) * math.sin(azimuth),
        -math.cos(elevation) * math.cos(azimuth),
        math.sin(elevation),
    )
    return tuple(
        float(center[i] + scale * (target[i] + distance * direction[i]))
        for i in range(3)
    )



# Default editable raw Papyrus XYZ eye for the Fixed Camera preview.
FIXED_CAMERA_DEFAULT_EYE = (0.0, 0.0, 5000.0)


def fixed_eye_view_target(center, scale, eye_xyz, azimuth, elevation, distance):
    """Target for a perspective eye fixed at *eye_xyz* in raw Papyrus units.

    The renderer normalizes each vertex to (raw - center) / scale; the
    camera_view target is then offset backward from the eye by its spherical
    direction times distance. This keeps the physical eye fixed while
    look direction changes. The BSP/RES eye is in the same raw coordinates.
    """
    if not math.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid mesh scale")
    if not math.isfinite(distance) or distance <= 0:
        raise ValueError("Invalid camera distance")
    eye = np.asarray(eye_xyz, dtype=np.float64)
    if eye.shape != (3,) or not np.isfinite(eye).all():
        raise ValueError("Expected three finite raw XYZ eye coordinates")
    direction = np.array((
        math.cos(elevation) * math.sin(azimuth),
        -math.cos(elevation) * math.cos(azimuth),
        math.sin(elevation),
    ), dtype=np.float64)
    return (eye - np.asarray(center, dtype=np.float64)) / scale - distance * direction


def origin_view_target(center, scale, azimuth, elevation, distance):
    """Compatibility helper for callers explicitly requesting raw XYZ zero."""
    return fixed_eye_view_target(
        center, scale, (0.0, 0.0, 0.0), azimuth, elevation, distance)

def ordered_bsp_indices(model, mesh, camera, distance=0.0):
    """Return (uint32 indices, visible polygon IDs, traversal statistics).

    Model.switched_polygons owns all FACE/FACE2/BSPF/BSPA/BSP2/BSPN
    side-selection and back-to-front ordering. Missing/degenerate polygons
    remain absent from the draw list, but appear in the visibility set so
    they can be diagnosed independently.
    """
    polygons, stats, lod = model.switched_polygons(
        distance, camera, bsp_mode="original"
    )
    spans = [mesh.polygon_ranges[offset] for offset in polygons
             if offset in mesh.polygon_ranges]
    indices = np.empty(sum(count for _, count in spans), dtype=np.uint32)
    cursor = 0
    for start, count in spans:
        indices[cursor:cursor + count] = np.arange(
            start, start + count, dtype=np.uint32
        )
        cursor += count
    info = dict(stats)
    info["mesh_polygons"] = len(spans)
    info["triangles"] = cursor // 3
    info["lod_selections"] = len(lod)
    return indices, frozenset(polygons), info
