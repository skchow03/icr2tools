"""Camera overlays for track preview."""
from __future__ import annotations

import math
from typing import Sequence

from PyQt5 import QtCore, QtGui

from icr2_core.cam.helpers import CameraPosition
from track_viewer.rendering.primitives.mapping import Transform, map_point

CAMERA_TRIANGLE_HEIGHT = 12
CAMERA_TRIANGLE_HALF_WIDTH = 7
CAMERA_LABEL_PADDING = 4


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

    pen_color = QtGui.QColor("#ffeb3b") if selected else base_color
    pen = QtGui.QPen(pen_color)
    pen.setWidth(3 if selected else 1)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(QtGui.QBrush(base_color))

    triangle = QtGui.QPolygonF(
        [
            QtCore.QPointF(0, 0),  # tip at the camera position
            QtCore.QPointF(-CAMERA_TRIANGLE_HALF_WIDTH, -CAMERA_TRIANGLE_HEIGHT),
            QtCore.QPointF(CAMERA_TRIANGLE_HALF_WIDTH, -CAMERA_TRIANGLE_HEIGHT),
        ]
    )
    painter.drawPolygon(triangle)

    painter.restore()


def _camera_label(camera: CameraPosition) -> str | None:
    if camera.camera_type == 7:
        return f"F{camera.index}"
    if camera.camera_type == 6:
        return f"P{camera.index}"
    return None


def _draw_camera_label(
    painter: QtGui.QPainter, center: QtCore.QPointF, label: str
) -> None:
    painter.save()
    font = QtGui.QFont(painter.font())
    font.setPointSize(max(8, font.pointSize() - 1))
    painter.setFont(font)
    painter.setPen(QtGui.QPen(QtGui.QColor("#ffffff")))
    metrics = QtGui.QFontMetrics(font)
    text_width = metrics.horizontalAdvance(label)
    text_height = metrics.height()
    rect = QtCore.QRectF(
        center.x() - text_width / 2,
        center.y() - CAMERA_TRIANGLE_HEIGHT - CAMERA_LABEL_PADDING - text_height,
        text_width,
        text_height,
    )
    painter.drawText(rect, QtCore.Qt.AlignCenter, label)
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
        6: QtGui.QColor("#f44336"),
        7: QtGui.QColor("#2196f3"),
    }
    for index, cam in enumerate(cameras):
        point = map_point(cam.x, cam.y, transform, viewport_height)
        color = type_colors.get(cam.camera_type, QtGui.QColor("#ffffff"))
        if cam.camera_type == 7 and cam.type7 is not None:
            _draw_camera_orientation(
                painter, cam, point, transform, color, viewport_height
            )
        _draw_camera_symbol(painter, point, color, index == selected_camera)
        label = _camera_label(cam)
        if label:
            _draw_camera_label(painter, point, label)
