"""Surface and boundary overlays for track preview."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from PyQt5 import QtCore, QtGui

from icr2_core.trk.surface_mesh import GroundSurfaceStrip
from icr2_core.trk.trk_utils import color_from_ground_type
from track_viewer.rendering.geometry_stats import GeometryStats
from track_viewer.rendering.primitives.mapping import Point2D, Transform, map_point


@dataclass(frozen=True)
class SurfacePolygon:
    polygon: QtGui.QPolygonF
    fill: QtGui.QColor
    outline: QtGui.QColor


def build_surface_cache(
    surface_mesh: Sequence[GroundSurfaceStrip],
    stats: GeometryStats | None = None,
) -> list[SurfacePolygon]:
    """Build track-space surface geometry for reuse."""

    cache: list[SurfacePolygon] = []
    for strip in surface_mesh:
        base_color = QtGui.QColor(color_from_ground_type(strip.ground_type))
        fill = QtGui.QColor(base_color)
        fill.setAlpha(200)
        outline = base_color.darker(125)
        points = [QtCore.QPointF(x, y) for x, y in strip.points]
        poly = QtGui.QPolygonF(points)
        cache.append(SurfacePolygon(poly, fill, outline))
    if stats is not None:
        stats.surface_polygons += len(cache)
        stats.surface_triangles += len(cache) * 2
    return cache


def build_boundary_path(
    edges: Sequence[tuple[Point2D, Point2D]],
    stats: GeometryStats | None = None,
) -> QtGui.QPainterPath:
    """Build a track-space painter path for boundary edges."""

    path = QtGui.QPainterPath()
    for start, end in edges:
        path.moveTo(QtCore.QPointF(start[0], start[1]))
        path.lineTo(QtCore.QPointF(end[0], end[1]))
    if stats is not None:
        stats.boundary_segments += len(edges)
    return path


def build_centerline_path(
    sampled_centerline: Sequence[Point2D],
    stats: GeometryStats | None = None,
) -> QtGui.QPainterPath:
    """Build a track-space painter path for the sampled centerline."""

    path = QtGui.QPainterPath()
    if not sampled_centerline:
        return path
    start = sampled_centerline[0]
    path.moveTo(QtCore.QPointF(start[0], start[1]))
    for point in sampled_centerline[1:]:
        path.lineTo(QtCore.QPointF(point[0], point[1]))
    if stats is not None:
        stats.centerline_segments += max(0, len(sampled_centerline) - 1)
    return path


def draw_track_boundaries(
    painter: QtGui.QPainter,
    edges: Sequence[tuple[Point2D, Point2D]],
    transform: Transform,
    viewport_height: int,
    *,
    color: QtGui.QColor | str = "lightgray",
    width: int = 2,
) -> None:
    if not edges:
        return

    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setPen(QtGui.QPen(QtGui.QColor(color), width))
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
) -> None:
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    points = [map_point(x, y, transform, viewport_height) for x, y in sampled_centerline]
    painter.setPen(QtGui.QPen(QtGui.QColor(color), width))
    painter.drawPolyline(QtGui.QPolygonF(points))
