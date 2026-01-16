"""Camera overlays for track preview."""
from __future__ import annotations

import math
from typing import Sequence

from PyQt5 import QtCore, QtGui

from icr2_core.cam.helpers import CameraPosition
from track_viewer.model.track_preview_model import TrackPreviewModel
from track_viewer.model.view_state import TrackPreviewViewState
from track_viewer.rendering import draw_camera_range_markers, draw_zoom_points
from track_viewer.rendering.base.centerline_renderer import CenterlineRenderer
from track_viewer.rendering.primitives.mapping import Transform, map_point
from track_viewer.services.camera_service import CameraService

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
    if camera.camera_type == 2:
        return f"A{camera.index}"
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
    allowed_indices: set[int] | None,
    transform: Transform,
    viewport_height: int,
) -> None:
    if not cameras:
        return
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    type_colors = {
        2: QtGui.QColor("#e91e63"),
        6: QtGui.QColor("#f44336"),
        7: QtGui.QColor("#2196f3"),
    }
    for index, cam in enumerate(cameras):
        if allowed_indices is not None and index not in allowed_indices:
            continue
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


class CameraOverlay:
    """Render camera overlays and helper markers."""

    def __init__(
        self, camera_service: CameraService, centerline_renderer: CenterlineRenderer
    ) -> None:
        self._camera_service = camera_service
        self._centerline_renderer = centerline_renderer

    def draw(
        self,
        painter: QtGui.QPainter,
        model: TrackPreviewModel,
        state: TrackPreviewViewState,
        transform: Transform,
        viewport_height: int,
    ) -> None:
        self.draw_ranges(painter, model, state, transform, viewport_height)
        self.draw_cameras(painter, state, transform, viewport_height)
        self.draw_zoom_points(painter, model, state, transform, viewport_height)

    def draw_ranges(
        self,
        painter: QtGui.QPainter,
        model: TrackPreviewModel,
        state: TrackPreviewViewState,
        transform: Transform,
        viewport_height: int,
    ) -> None:
        if not state.show_center_line:
            return
        draw_camera_range_markers(
            painter,
            self._camera_view_ranges(state.selected_camera, state),
            transform,
            viewport_height,
            lambda dlong: self._centerline_renderer.centerline_point_and_normal(
                model, dlong
            ),
        )

    def draw_cameras(
        self,
        painter: QtGui.QPainter,
        state: TrackPreviewViewState,
        transform: Transform,
        viewport_height: int,
    ) -> None:
        if not state.show_cameras:
            return
        allowed_indices = None
        if state.show_cameras_current_tv_only:
            allowed_indices = self._camera_service.camera_indices_for_view(
                state.current_tv_mode_index
            )
        draw_camera_positions(
            painter,
            self._camera_service.cameras,
            state.selected_camera,
            allowed_indices,
            transform,
            viewport_height,
        )

    def draw_zoom_points(
        self,
        painter: QtGui.QPainter,
        model: TrackPreviewModel,
        state: TrackPreviewViewState,
        transform: Transform,
        viewport_height: int,
    ) -> None:
        if not state.show_zoom_points:
            return
        draw_zoom_points(
            painter,
            self._zoom_points_for_camera(state),
            transform,
            viewport_height,
            lambda dlong: self._centerline_renderer.centerline_point(model, dlong),
        )

    def _camera_view_ranges(
        self, camera_index: int | None, state: TrackPreviewViewState
    ) -> list[tuple[float, float]]:
        if camera_index is None:
            return []
        if camera_index < 0 or camera_index >= len(self._camera_service.cameras):
            return []
        ranges: list[tuple[float, float]] = []
        if state.show_cameras_current_tv_only:
            view_index = state.current_tv_mode_index
            if view_index < 0 or view_index >= len(self._camera_service.camera_views):
                return []
            views = [self._camera_service.camera_views[view_index]]
        else:
            views = self._camera_service.camera_views
        for view in views:
            for entry in view.entries:
                if entry.camera_index != camera_index:
                    continue
                if entry.start_dlong is None or entry.end_dlong is None:
                    continue
                ranges.append((float(entry.start_dlong), float(entry.end_dlong)))
        return ranges

    def _zoom_points_for_camera(
        self, state: TrackPreviewViewState
    ) -> list[tuple[float, QtGui.QColor]]:
        if not state.show_zoom_points:
            return []
        if state.selected_camera is None:
            return []
        if state.selected_camera < 0 or state.selected_camera >= len(
            self._camera_service.cameras
        ):
            return []

        camera = self._camera_service.cameras[state.selected_camera]
        params = camera.type6
        if params is None:
            return []

        return [
            (params.start_point, QtGui.QColor("#ffeb3b")),
            (params.middle_point, QtGui.QColor("#00e676")),
            (params.end_point, QtGui.QColor("#42a5f5")),
        ]
