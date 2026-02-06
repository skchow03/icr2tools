from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Tuple

from PyQt5 import QtCore, QtGui
from sg_viewer.models.preview_fsection import PreviewFSection
from sg_viewer.models.sg_model import SectionPreview
from sg_viewer.preview.render_state import split_nodes_by_status
from sg_viewer.sg_preview.model import SgPreviewModel
from sg_viewer.sg_preview.render import render_sg_preview
from sg_viewer.sg_preview.transform import ViewTransform
from sg_viewer.sg_preview.view_state import SgPreviewViewState
from sg_viewer.services import sg_rendering

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]
BASE_WIDTH = 3.0

@dataclass
class PreviewColors:
    background: QtGui.QColor
    centerline: QtGui.QColor
    nodes_connected: QtGui.QColor
    nodes_disconnected: QtGui.QColor
    radii: QtGui.QColor


def default_preview_colors() -> PreviewColors:
    return PreviewColors(
        background=QtGui.QColor("black"),
        centerline=QtGui.QColor("lightgray"),
        nodes_connected=QtGui.QColor("limegreen"),
        nodes_disconnected=QtGui.QColor("orange"),
        radii=QtGui.QColor(140, 140, 140),
    )


@dataclass
class BasePreviewState:
    rect: QtCore.QRect
    background_color: QtGui.QColor
    background_image: QtGui.QImage | None
    background_scale_500ths_per_px: float | None
    background_origin: Point | None
    sampled_centerline: list[Point]
    selected_section_points: list[Point]
    section_endpoints: list[tuple[Point, Point]]
    selected_section_index: int | None
    show_curve_markers: bool
    show_axes: bool
    sections: Iterable
    fsections: list[PreviewFSection]
    selected_curve_index: int | None
    start_finish_mapping: tuple[Point, Point, Point] | None
    status_message: str
    split_section_mode: bool
    split_hover_point: Point | None
    xsect_dlat: float | None
    show_xsect_dlat_line: bool
    centerline_color: QtGui.QColor
    radii_color: QtGui.QColor
    fsection_surface_colors: dict[int, QtGui.QColor]


@dataclass
class NodeOverlayState:
    node_positions: dict[tuple[int, str], Point]
    node_status: dict[tuple[int, str], str]
    node_radius_px: float
    nodes_connected_color: QtGui.QColor
    nodes_disconnected_color: QtGui.QColor
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


@dataclass
class DragHeadingState:
    section: SectionPreview | None
    end_point: Point | None


@dataclass
class SgPreviewState:
    model: SgPreviewModel | None
    transform: ViewTransform | None
    view_state: SgPreviewViewState
    enabled: bool


def paint_preview(
    painter: QtGui.QPainter,
    base_state: BasePreviewState,
    creation_state: CreationOverlayState,
    node_state: NodeOverlayState | None,
    drag_heading_state: DragHeadingState | None,
    sg_preview_state: SgPreviewState | None,
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

    if transform is None:
        _draw_placeholder(painter, base_state.rect, "Unable to fit view")
        return

    if not base_state.sampled_centerline:
        _draw_placeholder(painter, base_state.rect, base_state.status_message)
    else:
        _draw_axes(
            painter, base_state.rect, base_state.show_axes, transform, widget_height
        )

        if base_state.show_xsect_dlat_line and base_state.xsect_dlat is not None:
            _draw_xsect_dlat_line(
                painter,
                base_state.sections,
                base_state.xsect_dlat,
                transform,
                widget_height,
                base_state.radii_color,
            )
        if sg_preview_state and sg_preview_state.enabled:
            render_sg_preview(
                painter,
                sg_preview_state.model,
                sg_preview_state.transform,
                sg_preview_state.view_state,
            )
        _draw_centerlines(
            painter,
            base_state.sections,
            base_state.selected_section_points,
            base_state.fsections,
            transform,
            widget_height,
            centerline_color=base_state.centerline_color,
            fsection_surface_colors=base_state.fsection_surface_colors,
        )

        if base_state.show_curve_markers:
            _draw_curve_markers(
                painter,
                [
                    sect
                    for sect in base_state.sections
                    if getattr(sect, "center", None) is not None
                ],
                base_state.selected_curve_index,
                transform,
                widget_height,
                base_state.radii_color,
            )

        _draw_start_finish_line(
            painter,
            base_state.start_finish_mapping,
            transform,
            widget_height,
        )

        if base_state.split_section_mode and base_state.split_hover_point is not None:
            _draw_split_hover_node(
                painter,
                base_state.split_hover_point,
                transform,
                widget_height,
            )

    _draw_creation_overlays(painter, base_state.rect, creation_state, transform, widget_height)
    _draw_drag_heading_guide(
        painter,
        base_state.rect,
        drag_heading_state,
        transform,
        widget_height,
    )
    _draw_nodes(painter, node_state, transform, widget_height)
    _draw_status_overlay(painter, base_state.rect, base_state.status_message)


def _draw_creation_overlays(
    painter: QtGui.QPainter,
    rect: QtCore.QRect,
    creation_state: CreationOverlayState,
    transform: Transform,
    widget_height: int,
) -> None:
    _draw_new_straight(painter, creation_state, transform, widget_height)
    _draw_new_curve(painter, rect, creation_state, transform, widget_height)


def _draw_drag_heading_guide(
    painter: QtGui.QPainter,
    rect: QtCore.QRect,
    drag_heading_state: DragHeadingState | None,
    transform: Transform,
    widget_height: int,
) -> None:
    if drag_heading_state is None:
        return

    if drag_heading_state.section is None or drag_heading_state.end_point is None:
        return

    end_point = _map_point(drag_heading_state.end_point, transform, widget_height)
    _draw_curve_heading_line(
        painter,
        rect,
        drag_heading_state.section,
        end_point,
        transform,
    )


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


def _draw_axes(
    painter: QtGui.QPainter,
    rect: QtCore.QRect,
    show_axes: bool,
    transform: Transform,
    widget_height: int,
) -> None:
    if not show_axes:
        return

    scale, offsets = transform
    if scale == 0:
        return

    offset_x, offset_y = offsets
    world_left = (0 - offset_x) / scale
    world_right = (rect.width() - offset_x) / scale
    world_bottom = (-offset_y) / scale
    world_top = (widget_height - offset_y) / scale

    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(QtGui.QColor(170, 170, 170), 1)
    pen.setStyle(QtCore.Qt.SolidLine)
    painter.setPen(pen)

    painter.drawLine(
        sg_rendering.map_point(0, world_bottom, transform, widget_height),
        sg_rendering.map_point(0, world_top, transform, widget_height),
    )
    painter.drawLine(
        sg_rendering.map_point(world_left, 0, transform, widget_height),
        sg_rendering.map_point(world_right, 0, transform, widget_height),
    )
    painter.restore()


def _draw_centerlines(
    painter: QtGui.QPainter,
    sections: Iterable[SectionPreview],
    selected_section_points: Iterable[Point],
    fsections: list[PreviewFSection],
    transform: Transform,
    widget_height: int,
    *,
    centerline_color: QtGui.QColor,
    fsection_surface_colors: dict[int, QtGui.QColor],
) -> None:
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)

    for section in sections:
        polyline = section.polyline
        if len(polyline) < 2:
            continue

        mapped = [
            sg_rendering.map_point(point[0], point[1], transform, widget_height)
            for point in polyline
        ]
        segments = sg_rendering.split_polyline_by_surface(
            mapped,
            section.start_dlat,
            section.end_dlat,
            fsections,
        )

        for surface, pts in segments:
            color = fsection_surface_colors.get(
                surface, sg_rendering.DEFAULT_SURFACE_COLOR
            )
            pen = QtGui.QPen(color)
            pen.setWidthF(BASE_WIDTH)
            pen.setCapStyle(QtCore.Qt.RoundCap)
            pen.setJoinStyle(QtCore.Qt.RoundJoin)
            painter.setPen(pen)
            painter.drawPolyline(QtGui.QPolygonF(pts))

    selected_points = [
        sg_rendering.map_point(point[0], point[1], transform, widget_height)
        for point in selected_section_points
    ]
    if len(selected_points) >= 2:
        pen = QtGui.QPen(centerline_color)
        pen.setWidthF(BASE_WIDTH + 1)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(QtGui.QPolygonF(selected_points))

    painter.restore()


def _draw_xsect_dlat_line(
    painter: QtGui.QPainter,
    sections: Iterable[SectionPreview],
    dlat: float,
    transform: Transform,
    widget_height: int,
) -> None:
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(QtGui.QColor("limegreen"))
    pen.setWidthF(BASE_WIDTH)
    pen.setStyle(QtCore.Qt.DotLine)
    pen.setCapStyle(QtCore.Qt.RoundCap)
    pen.setJoinStyle(QtCore.Qt.RoundJoin)
    painter.setPen(pen)

    for section in sections:
        polyline = section.polyline
        if len(polyline) < 2:
            continue

        offset_points: list[QtCore.QPointF] = []
        for idx, point in enumerate(polyline):
            if idx == 0:
                prev_point = point
                next_point = polyline[idx + 1]
            elif idx == len(polyline) - 1:
                prev_point = polyline[idx - 1]
                next_point = point
            else:
                prev_point = polyline[idx - 1]
                next_point = polyline[idx + 1]

            dx = next_point[0] - prev_point[0]
            dy = next_point[1] - prev_point[1]
            length = math.hypot(dx, dy)
            if length == 0:
                continue
            nx = -dy / length
            ny = dx / length
            offset_points.append(
                sg_rendering.map_point(
                    point[0] + nx * dlat,
                    point[1] + ny * dlat,
                    transform,
                    widget_height,
                )
            )

        if len(offset_points) >= 2:
            painter.drawPolyline(QtGui.QPolygonF(offset_points))

    painter.restore()


def _draw_curve_markers(
    painter: QtGui.QPainter,
    sections,
    selected_curve_index: int | None,
    transform: Transform,
    widget_height: int,
    default_color: QtGui.QColor,
) -> None:
    sg_rendering.draw_curve_markers(
        painter,
        sections,
        selected_curve_index,
        transform,
        widget_height,
        default_color=default_color,
    )


def _draw_start_finish_line(
    painter: QtGui.QPainter,
    mapping: tuple[Point, Point, Point] | None,
    transform: Transform,
    widget_height: int,
) -> None:
    sg_rendering.draw_start_finish_line(painter, mapping, transform, widget_height)


def _draw_split_hover_node(
    painter: QtGui.QPainter,
    point: Point,
    transform: Transform,
    widget_height: int,
) -> None:
    mapped_point = _map_point(point, transform, widget_height)
    radius = 5

    painter.save()
    painter.setPen(QtGui.QPen(QtCore.Qt.yellow, 1))
    painter.setBrush(QtGui.QBrush(QtCore.Qt.yellow))
    painter.drawEllipse(mapped_point, radius, radius)
    painter.restore()


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
    rect: QtCore.QRect,
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

    _draw_curve_heading_line(
        painter,
        rect,
        preview_section,
        qp_points[-1] if qp_points else None,
        transform,
    )

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
        painter.setBrush(node_state.nodes_connected_color)
        painter.setPen(QtCore.Qt.NoPen)
        painter.drawEllipse(point, node_state.node_radius_px, node_state.node_radius_px)

    for _, (x, y) in orange_nodes:
        point = _map_point((x, y), transform, widget_height)
        painter.setBrush(node_state.nodes_disconnected_color)
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


def _draw_status_overlay(
    painter: QtGui.QPainter, rect: QtCore.QRect, message: str
) -> None:
    if not message:
        return

    sg_rendering.draw_status_message(painter, rect, message)


def _draw_curve_heading_line(
    painter: QtGui.QPainter,
    rect: QtCore.QRect,
    preview_section: SectionPreview | None,
    end_point: QtCore.QPointF | None,
    transform: Transform,
) -> None:
    if preview_section is None or preview_section.end_heading is None or end_point is None:
        return

    scale, _ = transform
    heading_dx, heading_dy = preview_section.end_heading
    if scale == 0:
        return

    direction = QtCore.QPointF(heading_dx * scale, -heading_dy * scale)
    if direction.manhattanLength() == 0:
        return

    target = _project_to_rect_edge(end_point, direction, rect)
    if target is None:
        return

    pen = QtGui.QPen(QtGui.QColor("magenta"), 1)
    pen.setStyle(QtCore.Qt.DotLine)
    pen.setCapStyle(QtCore.Qt.FlatCap)
    painter.setPen(pen)
    painter.setBrush(QtCore.Qt.NoBrush)
    painter.drawLine(end_point, target)


def _project_to_rect_edge(
    start: QtCore.QPointF, direction: QtCore.QPointF, rect: QtCore.QRect
) -> QtCore.QPointF | None:
    rectf = QtCore.QRectF(rect)
    dx = direction.x()
    dy = direction.y()

    candidates: list[float] = []

    if dx > 0:
        candidates.append((rectf.right() - start.x()) / dx)
    elif dx < 0:
        candidates.append((rectf.left() - start.x()) / dx)

    if dy > 0:
        candidates.append((rectf.bottom() - start.y()) / dy)
    elif dy < 0:
        candidates.append((rectf.top() - start.y()) / dy)

    positive_steps = [t for t in candidates if t > 0]
    if not positive_steps:
        return None

    step = min(positive_steps)
    return QtCore.QPointF(start.x() + dx * step, start.y() + dy * step)
