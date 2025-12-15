from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple

from PyQt5 import QtCore, QtGui

from sg_viewer.services import rendering_service
from sg_viewer.models.sg_model import SectionPreview

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]


@dataclass
class BasePreviewState:
    rect: QtCore.QRect
    background_color: QtGui.QColor
    background_image: QtGui.QImage | None
    background_scale_500ths_per_px: float | None
    background_origin: Point | None
    sampled_centerline: list[Point]
    centerline_polylines: list[list[Point]]
    selected_section_points: list[Point]
    section_endpoints: list[tuple[Point, Point]]
    selected_section_index: int | None
    show_curve_markers: bool
    sections: Iterable
    selected_curve_index: int | None
    start_finish_mapping: tuple[Point, Point, Point] | None
    status_message: str


@dataclass
class CreationOverlayState:
    new_straight_active: bool
    new_straight_start: Point | None
    new_straight_end: Point | None
    new_curve_active: bool
    new_curve_start: Point | None
    new_curve_end: Point | None
    new_curve_preview: SectionPreview | None


def paint_preview(
    painter: QtGui.QPainter,
    base_state: BasePreviewState,
    creation_state: CreationOverlayState,
    transform: Transform | None,
    widget_height: int,
) -> None:
    """Draw the preview and any active creation overlays."""

    rendering_service.paint_preview(
        painter,
        base_state.rect,
        base_state.background_color,
        base_state.background_image,
        base_state.background_scale_500ths_per_px,
        base_state.background_origin,
        base_state.sampled_centerline,
        base_state.centerline_polylines,
        base_state.selected_section_points,
        base_state.section_endpoints,
        base_state.selected_section_index,
        base_state.show_curve_markers,
        base_state.sections,
        base_state.selected_curve_index,
        base_state.start_finish_mapping,
        transform,
        widget_height,
        base_state.status_message,
    )

    if transform is None:
        return

    _draw_creation_overlays(painter, creation_state, transform, widget_height)


def _draw_creation_overlays(
    painter: QtGui.QPainter,
    creation_state: CreationOverlayState,
    transform: Transform,
    widget_height: int,
) -> None:
    _draw_new_straight(painter, creation_state, transform, widget_height)
    _draw_new_curve(painter, creation_state, transform, widget_height)


def _map_point(
    point: Point, transform: Transform, widget_height: int
) -> QtCore.QPointF:
    scale, offsets = transform
    ox, oy = offsets
    x, y = point
    return QtCore.QPointF(ox + x * scale, widget_height - (oy + y * scale))


def _draw_new_straight(
    painter: QtGui.QPainter,
    creation_state: CreationOverlayState,
    transform: Transform,
    widget_height: int,
) -> None:
    if not creation_state.new_straight_active or creation_state.new_straight_start is None:
        return

    start = creation_state.new_straight_start
    end = creation_state.new_straight_end or start

    start_point = _map_point(start, transform, widget_height)
    end_point = _map_point(end, transform, widget_height)

    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setPen(QtGui.QPen(QtGui.QColor("cyan"), 2))
    painter.drawLine(start_point, end_point)
    painter.setBrush(QtGui.QColor("cyan"))
    painter.setPen(QtCore.Qt.NoPen)
    painter.drawEllipse(start_point, 5, 5)
    painter.drawEllipse(end_point, 5, 5)
    painter.restore()


def _draw_new_curve(
    painter: QtGui.QPainter,
    creation_state: CreationOverlayState,
    transform: Transform,
    widget_height: int,
) -> None:
    if not creation_state.new_curve_active or creation_state.new_curve_start is None:
        return

    preview_section = creation_state.new_curve_preview
    if preview_section and preview_section.polyline:
        polyline_points = preview_section.polyline
    else:
        end_point = creation_state.new_curve_end or creation_state.new_curve_start
        polyline_points = [creation_state.new_curve_start, end_point]

    qp_points = [_map_point(point, transform, widget_height) for point in polyline_points]

    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    painter.setPen(QtGui.QPen(QtGui.QColor("magenta"), 2))
    if len(qp_points) >= 2:
        painter.drawPolyline(QtGui.QPolygonF(qp_points))
    painter.setBrush(QtGui.QColor("magenta"))
    painter.setPen(QtCore.Qt.NoPen)
    for point in qp_points:
        painter.drawEllipse(point, 5, 5)
    painter.restore()
