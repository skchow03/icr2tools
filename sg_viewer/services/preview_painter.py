from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Tuple

from sg_viewer.services.tsd_io import TrackSurfaceDetailLine

from PyQt5 import QtCore, QtGui
from sg_viewer.rendering.fsection_style_map import resolve_fsection_style
from sg_viewer.model.dlong_mapping import dlong_to_section_position
from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.model.preview_state import SgPreviewModel, SgPreviewViewState
from sg_viewer.preview.render_state import split_nodes_by_status
from sg_viewer.preview.transform import ViewTransform
from sg_viewer.services import sg_rendering

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]
BASE_WIDTH = 3.0
_SURFACE_FILL_RGBA = (60, 160, 120, 255)
_SURFACE_OUTLINE_RGBA = (80, 200, 150, 255)
_FSECT_OUTLINE_RGBA = (120, 180, 220, 255)
_SHOW_FSECT_OUTLINES = False
_MRK_TARGET_SECTION_LENGTH = 14.0 * 6000.0
_MRK_NOTCH_HALF_LENGTH_PX = 4.0
ICR2_UNITS_PER_FOOT = 500.0 * 12.0
MIN_TSD_SAMPLE_STEP = ICR2_UNITS_PER_FOOT
TARGET_TSD_PIXELS_PER_SAMPLE = 6.0

@dataclass
class PreviewColors:
    background: QtGui.QColor
    centerline_unselected: QtGui.QColor
    centerline_selected: QtGui.QColor
    centerline_long_curve: QtGui.QColor
    nodes_connected: QtGui.QColor
    nodes_disconnected: QtGui.QColor
    radii_unselected: QtGui.QColor
    radii_selected: QtGui.QColor
    xsect_dlat_line: QtGui.QColor


def default_preview_colors() -> PreviewColors:
    return PreviewColors(
        background=QtGui.QColor("black"),
        centerline_unselected=QtGui.QColor("lightgray"),
        centerline_selected=QtGui.QColor("yellow"),
        centerline_long_curve=QtGui.QColor("red"),
        nodes_connected=QtGui.QColor("limegreen"),
        nodes_disconnected=QtGui.QColor("orange"),
        radii_unselected=QtGui.QColor(140, 140, 140),
        radii_selected=QtGui.QColor("magenta"),
        xsect_dlat_line=QtGui.QColor("limegreen"),
    )


@dataclass
class BasePreviewState:
    rect: QtCore.QRect
    background_color: QtGui.QColor
    background_image: QtGui.QImage | None
    background_brightness: float
    background_scale_500ths_per_px: float | None
    background_origin: Point | None
    track_opacity: float
    sampled_centerline: list[Point]
    selected_section_points: list[Point]
    section_endpoints: list[tuple[Point, Point]]
    selected_section_index: int | None
    show_curve_markers: bool
    show_axes: bool
    sections: Iterable
    selected_curve_index: int | None
    start_finish_mapping: tuple[Point, Point, Point] | None
    status_message: str
    split_section_mode: bool
    split_hover_point: Point | None
    xsect_dlat: float | None
    show_xsect_dlat_line: bool
    centerline_unselected_color: QtGui.QColor
    centerline_selected_color: QtGui.QColor
    centerline_long_curve_color: QtGui.QColor
    radii_unselected_color: QtGui.QColor
    radii_selected_color: QtGui.QColor
    xsect_dlat_line_color: QtGui.QColor
    integrity_boundary_violation_points: tuple[Point, ...]


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
    show_mrk_notches: bool = False
    selected_mrk_wall: tuple[int, int, int] | None = None
    highlighted_mrk_walls: tuple[tuple[int, int, int, int, str], ...] = ()
    show_tsd_lines: bool = False
    tsd_lines: tuple[TrackSurfaceDetailLine, ...] = ()
    tsd_palette: tuple[QtGui.QColor, ...] = ()


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
        base_state.background_brightness,
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
        track_opacity = max(0.0, min(1.0, float(base_state.track_opacity)))
        painter.save()
        painter.setOpacity(track_opacity)
        _draw_axes(
            painter, base_state.rect, base_state.show_axes, transform, widget_height
        )

        if sg_preview_state and sg_preview_state.enabled:
            render_sg_preview(
                painter,
                sg_preview_state.model,
                sg_preview_state.transform,
                sg_preview_state.view_state,
                show_mrk_notches=sg_preview_state.show_mrk_notches,
                selected_mrk_wall=sg_preview_state.selected_mrk_wall,
                highlighted_mrk_walls=sg_preview_state.highlighted_mrk_walls,
            )
        if sg_preview_state and sg_preview_state.show_tsd_lines:
            _draw_tsd_lines(
                painter,
                sg_preview_state.tsd_lines,
                sg_preview_state.tsd_palette,
                base_state.sections,
                transform,
                widget_height,
            )
        _draw_centerlines(
            painter,
            base_state.sections,
            base_state.selected_section_points,
            transform,
            widget_height,
            centerline_unselected_color=base_state.centerline_unselected_color,
            centerline_selected_color=base_state.centerline_selected_color,
            centerline_long_curve_color=base_state.centerline_long_curve_color,
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
                base_state.radii_unselected_color,
                base_state.radii_selected_color,
            )

        _draw_start_finish_line(
            painter,
            base_state.start_finish_mapping,
            transform,
            widget_height,
        )
        if base_state.show_xsect_dlat_line and base_state.xsect_dlat is not None:
            _draw_xsect_dlat_line(
                painter,
                base_state.sections,
                base_state.xsect_dlat,
                base_state.xsect_dlat_line_color,
                transform,
                widget_height,
            )
        _draw_integrity_boundary_violation_points(
            painter,
            base_state.integrity_boundary_violation_points,
            transform,
            widget_height,
        )
        painter.restore()

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


def render_sg_preview(
    painter,
    model: SgPreviewModel,
    transform: ViewTransform,
    view_state: SgPreviewViewState,
    *,
    show_mrk_notches: bool = False,
    selected_mrk_wall: tuple[int, int, int] | None = None,
    highlighted_mrk_walls: tuple[tuple[int, int, int, int, str], ...] = (),
) -> None:
    if model is None or transform is None:
        return

    painter.save()
    painter.setRenderHint(type(painter).Antialiasing, True)

    if view_state.show_surfaces:
        _draw_surfaces(painter, model, transform)

    if view_state.show_boundaries:
        _draw_boundaries(painter, model, transform)
        if show_mrk_notches:
            _draw_mrk_notches(
                painter,
                model,
                transform,
                selected_wall=selected_mrk_wall,
                highlighted_walls=highlighted_mrk_walls,
            )

    if _SHOW_FSECT_OUTLINES:
        _draw_fsect_outlines(painter, model, transform)

    painter.restore()


def _draw_surfaces(painter, model: SgPreviewModel, transform: ViewTransform) -> None:
    for fsect in model.fsects:
        for surface in fsect.surfaces:
            attrs = surface.attrs or {}
            style = resolve_fsection_style(attrs.get("type1"), attrs.get("type2"))
            base_color = (
                style.surface_color
                if style is not None and style.surface_color is not None
                else sg_rendering.DEFAULT_SURFACE_COLOR
            )
            fill = _make_color_from_qcolor(painter, base_color, _SURFACE_FILL_RGBA[3])
            outline = _make_color_from_qcolor(
                painter, base_color.darker(130), _SURFACE_OUTLINE_RGBA[3]
            )
            points = _map_points(surface.outline, transform)
            if len(points) < 3:
                continue
            _set_brush(painter, fill)
            _set_pen(painter, outline, 1.0)
            painter.drawPolygon(points)


def _draw_boundaries(painter, model: SgPreviewModel, transform: ViewTransform) -> None:
    for fsect in model.fsects:
        for boundary in fsect.boundaries:
            attrs = boundary.attrs or {}
            style = resolve_fsection_style(attrs.get("type1"), attrs.get("type2"))
            if style is None or style.role != "boundary" or style.boundary_color is None:
                continue
            pen = sg_rendering.make_boundary_pen(
                style.boundary_color,
                is_fence=style.is_fence,
                width=style.boundary_width or 2.0,
            )
            points = _map_points(boundary.points, transform)
            if len(points) < 2:
                continue
            painter.setPen(pen)
            painter.drawPolyline(points)


def _draw_fsect_outlines(painter, model: SgPreviewModel, transform: ViewTransform) -> None:
    color = _make_color(painter, *_FSECT_OUTLINE_RGBA)
    _set_pen(painter, color, 1.0)
    for fsect in model.fsects:
        for surface in fsect.surfaces:
            points = _map_points(surface.outline, transform)
            if len(points) < 3:
                continue
            painter.drawPolygon(points)


def _draw_mrk_notches(
    painter,
    model: SgPreviewModel,
    transform: ViewTransform,
    *,
    selected_wall: tuple[int, int, int] | None,
    highlighted_walls: tuple[tuple[int, int, int, int, str], ...],
) -> None:
    notch_pen = QtGui.QPen(QtGui.QColor("white"))
    notch_pen.setWidthF(1.5)
    notch_pen.setCosmetic(True)
    notch_pen.setCapStyle(QtCore.Qt.SquareCap)
    painter.setPen(notch_pen)

    highlight_samples: list[tuple[list[Point], float, float, str]] = []

    highlighted_lookup: dict[tuple[int, int], dict[int, str]] = {}
    for boundary_index, section_index, start_wall, wall_count, color in highlighted_walls:
        if wall_count <= 0:
            continue
        key = (section_index, boundary_index)
        indices = highlighted_lookup.setdefault(key, {})
        for wall in range(max(0, start_wall), max(0, start_wall) + wall_count):
            indices[wall] = color

    # MRK highlights are driven entirely by table entries so that all MRKs
    # are rendered simultaneously with their texture-derived colors.
    _ = selected_wall

    for section_index, fsect in enumerate(model.fsects):
        for boundary_index, boundary in enumerate(fsect.boundaries):
            points = [
                (float(point[0]), float(point[1]))
                for point in boundary.points
                if point is not None
            ]
            notch_points = _division_points_for_polyline(
                points,
                target_length=_MRK_TARGET_SECTION_LENGTH,
            )
            for notch in notch_points:
                _draw_polyline_notch(
                    painter,
                    transform,
                    points,
                    notch,
                    half_length_px=_MRK_NOTCH_HALF_LENGTH_PX,
                )
            requested_indices = _resolve_mrk_highlight_indices(
                highlighted_lookup,
                section_index=section_index,
                boundary_index=boundary_index,
            )
            if not requested_indices:
                continue
            wall_ranges = _division_wall_ranges(points, notch_points)
            for wall_index, color in requested_indices.items():
                if wall_index >= len(wall_ranges):
                    continue
                wall_range = wall_ranges[wall_index]
                highlight_samples.append((points, wall_range[0], wall_range[1], color))

    if not highlight_samples:
        return

    for points, start_distance, end_distance, color in highlight_samples:
        highlight_pen = QtGui.QPen(QtGui.QColor(color))
        highlight_pen.setWidthF(4.0)
        highlight_pen.setCosmetic(True)
        highlight_pen.setCapStyle(QtCore.Qt.RoundCap)
        painter.setPen(highlight_pen)
        _draw_polyline_segment(
            painter,
            transform,
            points,
            start_distance,
            end_distance,
        )


def _resolve_mrk_highlight_indices(
    highlighted_lookup: dict[tuple[int, int], dict[int, str]],
    *,
    section_index: int,
    boundary_index: int,
) -> dict[int, str]:
    """Resolve MRK table identifiers against zero-based preview indices.

    The MRK tab inputs are zero-based. Restrict lookup to an exact
    section/boundary match so a selection does not also render on the previous
    section/boundary pair.
    """

    return dict(highlighted_lookup.get((section_index, boundary_index), {}))


def _division_points_for_polyline(
    points: list[Point], *, target_length: float
) -> list[float]:
    if len(points) < 2:
        return []
    lengths = _polyline_segment_lengths(points)
    total = sum(lengths)
    if total <= 0.0:
        return []
    segment_count = max(1, int(round(total / target_length)))
    spacing = total / float(segment_count)
    return [spacing * index for index in range(1, segment_count)]


def _polyline_segment_lengths(points: list[Point]) -> list[float]:
    lengths: list[float] = []
    for index in range(len(points) - 1):
        x1, y1 = points[index]
        x2, y2 = points[index + 1]
        lengths.append(math.hypot(x2 - x1, y2 - y1))
    return lengths


def _division_wall_ranges(
    points: list[Point],
    notch_points: list[float],
) -> list[tuple[float, float]]:
    segment_lengths = _polyline_segment_lengths(points)
    total = sum(segment_lengths)
    if total <= 0.0:
        return []
    cuts = [0.0, *notch_points, total]
    return [
        (cuts[index], cuts[index + 1])
        for index in range(len(cuts) - 1)
    ]


def _draw_polyline_segment(
    painter: QtGui.QPainter,
    transform: ViewTransform,
    points: list[Point],
    start_distance: float,
    end_distance: float,
) -> None:
    start_sample = _sample_polyline_with_tangent(points, start_distance)
    end_sample = _sample_polyline_with_tangent(points, end_distance)
    if start_sample is None or end_sample is None:
        return
    start_point, _ = start_sample
    end_point, _ = end_sample
    path = QtGui.QPainterPath()
    sx, sy = transform.world_to_screen(start_point)
    path.moveTo(sx, sy)
    for waypoint in _polyline_points_between_distances(points, start_distance, end_distance):
        wx, wy = transform.world_to_screen(waypoint)
        path.lineTo(wx, wy)
    ex, ey = transform.world_to_screen(end_point)
    path.lineTo(ex, ey)
    painter.drawPath(path)


def _polyline_points_between_distances(
    points: list[Point], start_distance: float, end_distance: float
) -> list[Point]:
    if len(points) < 2:
        return []
    if end_distance <= start_distance:
        return []
    output: list[Point] = []
    distance_cursor = 0.0
    for index in range(len(points) - 1):
        seg_len = math.hypot(points[index + 1][0] - points[index][0], points[index + 1][1] - points[index][1])
        next_distance = distance_cursor + seg_len
        if seg_len > 1e-9 and start_distance < next_distance <= end_distance:
            output.append(points[index + 1])
        distance_cursor = next_distance
    return output[:-1] if output else output


def _draw_polyline_notch(
    painter: QtGui.QPainter,
    transform: ViewTransform,
    points: list[Point],
    distance_along: float,
    *,
    half_length_px: float,
) -> None:
    sample = _sample_polyline_with_tangent(points, distance_along)
    if sample is None:
        return
    (x, y), (tx, ty) = sample
    tx_len = math.hypot(tx, ty)
    if tx_len <= 1e-9:
        return
    nx = -ty / tx_len
    ny = tx / tx_len
    sx, sy = transform.world_to_screen((x, y))
    start = QtCore.QPointF(sx - nx * half_length_px, sy + ny * half_length_px)
    end = QtCore.QPointF(sx + nx * half_length_px, sy - ny * half_length_px)
    painter.drawLine(start, end)


def _sample_polyline_with_tangent(
    points: list[Point],
    distance_along: float,
) -> tuple[Point, Point] | None:
    remaining = max(0.0, float(distance_along))
    for index in range(len(points) - 1):
        x1, y1 = points[index]
        x2, y2 = points[index + 1]
        dx = x2 - x1
        dy = y2 - y1
        seg_len = math.hypot(dx, dy)
        if seg_len <= 1e-9:
            continue
        if remaining <= seg_len:
            t = remaining / seg_len
            return ((x1 + dx * t, y1 + dy * t), (dx, dy))
        remaining -= seg_len
    if len(points) < 2:
        return None
    x1, y1 = points[-2]
    x2, y2 = points[-1]
    return ((x2, y2), (x2 - x1, y2 - y1))


def _map_points(points: Iterable[Point], transform: ViewTransform) -> QtGui.QPolygonF:
    polygon = QtGui.QPolygonF()
    for point in points:
        x, y = transform.world_to_screen(point)
        polygon.append(QtCore.QPointF(x, y))
    return polygon


def _make_color(painter, r: int, g: int, b: int, a: int = 255):
    color = painter.pen().color()
    color.setRgb(r, g, b, a)
    return color


def _make_color_from_qcolor(painter, color: QtGui.QColor, a: int = 255):
    updated = QtGui.QColor(color)
    updated.setAlpha(a)
    return updated


def _set_pen(painter, color, width: float) -> None:
    pen = painter.pen()
    pen.setColor(color)
    pen.setWidthF(width)
    painter.setPen(pen)


def _set_brush(painter, color) -> None:
    brush = painter.brush()
    brush.setColor(color)
    brush.setStyle(QtCore.Qt.SolidPattern)
    painter.setBrush(brush)


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
    background_brightness: float,
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
            brightness_pct=background_brightness,
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
    transform: Transform,
    widget_height: int,
    *,
    centerline_unselected_color: QtGui.QColor,
    centerline_selected_color: QtGui.QColor,
    centerline_long_curve_color: QtGui.QColor,
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
        line_color = (
            centerline_long_curve_color
            if _is_long_curve_section(section)
            else centerline_unselected_color
        )
        pen = QtGui.QPen(line_color)
        pen.setWidthF(BASE_WIDTH)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(QtGui.QPolygonF(mapped))

    selected_points = [
        sg_rendering.map_point(point[0], point[1], transform, widget_height)
        for point in selected_section_points
    ]
    if len(selected_points) >= 2:
        pen = QtGui.QPen(centerline_selected_color)
        pen.setWidthF(BASE_WIDTH + 1)
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(QtGui.QPolygonF(selected_points))

    painter.restore()


def _is_long_curve_section(section: SectionPreview) -> bool:
    if section.center is None or section.radius is None or section.length <= 0:
        return False
    arc_degrees = math.degrees(section.length / abs(section.radius))
    return arc_degrees > 120.0




def _draw_tsd_lines(
    painter: QtGui.QPainter,
    tsd_lines: tuple[TrackSurfaceDetailLine, ...],
    tsd_palette: tuple[QtGui.QColor, ...],
    sections: Iterable[SectionPreview],
    transform: Transform,
    widget_height: int,
) -> None:
    if not tsd_lines:
        return

    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    section_list = [section for section in sections if section.length > 0]

    for line in tsd_lines:
        world_points = _sample_tsd_detail_line(line, section_list, transform[0])
        if len(world_points) < 2:
            continue
        mapped_points = [
            sg_rendering.map_point(point[0], point[1], transform, widget_height)
            for point in world_points
        ]

        color_index = max(0, min(255, int(line.color_index)))
        if tsd_palette:
            color = QtGui.QColor(tsd_palette[color_index % len(tsd_palette)])
        else:
            color = QtGui.QColor(color_index, color_index, color_index)
        width_px = _tsd_width_to_pixels(line.width_500ths, transform[0])

        pen = QtGui.QPen(color)
        pen.setWidthF(width_px)
        if line.command == "Detail_Dash":
            pen.setStyle(QtCore.Qt.DashLine)
            pen.setDashPattern([8.0, 8.0])
        pen.setCapStyle(QtCore.Qt.RoundCap)
        pen.setJoinStyle(QtCore.Qt.RoundJoin)
        painter.setPen(pen)
        painter.drawPolyline(QtGui.QPolygonF(mapped_points))

    painter.restore()


def _tsd_width_to_pixels(width_500ths: int, pixels_per_world_unit: float) -> float:
    """Convert a TSD width from world 500ths units to on-screen pixels."""
    width_in_world_units = float(width_500ths)
    return max(1.0, width_in_world_units * float(pixels_per_world_unit))


def _sample_tsd_detail_line(
    line: TrackSurfaceDetailLine,
    sections: list[SectionPreview],
    pixels_per_world_unit: float,
) -> list[Point]:
    if not sections:
        return []

    track_length = max(
        (float(section.start_dlong) + float(section.length) for section in sections),
        default=0.0,
    )
    if track_length <= 0:
        return []

    start_dlong = float(line.start_dlong)
    end_dlong = float(line.end_dlong)
    span = end_dlong - start_dlong
    if span < 0:
        span += track_length
    if math.isclose(span, 0.0):
        span = track_length

    adaptive_step = TARGET_TSD_PIXELS_PER_SAMPLE / max(pixels_per_world_unit, 1e-9)
    increment = max(MIN_TSD_SAMPLE_STEP, adaptive_step)
    step_count = max(1, int(math.ceil(span / increment)))

    points: list[Point] = []
    for step in range(step_count + 1):
        along = min(span, step * increment)
        fraction = along / span if span > 0 else 0.0
        dlong = (start_dlong + along) % track_length
        dlat_500ths = float(line.start_dlat) + (
            float(line.end_dlat) - float(line.start_dlat)
        ) * fraction
        dlat = dlat_500ths
        point = _point_on_track_at_dlong(sections, dlong, dlat, track_length)
        if point is not None:
            points.append(point)

    return points


def _point_on_track_at_dlong(
    sections: list[SectionPreview],
    dlong: float,
    dlat: float,
    track_length: float,
) -> Point | None:
    position = dlong_to_section_position(sections, dlong, track_length)
    if position is None:
        return None

    section = sections[position.section_index]
    fraction = max(0.0, min(1.0, position.fraction))
    return _point_on_section(section, fraction, dlat)


def _point_on_section(section: SectionPreview, fraction: float, dlat: float) -> Point:
    sx, sy = section.start
    ex, ey = section.end
    center = section.center

    if center is None:
        dx = ex - sx
        dy = ey - sy
        cx = sx + dx * fraction
        cy = sy + dy * fraction
        length = math.hypot(dx, dy)
        if length <= 0:
            return (cx, cy)
        nx = -dy / length
        ny = dx / length
        return (cx + nx * dlat, cy + ny * dlat)

    center_x, center_y = center
    start_vec = (sx - center_x, sy - center_y)
    end_vec = (ex - center_x, ey - center_y)
    base_radius = math.hypot(start_vec[0], start_vec[1])
    if base_radius <= 0:
        return (sx, sy)

    start_angle = math.atan2(start_vec[1], start_vec[0])
    end_angle = math.atan2(end_vec[1], end_vec[0])
    ccw = _is_ccw_turn(start_vec, end_vec, section.start_heading)
    delta = _angle_delta(start_angle, end_angle, ccw)
    angle = start_angle + delta * fraction

    sign = -1.0 if ccw else 1.0
    radius = max(0.0, base_radius + sign * dlat)
    return (
        center_x + math.cos(angle) * radius,
        center_y + math.sin(angle) * radius,
    )


def _is_ccw_turn(
    start_vec: Point,
    end_vec: Point,
    heading: tuple[float, float] | None,
) -> bool:
    if heading is not None:
        cross = start_vec[0] * heading[1] - start_vec[1] * heading[0]
        if not math.isclose(cross, 0.0, abs_tol=1e-12):
            return cross > 0

    cross = start_vec[0] * end_vec[1] - start_vec[1] * end_vec[0]
    return cross > 0


def _angle_delta(start_angle: float, end_angle: float, ccw: bool) -> float:
    delta = end_angle - start_angle
    if ccw:
        while delta <= 0:
            delta += math.tau
    else:
        while delta >= 0:
            delta -= math.tau
    return delta
def _draw_xsect_dlat_line(
    painter: QtGui.QPainter,
    sections: Iterable[SectionPreview],
    dlat: float,
    line_color: QtGui.QColor,
    transform: Transform,
    widget_height: int,
) -> None:
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(line_color)
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
    selected_color: QtGui.QColor,
) -> None:
    sg_rendering.draw_curve_markers(
        painter,
        sections,
        selected_curve_index,
        transform,
        widget_height,
        default_color=default_color,
        selected_color=selected_color,
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


def _draw_integrity_boundary_violation_points(
    painter: QtGui.QPainter,
    points: tuple[Point, ...],
    transform: Transform,
    widget_height: int,
) -> None:
    if not points:
        return

    pen = QtGui.QPen(QtGui.QColor("red"))
    pen.setWidth(2)
    painter.setPen(pen)
    painter.setBrush(QtGui.QBrush(QtGui.QColor("red")))

    diameter = 8.0
    radius = diameter / 2.0
    for point in points:
        mapped = _map_point(point, transform, widget_height)
        painter.drawEllipse(
            QtCore.QRectF(
                mapped.x() - radius,
                mapped.y() - radius,
                diameter,
                diameter,
            )
        )


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
