"""Surface and boundary overlays for track preview."""
from __future__ import annotations

from typing import Sequence

from PyQt5 import QtCore, QtGui

from icr2_core.trk.surface_mesh import GroundSurfaceStrip
from icr2_core.trk.trk_utils import color_from_ground_type
from track_viewer.rendering.primitives.mapping import Point2D, Transform, map_point


def render_surface_to_pixmap(
    surface_mesh: Sequence[GroundSurfaceStrip],
    transform: Transform | None,
    size: QtCore.QSize,
) -> QtGui.QPixmap:
    """Render the ground surface mesh into a pixmap for reuse."""

    pixmap = QtGui.QPixmap(size)
    pixmap.fill(QtCore.Qt.transparent)
    if not transform:
        return pixmap

    painter = QtGui.QPainter(pixmap)
    painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
    for strip in surface_mesh:
        base_color = QtGui.QColor(color_from_ground_type(strip.ground_type))
        fill = QtGui.QColor(base_color)
        fill.setAlpha(200)
        outline = base_color.darker(125)
        points = [
            map_point(x, y, transform, size.height()) for x, y in strip.points
        ]
        poly = QtGui.QPolygonF(points)
        painter.setBrush(QtGui.QBrush(fill))
        painter.setPen(QtGui.QPen(outline, 1))
        painter.drawPolygon(poly)
    painter.end()
    return pixmap


def draw_track_boundaries(
    painter: QtGui.QPainter,
    edges: Sequence[tuple[Point2D, Point2D]],
    transform: Transform,
    viewport_height: int,
    *,
    color: QtGui.QColor | str = "lightgray",
    width: int = 2,
    antialias: bool = True,
    mapped_lines: Sequence[QtCore.QLineF] | None = None,
) -> None:
    if not edges and not mapped_lines:
        return

    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, antialias)
    painter.setPen(QtGui.QPen(QtGui.QColor(color), width))
    if mapped_lines is not None:
        for line in mapped_lines:
            painter.drawLine(line)
    else:
        for start, end in edges:
            painter.drawLine(
                QtCore.QLineF(
                    map_point(start[0], start[1], transform, viewport_height),
                    map_point(end[0], end[1], transform, viewport_height),
                )
            )
    painter.restore()


def draw_centerline(
    painter: QtGui.QPainter,
    sampled_centerline: Sequence[Point2D],
    transform: Transform,
    viewport_height: int,
    *,
    color: QtGui.QColor | str = "white",
    width: int = 2,
    mapped_polyline: QtGui.QPolygonF | None = None,
) -> None:
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    if mapped_polyline is None:
        points = [
            map_point(x, y, transform, viewport_height)
            for x, y in sampled_centerline
        ]
        mapped_polyline = QtGui.QPolygonF(points)
    painter.setPen(QtGui.QPen(QtGui.QColor(color), width))
    painter.drawPolyline(mapped_polyline)
