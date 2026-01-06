"""Drawing helpers for the track preview widget."""
from __future__ import annotations

import math
from typing import List, Tuple

from PyQt5 import QtCore, QtGui

from icr2_core.lp.lpcalc import get_trk_sect_radius
from icr2_core.trk.trk_utils import dlong2sect, getbounddlat, getxyz
from track_viewer import rendering
from track_viewer.common.preview_constants import LP_COLORS, LP_FILE_NAMES
from track_viewer.model.pit_models import PIT_DLONG_LINE_COLORS
from track_viewer.model.track_preview_model import TrackPreviewModel
from track_viewer.model.view_state import TrackPreviewViewState
from track_viewer.services.camera_service import CameraService


class TrackPreviewRenderer:
    """Render track preview geometry using the shared view state."""

    def __init__(
        self,
        model: TrackPreviewModel,
        camera_service: CameraService,
        state: TrackPreviewViewState,
    ) -> None:
        self._model = model
        self._camera_service = camera_service
        self._state = state

    def paint(self, painter: QtGui.QPainter, size: QtCore.QSize) -> None:
        if not self._model.surface_mesh or not self._model.bounds:
            painter.setPen(QtGui.QPen(QtGui.QColor("lightgray")))
            painter.drawText(
                painter.viewport(), QtCore.Qt.AlignCenter, self._state.status_message
            )
            return

        transform = self._state.current_transform(self._model.bounds, size)
        if (
            self._state.cached_surface_pixmap is None
            or self._state.pixmap_size != size
        ):
            self._state.cached_surface_pixmap = rendering.render_surface_to_pixmap(
                self._model.surface_mesh, transform, size
            )
            self._state.pixmap_size = size

        painter.drawPixmap(0, 0, self._state.cached_surface_pixmap)

        height = size.height()

        if transform and self._state.show_boundaries:
            rendering.draw_track_boundaries(
                painter, self._model.boundary_edges, transform, height
            )

        if transform and self._state.show_center_line and self._model.sampled_centerline:
            rendering.draw_centerline(
                painter,
                self._model.sampled_centerline,
                transform,
                height,
            )

        if transform and self._state.show_center_line:
            rendering.draw_start_finish_line(
                painter,
                transform,
                height,
                self._centerline_point_and_normal,
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
                rendering.draw_camera_positions(
                    painter,
                    self._camera_service.cameras,
                    self._state.selected_camera,
                    transform,
                    height,
                )
            rendering.draw_ai_lines(
                painter,
                self._model.visible_lp_files,
                self._get_ai_line_points,
                transform,
                height,
                self._lp_color,
                gradient=self._state.ai_color_mode,
                get_records=self._model.ai_line_records,
                line_width=self._state.ai_line_width,
                acceleration_window=self._state.ai_acceleration_window,
            )
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
                    color="#ffeb3b",
                    width=2,
                )
            if self._state.show_pit_stall_center_dlat:
                rendering.draw_pit_stall_range(
                    painter,
                    self._pit_stall_range_points(),
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
        self._draw_cursor_position(painter, size)

    def _get_ai_line_points(self, lp_name: str) -> List[Tuple[float, float]]:
        return [(p.x, p.y) for p in self._model.ai_line_records(lp_name)]

    @staticmethod
    def _lp_color(name: str) -> str:
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

    def _draw_status_overlay(self, painter: QtGui.QPainter) -> None:
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
            line_label = (
                "Center line"
                if self._state.nearest_projection_line == "center-line"
                else f"{self._state.nearest_projection_line} line"
            )
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

    def _centerline_section_info(self, dlong: float) -> list[str]:
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
        if not self._model.trk or not self._model.centerline:
            return None
        track_length = float(self._model.trk.trklength)
        if track_length <= 0:
            return None
        wrapped = dlong % track_length
        cx, cy, _ = getxyz(self._model.trk, wrapped, 0, self._model.centerline)
        return cx, cy

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
        for view in self._camera_service.camera_views:
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
