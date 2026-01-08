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
    antialias: bool = True,
    mapped_lines: Sequence[tuple[QtCore.QLineF, QtGui.QColor]] | None = None,
) -> None:
    if not segments and not mapped_lines:
        return
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, antialias)
    if mapped_lines is not None:
        for line, color in mapped_lines:
            pen = QtGui.QPen(QtGui.QColor(color), width)
            painter.setPen(pen)
            painter.drawLine(line)
    else:
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


def draw_pit_stall_range(
    painter: QtGui.QPainter,
    points: Sequence[Point2D],
    transform: Transform,
    viewport_height: int,
    *,
    color: str = "#00ff00",
    width: int = 2,
    antialias: bool = True,
    mapped_polyline: QtGui.QPolygonF | None = None,
) -> None:
    if len(points) < 2 and mapped_polyline is None:
        return
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, antialias)
    pen = QtGui.QPen(QtGui.QColor(color), width)
    pen.setStyle(QtCore.Qt.DashLine)
    painter.setPen(pen)
    if mapped_polyline is None:
        mapped = [
            map_point(point[0], point[1], transform, viewport_height)
            for point in points
        ]
        mapped_polyline = QtGui.QPolygonF(mapped)
    painter.drawPolyline(mapped_polyline)
    painter.restore()


def draw_pit_stall_cars(
    painter: QtGui.QPainter,
    polygons: Sequence[Sequence[Point2D]],
    transform: Transform,
    viewport_height: int,
    *,
    color: str = "#ffffff",
    outline: str = "#ffffff",
    width: int = 1,
    alpha: int = 255,
    antialias: bool = True,
    mapped_polygons: Sequence[QtGui.QPolygonF] | None = None,
) -> None:
    if not polygons and not mapped_polygons:
        return
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, antialias)
    brush_color = QtGui.QColor(color)
    brush_color.setAlpha(alpha)
    painter.setBrush(QtGui.QBrush(brush_color))
    pen = QtGui.QPen(QtGui.QColor(outline), width)
    painter.setPen(pen)
    if mapped_polygons is not None:
        for polygon in mapped_polygons:
            if polygon.size() < 3:
                continue
            painter.drawPolygon(polygon)
    else:
        for polygon in polygons:
            if len(polygon) < 3:
                continue
            mapped = [
                map_point(point[0], point[1], transform, viewport_height)
                for point in polygon
            ]
            painter.drawPolygon(QtGui.QPolygonF(mapped))
    painter.restore()
