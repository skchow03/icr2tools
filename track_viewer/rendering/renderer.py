"""Rendering helpers for the track preview widget.

This module belongs to the rendering layer. It converts model/view-state data
into draw calls on a QPainter without mutating the model or performing IO.
All geometry is in world coordinates until mapped to screen space.
"""
from __future__ import annotations

from PyQt5 import QtCore, QtGui

from track_viewer.model.lp_editing_session import LPEditingSession
from track_viewer.model.track_preview_model import TrackPreviewModel
from track_viewer.model.view_state import TrackPreviewViewState
from track_viewer.rendering.base.centerline_renderer import CenterlineRenderer
from track_viewer.rendering.base.surface_renderer import SurfaceRenderer
from track_viewer.rendering.overlays.ai_line_overlay import AiLineOverlay
from track_viewer.rendering.overlays.camera_overlay import CameraOverlay
from track_viewer.rendering.overlays.flag_overlay import FlagOverlay
from track_viewer.rendering.overlays.pit_overlay import PitOverlay
from track_viewer.rendering.overlays.selection_overlay import SelectionOverlay
from track_viewer.rendering.overlays.ui_overlay import UiOverlay
from track_viewer.rendering.overlays.weather_compass_overlay import (
    WeatherCompassOverlay,
)
from track_viewer.services.camera_service import CameraService


class TrackPreviewRenderer:
    """Render track preview geometry using model data and view state."""

    def __init__(
        self,
        model: TrackPreviewModel,
        camera_service: CameraService,
        state: TrackPreviewViewState,
        lp_session: LPEditingSession,
    ) -> None:
        self._model = model
        self._state = state
        self._surface_renderer = SurfaceRenderer()
        self._centerline_renderer = CenterlineRenderer()
        self._camera_overlay = CameraOverlay(camera_service, self._centerline_renderer)
        self._ai_line_overlay = AiLineOverlay()
        self._pit_overlay = PitOverlay()
        self._flag_overlay = FlagOverlay()
        self._selection_overlay = SelectionOverlay(lp_session)
        self._ui_overlay = UiOverlay(lp_session, self._centerline_renderer)
        self._weather_compass_overlay = WeatherCompassOverlay()

    def paint(self, painter: QtGui.QPainter, size: QtCore.QSize) -> None:
        """Draw the preview in painter order (surface → overlays → UI)."""
        if not self._model.bounds:
            painter.setPen(QtGui.QPen(QtGui.QColor("lightgray")))
            painter.drawText(
                painter.viewport(), QtCore.Qt.AlignCenter, self._state.status_message
            )
            self._weather_compass_overlay.draw(
                painter, self._model, self._state, (1.0, (0.0, 0.0)), size.height()
            )
            return

        transform = self._state.current_transform(self._model.bounds, size)
        if not transform:
            return

        height = size.height()
        self._surface_renderer.draw(
            painter, self._model, self._state, transform, height
        )
        self._centerline_renderer.draw(
            painter, self._model, self._state, transform, height
        )
        self._centerline_renderer.draw_start_finish(
            painter, self._model, transform, height
        )
        self._camera_overlay.draw_ranges(
            painter, self._model, self._state, transform, height
        )
        self._selection_overlay.draw_projection_point(
            painter, self._state, transform, height
        )
        self._camera_overlay.draw_cameras(painter, self._state, transform, height)
        self._ai_line_overlay.draw(
            painter, self._model, self._state, transform, height
        )
        self._selection_overlay.draw_selected_lp_segment(
            painter, self._model, self._state, transform, height
        )
        self._flag_overlay.draw(painter, self._model, self._state, transform, height)
        self._pit_overlay.draw(painter, self._model, self._state, transform, height)
        self._camera_overlay.draw_zoom_points(
            painter, self._model, self._state, transform, height
        )

        self._ui_overlay.draw_lp_shortcut_overlay(painter, size)
        self._ui_overlay.draw_status(painter, self._model, self._state)
        self._ui_overlay.draw_camera_guidance(painter, self._state, size)
        self._ui_overlay.draw_cursor_position(painter, self._state, size)
        self._weather_compass_overlay.draw(
            painter, self._model, self._state, transform, height
        )

    def invalidate_surface_cache(self) -> None:
        """Drop cached geometry derived from the current track."""
        self._surface_renderer.invalidate_cache()
        self._centerline_renderer.invalidate_cache()
        self._ai_line_overlay.invalidate_cache()
