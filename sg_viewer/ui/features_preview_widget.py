from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.trk.surface_mesh import (
    GroundSurfaceStrip,
    build_ground_surface_mesh,
    compute_mesh_bounds,
)
from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import color_from_ground_type, getbounddlat, getxyz
from sg_viewer.geometry import preview_transform
from sg_viewer.models import preview_state
from sg_viewer.preview.transform import pan_transform_state, zoom_transform_state
from sg_viewer.services import sg_rendering

Point = tuple[float, float]
Bounds = tuple[float, float, float, float]
Transform = tuple[float, tuple[float, float]]


@dataclass(frozen=True)
class BoundaryLine:
    points: tuple[Point, ...]
    is_wall: bool
    has_fence: bool


class FeaturesPreviewWidget(QtWidgets.QWidget):
    """Preview widget for track surface features."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumSize(640, 480)

        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor("black"))
        self.setPalette(palette)

        self._surface_mesh: list[GroundSurfaceStrip] = []
        self._bounds: Bounds | None = None
        self._centerline: list[Point] = []
        self._boundaries: list[BoundaryLine] = []
        self._transform_state = preview_state.TransformState()
        self._status_message = "Load an SG file to view track surfaces."
        self._is_panning = False
        self._last_mouse_pos: QtCore.QPoint | None = None
        self.setMouseTracking(True)
        self.setCursor(QtCore.Qt.OpenHandCursor)

    def set_surface_data(
        self,
        trk: TRKFile | None,
        cline: Iterable[Point] | None,
        sampled_centerline: Iterable[Point] | None,
        sampled_bounds: Bounds | None,
    ) -> None:
        self._centerline = list(sampled_centerline or [])
        self._boundaries = []

        if trk is None:
            self._surface_mesh = []
            self._bounds = sampled_bounds
            self._status_message = "Load an SG file to view track surfaces."
        else:
            self._surface_mesh = build_ground_surface_mesh(trk, list(cline) if cline else None)
            surface_bounds = compute_mesh_bounds(self._surface_mesh)
            self._bounds = surface_bounds or sampled_bounds
            if cline:
                self._boundaries = self._build_boundaries(trk, list(cline))
            if not self._surface_mesh:
                self._status_message = "No surface data available for this track."
            else:
                self._status_message = ""

        self._update_fit_scale()
        self.update()

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:
        painter = QtGui.QPainter(self)
        rect = event.rect()
        painter.fillRect(rect, self.palette().window())

        transform, updated_state = preview_transform.current_transform(
            self._transform_state, self._bounds, (self.width(), self.height())
        )
        self._transform_state = updated_state

        if transform is None:
            sg_rendering.draw_placeholder(
                painter, rect, self._status_message or "Unable to fit view"
            )
            return

        if self._surface_mesh:
            self._draw_surface_mesh(painter, self._surface_mesh, transform, self.height())

        if self._boundaries:
            self._draw_boundaries(painter, self._boundaries, transform, self.height())

        if self._status_message:
            sg_rendering.draw_status_message(painter, rect, self._status_message)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_fit_scale()

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:  # noqa: D401 - Qt signature
        widget_size = (self.width(), self.height())
        transform, updated_state = preview_transform.current_transform(
            self._transform_state, self._bounds, widget_size
        )
        self._transform_state = updated_state
        default_center_value = preview_state.default_center(
            preview_transform.apply_default_bounds(self._bounds)
        )
        new_state = zoom_transform_state(
            self._transform_state,
            event.angleDelta().y(),
            (event.pos().x(), event.pos().y()),
            widget_size,
            self.height(),
            transform,
            lambda s: preview_state.clamp_scale(s, self._transform_state),
            lambda: default_center_value,
            lambda p: preview_state.map_to_track(transform, p, self.height()),
        )
        if new_state is None:
            return
        self._transform_state = new_state
        self.update()
        event.accept()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401 - Qt signature
        if event.button() == QtCore.Qt.LeftButton:
            widget_size = (self.width(), self.height())
            transform, updated_state = preview_transform.current_transform(
                self._transform_state, self._bounds, widget_size
            )
            self._transform_state = updated_state
            if transform is not None:
                self._is_panning = True
                self._last_mouse_pos = event.pos()
                self._transform_state = replace(self._transform_state, user_transform_active=True)
                self.setCursor(QtCore.Qt.ClosedHandCursor)
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401 - Qt signature
        if self._is_panning and self._last_mouse_pos is not None:
            widget_size = (self.width(), self.height())
            transform, updated_state = preview_transform.current_transform(
                self._transform_state, self._bounds, widget_size
            )
            self._transform_state = updated_state
            if transform:
                scale, _ = transform
                delta = event.pos() - self._last_mouse_pos
                self._last_mouse_pos = event.pos()
                center = self._transform_state.view_center or preview_state.default_center(
                    preview_transform.apply_default_bounds(self._bounds)
                )
                if center is not None:
                    self._transform_state = pan_transform_state(
                        self._transform_state,
                        (delta.x(), delta.y()),
                        scale,
                        center,
                    )
                    self.update()
                    event.accept()
                    return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401 - Qt signature
        if event.button() == QtCore.Qt.LeftButton:
            self._is_panning = False
            self._last_mouse_pos = None
            self.setCursor(QtCore.Qt.OpenHandCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _update_fit_scale(self) -> None:
        self._transform_state = preview_transform.update_fit_scale(
            self._transform_state, self._bounds, (self.width(), self.height())
        )

    @staticmethod
    def _draw_surface_mesh(
        painter: QtGui.QPainter,
        mesh: Iterable[GroundSurfaceStrip],
        transform: Transform,
        widget_height: int,
    ) -> None:
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        for strip in mesh:
            base_color = QtGui.QColor(color_from_ground_type(strip.ground_type))
            fill = QtGui.QColor(base_color)
            fill.setAlpha(210)
            outline = QtGui.QColor(base_color).darker(140)

            painter.setBrush(QtGui.QBrush(fill))
            painter.setPen(QtGui.QPen(outline, 1))

            polygon = QtGui.QPolygonF(
                [
                    sg_rendering.map_point(x, y, transform, widget_height)
                    for x, y in strip.points
                ]
            )
            painter.drawPolygon(polygon)

        painter.restore()

    @staticmethod
    def _draw_boundaries(
        painter: QtGui.QPainter,
        boundaries: Iterable[BoundaryLine],
        transform: Transform,
        widget_height: int,
    ) -> None:
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

        for boundary in boundaries:
            color = QtGui.QColor("white") if boundary.is_wall else QtGui.QColor("cyan")
            pen = QtGui.QPen(color, 2)
            if boundary.has_fence:
                pen.setStyle(QtCore.Qt.DashLine)
            pen.setCapStyle(QtCore.Qt.RoundCap)
            pen.setJoinStyle(QtCore.Qt.RoundJoin)
            painter.setPen(pen)

            path = QtGui.QPainterPath()
            points_iter = iter(boundary.points)
            try:
                first = next(points_iter)
            except StopIteration:
                continue

            path.moveTo(sg_rendering.map_point(first[0], first[1], transform, widget_height))
            for x, y in points_iter:
                path.lineTo(sg_rendering.map_point(x, y, transform, widget_height))

            painter.drawPath(path)

        painter.restore()

    @staticmethod
    def _build_boundaries(trk: TRKFile, cline: list[Point]) -> list[BoundaryLine]:
        boundaries: list[BoundaryLine] = []
        for sect_idx, sect in enumerate(trk.sects):
            if sect.num_bounds <= 0:
                continue

            if sect.type == 1:
                num_samples = 2
            else:
                num_samples = max(3, round(sect.length / 5000))

            for bound_idx in range(sect.num_bounds):
                bound_type = sect.bound_type[bound_idx]
                is_wall = bool(bound_type & 4)
                has_fence = bool(bound_type & 2)
                points: list[Point] = []
                for step in range(num_samples):
                    subsect = step / (num_samples - 1)
                    dlong = sect.start_dlong + sect.length * subsect
                    dlat = getbounddlat(trk, sect_idx, subsect, bound_idx)
                    x, y, _ = getxyz(trk, dlong, dlat, cline)
                    points.append((x, y))

                if points:
                    boundaries.append(
                        BoundaryLine(
                            points=tuple(points),
                            is_wall=is_wall,
                            has_fence=has_fence,
                        )
                    )

        return boundaries
