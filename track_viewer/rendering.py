"""Rendering helpers for the track preview widget."""
from __future__ import annotations

import math
from typing import Callable, Iterable, Sequence

from PyQt5 import QtCore, QtGui

from icr2_core.cam.helpers import CameraPosition
from icr2_core.trk.surface_mesh import GroundSurfaceStrip
from icr2_core.trk.trk_utils import color_from_ground_type

Transform = tuple[float, tuple[float, float]]
Point2D = tuple[float, float]


def map_point(
    x: float, y: float, transform: Transform, viewport_height: int
) -> QtCore.QPointF:
    """Convert track coordinates into Qt viewport coordinates."""

    scale, offsets = transform
    px = x * scale + offsets[0]
    py = y * scale + offsets[1]
    return QtCore.QPointF(px, viewport_height - py)


def centerline_screen_bounds(
    sampled_bounds: tuple[float, float, float, float] | None,
    transform: Transform,
    viewport_height: int,
) -> QtCore.QRectF | None:
    """Project sampled bounds into screen space."""

    if not sampled_bounds:
        return None

    min_x, max_x, min_y, max_y = sampled_bounds
    corners = [
        map_point(min_x, min_y, transform, viewport_height),
        map_point(min_x, max_y, transform, viewport_height),
        map_point(max_x, min_y, transform, viewport_height),
        map_point(max_x, max_y, transform, viewport_height),
    ]
    min_px = min(p.x() for p in corners)
    max_px = max(p.x() for p in corners)
    min_py = min(p.y() for p in corners)
    max_py = max(p.y() for p in corners)
    return QtCore.QRectF(min_px, min_py, max_px - min_px, max_py - min_py)


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


def draw_ai_lines(
    painter: QtGui.QPainter,
    visible_lp_files: Iterable[str],
    get_points: Callable[[str], Sequence[Point2D]],
    transform: Transform,
    viewport_height: int,
    lp_color: Callable[[str], str],
) -> None:
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    for name in sorted(set(visible_lp_files)):
        points = get_points(name)
        if not points:
            continue
        mapped = [map_point(px, py, transform, viewport_height) for px, py in points]
        color = QtGui.QColor(lp_color(name))
        painter.setPen(QtGui.QPen(color, 2))
        painter.drawPolyline(QtGui.QPolygonF(mapped))


def draw_flags(
    painter: QtGui.QPainter,
    flags: Sequence[Point2D],
    selected_flag: int | None,
    transform: Transform,
    viewport_height: int,
) -> None:
    if not flags:
        return
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    radius = 6
    for index, (fx, fy) in enumerate(flags):
        point = map_point(fx, fy, transform, viewport_height)
        color = QtGui.QColor("#ffcc33")
        if index == selected_flag:
            color = QtGui.QColor("#ff7f0e")
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


def _draw_camera_orientation(
    painter: QtGui.QPainter,
    camera: CameraPosition,
    center: QtCore.QPointF,
    transform: Transform,
    base_color: QtGui.QColor,
    viewport_height: int,
) -> None:
    scale, _ = transform
    if scale == 0 or camera.type7 is None:
        return

    angle_scale = math.pi / 2147483648
    angle = camera.type7.z_axis_rotation * angle_scale
    direction = QtCore.QPointF(math.cos(angle), math.sin(angle))

    line_length_px = 18.0
    line_length_track = line_length_px / scale

    end = map_point(
        camera.x + direction.x() * line_length_track,
        camera.y + direction.y() * line_length_track,
        transform,
        viewport_height,
    )
    pen = QtGui.QPen(QtGui.QColor(base_color))
    pen.setWidth(2)
    pen.setCapStyle(QtCore.Qt.RoundCap)

    painter.save()
    painter.setPen(pen)
    painter.drawLine(QtCore.QLineF(center, end))
    painter.restore()


def _draw_camera_symbol(
    painter: QtGui.QPainter,
    center: QtCore.QPointF,
    base_color: QtGui.QColor,
    selected: bool,
) -> None:
    painter.save()
    painter.translate(center)
    pen = QtGui.QPen(QtGui.QColor("#111111"))
    pen.setWidth(1 if not selected else 2)
    pen.setColor(base_color if not selected else QtGui.QColor("#ff4081"))
    painter.setPen(pen)
    painter.setBrush(QtGui.QBrush(base_color))

    body_width = 14
    body_height = 9
    lens_radius = 3
    viewfinder_width = 5
    viewfinder_height = 4

    body_rect = QtCore.QRectF(-body_width / 2, -body_height / 2, body_width, body_height)
    painter.drawRoundedRect(body_rect, 2, 2)

    lens_center = QtCore.QPointF(body_width / 2 - lens_radius - 1, 0)
    painter.drawEllipse(lens_center, lens_radius, lens_radius)

    viewfinder_rect = QtCore.QRectF(
        -body_width / 2,
        -body_height / 2 - viewfinder_height + 1,
        viewfinder_width,
        viewfinder_height,
    )
    painter.drawRoundedRect(viewfinder_rect, 1.5, 1.5)

    painter.restore()


def draw_camera_positions(
    painter: QtGui.QPainter,
    cameras: Sequence[CameraPosition],
    selected_camera: int | None,
    transform: Transform,
    viewport_height: int,
) -> None:
    if not cameras:
        return
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    type_colors = {
        2: QtGui.QColor("#ffeb3b"),
        6: QtGui.QColor("#ff9800"),
        7: QtGui.QColor("#4dd0e1"),
    }
    for index, cam in enumerate(cameras):
        point = map_point(cam.x, cam.y, transform, viewport_height)
        color = type_colors.get(cam.camera_type, QtGui.QColor("#ffffff"))
        if cam.camera_type == 7 and cam.type7 is not None:
            _draw_camera_orientation(painter, cam, point, transform, color, viewport_height)
        _draw_camera_symbol(painter, point, color, index == selected_camera)


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
