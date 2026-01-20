from __future__ import annotations

from PyQt5 import QtGui

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
        self._background_color = background_color

    def paint(self, painter: QtGui.QPainter) -> None:
        widget_size = self._context.widget_size()
        transform = self._runtime.current_transform(widget_size)

        node_state = None
        if transform is not None:
            node_state = preview_painter.NodeOverlayState(
                node_positions=self._runtime.build_node_positions(),
                node_status=self._runtime.node_status,
                node_radius_px=self._runtime.node_radius_px,
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

        preview_painter.paint_preview(
            painter,
            preview_painter.BasePreviewState(
                rect=painter.viewport(),
                background_color=self._background_color,
                background_image=background.image,
                background_scale_500ths_per_px=background.scale_500ths_per_px,
                background_origin=background.world_xy_at_image_uv_00,
                sampled_centerline=section_manager.sampled_centerline,
                centerline_polylines=section_manager.centerline_polylines,
                selected_section_points=selection.selected_section_points,
                section_endpoints=section_manager.section_endpoints,
                selected_section_index=selection.selected_section_index,
                show_curve_markers=self._runtime.show_curve_markers,
                show_axes=self._runtime.show_axes,
                sections=section_manager.sections,
                selected_curve_index=selection.selected_curve_index,
                start_finish_mapping=self._runtime.start_finish_mapping,
                status_message=self._runtime.status_message,
                split_section_mode=self._runtime.split_section_mode,
                split_hover_point=self._runtime.split_hover_point,
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
            transform,
            self._context.widget_height(),
        )
