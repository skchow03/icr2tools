"""Renderer for the track preview widget."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Sequence, Tuple

from PyQt5 import QtCore, QtGui

from icr2_core.cam.helpers import CameraPosition
from icr2_core.trk.surface_mesh import GroundSurfaceStrip
from track_viewer import rendering

Transform = rendering.Transform
Point2D = rendering.Point2D


@dataclass
class ProjectionOverlay:
    """Data about the currently highlighted projection point."""

    line_name: str | None
    dlong: float | None
    dlat: float | None
    speed: float | None
    elevation: float | None
    acceleration: float | None


@dataclass
class HudInfo:
    """HUD overlay details for text rendering."""

    status_message: str
    track_length: float | None
    projection: ProjectionOverlay
    cursor_position: tuple[float, float] | None


@dataclass
class PreviewRenderConfig:
    """Runtime rendering options for the preview."""

    show_boundaries: bool
    show_center_line: bool
    show_cameras: bool
    show_zoom_points: bool
    ai_color_mode: str
    ai_line_width: int
    ai_acceleration_window: int
    selected_flag: int | None
    selected_camera: int | None


@dataclass
class PreviewRenderData:
    """Static data sources needed to render the preview."""

    surface_mesh: Sequence[GroundSurfaceStrip] | None
    bounds: tuple[float, float, float, float] | None
    boundary_edges: Sequence[tuple[Point2D, Point2D]]
    sampled_centerline: Sequence[Point2D]
    sampled_bounds: tuple[float, float, float, float] | None
    visible_lp_files: Iterable[str]
    flags: Sequence[Point2D]
    cameras: Sequence[CameraPosition]
    zoom_points: Iterable[tuple[float, QtGui.QColor]]
    camera_ranges: Iterable[tuple[float, float]]
    centerline_point_and_normal: Callable[[float], tuple[Point2D, Point2D] | None]
    centerline_point: Callable[[float], Point2D | None]
    get_ai_line_points: Callable[[str], Sequence[Point2D]]
    get_ai_line_records: Callable[[str], Sequence[object]]
    lp_color: Callable[[str], str]
    highlight_point: tuple[float, float] | None


class PreviewRenderer:
    """Encapsulates all drawing and transform state for the preview widget."""

    def __init__(
        self,
        model_bounds_provider: Callable[[], tuple[float, float, float, float] | None],
        default_center_provider: Callable[[], tuple[float, float] | None],
    ) -> None:
        self._model_bounds = model_bounds_provider
        self._default_center = default_center_provider
        self._cached_surface_pixmap: QtGui.QPixmap | None = None
        self._pixmap_size: QtCore.QSize | None = None
        self.view_center: tuple[float, float] | None = None
        self.fit_scale: float | None = None
        self.current_scale: float | None = None
        self.user_transform_active = False

    # ------------------------------------------------------------------
    # Transform helpers
    # ------------------------------------------------------------------
    def reset(self, *, view_center: tuple[float, float] | None = None) -> None:
        """Reset cached rendering data and optionally set the view center."""

        self._cached_surface_pixmap = None
        self._pixmap_size = None
        self.view_center = view_center
        self.fit_scale = None
        self.current_scale = None
        self.user_transform_active = False

    def invalidate_cache(self) -> None:
        self._cached_surface_pixmap = None
        self._pixmap_size = None

    def calculate_fit_scale(self, viewport_size: QtCore.QSize) -> float | None:
        bounds = self._model_bounds()
        if not bounds:
            return None
        min_x, max_x, min_y, max_y = bounds
        track_w = max_x - min_x
        track_h = max_y - min_y
        if track_w <= 0 or track_h <= 0:
            return None
        margin = 24
        available_w = max(viewport_size.width() - margin * 2, 1)
        available_h = max(viewport_size.height() - margin * 2, 1)
        scale_x = available_w / track_w
        scale_y = available_h / track_h
        return min(scale_x, scale_y)

    def update_fit_scale(self, viewport_size: QtCore.QSize) -> None:
        fit = self.calculate_fit_scale(viewport_size)
        self.fit_scale = fit
        if fit is not None and not self.user_transform_active:
            self.current_scale = fit
            if self.view_center is None:
                self.view_center = self._default_center()
            self.invalidate_cache()

    def current_transform(self, viewport_size: QtCore.QSize) -> Transform | None:
        bounds = self._model_bounds()
        if not bounds:
            return None
        if self.current_scale is None:
            self.update_fit_scale(viewport_size)
        if self.current_scale is None:
            return None
        center = self.view_center or self._default_center()
        if center is None:
            return None
        w, h = viewport_size.width(), viewport_size.height()
        offsets = (
            w / 2 - center[0] * self.current_scale,
            h / 2 - center[1] * self.current_scale,
        )
        return self.current_scale, offsets

    def map_to_track(
        self, point: QtCore.QPointF, viewport_size: QtCore.QSize
    ) -> Tuple[float, float] | None:
        transform = self.current_transform(viewport_size)
        if not transform:
            return None
        scale, offsets = transform
        x = (point.x() - offsets[0]) / scale
        py = viewport_size.height() - point.y()
        y = (py - offsets[1]) / scale
        return x, y

    def clamp_scale(self, scale: float) -> float:
        base = self.fit_scale or self.current_scale or 1.0
        min_scale = base * 0.1
        max_scale = base * 25.0
        return max(min_scale, min(max_scale, scale))

    def set_view_center(self, center: tuple[float, float] | None) -> None:
        if center == self.view_center:
            return
        self.view_center = center
        self.invalidate_cache()

    def set_current_scale(self, scale: float | None) -> None:
        if scale == self.current_scale:
            return
        self.current_scale = scale
        self.invalidate_cache()

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def render(
        self,
        painter: QtGui.QPainter,
        viewport_size: QtCore.QSize,
        *,
        background_color: QtGui.QColor,
        data: PreviewRenderData,
        config: PreviewRenderConfig,
        hud: HudInfo,
    ) -> None:
        painter.fillRect(QtCore.QRectF(QtCore.QPointF(0, 0), viewport_size), background_color)

        if not data.surface_mesh or not data.bounds:
            painter.setPen(QtGui.QPen(QtGui.QColor("lightgray")))
            painter.drawText(
                QtCore.QRectF(QtCore.QPointF(0, 0), viewport_size),
                QtCore.Qt.AlignCenter,
                hud.status_message,
            )
            return

        transform = self.current_transform(viewport_size)
        if self._cached_surface_pixmap is None or self._pixmap_size != viewport_size:
            self._cached_surface_pixmap = rendering.render_surface_to_pixmap(
                data.surface_mesh, transform, viewport_size
            )
            self._pixmap_size = viewport_size

        painter.drawPixmap(0, 0, self._cached_surface_pixmap)

        if transform and config.show_boundaries:
            rendering.draw_track_boundaries(
                painter, data.boundary_edges, transform, viewport_size.height()
            )

        if config.show_center_line and data.sampled_centerline and transform:
            rendering.draw_centerline(
                painter, data.sampled_centerline, transform, viewport_size.height()
            )

        if transform and config.show_center_line:
            rendering.draw_start_finish_line(
                painter,
                transform,
                viewport_size.height(),
                data.centerline_point_and_normal,
            )

        if transform and config.show_center_line:
            rendering.draw_camera_range_markers(
                painter,
                data.camera_ranges,
                transform,
                viewport_size.height(),
                data.centerline_point_and_normal,
            )

        if transform and data.highlight_point:
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            highlight = rendering.map_point(
                data.highlight_point[0],
                data.highlight_point[1],
                transform,
                viewport_size.height(),
            )
            pen = QtGui.QPen(QtGui.QColor("#ff5252"))
            pen.setWidth(2)
            painter.setPen(pen)
            painter.setBrush(QtGui.QBrush(QtGui.QColor("#ff5252")))
            painter.drawEllipse(highlight, 5, 5)

        if transform:
            if config.show_cameras:
                rendering.draw_camera_positions(
                    painter,
                    data.cameras,
                    config.selected_camera,
                    transform,
                    viewport_size.height(),
                )
            rendering.draw_ai_lines(
                painter,
                data.visible_lp_files,
                data.get_ai_line_points,
                transform,
                viewport_size.height(),
                data.lp_color,
                gradient=config.ai_color_mode,
                get_records=data.get_ai_line_records,
                line_width=config.ai_line_width,
                acceleration_window=config.ai_acceleration_window,
            )
            rendering.draw_flags(
                painter,
                data.flags,
                config.selected_flag,
                transform,
                viewport_size.height(),
            )
            if config.show_zoom_points:
                rendering.draw_zoom_points(
                    painter,
                    data.zoom_points,
                    transform,
                    viewport_size.height(),
                    data.centerline_point,
                )

        self._draw_overlay_text(painter, viewport_size, hud)

    def _draw_overlay_text(
        self, painter: QtGui.QPainter, viewport_size: QtCore.QSize, hud: HudInfo
    ) -> None:
        painter.setPen(QtGui.QPen(QtGui.QColor("white")))
        y = 20
        if hud.track_length is not None:
            track_length_text = f"Track length: {int(round(hud.track_length))} DLONG"
            painter.drawText(12, y, track_length_text)
            y += 16
        painter.drawText(12, y, hud.status_message)
        y += 16

        projection = hud.projection
        if projection.line_name:
            line_label = (
                "Center line"
                if projection.line_name == "center-line"
                else f"{projection.line_name} line"
            )
            painter.drawText(12, y, line_label)
            y += 16
        if projection.dlong is not None:
            dlong_text = f"DLONG: {int(round(projection.dlong))}"
            painter.drawText(12, y, dlong_text)
            y += 16
        if projection.dlat is not None:
            dlat_text = f"DLAT: {int(round(projection.dlat))}"
            painter.drawText(12, y, dlat_text)
            y += 16
        if projection.speed is not None:
            speed_text = f"Speed: {projection.speed:.1f} mph"
            painter.drawText(12, y, speed_text)
            y += 16
        if projection.acceleration is not None:
            accel_text = f"Accel: {projection.acceleration:+.3f} ft/s²"
            painter.drawText(12, y, accel_text)
            y += 16
        if projection.elevation is not None:
            elevation_text = (
                f"Elevation: {projection.elevation:.2f} (DLAT = 0)"
            )
            painter.drawText(12, y, elevation_text)

        if hud.cursor_position is None:
            return

        metrics = painter.fontMetrics()
        line_height = metrics.height()
        margin = 12
        cursor_lines = [
            f"Cursor X: {hud.cursor_position[0]:.2f}",
            f"Cursor Y: {hud.cursor_position[1]:.2f}",
        ]
        max_width = max(metrics.horizontalAdvance(line) for line in cursor_lines)
        start_x = viewport_size.width() - margin - max_width
        start_y = margin + metrics.ascent()

        for line in cursor_lines:
            painter.drawText(start_x, start_y, line)
            start_y += line_height
