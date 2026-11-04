"""Polygon-boundary wireframe for the GPU viewer, independent of Qt/OpenGL.

Draw actual Papyrus polygon outlines rather than triangles, so a triangulated
quad or a concave n-gon never acquires artificial diagonal lines. Geometry
comes from the already transformed/flattened scene and is normalized using
the same center/scale as the filled GPU mesh. No source/binary is mutated.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class WireframeMesh:
    vertices: np.ndarray  # float32 N x 3, consecutive pairs are GL_LINES
    polygon_ranges: dict[int, tuple[int, int]]  # flattened polygon -> line range
    polygon_count: int
    segment_count: int


def make_wireframe(geometry, mesh) -> WireframeMesh:
    """Build and cache boundary segments only for renderable polygons.

    Preserve original collinear boundary edges, excluding repeated/zero-length
    edges. Ignore LINE primitives and non-meshed polygons, matching the filled
    viewer's renderable polygon set.
    """
    center = np.asarray(mesh.center, dtype=np.float64)
    scale = float(mesh.scale)
    if not np.isfinite(center).all() or not np.isfinite(scale) or scale <= 0:
        raise ValueError("Invalid GPU geometry normalization")
    coordinates = []
    spans = {}
    for offset in mesh.polygon_ranges:
        polygon = geometry.polygons.get(offset)
        if polygon is None:
            continue
        refs = polygon.unique_refs
        if len(refs) < 3:
            continue
        try:
            points = np.asarray(
                [geometry.vertices[r].xyz for r in refs], dtype=np.float64)
        except (KeyError, TypeError, ValueError):
            continue
        if not np.isfinite(points).all():
            continue
        first = len(coordinates)
        normalized = (points - center) / scale
        for i, start in enumerate(normalized):
            end = normalized[(i + 1) % len(normalized)]
            if np.array_equal(start, end):
                continue
            coordinates.append(start)
            coordinates.append(end)
        if len(coordinates) > first:
            spans[offset] = (first, len(coordinates) - first)
    vertices = np.ascontiguousarray(
        np.asarray(coordinates, dtype=np.float32).reshape(-1, 3))
    return WireframeMesh(vertices, spans, len(spans), len(vertices) // 2)
