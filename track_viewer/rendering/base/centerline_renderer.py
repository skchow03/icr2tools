"""Centerline rendering and geometry helpers for the track preview."""
from __future__ import annotations

import math

from PyQt5 import QtCore, QtGui

from icr2_core.lp.lpcalc import get_trk_sect_radius
from icr2_core.trk.trk_utils import dlong2sect, getbounddlat, getxyz
from track_viewer.model.track_preview_model import TrackPreviewModel
from track_viewer.model.view_state import TrackPreviewViewState
from track_viewer.rendering import (
    DLONG_TO_FEET,
    build_centerline_path,
    draw_start_finish_segment,
)
from track_viewer.rendering.base.transform import surface_transform


class CenterlineRenderer:
    """Render centerline geometry and provide derived measurements."""

    def __init__(self) -> None:
        self._centerline_path_cache = QtGui.QPainterPath()
        self._centerline_cache_key: tuple[object | None, int] | None = None

    def invalidate_cache(self) -> None:
        self._centerline_path_cache = QtGui.QPainterPath()
        self._centerline_cache_key = None

    def draw(
        self,
        painter: QtGui.QPainter,
        model: TrackPreviewModel,
        state: TrackPreviewViewState,
        transform: tuple[float, tuple[float, float]],
        viewport_height: int,
    ) -> None:
        if not state.show_center_line or not model.sampled_centerline:
            return
        self._ensure_centerline_cache(model)
        if self._centerline_path_cache.isEmpty():
            return
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        pen = QtGui.QPen(QtGui.QColor("white"), 2)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.setTransform(surface_transform(transform, viewport_height))
        painter.drawPath(self._centerline_path_cache)
        painter.restore()

    def draw_start_finish(
        self,
        painter: QtGui.QPainter,
        model: TrackPreviewModel,
        transform: tuple[float, tuple[float, float]],
        viewport_height: int,
    ) -> None:
        segment = self.start_finish_segment(model)
        if segment is None:
            return
        draw_start_finish_segment(
            painter,
            transform,
            viewport_height,
            segment[0],
            segment[1],
        )

    def start_finish_segment(
        self, model: TrackPreviewModel
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """Return the boundary-to-boundary start/finish segment at DLONG 0."""
        if not model.trk or not model.centerline:
            return None
        track_length = float(model.trk.trklength or 0.0)
        if track_length <= 0:
            return None
        dlong = 0.0 % track_length
        sect_info = dlong2sect(model.trk, dlong)
        if not sect_info:
            return None
        sect_index, subsect = sect_info
        if sect_index is None or subsect is None:
            return None
        section = model.trk.sects[sect_index]
        dlats: list[float] = []
        for bound_index in range(section.num_bounds):
            dlats.append(getbounddlat(model.trk, sect_index, subsect, bound_index))
        if not dlats:
            return None
        min_dlat = min(dlats)
        max_dlat = max(dlats)
        start_x, start_y, _ = getxyz(model.trk, dlong, min_dlat, model.centerline)
        end_x, end_y, _ = getxyz(model.trk, dlong, max_dlat, model.centerline)
        return (start_x, start_y), (end_x, end_y)

    def centerline_section_info(
        self, model: TrackPreviewModel, state: TrackPreviewViewState, dlong: float
    ) -> list[str]:
        """Return human-readable section info for the given DLONG."""
        if model.trk is None:
            return []
        sect_info = dlong2sect(model.trk, dlong)
        if not sect_info:
            return []
        sect_index, _ = sect_info
        if sect_index is None or not (0 <= sect_index < model.trk.num_sects):
            return []
        section = model.trk.sects[sect_index]
        section_lines = [
            f"Section: {sect_index}",
            "Type: Curve" if section.type == 2 else "Type: Straight",
        ]
        if section.type == 2:
            radius_value: float | None = None
            if hasattr(section, "radius"):
                radius_value = float(section.radius)
            elif sect_index < model.trk.num_sects - 1:
                try:
                    radius_value = get_trk_sect_radius(model.trk, sect_index)
                except ZeroDivisionError:
                    radius_value = None
            if radius_value is not None and math.isfinite(radius_value):
                radius = abs(radius_value)
                if state.show_radius_raw:
                    section_lines.append(f"Radius: {int(round(radius))} 500ths")
                else:
                    radius_feet = radius * DLONG_TO_FEET
                    section_lines.append(f"Radius: {radius_feet:.2f} ft")
        return section_lines

    def centerline_point_and_normal(
        self, model: TrackPreviewModel, dlong: float
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """Estimate a centerline point and normal vector at the DLONG."""
        if not model.trk or not model.centerline:
            return None
        track_length = float(model.trk.trklength)
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

        px, py, _ = getxyz(model.trk, prev_dlong, 0, model.centerline)
        nx, ny, _ = getxyz(model.trk, next_dlong, 0, model.centerline)
        cx, cy, _ = getxyz(model.trk, base, 0, model.centerline)

        vx = nx - px
        vy = ny - py
        length = (vx * vx + vy * vy) ** 0.5
        if length == 0:
            return None
        normal = (-vy / length, vx / length)
        return (cx, cy), normal

    def centerline_point(
        self, model: TrackPreviewModel, dlong: float
    ) -> tuple[float, float] | None:
        """Return the world-space centerline point at a DLONG."""
        if not model.trk or not model.centerline:
            return None
        track_length = float(model.trk.trklength)
        if track_length <= 0:
            return None
        wrapped = dlong % track_length
        cx, cy, _ = getxyz(model.trk, wrapped, 0, model.centerline)
        return cx, cy

    def _ensure_centerline_cache(self, model: TrackPreviewModel) -> None:
        key = (model.track_path, id(model.sampled_centerline))
        if key == self._centerline_cache_key:
            return
        self._centerline_path_cache = build_centerline_path(model.sampled_centerline)
        self._centerline_cache_key = key
