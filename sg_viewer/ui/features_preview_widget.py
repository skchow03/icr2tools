from __future__ import annotations

from typing import Iterable

from PyQt5 import QtGui, QtWidgets

from icr2_core.trk.surface_mesh import (
    GroundSurfaceStrip,
    build_ground_surface_mesh,
    compute_mesh_bounds,
)
from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import color_from_ground_type
from sg_viewer.geometry import preview_transform
from sg_viewer.models import preview_state
from sg_viewer.services import sg_rendering

Point = tuple[float, float]
Bounds = tuple[float, float, float, float]
Transform = tuple[float, tuple[float, float]]


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
        self._transform_state = preview_state.TransformState()
        self._status_message = "Load an SG file to view track surfaces."

    def set_surface_data(
        self,
        trk: TRKFile | None,
        cline: Iterable[Point] | None,
        sampled_centerline: Iterable[Point] | None,
        sampled_bounds: Bounds | None,
    ) -> None:
        self._centerline = list(sampled_centerline or [])

        if trk is None:
            self._surface_mesh = []
            self._bounds = sampled_bounds
            self._status_message = "Load an SG file to view track surfaces."
        else:
            self._surface_mesh = build_ground_surface_mesh(trk, list(cline) if cline else None)
            surface_bounds = compute_mesh_bounds(self._surface_mesh)
            self._bounds = surface_bounds or sampled_bounds
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

        if self._centerline:
            sg_rendering.draw_centerlines(
                painter, [self._centerline], [], transform, self.height()
            )

        if self._status_message:
            sg_rendering.draw_status_message(painter, rect, self._status_message)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_fit_scale()

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
