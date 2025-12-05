from __future__ import annotations

from typing import Iterable, Tuple

from PyQt5 import QtCore, QtGui

from track_viewer import rendering

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]


def draw_placeholder(painter: QtGui.QPainter, rect: QtCore.QRect, message: str) -> None:
    painter.setPen(QtGui.QPen(QtGui.QColor("lightgray")))
    painter.drawText(rect, QtCore.Qt.AlignCenter, message)


def draw_centerlines(
    painter: QtGui.QPainter,
    sampled_centerline: Iterable[Point],
    selected_section_points: Iterable[Point],
    transform: Transform,
    widget_height: int,
) -> None:
    rendering.draw_centerline(
        painter,
        sampled_centerline,
        transform,
        widget_height,
        color="white",
        width=3,
    )

    if selected_section_points:
        rendering.draw_centerline(
            painter,
            selected_section_points,
            transform,
            widget_height,
            color="red",
            width=4,
        )


def draw_curve_markers(
    painter: QtGui.QPainter,
    curve_markers,
    selected_curve_index: int | None,
    transform: Transform,
    widget_height: int,
) -> None:
    if not curve_markers:
        return

    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    default_color = QtGui.QColor(140, 140, 140)
    highlight_color = QtGui.QColor("red")

    for idx, marker in curve_markers.items():
        is_selected = idx == selected_curve_index
        color = highlight_color if is_selected else default_color
        width = 2 if is_selected else 1

        painter.setPen(QtGui.QPen(color, width))
        painter.setBrush(QtGui.QBrush(color))

        center_point = rendering.map_point(marker.center[0], marker.center[1], transform, widget_height)
        start_point = rendering.map_point(marker.start[0], marker.start[1], transform, widget_height)
        end_point = rendering.map_point(marker.end[0], marker.end[1], transform, widget_height)

        painter.drawLine(QtCore.QLineF(center_point, start_point))
        painter.drawLine(QtCore.QLineF(center_point, end_point))
        painter.drawEllipse(center_point, 4, 4)

    painter.restore()


def draw_section_endpoints(
    painter: QtGui.QPainter,
    section_endpoints: list[tuple[Point, Point]],
    selected_section_index: int | None,
    transform: Transform,
    widget_height: int,
) -> None:
    if not section_endpoints:
        return

    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

    base_color = QtGui.QColor(0, 220, 255)
    base_pen = QtGui.QPen(base_color, 1)
    base_brush = QtGui.QBrush(base_color)

    size = 6.0
    half = size / 2

    painter.setPen(base_pen)
    painter.setBrush(base_brush)

    for start, end in section_endpoints:
        for point in (start, end):
            mapped = rendering.map_point(point[0], point[1], transform, widget_height)
            painter.drawRect(QtCore.QRectF(mapped.x() - half, mapped.y() - half, size, size))

    if selected_section_index is not None and 0 <= selected_section_index < len(section_endpoints):
        _, end_point = section_endpoints[selected_section_index]
        mapped_end = rendering.map_point(end_point[0], end_point[1], transform, widget_height)

        highlight_size = 12.0
        highlight_half = highlight_size / 2

        highlight_pen = QtGui.QPen(QtGui.QColor("yellow"), 2)
        painter.setPen(highlight_pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawRect(
            QtCore.QRectF(
                mapped_end.x() - highlight_half,
                mapped_end.y() - highlight_half,
                highlight_size,
                highlight_size,
            )
        )

    painter.restore()


def draw_start_finish_line(
    painter: QtGui.QPainter,
    mapping: tuple[Point, Point, Point] | None,
    transform: Transform,
    widget_height: int,
) -> None:
    if mapping is None:
        return

    (cx, cy), normal, tangent = mapping
    scale, _ = transform
    if scale == 0:
        return

    half_length_track = 12.0 / scale
    direction_length_track = 10.0 / scale

    start = rendering.map_point(
        cx - normal[0] * half_length_track,
        cy - normal[1] * half_length_track,
        transform,
        widget_height,
    )
    end = rendering.map_point(
        cx + normal[0] * half_length_track,
        cy + normal[1] * half_length_track,
        transform,
        widget_height,
    )

    direction_start = end
    direction_end = rendering.map_point(
        cx + normal[0] * half_length_track + tangent[0] * direction_length_track,
        cy + normal[1] * half_length_track + tangent[1] * direction_length_track,
        transform,
        widget_height,
    )

    pen = QtGui.QPen(QtGui.QColor("white"), 3.0)
    pen.setCapStyle(QtCore.Qt.RoundCap)

    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setPen(pen)
    painter.drawLine(QtCore.QLineF(start, end))
    painter.drawLine(QtCore.QLineF(direction_start, direction_end))
    painter.restore()
