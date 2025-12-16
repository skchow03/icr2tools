from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple

from PyQt5 import QtCore, QtGui

from sg_viewer.models.sg_model import SectionPreview
from sg_viewer.preview.render_state import split_nodes_by_status
from sg_viewer.services import sg_rendering

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
class NodeOverlayState:
    node_positions: dict[tuple[int, str], Point]
    node_status: dict[tuple[int, str], str]
    node_radius_px: float
    hovered_node: tuple[int, str] | None = None
    connection_target: tuple[int, str] | None = None


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
    node_state: NodeOverlayState | None,
    transform: Transform | None,
    widget_height: int,
) -> None:
    """Draw the preview and any active creation overlays."""

    _draw_background(
        painter,
        base_state.rect,
        base_state.background_color,
        base_state.background_image,
        base_state.background_scale_500ths_per_px,
        base_state.background_origin,
        transform,
        widget_height,
    )

    if not base_state.sampled_centerline:
        _draw_placeholder(painter, base_state.rect, base_state.status_message)
        return

    if transform is None:
        _draw_placeholder(painter, base_state.rect, "Unable to fit view")
        return

    _draw_centerlines(
        painter,
        base_state.centerline_polylines,
        base_state.selected_section_points,
        transform,
        widget_height,
    )

    if base_state.show_curve_markers:
        _draw_curve_markers(
            painter,
            [sect for sect in base_state.sections if getattr(sect, "center", None) is not None],
            base_state.selected_curve_index,
            transform,
            widget_height,
        )

    _draw_start_finish_line(
        painter,
        base_state.start_finish_mapping,
        transform,
        widget_height,
    )

    _draw_creation_overlays(painter, creation_state, transform, widget_height)
    _draw_nodes(painter, node_state, transform, widget_height)


def _draw_creation_overlays(
    painter: QtGui.QPainter,
    creation_state: CreationOverlayState,
    transform: Transform,
    widget_height: int,
) -> None:
    _draw_new_straight(painter, creation_state, transform, widget_height)
    _draw_new_curve(painter, creation_state, transform, widget_height)


def _draw_background(
    painter: QtGui.QPainter,
    rect: QtCore.QRect,
    background_color: QtGui.QColor,
    background_image: QtGui.QImage | None,
    background_scale_500ths_per_px: float | None,
    background_origin: Point | None,
    transform: Transform | None,
    widget_height: int,
) -> None:
    painter.fillRect(rect, background_color)

    if (
        transform
        and background_image
        and background_scale_500ths_per_px
        and background_scale_500ths_per_px > 0
    ):
        sg_rendering.draw_background_image(
            painter,
            background_image,
            background_origin or (0.0, 0.0),
            background_scale_500ths_per_px,
            transform,
            widget_height,
        )


def _draw_placeholder(
    painter: QtGui.QPainter, rect: QtCore.QRect, message: str
) -> None:
    sg_rendering.draw_placeholder(painter, rect, message)


def _draw_centerlines(
    painter: QtGui.QPainter,
    centerline_polylines: Iterable[Iterable[Point]],
    selected_section_points: Iterable[Point],
    transform: Transform,
    widget_height: int,
) -> None:
    sg_rendering.draw_centerlines(
        painter, centerline_polylines, selected_section_points, transform, widget_height
    )


def _draw_curve_markers(
    painter: QtGui.QPainter,
    sections,
    selected_curve_index: int | None,
    transform: Transform,
    widget_height: int,
) -> None:
    sg_rendering.draw_curve_markers(
        painter, sections, selected_curve_index, transform, widget_height
    )


def _draw_start_finish_line(
    painter: QtGui.QPainter,
    mapping: tuple[Point, Point, Point] | None,
    transform: Transform,
    widget_height: int,
) -> None:
    sg_rendering.draw_start_finish_line(painter, mapping, transform, widget_height)


def _map_point(
    point: Point, transform: Transform, widget_height: int
) -> QtCore.QPointF:
    return sg_rendering.map_point(point[0], point[1], transform, widget_height)


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


def _draw_nodes(
    painter: QtGui.QPainter,
    node_state: NodeOverlayState | None,
    transform: Transform,
    widget_height: int,
) -> None:
    if node_state is None:
        return

    green_nodes, orange_nodes = split_nodes_by_status(
        node_state.node_positions, node_state.node_status
    )

    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

    for _, (x, y) in green_nodes:
        point = _map_point((x, y), transform, widget_height)
        painter.setBrush(QtGui.QColor("limegreen"))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawEllipse(point, node_state.node_radius_px, node_state.node_radius_px)

    for _, (x, y) in orange_nodes:
        point = _map_point((x, y), transform, widget_height)
        painter.setBrush(QtGui.QColor("orange"))
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawEllipse(point, node_state.node_radius_px, node_state.node_radius_px)

    # --------------------------------------------------
    # Hovered unconnected node (drawn on top)
    # --------------------------------------------------
    if node_state.hovered_node is not None:
        key = node_state.hovered_node
        pos = node_state.node_positions.get(key)
        if pos is not None:
            x, y = pos
            point = _map_point((x, y), transform, widget_height)

            painter.setPen(QtGui.QPen(QtGui.QColor("yellow"), 3))
            painter.setBrush(QtGui.QColor(255, 255, 0, 160))
            painter.drawEllipse(
                point,
                node_state.node_radius_px + 3,
                node_state.node_radius_px + 3,
            )

    # --------------------------------------------------
    # Connection target (distinct from hover)
    # --------------------------------------------------
    if node_state.connection_target is not None:
        key = node_state.connection_target
        pos = node_state.node_positions.get(key)
        if pos is not None:
            x, y = pos
            point = _map_point((x, y), transform, widget_height)

            painter.setPen(QtGui.QPen(QtGui.QColor("cyan"), 3))
            painter.setBrush(QtCore.Qt.NoBrush)
            painter.drawEllipse(
                point,
                node_state.node_radius_px + 12,
                node_state.node_radius_px + 12,
            )



    painter.restore()
