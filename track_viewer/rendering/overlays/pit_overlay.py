"""Pit overlays for track preview."""
from __future__ import annotations

from typing import Sequence

from PyQt5 import QtCore, QtGui

from track_viewer.rendering.primitives.mapping import Point2D, Transform, map_point


def draw_pit_dlong_lines(
    painter: QtGui.QPainter,
    segments: Sequence[tuple[Point2D, Point2D, str]],
    transform: Transform,
    viewport_height: int,
    *,
    width: int = 2,
) -> None:
    if not segments:
        return
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    for start, end, color in segments:
        pen = QtGui.QPen(QtGui.QColor(color), width)
        painter.setPen(pen)
        painter.drawLine(
            QtCore.QLineF(
                map_point(start[0], start[1], transform, viewport_height),
                map_point(end[0], end[1], transform, viewport_height),
            )
        )
    painter.restore()
