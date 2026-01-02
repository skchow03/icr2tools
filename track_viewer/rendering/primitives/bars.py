"""Perpendicular bar drawing helpers."""
from __future__ import annotations

from typing import Callable, Iterable

from PyQt5 import QtCore, QtGui

from .mapping import Point2D, Transform, map_point


def _draw_perpendicular_bar(
    painter: QtGui.QPainter,
    transform: Transform,
    viewport_height: int,
    center_and_normal: Callable[[float], tuple[Point2D, Point2D] | None],
    dlong: float,
    *,
    color: QtGui.QColor | str = "#ff4081",
    width: float = 3.0,
    half_length_px: float = 10.0,
) -> None:
    mapping = center_and_normal(dlong)
    if mapping is None:
        return
    (cx, cy), (nx, ny) = mapping
    scale, _ = transform
    if scale == 0:
        return

    half_length_track = half_length_px / scale
    start = map_point(
        cx - nx * half_length_track,
        cy - ny * half_length_track,
        transform,
        viewport_height,
    )
    end = map_point(
        cx + nx * half_length_track,
        cy + ny * half_length_track,
        transform,
        viewport_height,
    )
    pen = QtGui.QPen(QtGui.QColor(color), width)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    painter.save()
    painter.setPen(pen)
    painter.drawLine(QtCore.QLineF(start, end))
    painter.restore()


def draw_start_finish_line(
    painter: QtGui.QPainter,
    transform: Transform,
    viewport_height: int,
    center_and_normal: Callable[[float], tuple[Point2D, Point2D] | None],
) -> None:
    _draw_perpendicular_bar(
        painter,
        transform,
        viewport_height,
        center_and_normal,
        0.0,
        color="white",
        width=3.0,
        half_length_px=12.0,
    )


def draw_camera_range_markers(
    painter: QtGui.QPainter,
    ranges: Iterable[tuple[float, float]],
    transform: Transform,
    viewport_height: int,
    center_and_normal: Callable[[float], tuple[Point2D, Point2D] | None],
) -> None:
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    for start_dlong, end_dlong in ranges:
        _draw_perpendicular_bar(
            painter, transform, viewport_height, center_and_normal, float(start_dlong)
        )
        _draw_perpendicular_bar(
            painter, transform, viewport_height, center_and_normal, float(end_dlong)
        )
