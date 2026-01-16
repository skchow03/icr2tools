"""Pit overlays for track preview."""
from __future__ import annotations

import math
from typing import Sequence

from PyQt5 import QtCore, QtGui

from icr2_core.trk.trk_utils import dlong2sect, getbounddlat, getxyz
from track_viewer.model.pit_models import PIT_DLAT_LINE_COLORS, PIT_DLONG_LINE_COLORS
from track_viewer.model.track_preview_model import TrackPreviewModel
from track_viewer.model.view_state import TrackPreviewViewState
from track_viewer.rendering.primitives.mapping import Point2D, Transform, map_point


def draw_pit_dlong_lines(
    painter: QtGui.QPainter,
    segments: Sequence[tuple[Point2D, Point2D, str]],
    transform: Transform,
    viewport_height: int,
    *,
    width: int = 2,
) -> None:
    if not segments:
        return
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    for start, end, color in segments:
        pen = QtGui.QPen(QtGui.QColor(color), width)
        painter.setPen(pen)
        painter.drawLine(
            QtCore.QLineF(
                map_point(start[0], start[1], transform, viewport_height),
                map_point(end[0], end[1], transform, viewport_height),
            )
        )
    painter.restore()


def draw_pit_stall_range(
    painter: QtGui.QPainter,
    points: Sequence[Point2D],
    transform: Transform,
    viewport_height: int,
    *,
    color: str = "#00ff00",
    width: int = 2,
) -> None:
    if len(points) < 2:
        return
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    pen = QtGui.QPen(QtGui.QColor(color), width)
    pen.setStyle(QtCore.Qt.DashLine)
    painter.setPen(pen)
    mapped = [
        map_point(point[0], point[1], transform, viewport_height)
        for point in points
    ]
    painter.drawPolyline(QtGui.QPolygonF(mapped))
    painter.restore()


def draw_pit_stall_cars(
    painter: QtGui.QPainter,
    polygons: Sequence[Sequence[Point2D]],
    transform: Transform,
    viewport_height: int,
    *,
    color: str = "#ffffff",
    outline: str = "#ffffff",
    width: int = 1,
    alpha: int = 255,
) -> None:
    if not polygons:
        return
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
    brush_color = QtGui.QColor(color)
    brush_color.setAlpha(alpha)
    painter.setBrush(QtGui.QBrush(brush_color))
    pen = QtGui.QPen(QtGui.QColor(outline), width)
    painter.setPen(pen)
    for polygon in polygons:
        if len(polygon) < 3:
            continue
        mapped = [
            map_point(point[0], point[1], transform, viewport_height)
            for point in polygon
        ]
        painter.drawPolygon(QtGui.QPolygonF(mapped))
    painter.restore()


class PitOverlay:
    """Render pit lane overlays."""

    PIT_CAR_LENGTH_DLONG = 99208.0
    PIT_CAR_WIDTH_DLAT = 40000.0

    def draw(
        self,
        painter: QtGui.QPainter,
        model: TrackPreviewModel,
        state: TrackPreviewViewState,
        transform: Transform,
        viewport_height: int,
    ) -> None:
        if state.show_section_dividers:
            draw_pit_dlong_lines(
                painter,
                self._section_divider_segments(model),
                transform,
                viewport_height,
                width=1,
            )
        if state.show_pit_wall_dlat:
            draw_pit_stall_range(
                painter,
                self._pit_wall_range_points(model, state),
                transform,
                viewport_height,
                color=PIT_DLAT_LINE_COLORS.get(0, "#ffeb3b"),
                width=2,
            )
        if state.show_pit_stall_center_dlat:
            draw_pit_stall_range(
                painter,
                self._pit_stall_range_points(model, state),
                transform,
                viewport_height,
                color=PIT_DLAT_LINE_COLORS.get(5, "#00ff00"),
            )
        if state.show_pit_stall_cars:
            draw_pit_stall_cars(
                painter,
                self._pit_stall_car_polygons(model, state),
                transform,
                viewport_height,
            )
        draw_pit_dlong_lines(
            painter,
            self._pit_dlong_segments(model, state),
            transform,
            viewport_height,
        )

    def _pit_dlong_segments(
        self, model: TrackPreviewModel, state: TrackPreviewViewState
    ) -> list[tuple[tuple[float, float], tuple[float, float], str]]:
        if (
            model.trk is None
            or not model.centerline
            or state.pit_params is None
            or not state.visible_pit_indices
        ):
            return []
        track_length = float(model.trk.trklength or 0.0)
        if track_length <= 0:
            return []
        values = state.pit_params.values()
        segments: list[tuple[tuple[float, float], tuple[float, float], str]] = []
        for index in sorted(state.visible_pit_indices):
            if index < 0 or index >= len(values):
                continue
            dlong = float(values[index])
            dlong = dlong % track_length
            sect_info = dlong2sect(model.trk, dlong)
            if not sect_info:
                continue
            sect_index, subsect = sect_info
            if sect_index is None or subsect is None:
                continue
            section = model.trk.sects[sect_index]
            dlats: list[float] = []
            for bound_index in range(section.num_bounds):
                dlats.append(
                    getbounddlat(model.trk, sect_index, subsect, bound_index)
                )
            if not dlats:
                continue
            min_dlat = min(dlats)
            max_dlat = max(dlats)
            start_x, start_y, _ = getxyz(
                model.trk, dlong, min_dlat, model.centerline
            )
            end_x, end_y, _ = getxyz(model.trk, dlong, max_dlat, model.centerline)
            color = PIT_DLONG_LINE_COLORS.get(index, "#ffffff")
            segments.append(((start_x, start_y), (end_x, end_y), color))
        return segments

    def _pit_range_points(
        self, model: TrackPreviewModel, start_dlong: float, end_dlong: float, dlat: float
    ) -> list[tuple[float, float]]:
        """Sample a pit range into world-space points along the centerline."""
        if model.trk is None or not model.centerline:
            return []
        track_length = float(model.trk.trklength or 0.0)
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
            px, py, _ = getxyz(model.trk, dlong, dlat, model.centerline)
            points.append((px, py))
            last_dlong = dlong
            current += step
        end_wrapped = end_dlong % track_length
        if last_dlong != end_wrapped:
            px, py, _ = getxyz(model.trk, end_wrapped, dlat, model.centerline)
            points.append((px, py))
        return points

    def _pit_stall_range_points(
        self, model: TrackPreviewModel, state: TrackPreviewViewState
    ) -> list[tuple[float, float]]:
        if state.pit_params is None:
            return []
        return self._pit_range_points(
            model,
            state.pit_params.player_pit_stall_dlong,
            state.pit_params.last_pit_stall_dlong,
            state.pit_params.pit_stall_center_dlat,
        )

    def _pit_wall_range_points(
        self, model: TrackPreviewModel, state: TrackPreviewViewState
    ) -> list[tuple[float, float]]:
        if state.pit_params is None:
            return []
        return self._pit_range_points(
            model,
            state.pit_params.player_pit_stall_dlong,
            state.pit_params.last_pit_stall_dlong,
            state.pit_params.pitwall_dlat,
        )

    def _pit_stall_car_polygons(
        self, model: TrackPreviewModel, state: TrackPreviewViewState
    ) -> list[list[tuple[float, float]]]:
        """Build world-space rectangles for each pit stall car."""
        if state.pit_params is None or model.trk is None or not model.centerline:
            return []
        track_length = float(model.trk.trklength or 0.0)
        if track_length <= 0:
            return []
        count = max(0, int(state.pit_params.pit_stall_count))
        if count <= 0:
            return []
        start_dlong = float(state.pit_params.player_pit_stall_dlong)
        end_dlong = float(state.pit_params.last_pit_stall_dlong)
        start_dlong = start_dlong % track_length
        end_dlong = end_dlong % track_length
        if end_dlong < start_dlong:
            end_dlong += track_length
        spacing = 0.0 if count == 1 else (end_dlong - start_dlong) / (count - 1)
        center_dlat = float(state.pit_params.pit_stall_center_dlat)
        half_width = self.PIT_CAR_WIDTH_DLAT / 2.0
        polygons: list[list[tuple[float, float]]] = []
        for index in range(count):
            tail_dlong = (start_dlong + spacing * index) % track_length
            head_dlong = (tail_dlong + self.PIT_CAR_LENGTH_DLONG) % track_length
            tail_left_x, tail_left_y, _ = getxyz(
                model.trk,
                tail_dlong,
                center_dlat + half_width,
                model.centerline,
            )
            tail_right_x, tail_right_y, _ = getxyz(
                model.trk,
                tail_dlong,
                center_dlat - half_width,
                model.centerline,
            )
            head_right_x, head_right_y, _ = getxyz(
                model.trk,
                head_dlong,
                center_dlat - half_width,
                model.centerline,
            )
            head_left_x, head_left_y, _ = getxyz(
                model.trk,
                head_dlong,
                center_dlat + half_width,
                model.centerline,
            )
            track_midpoint = (tail_dlong + self.PIT_CAR_LENGTH_DLONG / 2.0) % track_length
            mid_left_x, mid_left_y, _ = getxyz(
                model.trk,
                track_midpoint,
                center_dlat + half_width,
                model.centerline,
            )
            mid_right_x, mid_right_y, _ = getxyz(
                model.trk,
                track_midpoint,
                center_dlat - half_width,
                model.centerline,
            )
            along_x = head_left_x - tail_left_x
            along_y = head_left_y - tail_left_y
            along_length = math.hypot(along_x, along_y)
            if along_length > 0.0:
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
        self, model: TrackPreviewModel
    ) -> list[tuple[tuple[float, float], tuple[float, float], str]]:
        if model.trk is None or not model.centerline:
            return []
        track_length = float(model.trk.trklength or 0.0)
        if track_length <= 0:
            return []
        segments: list[tuple[tuple[float, float], tuple[float, float], str]] = []
        seen_dlongs: set[float] = set()
        for section in model.trk.sects:
            try:
                dlong = float(section.start_dlong)
            except (TypeError, ValueError):
                continue
            dlong = dlong % track_length
            if dlong in seen_dlongs:
                continue
            seen_dlongs.add(dlong)
            sect_info = dlong2sect(model.trk, dlong)
            if not sect_info:
                continue
            sect_index, subsect = sect_info
            if sect_index is None or subsect is None:
                continue
            sect = model.trk.sects[sect_index]
            dlats: list[float] = []
            for bound_index in range(sect.num_bounds):
                dlats.append(getbounddlat(model.trk, sect_index, subsect, bound_index))
            if not dlats:
                continue
            min_dlat = min(dlats)
            max_dlat = max(dlats)
            start_x, start_y, _ = getxyz(
                model.trk, dlong, min_dlat, model.centerline
            )
            end_x, end_y, _ = getxyz(model.trk, dlong, max_dlat, model.centerline)
            segments.append(((start_x, start_y), (end_x, end_y), "lightgray"))
        return segments
