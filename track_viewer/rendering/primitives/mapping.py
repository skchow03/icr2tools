"""Mapping helpers for track preview rendering."""
from __future__ import annotations

from typing import Tuple

from PyQt5 import QtCore

Transform = tuple[float, tuple[float, float]]
Point2D = tuple[float, float]


def map_point(
    x: float, y: float, transform: Transform, viewport_height: int
) -> QtCore.QPointF:
    """Convert track coordinates into Qt viewport coordinates."""

    scale, offsets = transform
    px = x * scale + offsets[0]
    py = y * scale + offsets[1]
    return QtCore.QPointF(px, viewport_height - py)


def centerline_screen_bounds(
    sampled_bounds: tuple[float, float, float, float] | None,
    transform: Transform,
    viewport_height: int,
) -> QtCore.QRectF | None:
    """Project sampled bounds into screen space."""

    if not sampled_bounds:
        return None

    min_x, max_x, min_y, max_y = sampled_bounds
    corners = [
        map_point(min_x, min_y, transform, viewport_height),
        map_point(min_x, max_y, transform, viewport_height),
        map_point(max_x, min_y, transform, viewport_height),
        map_point(max_x, max_y, transform, viewport_height),
    ]
    min_px = min(p.x() for p in corners)
    max_px = max(p.x() for p in corners)
    min_py = min(p.y() for p in corners)
    max_py = max(p.y() for p in corners)
    return QtCore.QRectF(min_px, min_py, max_px - min_px, max_py - min_py)
