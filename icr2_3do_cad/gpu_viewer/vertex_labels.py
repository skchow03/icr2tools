"""Read-only vertex label inventory and vectorized screen projection.

Source-named vertices retain the user's authored pointers; binary 3DO
vertices without names use the export convention _<body offset>. Plane-only
source vertices are included when their compiled label offsets are known.
Dynamic/external model geometry is deliberately excluded: it has no root
model source pointer name.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import struct
import numpy as np


_BINARY_NAME = re.compile(r"^_(\d+)$")


@dataclass(frozen=True)
class LabelledVertex:
    offset: int
    label: str
    xyz: tuple[int, int, int]


@dataclass(frozen=True)
class ScreenVertex:
    offset: int
    label: str
    x: float
    y: float
    depth: float
    xyz: tuple[int, int, int]


def labelled_model_vertices(model, source_vertex_labels=None):
    """Return every known root-model vertex once, with its source pointer.

    Model.vertices covers the decoded references in the binary scene.
    The N3 compiler may also emit plane-only named vertices that a raw 3DO
    parser cannot recover because its plane contains only coefficients.
    Include these only when a validated source index names them and
    n3_label_offsets points at their compiled 16-byte vertex record.
    """
    if model is None:
        return ()
    vertices = {
        int(offset): tuple(int(value) for value in vertex.xyz)
        for offset, vertex in model.vertices.items()
    }
    mapping = getattr(model, "n3_label_offsets", {}) or {}
    supplied_names = set(source_vertex_labels or ())
    if supplied_names and mapping:
        body = getattr(model, "body", b"")
        for label in supplied_names:
            offset = mapping.get(label)
            if (not isinstance(offset, int) or offset < 0 or
                    offset + 16 > len(body) or offset in vertices):
                continue
            vertices[offset] = struct.unpack_from("<3i", body, offset + 4)
    # Prefer a genuine authored label to a binary-like alias when they map to
    # the same record. Never use a non-vertex label for an arbitrary offset.
    names = {}
    for label, offset in mapping.items():
        if (offset in vertices and
                (not supplied_names or label in supplied_names or
                 offset in model.vertices)):
            previous = names.get(offset)
            if previous is None or (previous.startswith("_") and
                                    not label.startswith("_")):
                names[offset] = label
    return tuple(LabelledVertex(offset, names.get(offset, f"_{offset}"), xyz)
                 for offset, xyz in sorted(vertices.items()))


def project_labelled_vertices(vertices, mesh, matrix, width, height):
    """Project all vertices in one NumPy batch; discard clipped/behind-eye.

    Screen positions are in Qt logical pixels, using precisely the same
    centering, scaling and MVP convention as vertex selection and BSP arrows.
    Sort far-to-near so nearby labels remain on top if positions coincide.
    """
    if (not vertices or mesh is None or width <= 0 or height <= 0):
        return ()
    center = np.asarray(mesh.center, dtype=np.float64)
    scale = float(mesh.scale)
    if not np.isfinite(scale) or scale <= 0:
        return ()
    coords = np.asarray([item.xyz for item in vertices], dtype=np.float64)
    normalized = (coords - center) / scale
    points = np.column_stack((normalized, np.ones(len(vertices))))
    clip = points @ np.asarray(matrix, dtype=np.float64).T
    w = clip[:, 3]
    valid = (np.isfinite(clip).all(axis=1) & (w > 0)
             & (np.abs(clip[:, :3]) <= w[:, None]).all(axis=1))
    indices = np.flatnonzero(valid)
    if not len(indices):
        return ()
    ndc = clip[indices, :3] / w[indices, None]
    screen_x = width * (ndc[:, 0] + 1.0) / 2
    screen_y = height * (1.0 - ndc[:, 1]) / 2
    # NDC depth +1 is farther than -1 in both perspective and orthographic.
    order = np.argsort(-ndc[:, 2], kind="stable")
    return tuple(ScreenVertex(
        vertices[int(indices[i])].offset,
        vertices[int(indices[i])].label,
        float(screen_x[i]), float(screen_y[i]), float(ndc[i, 2]),
        vertices[int(indices[i])].xyz)
        for i in order)
