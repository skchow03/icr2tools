"""Zoom overlays for track preview."""
from __future__ import annotations

from typing import Callable, Iterable

from PyQt5 import QtGui

from track_viewer.rendering.primitives.mapping import Point2D, Transform, map_point


def draw_zoom_points(
    painter: QtGui.QPainter,
    points: Iterable[tuple[float, QtGui.QColor]],
    transform: Transform,
    viewport_height: int,
    centerline_point: Callable[[float], Point2D | None],
) -> None:
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(QtGui.QColor("black"))
    pen.setWidth(3)
    painter.setPen(pen)

    for dlong, color in points:
        if dlong is None:
            continue
        point = centerline_point(dlong)
        if point is None:
            continue
        mapped = map_point(point[0], point[1], transform, viewport_height)
        painter.setBrush(QtGui.QBrush(color))
        painter.drawEllipse(mapped, 7, 7)

    painter.restore()
