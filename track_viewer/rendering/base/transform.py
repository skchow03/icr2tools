"""Qt transform helpers for track preview rendering."""
from __future__ import annotations

from PyQt5 import QtGui

from track_viewer.rendering.primitives.mapping import Transform


def surface_transform(
    transform: Transform, viewport_height: int
) -> QtGui.QTransform:
    """Convert a world-space transform into Qt screen-space coordinates."""
    scale, offsets = transform
    return QtGui.QTransform(
        scale,
        0.0,
        0.0,
        -scale,
        offsets[0],
        viewport_height - offsets[1],
    )
