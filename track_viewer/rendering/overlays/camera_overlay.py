"""Camera overlays for track preview."""
from __future__ import annotations

import math
from typing import Sequence

from PyQt5 import QtCore, QtGui

from icr2_core.cam.helpers import CameraPosition
from track_viewer.rendering.primitives.mapping import Transform, map_point


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
            _draw_camera_orientation(
                painter, cam, point, transform, color, viewport_height
            )
        _draw_camera_symbol(painter, point, color, index == selected_camera)
