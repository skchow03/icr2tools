"""Turn Papyrus Model polygons into one GPU-ready triangle buffer.

This module is deliberately independent of Qt and OpenGL.  No modification to
the source Model or the 3DO binary is required to preview it on a GPU.

The preview is depth-tested flat colour; it is NOT ICR2's BSP/painter renderer.
"""
from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from time import perf_counter

import numpy as np


@dataclass
class MeshData:
    """Packed xyz/rgb float32 attributes in an N x 6 array."""
    vertices: np.ndarray
    polygon_count: int
    triangle_count: int
    skipped_polygons: int
    center: tuple[float, float, float]
    scale: float
    build_ms: float
    fan_fallbacks: int = 0

    @property
    def size_bytes(self) -> int:
        return int(self.vertices.nbytes)


def _signed_area(xy):
    x = xy[:, 0]
    y = xy[:, 1]
    return float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _cross2(a, b, c):
    return float((b[0] - a[0]) * (c[1] - a[1]) -
                 (b[1] - a[1]) * (c[0] - a[0]))


def triangulate(points):
    """Return indices forming triangles of a planar, potentially concave face.

    Project onto the dominant Newell-normal axis before ear clipping.  Keep
    supplied winding.  Repeated and collinear vertices are discarded from
    the temporary triangulation only (never from the Papyrus Model).

    Returns (triangles, used_fan_fallback).  If the polygon is degenerate,
    return an empty list.
    """
    vertices = np.asarray(points, dtype=np.float64)
    if vertices.ndim != 2 or vertices.shape[1] != 3 or len(vertices) < 3:
        return [], False
    if not np.isfinite(vertices).all():
        return [], False
    indices = []
    for i in range(len(vertices)):
        if not indices or not np.array_equal(vertices[i], vertices[indices[-1]]):
            indices.append(i)
    if len(indices) > 1 and np.array_equal(vertices[indices[0]], vertices[indices[-1]]):
        indices.pop()
    if len(indices) < 3:
        return [], False
    p = vertices[indices]
    # Newell's method is reliable for nearly planar polygons and long strips.
    normal = np.sum(np.cross(p, np.roll(p, -1, axis=0)), axis=0)
    axis = int(np.argmax(np.abs(normal)))
    if abs(normal[axis]) <= 1e-12:
        return [], False
    xy = p[:, [i for i in range(3) if i != axis]]
    area = _signed_area(xy)
    if abs(area) <= 1e-12:
        return [], False
    sign = 1.0 if area > 0 else -1.0
    remaining = list(range(len(indices)))
    triangles = []
    # The cap protects the UI from pathologically large/ill-conditioned faces.
    # For usual 3DO triangles, quads and small polygons this always ear-clips.
    attempts = 0
    max_attempts = len(indices) * len(indices)
    while len(remaining) > 3 and attempts < max_attempts:
        found = False
        for j, curr in enumerate(remaining):
            prev = remaining[j - 1]
            nxt = remaining[(j + 1) % len(remaining)]
            if sign * _cross2(xy[prev], xy[curr], xy[nxt]) <= 1e-9:
                continue
            # Exclude ears containing another projected vertex.
            a, b, c = xy[prev], xy[curr], xy[nxt]
            blocked = False
            for test in remaining:
                if test in (prev, curr, nxt):
                    continue
                q = xy[test]
                if (sign * _cross2(a, b, q) >= -1e-9 and
                    sign * _cross2(b, c, q) >= -1e-9 and
                    sign * _cross2(c, a, q) >= -1e-9):
                    blocked = True
                    break
            if blocked:
                continue
            triangles.append((indices[prev], indices[curr], indices[nxt]))
            del remaining[j]
            found = True
            break
        if not found:
            break
        attempts += 1
    if len(remaining) == 3:
        triangles.append(tuple(indices[i] for i in remaining))
        return triangles, False
    # Non-simple, nearly collinear, or extremely complex faces may not admit
    # clean ear clipping. Use a fan only as an explicitly counted fallback.
    root = indices[0]
    return [(root, indices[i], indices[i+1]) for i in range(1, len(indices)-1)], True


def read_palette(path: str | Path | None):
    """Read 256 RGB entries from the existing gamepal.pcx, if Pillow exists."""
    if path is None:
        return None
    try:
        from PIL import Image
        with Image.open(path) as im:
            values = im.getpalette()
        if not values or len(values) < 768:
            return None
        return np.asarray(values[:768], dtype=np.float32).reshape(256, 3) / 255.0
    except (OSError, ImportError, ValueError):
        return None


def make_mesh(model, palette=None) -> MeshData:
    """Triangulate local polygons once, returning a single flat-colour VBO.

    Normalize XYZ around the model bounding centre to avoid precision loss
    on tracks whose Papyrus raw coordinates are several million units.
    External DYNAMIC geometry, MIP textures and PMP sprites are deferred.
    """
    started = perf_counter()
    if model.vertices:
        coords = np.asarray([v.xyz for v in model.vertices.values()], dtype=np.float64)
        lo = coords.min(axis=0)
        hi = coords.max(axis=0)
        center = (lo + hi) / 2.0
        scale = max(float(np.max(hi - lo)) / 2.0, 1.0)
    else:
        center = np.zeros(3, dtype=np.float64)
        scale = 1.0
    colors = []
    triangles = []
    good_polygons = 0
    skipped = 0
    fallbacks = 0
    for polygon in model.polygons.values():
        refs = polygon.unique_refs
        if len(refs) < 3:
            skipped += 1
            continue
        try:
            original = np.asarray([model.vertices[r].xyz for r in refs], dtype=np.float64)
        except KeyError:
            skipped += 1
            continue
        face_tris, fallback = triangulate(original)
        if not face_tris:
            skipped += 1
            continue
        good_polygons += 1
        fallbacks += int(fallback)
        pal_index = int(polygon.color) & 255
        if palette is not None:
            rgb = np.asarray(palette[pal_index], dtype=np.float32)
        else:
            # Neutral deterministic fallback when gamepal.pcx is unavailable.
            tint = 0.35 + (pal_index % 9) / 20.0
            rgb = np.array((tint, tint, tint), dtype=np.float32)
        normalized = ((original - center) / scale).astype(np.float32)
        for a, b, c in face_tris:
            for i in (a, b, c):
                x, y, z = normalized[i]
                triangles.append((float(x), float(y), float(z),
                                  float(rgb[0]), float(rgb[1]), float(rgb[2])))
    data = np.ascontiguousarray(np.asarray(triangles, dtype=np.float32).reshape(-1, 6))
    return MeshData(
        data, good_polygons, len(triangles)//3, skipped,
        tuple(map(float, center)), scale, (perf_counter()-started)*1000,
        fallbacks,
    )
