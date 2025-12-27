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

MPH_TO_FEET_PER_SECOND = 5280 / 3600
# One DLONG corresponds to 1/500 inch, or 1/6000 feet.
DLONG_TO_FEET = 1 / 6000


def compute_segment_acceleration(
    record_a: object, record_b: object, *, track_length: float | None = None
) -> float | None:
    """Estimate acceleration between two LP records in ft/s^2.

    The calculation uses the change in speed between consecutive AI line
    segments and converts the DLONG spacing into feet. Time is derived from
    the segment length and average speed to express the result in ft/s^2.
    """

    dlong_a = getattr(record_a, "dlong", None)
    dlong_b = getattr(record_b, "dlong", None)
    speed_a_mph = getattr(record_a, "speed_mph", None)
    speed_b_mph = getattr(record_b, "speed_mph", None)
    if None in {dlong_a, dlong_b, speed_a_mph, speed_b_mph}:
        return None

    delta_dlong = float(dlong_b) - float(dlong_a)
    if track_length is not None and delta_dlong < 0:
        delta_dlong += float(track_length)
    if delta_dlong <= 0:
        return None

    distance_feet = delta_dlong * DLONG_TO_FEET
    speed_a = float(speed_a_mph) * MPH_TO_FEET_PER_SECOND
    speed_b = float(speed_b_mph) * MPH_TO_FEET_PER_SECOND
    average_speed = (speed_a + speed_b) / 2
    if average_speed <= 0:
        return None

    time_seconds = distance_feet / average_speed
    if time_seconds <= 0:
        return None

    delta_speed = speed_b - speed_a
    return delta_speed / time_seconds


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


def draw_ai_lines(
    painter: QtGui.QPainter,
    visible_lp_files: Iterable[str],
    get_points: Callable[[str], Sequence[Point2D]],
    transform: Transform,
    viewport_height: int,
    lp_color: Callable[[str], str],
    *,
    gradient: str = "none",
    get_records: Callable[[str], Sequence[object]] | None = None,
    line_width: int = 2,
    acceleration_window: int = 3,
) -> None:
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    window_size = max(1, acceleration_window)
    pen_width = max(1, line_width)
    for name in sorted(set(visible_lp_files)):
        points = get_points(name)
        if not points:
            continue
        mapped = [map_point(px, py, transform, viewport_height) for px, py in points]

        if gradient != "none" and get_records is not None:
            records = get_records(name)
            speeds = [getattr(record, "speed_mph", None) for record in records]
            if len(mapped) >= 2 and len(speeds) >= 2:
                try:
                    min_speed = min(speed for speed in speeds if speed is not None)
                    max_speed = max(speed for speed in speeds if speed is not None)
                except ValueError:
                    min_speed = max_speed = None

                if gradient == "speed":

                    def _speed_to_color(speed_value: float | None) -> QtGui.QColor:
                        if (
                            speed_value is None
                            or min_speed is None
                            or max_speed is None
                            or max_speed == min_speed
                        ):
                            return QtGui.QColor(lp_color(name))
                        ratio = (speed_value - min_speed) / (max_speed - min_speed)
                        ratio = max(0.0, min(1.0, ratio))
                        red = int(round(255 * (1 - ratio)))
                        green = int(round(255 * ratio))
                        return QtGui.QColor(red, green, 0)

                    for start, end, speed in zip(
                        mapped[:-1], mapped[1:], speeds[:-1]
                    ):
                        pen = QtGui.QPen(_speed_to_color(speed), pen_width)
                        painter.setPen(pen)
                        painter.drawLine(QtCore.QLineF(start, end))
                    continue

                if gradient == "acceleration":
                    raw_accelerations: list[float | None] = []
                    for record_a, record_b in zip(records[:-1], records[1:]):
                        raw_accelerations.append(
                            compute_segment_acceleration(record_a, record_b)
                        )

                    accelerations: list[float | None] = []
                    recent: list[float] = []
                    for accel in raw_accelerations:
                        if accel is not None:
                            recent.append(accel)
                        if len(recent) > window_size:
                            recent.pop(0)
                        if recent:
                            accelerations.append(sum(recent) / len(recent))
                        else:
                            accelerations.append(None)

                    max_accel = max(
                        (a for a in accelerations if a is not None and a > 0),
                        default=None,
                    )
                    max_decel = min(
                        (a for a in accelerations if a is not None and a < 0),
                        default=None,
                    )

                    def _accel_to_color(accel_value: float | None) -> QtGui.QColor:
                        if accel_value is None:
                            return QtGui.QColor(lp_color(name))
                        if accel_value >= 0:
                            if max_accel is None or max_accel == 0:
                                return QtGui.QColor(lp_color(name))
                            ratio = max(0.0, min(1.0, accel_value / max_accel))
                            red = int(round(255 * (1 - ratio)))
                            return QtGui.QColor(red, 255, 0)
                        if max_decel is None or max_decel == 0:
                            return QtGui.QColor(lp_color(name))
                        ratio = max(0.0, min(1.0, abs(accel_value) / abs(max_decel)))
                        green = int(round(255 * (1 - ratio)))
                        return QtGui.QColor(255, green, 0)

                    for start, end, accel in zip(mapped[:-1], mapped[1:], accelerations):
                        pen = QtGui.QPen(_accel_to_color(accel), pen_width)
                        painter.setPen(pen)
                        painter.drawLine(QtCore.QLineF(start, end))
                    continue

        color = QtGui.QColor(lp_color(name))
        painter.setPen(QtGui.QPen(color, pen_width))
        painter.drawPolyline(QtGui.QPolygonF(mapped))


def draw_lp_segment(
    painter: QtGui.QPainter,
    start: Point2D,
    end: Point2D,
    transform: Transform,
    viewport_height: int,
    *,
    color: QtGui.QColor | str = "#ffeb3b",
    width: int = 4,
) -> None:
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(QtGui.QColor(color), width)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    painter.setPen(pen)
    painter.drawLine(
        QtCore.QLineF(
            map_point(start[0], start[1], transform, viewport_height),
            map_point(end[0], end[1], transform, viewport_height),
        )
    )
    painter.restore()


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

    pen_color = base_color if not selected else QtGui.QColor("#ff4081")
    pen = QtGui.QPen(pen_color)
    pen.setWidth(2 if selected else 1)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(QtGui.QBrush(base_color))

    triangle_height = 12
    half_width = 7

    triangle = QtGui.QPolygonF(
        [
            QtCore.QPointF(0, 0),  # tip at the camera position
            QtCore.QPointF(-half_width, -triangle_height),
            QtCore.QPointF(half_width, -triangle_height),
        ]
    )
    painter.drawPolygon(triangle)

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
