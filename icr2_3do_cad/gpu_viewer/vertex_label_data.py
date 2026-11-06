"""Project root-model vertices and resolve their N3 pointer labels.

This module has no Qt or OpenGL dependency. It shares the GPU picker's
normalized root-model coordinates and camera matrix, and only returns points
inside the viewport's clip volume. DYNAMIC/EXTERN geometry belongs to other
source files and is deliberately not mixed into these labels.
"""
from __future__ import annotations

import numpy as np


def vertex_pointer_names(model):
    """Map compiled vertex offsets to source pointer names, if available.

    Binary .3DO files carry no pointer names. Their generated N3 declarations
    are named _<body offset>; use the same convention until source is ready.
    """
    if model is None:
        return {}
    result = {int(offset): f"_{offset}" for offset in model.vertices}
    for label, offset in getattr(model, "n3_label_offsets", {}).items():
        if offset in result:
            result[int(offset)] = str(label)
    return result


def project_vertex_labels(picker, names, matrix, width, height):
    """Return (body_offset, screen_x, screen_y, pointer_name) for each visible vertex.

    Vectorized clip tests match VertexPicker.nearest: finite homogeneous
    coordinates, positive W, and X/Y/Z inside the frustum. This displays
    *every* on-screen root vertex, including coincident positions and
    overlapping labels. It never silently drops labels to reduce density.
    """
    if (picker is None or not len(picker.offsets)
            or width <= 0 or height <= 0):
        return []
    positions = np.column_stack((
        picker.normalized,
        np.ones(len(picker.offsets), dtype=np.float64)))
    projected = positions @ np.asarray(matrix, dtype=np.float64).T
    w = projected[:, 3]
    visible = (np.isfinite(projected).all(axis=1) & (w > 0)
               & (np.abs(projected[:, :3]) <= w[:, None]).all(axis=1))
    if not np.any(visible):
        return []
    selected = projected[visible]
    ndc = selected[:, :2] / selected[:, 3, None]
    xs = (ndc[:, 0] + 1.0) * (width * 0.5)
    ys = (1.0 - ndc[:, 1]) * (height * 0.5)
    return [
        (int(offset), float(x), float(y),
         names.get(int(offset), f"_{int(offset)}"))
        for offset, x, y in zip(picker.offsets[visible], xs, ys)
    ]
