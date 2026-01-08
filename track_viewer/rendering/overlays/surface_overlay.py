"""Surface and boundary overlays for track preview."""
from __future__ import annotations

from typing import Sequence

from PyQt5 import QtCore, QtGui

from icr2_core.trk.surface_mesh import GroundSurfaceStrip
from icr2_core.trk.trk_utils import color_from_ground_type
from track_viewer.rendering.primitives.mapping import Point2D, Transform, map_point

DEFAULT_DECIMATION_PIXELS = 6.0


def _decimation_distance(transform: Transform) -> float:
    scale, _ = transform
    return max(1.0, DEFAULT_DECIMATION_PIXELS / max(scale, 0.01))


def _decimate_mapped_points(
    points: Sequence[QtCore.QPointF], min_distance: float
) -> list[QtCore.QPointF]:
    if len(points) < 2:
        return list(points)
    min_distance_sq = min_distance * min_distance
    decimated = [points[0]]
    last = points[0]
    for point in points[1:]:
        dx = point.x() - last.x()
        dy = point.y() - last.y()
        if dx * dx + dy * dy >= min_distance_sq:
            decimated.append(point)
            last = point
    if decimated[-1] is not points[-1]:
        decimated.append(points[-1])
    return decimated


def _segment_visible(
    start: QtCore.QPointF, end: QtCore.QPointF, viewport: QtCore.QRectF
) -> bool:
    min_x = min(start.x(), end.x())
    max_x = max(start.x(), end.x())
    min_y = min(start.y(), end.y())
    max_y = max(start.y(), end.y())
    segment_rect = QtCore.QRectF(min_x, min_y, max_x - min_x, max_y - min_y)
    return segment_rect.intersects(viewport)


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
    viewport = QtCore.QRectF(painter.viewport())
    decimation_distance = _decimation_distance(transform)
    min_distance_sq = decimation_distance * decimation_distance
    if mapped_lines is not None:
        for line in mapped_lines:
            start = line.p1()
            end = line.p2()
            dx = end.x() - start.x()
            dy = end.y() - start.y()
            if dx * dx + dy * dy < min_distance_sq:
                continue
            if not _segment_visible(start, end, viewport):
                continue
            painter.drawLine(line)
    else:
        for start, end in edges:
            mapped_start = map_point(start[0], start[1], transform, viewport_height)
            mapped_end = map_point(end[0], end[1], transform, viewport_height)
            dx = mapped_end.x() - mapped_start.x()
            dy = mapped_end.y() - mapped_start.y()
            if dx * dx + dy * dy < min_distance_sq:
                continue
            if not _segment_visible(mapped_start, mapped_end, viewport):
                continue
            painter.drawLine(QtCore.QLineF(mapped_start, mapped_end))
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
        points = _decimate_mapped_points(points, _decimation_distance(transform))
        mapped_polyline = QtGui.QPolygonF(points)
    painter.setPen(QtGui.QPen(QtGui.QColor(color), width))
    painter.drawPolyline(mapped_polyline)
