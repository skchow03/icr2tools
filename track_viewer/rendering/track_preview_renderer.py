"""Rendering helpers for the track preview widget.

This module belongs to the rendering layer. It converts model/view-state data
into draw calls on a QPainter without mutating the model or performing IO.
All geometry is in world coordinates until mapped to screen space.
"""
from __future__ import annotations

import math
from typing import Tuple

from PyQt5 import QtCore, QtGui

from icr2_core.lp.lpcalc import get_trk_sect_radius
from icr2_core.trk.trk_utils import dlong2sect, getbounddlat, getxyz
from track_viewer import rendering
from track_viewer.common.weather_compass import (
    heading_adjust_to_turns,
    turns_to_unit_vector,
    wind_variation_to_turns,
)
from track_viewer.common.preview_constants import LP_COLORS, LP_FILE_NAMES
from track_viewer.model.pit_models import PIT_DLAT_LINE_COLORS, PIT_DLONG_LINE_COLORS
from track_viewer.model.track_preview_model import TrackPreviewModel
from track_viewer.model.view_state import TrackPreviewViewState
from track_viewer.services.camera_service import CameraService


class TrackPreviewRenderer:
    """Render track preview geometry using model data and view state.

    The renderer caches derived draw primitives but does not own the model
    or perform persistence. It is mutable only for caching and is otherwise
    side-effect free beyond issuing draw calls to the provided QPainter.
    """

    PIT_CAR_LENGTH_DLONG = 99208.0
    PIT_CAR_WIDTH_DLAT = 40000.0

    def __init__(
        self,
        model: TrackPreviewModel,
        camera_service: CameraService,
        state: TrackPreviewViewState,
    ) -> None:
        self._model = model
        self._camera_service = camera_service
        self._state = state
        self._surface_cache: list[rendering.SurfacePolygon] = []
        self._surface_cache_key: tuple[object | None, int] | None = None
        self._boundary_path_cache = QtGui.QPainterPath()
        self._boundary_cache_key: tuple[object | None, int] | None = None
        self._centerline_path_cache = QtGui.QPainterPath()
        self._centerline_cache_key: tuple[object | None, int] | None = None
        self._ai_line_cache: dict[str, rendering.AiLineCache] = {}
        self._ai_line_cache_key: tuple[
            object | None, int, str, int, int
        ] | None = None

    def paint(self, painter: QtGui.QPainter, size: QtCore.QSize) -> None:
        """Draw the preview in painter order (surface → overlays → UI)."""
        if not self._model.bounds:
            painter.setPen(QtGui.QPen(QtGui.QColor("lightgray")))
            painter.drawText(
                painter.viewport(), QtCore.Qt.AlignCenter, self._state.status_message
            )
            self._draw_weather_compass(painter, size)
            return

        transform = self._state.current_transform(self._model.bounds, size)
        if transform and self._model.surface_mesh:
            self._ensure_surface_cache()
            painter.save()
            painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
            painter.setTransform(self._surface_transform(transform, size.height()))
            for surface in self._surface_cache:
                painter.setBrush(QtGui.QBrush(surface.fill))
                painter.setPen(QtGui.QPen(surface.outline, 1))
                painter.drawPolygon(surface.polygon)
            painter.restore()

        height = size.height()

        if transform and self._state.show_boundaries:
            self._ensure_boundary_cache()
            if not self._boundary_path_cache.isEmpty():
                painter.save()
                painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
                pen = QtGui.QPen(QtGui.QColor("lightgray"), 2)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.setTransform(self._surface_transform(transform, height))
                painter.drawPath(self._boundary_path_cache)
                painter.restore()

        if transform and self._state.show_center_line and self._model.sampled_centerline:
            self._ensure_centerline_cache()
            if not self._centerline_path_cache.isEmpty():
                painter.save()
                painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
                pen = QtGui.QPen(QtGui.QColor("white"), 2)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.setTransform(self._surface_transform(transform, height))
                painter.drawPath(self._centerline_path_cache)
                painter.restore()

        if transform:
            start_finish_segment = self._start_finish_segment()
            if start_finish_segment is not None:
                rendering.draw_start_finish_segment(
                    painter,
                    transform,
                    height,
                    start_finish_segment[0],
                    start_finish_segment[1],
                )

        if transform and self._state.show_center_line:
            rendering.draw_camera_range_markers(
                painter,
                self._camera_view_ranges(self._state.selected_camera),
                transform,
                height,
                self._centerline_point_and_normal,
            )

        if transform and self._state.nearest_projection_point:
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            highlight = rendering.map_point(
                self._state.nearest_projection_point[0],
                self._state.nearest_projection_point[1],
                transform,
                height,
            )
            pen = QtGui.QPen(QtGui.QColor("#ff5252"))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(QtGui.QBrush(QtGui.QColor("#ff5252")))
            painter.drawEllipse(highlight, 5, 5)

        if transform:
            if self._state.show_cameras:
                allowed_indices = None
                if self._state.show_cameras_current_tv_only:
                    allowed_indices = self._camera_service.camera_indices_for_view(
                        self._state.current_tv_mode_index
                    )
                rendering.draw_camera_positions(
                    painter,
                    self._camera_service.cameras,
                    self._state.selected_camera,
                    allowed_indices,
                    transform,
                    height,
                )
            self._draw_ai_lines(
                painter,
                transform,
                height,
            )
            self._draw_replay_line(painter, transform, height)
            self._draw_selected_lp_segment(painter, transform, height)
            rendering.draw_flags(
                painter,
                self._state.flags,
                self._state.selected_flag,
                transform,
                height,
                self._state.flag_radius,
            )
            if self._state.show_section_dividers:
                rendering.draw_pit_dlong_lines(
                    painter,
                    self._section_divider_segments(),
                    transform,
                    height,
                    width=1,
                )
            if self._state.show_pit_wall_dlat:
                rendering.draw_pit_stall_range(
                    painter,
                    self._pit_wall_range_points(),
                    transform,
                    height,
                    color=PIT_DLAT_LINE_COLORS.get(0, "#ffeb3b"),
                    width=2,
                )
            if self._state.show_pit_stall_center_dlat:
                rendering.draw_pit_stall_range(
                    painter,
                    self._pit_stall_range_points(),
                    transform,
                    height,
                    color=PIT_DLAT_LINE_COLORS.get(5, "#00ff00"),
                )
            if self._state.show_pit_stall_cars:
                rendering.draw_pit_stall_cars(
                    painter,
                    self._pit_stall_car_polygons(),
                    transform,
                    height,
                )
            rendering.draw_pit_dlong_lines(
                painter,
                self._pit_dlong_segments(),
                transform,
                height,
            )
            if self._state.show_zoom_points:
                rendering.draw_zoom_points(
                    painter,
                    self._zoom_points_for_camera(),
                    transform,
                    height,
                    self._centerline_point,
                )

        self._draw_lp_shortcut_overlay(painter, size)
        self._draw_status_overlay(painter)
        self._draw_camera_guidance(painter, size)
        self._draw_cursor_position(painter, size)
        self._draw_weather_compass(painter, size)

    def invalidate_surface_cache(self) -> None:
        """Drop cached geometry derived from the current track."""
        self._surface_cache = []
        self._surface_cache_key = None
        self._boundary_path_cache = QtGui.QPainterPath()
        self._boundary_cache_key = None
        self._centerline_path_cache = QtGui.QPainterPath()
        self._centerline_cache_key = None
        self._ai_line_cache = {}
        self._ai_line_cache_key = None

    def _ensure_surface_cache(self) -> None:
        key = (self._model.track_path, id(self._model.surface_mesh))
        if key == self._surface_cache_key and self._surface_cache:
            return
        self._surface_cache = rendering.build_surface_cache(self._model.surface_mesh)
        self._surface_cache_key = key

    def _ensure_boundary_cache(self) -> None:
        key = (self._model.track_path, id(self._model.boundary_edges))
        if key == self._boundary_cache_key:
            return
        self._boundary_path_cache = rendering.build_boundary_path(
            self._model.boundary_edges
        )
        self._boundary_cache_key = key

    def _ensure_centerline_cache(self) -> None:
        key = (self._model.track_path, id(self._model.sampled_centerline))
        if key == self._centerline_cache_key:
            return
        self._centerline_path_cache = rendering.build_centerline_path(
            self._model.sampled_centerline
        )
        self._centerline_cache_key = key

    def _ensure_ai_line_cache(self) -> None:
        key = (
            self._model.track_path,
            self._model.ai_line_cache_generation,
            self._state.ai_color_mode,
            self._state.ai_acceleration_window,
            self._state.ai_line_width,
            tuple(sorted(self._state.lp_colors.items())),
        )
        if key == self._ai_line_cache_key:
            return
        self._ai_line_cache = {}
        for lp_name in sorted(set(self._model.visible_lp_files)):
            records = self._model.ai_line_records(lp_name)
            cache = rendering.build_ai_line_cache(
                records,
                color=self._lp_color(lp_name),
                gradient=self._state.ai_color_mode,
                acceleration_window=self._state.ai_acceleration_window,
            )
            if cache is not None:
                self._ai_line_cache[lp_name] = cache
        self._ai_line_cache_key = key

    @staticmethod
    def _surface_transform(
        transform: tuple[float, tuple[float, float]], viewport_height: int
    ) -> QtGui.QTransform:
        """Convert a world-space transform into Qt screen-space coordinates."""
        scale, offsets = transform
        return QtGui.QTransform(
            scale,
            0.0,
            0.0,
            -scale,
            offsets[0],
            viewport_height - offsets[1],
        )

    def _draw_ai_lines(
        self,
        painter: QtGui.QPainter,
        transform: Tuple[float, Tuple[float, float]],
        height: int,
    ) -> None:
        """Draw AI lines in world space, mapped into screen coordinates."""
        if not self._model.visible_lp_files:
            return
        self._ensure_ai_line_cache()
        pen_width = max(1, self._state.ai_line_width)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.setTransform(self._surface_transform(transform, height))
        for name in sorted(set(self._model.visible_lp_files)):
            cache = self._ai_line_cache.get(name)
            if cache is None or cache.polygon.isEmpty():
                continue
            if cache.segment_colors:
                points = cache.polygon
                for index, color in enumerate(cache.segment_colors):
                    pen = QtGui.QPen(color, pen_width)
                    pen.setCosmetic(True)
                    painter.setPen(pen)
                    painter.drawLine(QtCore.QLineF(points[index], points[index + 1]))
                continue
            pen = QtGui.QPen(cache.base_color, pen_width)
            pen.setCosmetic(True)
            painter.setPen(pen)
            painter.drawPolyline(cache.polygon)
        painter.restore()

    def _draw_replay_line(
        self,
        painter: QtGui.QPainter,
        transform: Tuple[float, Tuple[float, float]],
        height: int,
    ) -> None:
        if not self._state.show_replay_line or not self._model.replay_lap_points:
            return
        polygon = QtGui.QPolygonF(
            [QtCore.QPointF(point.x, point.y) for point in self._model.replay_lap_points]
        )
        if polygon.isEmpty():
            return
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        pen = QtGui.QPen(QtGui.QColor("#4fc3f7"), 2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.setTransform(self._surface_transform(transform, height))
        painter.drawPolyline(polygon)
        painter.restore()

    def _lp_color(self, name: str) -> str:
        override = self._state.lp_colors.get(name)
        if override:
            return override
        try:
            index = LP_FILE_NAMES.index(name)
        except ValueError:
            return "#e53935"
        return LP_COLORS[index % len(LP_COLORS)]

    def _draw_selected_lp_segment(
        self,
        painter: QtGui.QPainter,
        transform: Tuple[float, Tuple[float, float]],
        height: int,
    ) -> None:
        """Highlight the selected LP record and its adjacent segment."""
        if (
            not self._state.selected_lp_line
            or self._state.selected_lp_index is None
            or self._state.selected_lp_line not in self._model.visible_lp_files
        ):
            return
        records = self._model.ai_line_records(self._state.selected_lp_line)
        if len(records) < 2:
            return
        index = self._state.selected_lp_index
        if 0 <= index < len(records):
            record = records[index]
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            marker = rendering.map_point(record.x, record.y, transform, height)
            pen = QtGui.QPen(QtGui.QColor("#fdd835"))
            pen.setWidth(1)
            painter.setPen(pen)
            painter.setBrush(QtGui.QBrush(QtGui.QColor("#fdd835")))
            painter.drawEllipse(marker, 4, 4)
        start_index = index
        end_index = index + 1
        if end_index >= len(records):
            end_index = index
            start_index = index - 1
        if 0 <= start_index < len(records) and 0 <= end_index < len(records):
            start_record = records[start_index]
            end_record = records[end_index]
            rendering.draw_lp_segment(
                painter,
                (start_record.x, start_record.y),
                (end_record.x, end_record.y),
                transform,
                height,
            )

    def _draw_lp_shortcut_overlay(
        self, painter: QtGui.QPainter, size: QtCore.QSize
    ) -> None:
        if not self._state.lp_shortcut_active:
            return
        self._draw_lp_editing_banner(painter, size)
        metrics = painter.fontMetrics()
        line_height = metrics.height()
        margin = 12
        step_value = self._state.lp_dlat_step
        lp_index_text = (
            "LP index: —"
            if self._state.selected_lp_index is None
            else f"LP index: {self._state.selected_lp_index}"
        )
        lines = [
            "LP arrow-key editing active:",
            "UP - next LP record",
            "DOWN - previous LP record",
            "PGUP - copy to next LP record",
            "PGDN - copy to previous LP record",
            f"LEFT - increase DLAT by {step_value}",
            f"RIGHT - decrease DLAT by {step_value}",
            lp_index_text,
        ]
        max_width = max(metrics.horizontalAdvance(line) for line in lines)
        start_x = size.width() - margin - max_width
        start_y = margin + metrics.ascent()
        painter.setPen(QtGui.QPen(QtGui.QColor("white")))
        for line in lines:
            painter.drawText(start_x, start_y, line)
            start_y += line_height

    def _draw_lp_editing_banner(
        self, painter: QtGui.QPainter, size: QtCore.QSize
    ) -> None:
        if not self._state.lp_editing_tab_active:
            return
        lp_name = self._state.active_lp_line
        if not lp_name or lp_name == "center-line":
            return
        painter.save()
        font = painter.font()
        font.setBold(True)
        font.setPointSize(max(font.pointSize() + 4, 14))
        painter.setFont(font)
        painter.setPen(QtGui.QPen(QtGui.QColor("#ffeb3b")))
        metrics = painter.fontMetrics()
        height = metrics.height()
        margin = 10
        banner_rect = QtCore.QRect(0, margin, size.width(), height + 4)
        painter.drawText(
            banner_rect,
            QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop,
            f"LP editing mode - {lp_name}",
        )
        painter.restore()

    def _draw_status_overlay(self, painter: QtGui.QPainter) -> None:
        """Render textual overlays in screen coordinates (no transforms)."""
        painter.setPen(QtGui.QPen(QtGui.QColor("white")))
        y = 20
        if self._model.track_length is not None:
            track_length_text = (
                f"Track length: {int(round(self._model.track_length))} DLONG"
            )
            painter.drawText(12, y, track_length_text)
            y += 16
        painter.drawText(12, y, self._state.status_message)
        y += 16
        if self._state.nearest_projection_line:
            if self._state.nearest_projection_line == "center-line":
                line_label = "Center line"
            elif self._state.nearest_projection_line == "replay-lap":
                if self._model.replay_lap_label:
                    line_label = f"Replay lap ({self._model.replay_lap_label})"
                else:
                    line_label = "Replay lap"
            else:
                line_label = f"{self._state.nearest_projection_line} line"
            painter.drawText(12, y, line_label)
            y += 16
        if self._state.nearest_projection_dlong is not None:
            dlong_text = f"DLONG: {int(round(self._state.nearest_projection_dlong))}"
            painter.drawText(12, y, dlong_text)
            y += 16
        if (
            self._state.nearest_projection_line == "center-line"
            and self._state.nearest_projection_dlong is not None
        ):
            for line in self._centerline_section_info(
                self._state.nearest_projection_dlong
            ):
                painter.drawText(12, y, line)
                y += 16
        if self._state.nearest_projection_dlat is not None:
            dlat_text = f"DLAT: {int(round(self._state.nearest_projection_dlat))}"
            painter.drawText(12, y, dlat_text)
            y += 16
        if self._state.nearest_projection_speed is not None:
            speed_text = f"Speed: {self._state.nearest_projection_speed:.1f} mph"
            painter.drawText(12, y, speed_text)
            y += 16
        if self._state.nearest_projection_acceleration is not None:
            accel_text = (
                f"Accel: {self._state.nearest_projection_acceleration:+.3f} ft/s²"
            )
            painter.drawText(12, y, accel_text)
            y += 16
        if self._state.nearest_projection_elevation is not None:
            elevation_text = (
                f"Elevation: {self._state.nearest_projection_elevation:.2f} (DLAT = 0)"
            )
            painter.drawText(12, y, elevation_text)

    def _draw_camera_guidance(
        self, painter: QtGui.QPainter, size: QtCore.QSize
    ) -> None:
        if not self._state.show_camera_guidance:
            return

        lines = [
            "LEFT-CLICK to select camera",
            "RIGHT-CLICK and drag to move selected camera",
        ]
        metrics = painter.fontMetrics()
        line_height = metrics.height()
        margin = 12
        max_width = max(metrics.horizontalAdvance(line) for line in lines)
        start_x = size.width() - margin - max_width
        start_y = margin + metrics.ascent()

        painter.setPen(QtGui.QPen(QtGui.QColor("white")))
        for line in lines:
            painter.drawText(start_x, start_y, line)
            start_y += line_height

    def _draw_cursor_position(
        self, painter: QtGui.QPainter, size: QtCore.QSize
    ) -> None:
        if self._state.cursor_position is None:
            return

        x, y = self._state.cursor_position
        lines = [
            f"Cursor X: {x:.2f}",
            f"Cursor Y: {y:.2f}",
        ]

        metrics = painter.fontMetrics()
        line_height = metrics.height()
        margin = 12
        max_width = max(metrics.horizontalAdvance(line) for line in lines)
        start_x = size.width() - margin - max_width
        start_y = (
            size.height()
            - margin
            - metrics.descent()
            - (len(lines) - 1) * line_height
        )

        painter.setPen(QtGui.QPen(QtGui.QColor("white")))
        for line in lines:
            painter.drawText(start_x, start_y, line)
            start_y += line_height

    def _draw_weather_compass(
        self, painter: QtGui.QPainter, size: QtCore.QSize
    ) -> None:
        if not self._state.show_weather_compass:
            return
        center = self._state.weather_compass_center(size)
        radius = self._state.weather_compass_radius(size)
        turns = self._state.weather_compass_turns()
        heading_adjust = (
            self._state.wind2_heading_adjust
            if self._state.weather_compass_source == "wind2"
            else self._state.wind_heading_adjust
        )
        heading_turns = (
            heading_adjust_to_turns(heading_adjust)
            if heading_adjust is not None
            else None
        )
        dx, dy = turns_to_unit_vector(turns)
        tip = QtCore.QPointF(center.x() + dx * radius, center.y() + dy * radius)
        handle_radius = self._state.weather_compass_handle_radius(size)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        outline_pen = QtGui.QPen(QtGui.QColor("#7f8c8d"))
        outline_pen.setWidth(1)
        line_color = QtGui.QColor("#7fe7f2")
        line_pen = QtGui.QPen(line_color)
        line_pen.setWidth(2)
        painter.setPen(line_pen)
        painter.drawLine(center, tip)
        painter.setBrush(line_color)
        painter.drawEllipse(tip, handle_radius, handle_radius)
        painter.setPen(outline_pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(center, radius, radius)
        if heading_turns is not None:
            heading_dx, heading_dy = turns_to_unit_vector(heading_turns)
            heading_tip = QtCore.QPointF(
                center.x() + heading_dx * radius,
                center.y() + heading_dy * radius,
            )
            heading_color = QtGui.QColor("#44d468")
            heading_pen = QtGui.QPen(heading_color)
            heading_pen.setWidth(2)
            painter.setPen(heading_pen)
            painter.drawLine(center, heading_tip)
            painter.setBrush(heading_color)
            painter.drawEllipse(heading_tip, handle_radius * 0.85, handle_radius * 0.85)
        variation = self._state.weather_compass_variation()
        if variation:
            delta_turns = wind_variation_to_turns(variation)
            dashed_pen = QtGui.QPen(line_color)
            dashed_pen.setWidth(1)
            dashed_pen.setStyle(QtCore.Qt.DashLine)
            painter.setPen(dashed_pen)
            for offset in (-delta_turns, delta_turns):
                offset_turns = (turns + offset) % 1.0
                vx, vy = turns_to_unit_vector(offset_turns)
                offset_tip = QtCore.QPointF(
                    center.x() + vx * radius, center.y() + vy * radius
                )
                painter.drawLine(center, offset_tip)
        painter.setPen(line_color)
        label_turns = heading_turns if heading_turns is not None else 0.0
        nx, ny = turns_to_unit_vector(label_turns)
        tangent = QtCore.QPointF(-ny, nx)
        arrow_length = max(6.0, handle_radius * 1.2)
        arrow_width = arrow_length * 0.6
        tip_distance = radius + handle_radius * 0.4
        tip = QtCore.QPointF(
            center.x() + nx * tip_distance,
            center.y() + ny * tip_distance,
        )
        base_distance = tip_distance - arrow_length
        base_center = QtCore.QPointF(
            center.x() + nx * base_distance,
            center.y() + ny * base_distance,
        )
        arrow = QtGui.QPolygonF(
            [
                tip,
                QtCore.QPointF(
                    base_center.x() + tangent.x() * (arrow_width / 2.0),
                    base_center.y() + tangent.y() * (arrow_width / 2.0),
                ),
                QtCore.QPointF(
                    base_center.x() - tangent.x() * (arrow_width / 2.0),
                    base_center.y() - tangent.y() * (arrow_width / 2.0),
                ),
            ]
        )
        painter.setBrush(line_color)
        painter.drawPolygon(arrow)
        painter.setBrush(QtCore.Qt.NoBrush)

        label_font = QtGui.QFont(painter.font())
        label_font.setPixelSize(8)
        label_font.setBold(True)
        painter.setFont(label_font)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
        metrics = QtGui.QFontMetrics(label_font)
        label = "N"
        label_width = metrics.horizontalAdvance(label)
        label_offset = handle_radius + metrics.height()
        label_center = QtCore.QPointF(
            center.x() + nx * (radius + label_offset),
            center.y() + ny * (radius + label_offset),
        )
        ascent = metrics.ascent()
        descent = metrics.descent()
        label_pos = QtCore.QPointF(
            round(label_center.x() - label_width / 2),
            round(label_center.y() + (ascent - descent) / 2),
        )
        painter.drawText(label_pos, label)
        painter.restore()

    def _centerline_section_info(self, dlong: float) -> list[str]:
        """Return human-readable section info for the given DLONG."""
        if self._model.trk is None:
            return []
        sect_info = dlong2sect(self._model.trk, dlong)
        if not sect_info:
            return []
        sect_index, _ = sect_info
        if sect_index is None or not (0 <= sect_index < self._model.trk.num_sects):
            return []
        section = self._model.trk.sects[sect_index]
        section_lines = [
            f"Section: {sect_index}",
            "Type: Curve" if section.type == 2 else "Type: Straight",
        ]
        if section.type == 2:
            radius_value: float | None = None
            if hasattr(section, "radius"):
                radius_value = float(section.radius)
            elif sect_index < self._model.trk.num_sects - 1:
                try:
                    radius_value = get_trk_sect_radius(self._model.trk, sect_index)
                except ZeroDivisionError:
                    radius_value = None
            if radius_value is not None and math.isfinite(radius_value):
                radius = abs(radius_value)
                if self._state.show_radius_raw:
                    section_lines.append(f"Radius: {int(round(radius))} 500ths")
                else:
                    radius_feet = radius * rendering.DLONG_TO_FEET
                    section_lines.append(f"Radius: {radius_feet:.2f} ft")
        return section_lines

    def _centerline_point_and_normal(
        self, dlong: float
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """Estimate a centerline point and normal vector at the DLONG."""
        if not self._model.trk or not self._model.centerline:
            return None
        track_length = float(self._model.trk.trklength)
        if track_length <= 0:
            return None

        def _wrap(value: float) -> float:
            while value < 0:
                value += track_length
            while value >= track_length:
                value -= track_length
            return value

        base = _wrap(float(dlong))
        delta = max(50.0, track_length * 0.002)
        prev_dlong = _wrap(base - delta)
        next_dlong = _wrap(base + delta)

        px, py, _ = getxyz(self._model.trk, prev_dlong, 0, self._model.centerline)
        nx, ny, _ = getxyz(self._model.trk, next_dlong, 0, self._model.centerline)
        cx, cy, _ = getxyz(self._model.trk, base, 0, self._model.centerline)

        vx = nx - px
        vy = ny - py
        length = (vx * vx + vy * vy) ** 0.5
        if length == 0:
            return None
        normal = (-vy / length, vx / length)
        return (cx, cy), normal

    def _centerline_point(self, dlong: float) -> tuple[float, float] | None:
        """Return the world-space centerline point at a DLONG."""
        if not self._model.trk or not self._model.centerline:
            return None
        track_length = float(self._model.trk.trklength)
        if track_length <= 0:
            return None
        wrapped = dlong % track_length
        cx, cy, _ = getxyz(self._model.trk, wrapped, 0, self._model.centerline)
        return cx, cy

    def _start_finish_segment(
        self,
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """Return the boundary-to-boundary start/finish segment at DLONG 0."""
        if not self._model.trk or not self._model.centerline:
            return None
        track_length = float(self._model.trk.trklength or 0.0)
        if track_length <= 0:
            return None
        dlong = 0.0 % track_length
        sect_info = dlong2sect(self._model.trk, dlong)
        if not sect_info:
            return None
        sect_index, subsect = sect_info
        if sect_index is None or subsect is None:
            return None
        section = self._model.trk.sects[sect_index]
        dlats: list[float] = []
        for bound_index in range(section.num_bounds):
            dlats.append(getbounddlat(self._model.trk, sect_index, subsect, bound_index))
        if not dlats:
            return None
        min_dlat = min(dlats)
        max_dlat = max(dlats)
        start_x, start_y, _ = getxyz(
            self._model.trk, dlong, min_dlat, self._model.centerline
        )
        end_x, end_y, _ = getxyz(
            self._model.trk, dlong, max_dlat, self._model.centerline
        )
        return (start_x, start_y), (end_x, end_y)

    def _pit_dlong_segments(
        self,
    ) -> list[tuple[tuple[float, float], tuple[float, float], str]]:
        if (
            self._model.trk is None
            or not self._model.centerline
            or self._state.pit_params is None
            or not self._state.visible_pit_indices
        ):
            return []
        track_length = float(self._model.trk.trklength or 0.0)
        if track_length <= 0:
            return []
        values = self._state.pit_params.values()
        segments: list[tuple[tuple[float, float], tuple[float, float], str]] = []
        for index in sorted(self._state.visible_pit_indices):
            if index < 0 or index >= len(values):
                continue
            dlong = float(values[index])
            dlong = dlong % track_length
            sect_info = dlong2sect(self._model.trk, dlong)
            if not sect_info:
                continue
            sect_index, subsect = sect_info
            if sect_index is None or subsect is None:
                continue
            section = self._model.trk.sects[sect_index]
            dlats: list[float] = []
            for bound_index in range(section.num_bounds):
                dlats.append(
                    getbounddlat(self._model.trk, sect_index, subsect, bound_index)
                )
            if not dlats:
                continue
            min_dlat = min(dlats)
            max_dlat = max(dlats)
            start_x, start_y, _ = getxyz(
                self._model.trk, dlong, min_dlat, self._model.centerline
            )
            end_x, end_y, _ = getxyz(
                self._model.trk, dlong, max_dlat, self._model.centerline
            )
            color = PIT_DLONG_LINE_COLORS.get(index, "#ffffff")
            segments.append(((start_x, start_y), (end_x, end_y), color))
        return segments

    def _pit_range_points(
        self, start_dlong: float, end_dlong: float, dlat: float
    ) -> list[tuple[float, float]]:
        """Sample a pit range into world-space points along the centerline."""
        if (
            self._model.trk is None
            or not self._model.centerline
        ):
            return []
        track_length = float(self._model.trk.trklength or 0.0)
        if track_length <= 0:
            return []
        start_dlong = float(start_dlong) % track_length
        end_dlong = float(end_dlong) % track_length
        if end_dlong < start_dlong:
            end_dlong += track_length
        step = max(5.0, track_length / 1000.0)
        points: list[tuple[float, float]] = []
        current = start_dlong
        last_dlong = None
        while current <= end_dlong:
            dlong = current % track_length
            px, py, _ = getxyz(self._model.trk, dlong, dlat, self._model.centerline)
            points.append((px, py))
            last_dlong = dlong
            current += step
        end_wrapped = end_dlong % track_length
        if last_dlong != end_wrapped:
            px, py, _ = getxyz(
                self._model.trk, end_wrapped, dlat, self._model.centerline
            )
            points.append((px, py))
        return points

    def _pit_stall_range_points(self) -> list[tuple[float, float]]:
        if self._state.pit_params is None:
            return []
        return self._pit_range_points(
            self._state.pit_params.player_pit_stall_dlong,
            self._state.pit_params.last_pit_stall_dlong,
            self._state.pit_params.pit_stall_center_dlat,
        )

    def _pit_wall_range_points(self) -> list[tuple[float, float]]:
        if self._state.pit_params is None:
            return []
        return self._pit_range_points(
            self._state.pit_params.player_pit_stall_dlong,
            self._state.pit_params.last_pit_stall_dlong,
            self._state.pit_params.pitwall_dlat,
        )

    def _pit_stall_car_polygons(self) -> list[list[tuple[float, float]]]:
        """Build world-space rectangles for each pit stall car."""
        if (
            self._state.pit_params is None
            or self._model.trk is None
            or not self._model.centerline
        ):
            return []
        track_length = float(self._model.trk.trklength or 0.0)
        if track_length <= 0:
            return []
        count = max(0, int(self._state.pit_params.pit_stall_count))
        if count <= 0:
            return []
        start_dlong = float(self._state.pit_params.player_pit_stall_dlong)
        end_dlong = float(self._state.pit_params.last_pit_stall_dlong)
        start_dlong = start_dlong % track_length
        end_dlong = end_dlong % track_length
        if end_dlong < start_dlong:
            end_dlong += track_length
        spacing = 0.0 if count == 1 else (end_dlong - start_dlong) / (count - 1)
        center_dlat = float(self._state.pit_params.pit_stall_center_dlat)
        half_width = self.PIT_CAR_WIDTH_DLAT / 2.0
        polygons: list[list[tuple[float, float]]] = []
        for index in range(count):
            tail_dlong = (start_dlong + spacing * index) % track_length
            head_dlong = (tail_dlong + self.PIT_CAR_LENGTH_DLONG) % track_length
            tail_left_x, tail_left_y, _ = getxyz(
                self._model.trk,
                tail_dlong,
                center_dlat + half_width,
                self._model.centerline,
            )
            tail_right_x, tail_right_y, _ = getxyz(
                self._model.trk,
                tail_dlong,
                center_dlat - half_width,
                self._model.centerline,
            )
            head_right_x, head_right_y, _ = getxyz(
                self._model.trk,
                head_dlong,
                center_dlat - half_width,
                self._model.centerline,
            )
            head_left_x, head_left_y, _ = getxyz(
                self._model.trk,
                head_dlong,
                center_dlat + half_width,
                self._model.centerline,
            )
            track_midpoint = (tail_dlong + self.PIT_CAR_LENGTH_DLONG / 2.0) % track_length
            mid_left_x, mid_left_y, _ = getxyz(
                self._model.trk,
                track_midpoint,
                center_dlat + half_width,
                self._model.centerline,
            )
            mid_right_x, mid_right_y, _ = getxyz(
                self._model.trk,
                track_midpoint,
                center_dlat - half_width,
                self._model.centerline,
            )
            along_x = head_left_x - tail_left_x
            along_y = head_left_y - tail_left_y
            along_length = math.hypot(along_x, along_y)
            if along_length > 0.0:
                scale = self.PIT_CAR_LENGTH_DLONG / along_length
                mid_center_x = (mid_left_x + mid_right_x) / 2.0
                mid_center_y = (mid_left_y + mid_right_y) / 2.0
                along_unit_x = along_x / along_length
                along_unit_y = along_y / along_length
                width_vec_x = mid_left_x - mid_right_x
                width_vec_y = mid_left_y - mid_right_y
                width_length = math.hypot(width_vec_x, width_vec_y)
                width_unit_x = width_vec_x / width_length if width_length > 0.0 else 0.0
                width_unit_y = width_vec_y / width_length if width_length > 0.0 else 0.0
                half_length = self.PIT_CAR_LENGTH_DLONG / 2.0
                half_width_world = width_length / 2.0
                tail_center_x = mid_center_x - along_unit_x * half_length
                tail_center_y = mid_center_y - along_unit_y * half_length
                head_center_x = mid_center_x + along_unit_x * half_length
                head_center_y = mid_center_y + along_unit_y * half_length
                tail_left_x = tail_center_x + width_unit_x * half_width_world
                tail_left_y = tail_center_y + width_unit_y * half_width_world
                tail_right_x = tail_center_x - width_unit_x * half_width_world
                tail_right_y = tail_center_y - width_unit_y * half_width_world
                head_right_x = head_center_x - width_unit_x * half_width_world
                head_right_y = head_center_y - width_unit_y * half_width_world
                head_left_x = head_center_x + width_unit_x * half_width_world
                head_left_y = head_center_y + width_unit_y * half_width_world
            polygons.append(
                [
                    (tail_left_x, tail_left_y),
                    (tail_right_x, tail_right_y),
                    (head_right_x, head_right_y),
                    (head_left_x, head_left_y),
                ]
            )
        return polygons

    def _section_divider_segments(
        self,
    ) -> list[tuple[tuple[float, float], tuple[float, float], str]]:
        if self._model.trk is None or not self._model.centerline:
            return []
        track_length = float(self._model.trk.trklength or 0.0)
        if track_length <= 0:
            return []
        segments: list[tuple[tuple[float, float], tuple[float, float], str]] = []
        seen_dlongs: set[float] = set()
        for section in self._model.trk.sects:
            try:
                dlong = float(section.start_dlong)
            except (TypeError, ValueError):
                continue
            dlong = dlong % track_length
            if dlong in seen_dlongs:
                continue
            seen_dlongs.add(dlong)
            sect_info = dlong2sect(self._model.trk, dlong)
            if not sect_info:
                continue
            sect_index, subsect = sect_info
            if sect_index is None or subsect is None:
                continue
            sect = self._model.trk.sects[sect_index]
            dlats: list[float] = []
            for bound_index in range(sect.num_bounds):
                dlats.append(
                    getbounddlat(self._model.trk, sect_index, subsect, bound_index)
                )
            if not dlats:
                continue
            min_dlat = min(dlats)
            max_dlat = max(dlats)
            start_x, start_y, _ = getxyz(
                self._model.trk, dlong, min_dlat, self._model.centerline
            )
            end_x, end_y, _ = getxyz(
                self._model.trk, dlong, max_dlat, self._model.centerline
            )
            segments.append(((start_x, start_y), (end_x, end_y), "lightgray"))
        return segments

    def _camera_view_ranges(self, camera_index: int | None) -> list[tuple[float, float]]:
        if camera_index is None:
            return []
        if camera_index < 0 or camera_index >= len(self._camera_service.cameras):
            return []
        ranges: list[tuple[float, float]] = []
        if self._state.show_cameras_current_tv_only:
            view_index = self._state.current_tv_mode_index
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

    def _zoom_points_for_camera(self) -> list[tuple[float, QtGui.QColor]]:
        if not self._state.show_zoom_points:
            return []
        if self._state.selected_camera is None:
            return []
        if self._state.selected_camera < 0 or self._state.selected_camera >= len(
            self._camera_service.cameras
        ):
            return []

        camera = self._camera_service.cameras[self._state.selected_camera]
        params = camera.type6
        if params is None:
            return []

        return [
            (params.start_point, QtGui.QColor("#ffeb3b")),
            (params.middle_point, QtGui.QColor("#00e676")),
            (params.end_point, QtGui.QColor("#42a5f5")),
        ]
