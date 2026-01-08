"""Flag overlays for track preview."""
from __future__ import annotations

from typing import Sequence

from PyQt5 import QtCore, QtGui

from track_viewer.rendering.primitives.mapping import Point2D, Transform, map_point


def draw_flags(
    painter: QtGui.QPainter,
    flags: Sequence[Point2D],
    selected_flag: int | None,
    transform: Transform,
    viewport_height: int,
    flag_radius: float,
    *,
    mapped_points: Sequence[QtCore.QPointF] | None = None,
) -> None:
    if not flags and not mapped_points:
        return
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    radius = 6
    dot_radius = 4
    scale, _ = transform
    if mapped_points is None:
        mapped_points = [
            map_point(fx, fy, transform, viewport_height) for fx, fy in flags
        ]
    for index, point in enumerate(mapped_points):
        color = QtGui.QColor("#ffcc33")
        if index == selected_flag:
            color = QtGui.QColor("#ff7f0e")
        if flag_radius > 0:
            radius_px = max(flag_radius * scale, 1.0)
            pen = QtGui.QPen(color, 2)
            pen.setStyle(QtCore.Qt.DotLine)
            pen.setCapStyle(QtCore.Qt.RoundCap)
            painter.setPen(pen)
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawEllipse(point, radius_px, radius_px)
        else:
            pen = QtGui.QPen(QtGui.QColor("black"))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(QtGui.QBrush(color))
            painter.drawEllipse(point, radius, radius)
            painter.setPen(QtGui.QPen(QtGui.QColor("black")))
            flag_pole = QtCore.QLineF(
                point.x(),
                point.y() - radius - 4,
                point.x(),
                point.y() - radius,
            )
            painter.drawLine(flag_pole)
        painter.setPen(QtGui.QPen(QtGui.QColor("black")))
        painter.setBrush(QtGui.QBrush(color))
        painter.drawEllipse(point, dot_radius, dot_radius)
