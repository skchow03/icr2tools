"""Zoom overlays for track preview."""
from __future__ import annotations

from typing import Callable, Iterable, Sequence

from PyQt5 import QtCore, QtGui

from track_viewer.rendering.primitives.mapping import Point2D, Transform, map_point


def draw_zoom_points(
    painter: QtGui.QPainter,
    points: Iterable[tuple[float, QtGui.QColor]],
    transform: Transform,
    viewport_height: int,
    centerline_point: Callable[[float], Point2D | None],
    *,
    mapped_points: Sequence[tuple[QtCore.QPointF, QtGui.QColor]] | None = None,
) -> None:
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(QtGui.QColor("black"))
    pen.setWidth(3)
    painter.setPen(pen)

    if mapped_points is None:
        mapped_points = []
        for dlong, color in points:
            if dlong is None:
                continue
            point = centerline_point(dlong)
            if point is None:
                continue
            mapped = map_point(point[0], point[1], transform, viewport_height)
            mapped_points.append((mapped, color))

    for mapped, color in mapped_points:
        painter.setBrush(QtGui.QBrush(color))
        painter.drawEllipse(mapped, 7, 7)

    painter.restore()
