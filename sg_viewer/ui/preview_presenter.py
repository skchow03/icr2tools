from __future__ import annotations

import math

from PyQt5 import QtGui

from icr2_core.sg_elevation import sg_altitude_at

from sg_viewer.preview.context import PreviewContext
from sg_viewer.preview.runtime import PreviewRuntime
from sg_viewer.services import preview_painter


class PreviewPresenter:
    def __init__(
        self,
        context: PreviewContext,
        runtime: PreviewRuntime,
        background_color: QtGui.QColor,
    ) -> None:
        self._context = context
        self._runtime = runtime
        self._colors = preview_painter.default_preview_colors()
        self._colors.background = QtGui.QColor(background_color)
        self._centerline_elevation_cache_key: tuple[object, ...] | None = None
        self._centerline_elevation_cache: tuple[
            tuple[tuple[float, float], tuple[float, float], QtGui.QColor, bool], ...
        ] = ()

    def set_preview_color(self, key: str, color: QtGui.QColor) -> None:
        if not hasattr(self._colors, key):
            raise ValueError(f"Unknown preview color key: {key}")
        setattr(self._colors, key, QtGui.QColor(color))

    def preview_color(self, key: str) -> QtGui.QColor:
        if not hasattr(self._colors, key):
            raise ValueError(f"Unknown preview color key: {key}")
        return QtGui.QColor(getattr(self._colors, key))

    def paint(self, painter: QtGui.QPainter) -> None:
        widget_size = self._context.widget_size()
        transform = self._runtime.current_transform(widget_size)

        node_state = None
        if transform is not None and self._runtime.show_centerline_and_nodes:
            node_state = preview_painter.NodeOverlayState(
                node_positions=self._runtime.build_node_positions(),
                node_status=self._runtime.node_status,
                node_radius_px=self._runtime.node_radius_px,
                nodes_connected_color=self._colors.nodes_connected,
                nodes_disconnected_color=self._colors.nodes_disconnected,
                hovered_node=self._runtime.hovered_endpoint,
                connection_target=self._runtime.interaction.connection_target,
            )

        creation_preview = self._runtime.creation_controller.preview_sections()
        drag_heading_state = None
        if transform is not None:
            dragged_heading = self._runtime.interaction.dragged_curve_heading()
            if dragged_heading is not None:
                drag_section, drag_end_point = dragged_heading
                drag_heading_state = preview_painter.DragHeadingState(
                    section=drag_section,
                    end_point=drag_end_point,
                )

        section_manager = self._runtime.section_manager
        selection = self._runtime.selection_manager
        background = self._runtime.background

        sg_preview_state = preview_painter.SgPreviewState(
            model=self._runtime.sg_preview_model,
            transform=self._runtime.sg_preview_transform(self._context.widget_height())
            if transform is not None
            else None,
            view_state=self._runtime.sg_preview_view_state,
            enabled=self._runtime.show_sg_fsects,
            show_mrk_notches=self._runtime.show_mrk_notches,
            selected_mrk_wall=self._runtime.selected_mrk_wall,
            highlighted_mrk_walls=self._runtime.highlighted_mrk_walls,
            mrk_wall_height_500ths=self._runtime.mrk_wall_height_500ths,
            mrk_armco_height_500ths=self._runtime.mrk_armco_height_500ths,
            mrk_length_multiplier=self._runtime.mrk_length_multiplier,
            show_tsd_lines=self._runtime.show_tsd_lines,
            show_tsd_selected_section_only=self._runtime.show_tsd_selected_section_only,
            selected_section_index=selection.selected_section_index,
            tsd_lines=self._runtime.tsd_lines,
            tsd_palette=self._runtime.tsd_palette,
            trackside_objects=self._runtime.trackside_objects if self._runtime.show_trackside_objects else (),
            selected_trackside_object_index=self._runtime.selected_trackside_object_index,
            selected_trackside_object_indices=self._runtime.selected_trackside_object_indices,
            focused_trackside_object_index=self._runtime.focused_trackside_object_index,
            trackside_move_enabled_indices=self._runtime.trackside_move_enabled_indices,
            trackside_order_labels=self._runtime.trackside_order_labels,
            section_geometry_version=self._runtime.section_geometry_version,
            tsd_lines_version=self._runtime.tsd_lines_version,
            tso_box_default_color=self._colors.tso_box_default,
            tso_box_selected_color=self._colors.tso_box_selected,
            tso_box_highlighted_color=self._colors.tso_box_highlighted,
            tso_pivot_color=self._colors.tso_pivot,
        )

        show_centerline_and_nodes = self._runtime.show_centerline_and_nodes

        preview_painter.paint_preview(
            painter,
            preview_painter.BasePreviewState(
                rect=painter.viewport(),
                background_color=self._colors.background,
                background_image=(
                    background.image if self._runtime.show_background_image else None
                ),
                background_brightness=background.brightness_pct,
                background_scale_500ths_per_px=background.scale_500ths_per_px,
                background_origin=background.world_xy_at_image_uv_00,
                track_opacity=self._runtime.track_opacity,
                sampled_centerline=section_manager.sampled_centerline,
                selected_section_points=(
                    selection.selected_section_points if show_centerline_and_nodes else []
                ),
                section_endpoints=section_manager.section_endpoints,
                selected_section_index=selection.selected_section_index,
                show_curve_markers=self._runtime.show_curve_markers,
                show_axes=self._runtime.show_axes,
                show_crosshair=self._runtime.show_crosshair,
                sections=section_manager.sections,
                selected_curve_index=selection.selected_curve_index,
                start_finish_mapping=self._runtime.start_finish_mapping,
                status_message=self._runtime.status_message,
                split_section_mode=self._runtime.split_section_mode,
                split_hover_point=self._runtime.split_hover_point,
                query_track_hover_point=self._runtime.query_track_hover_point,
                query_track_overlay_message=self._runtime.query_track_overlay_message,
                ruler_start_point=self._runtime.ruler_start_point,
                ruler_end_point=self._runtime.ruler_end_point,
                ruler_label=self._runtime.ruler_label,
                land_object_points=(
                    self._runtime.land_object_points_overlay
                    if self._runtime.show_land_objects
                    else ()
                ),
                land_object_polygons=(
                    self._runtime.land_object_polygons_overlay
                    if self._runtime.show_land_objects
                    else ()
                ),
                xsect_dlat=self._runtime.selected_xsect_dlat
                if self._runtime.show_sg_fsects
                else None,
                show_xsect_dlat_line=(
                    self._runtime.show_xsect_dlat_line
                    and self._runtime.show_sg_fsects
                ),
                centerline_unselected_color=self._colors.centerline_unselected,
                centerline_selected_color=self._colors.centerline_selected,
                centerline_long_curve_color=self._colors.centerline_long_curve,
                radii_unselected_color=self._colors.radii_unselected,
                radii_selected_color=self._colors.radii_selected,
                xsect_dlat_line_color=self._colors.xsect_dlat_line,
                integrity_boundary_violation_points=self._runtime.integrity_boundary_violation_points,
                centerline_elevation_segments=(
                    self._centerline_elevation_segments()
                    if self._runtime.show_centerline_elevation_gradient
                    else ()
                ),
                show_centerline_and_nodes=show_centerline_and_nodes,
            ),
            preview_painter.CreationOverlayState(
                new_straight_active=creation_preview.new_straight_active,
                new_straight_start=creation_preview.new_straight_start,
                new_straight_end=creation_preview.new_straight_end,
                new_curve_active=creation_preview.new_curve_active,
                new_curve_start=creation_preview.new_curve_start,
                new_curve_end=creation_preview.new_curve_end,
                new_curve_preview=creation_preview.new_curve_preview,
            ),
            node_state,
            drag_heading_state,
            sg_preview_state,
            transform,
            self._context.widget_height(),
        )

        box_rect = self._runtime._trackside_box_select_screen_rect()
        if box_rect is not None and box_rect.width() > 0.0 and box_rect.height() > 0.0:
            pen = QtGui.QPen(QtGui.QColor(80, 170, 255, 220))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(QtGui.QColor(80, 170, 255, 60))
            painter.drawRect(box_rect)


def _point_at_polyline_distance(polyline, distance: float):
    if not polyline:
        return 0.0, 0.0
    if distance <= 0.0 or len(polyline) == 1:
        return polyline[0]
    remaining = distance
    for start, end in zip(polyline, polyline[1:]):
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length <= 0.0:
            continue
        if remaining <= length:
            ratio = remaining / length
            return start[0] + dx * ratio, start[1] + dy * ratio
        remaining -= length
    return polyline[-1]


def _viridis_color(value: float) -> QtGui.QColor:
    stops = (
        (0.0, (68, 1, 84)),
        (0.25, (59, 82, 139)),
        (0.5, (33, 145, 140)),
        (0.75, (94, 201, 98)),
        (1.0, (253, 231, 37)),
    )
    value = max(0.0, min(1.0, value))
    for (left_pos, left_rgb), (right_pos, right_rgb) in zip(stops, stops[1:]):
        if value <= right_pos:
            ratio = (value - left_pos) / (right_pos - left_pos) if right_pos > left_pos else 0.0
            return QtGui.QColor(*[int(round(left_rgb[i] + (right_rgb[i] - left_rgb[i]) * ratio)) for i in range(3)])
    return QtGui.QColor(*stops[-1][1])


def _build_centerline_elevation_segments(runtime) -> tuple[tuple[tuple[float, float], tuple[float, float], QtGui.QColor, bool], ...]:
    sgfile = runtime.sgfile
    if sgfile is None:
        return ()
    sections = list(runtime.section_manager.sections)
    selected_index = runtime.selection_manager.selected_section_index
    samples: list[tuple[tuple[float, float], float, int]] = []
    # Keep the gradient lightweight: one color segment every 20 feet is enough
    # to show elevation trends without flooding the viewport with draw calls.
    step = 500.0 * 20.0
    for section in sections:
        if len(section.polyline) < 2 or section.length <= 0:
            continue
        source_id = getattr(section, "source_section_id", section.section_id)
        if source_id is None or source_id < 0:
            source_id = section.section_id
        intervals = max(1, int(math.ceil(float(section.length) / step)))
        for index in range(intervals + 1):
            distance = min(float(section.length), index * float(section.length) / intervals)
            subsect = 0.0 if section.length <= 0 else distance / float(section.length)
            samples.append((
                _point_at_polyline_distance(section.polyline, distance),
                float(sg_altitude_at(sgfile, int(source_id), subsect, 0.5)),
                int(section.section_id),
            ))
    if len(samples) < 2:
        return ()
    low = min(sample[1] for sample in samples)
    high = max(sample[1] for sample in samples)
    span = high - low
    segments = []
    for (start, alt0, section_id), (end, alt1, next_section_id) in zip(samples, samples[1:]):
        if start == end:
            continue
        value = 0.5 if span <= 0.0 else (((alt0 + alt1) / 2.0) - low) / span
        color = _viridis_color(value)
        selected = selected_index in (section_id, next_section_id)
        segments.append((start, end, color, selected))
    return tuple(segments)


def _centerline_elevation_segments(self: PreviewPresenter):
    key = (
        id(self._runtime.sgfile),
        self._runtime.section_geometry_version,
        getattr(self._runtime, "elevation_color_version", 0),
        self._runtime.selection_manager.selected_section_index,
    )
    if key != self._centerline_elevation_cache_key:
        self._centerline_elevation_cache_key = key
        self._centerline_elevation_cache = _build_centerline_elevation_segments(self._runtime)
    return self._centerline_elevation_cache


PreviewPresenter._centerline_elevation_segments = _centerline_elevation_segments
