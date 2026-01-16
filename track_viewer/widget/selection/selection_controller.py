"""Selection and hit-testing logic for the track preview widget."""
from __future__ import annotations

import math

from PyQt5 import QtCore

from track_viewer import rendering
from track_viewer.model.track_preview_model import TrackPreviewModel
from track_viewer.model.view_state import TrackPreviewViewState
from track_viewer.widget.interaction import InteractionCallbacks, PreviewIntent


class SelectionController:
    """Handles hit-testing and selection updates."""

    def __init__(
        self,
        model: TrackPreviewModel,
        camera_service,
        state: TrackPreviewViewState,
        callbacks: InteractionCallbacks,
    ) -> None:
        self._model = model
        self._camera_service = camera_service
        self._state = state
        self._callbacks = callbacks

    def emit_selected_camera(self) -> None:
        selected = None
        index = self._state.selected_camera
        if index is not None and 0 <= index < len(self._camera_service.cameras):
            selected = self._camera_service.cameras[index]
        self._callbacks.selected_camera_changed(index, selected)

    def set_selected_camera(self, index: int | None) -> None:
        if index is not None and (index < 0 or index >= len(self._camera_service.cameras)):
            index = None
        if index == self._state.selected_camera:
            return
        self._state.selected_camera = index
        self.emit_selected_camera()
        self._callbacks.state_changed(PreviewIntent.SELECTION_CHANGED)

    def set_selected_flag(self, index: int | None) -> None:
        if index is not None and (index < 0 or index >= len(self._state.flags)):
            index = None
        if index == self._state.selected_flag:
            return
        self._state.selected_flag = index
        coords = None
        if index is not None and 0 <= index < len(self._state.flags):
            coords = self._state.flags[index]
        self._callbacks.selected_flag_changed(coords)
        self._callbacks.state_changed(PreviewIntent.SELECTION_CHANGED)


    def camera_at_point(self, point: QtCore.QPointF, size: QtCore.QSize) -> int | None:
        transform = self._state.current_transform(self._model.bounds, size)
        if not transform:
            return None
        hit_radius = 16.0
        allowed_indices = None
        if self._state.show_cameras_current_tv_only:
            allowed_indices = self._camera_service.camera_indices_for_view(
                self._state.current_tv_mode_index
            )
        for index, cam in enumerate(self._camera_service.cameras):
            if allowed_indices is not None and index not in allowed_indices:
                continue
            camera_point = rendering.map_point(cam.x, cam.y, transform, size.height())
            if (
                math.hypot(
                    camera_point.x() - point.x(),
                    camera_point.y() - point.y(),
                )
                <= hit_radius
            ):
                return index
        return None

    def flag_at_point(self, point: QtCore.QPointF, size: QtCore.QSize) -> int | None:
        transform = self._state.current_transform(self._model.bounds, size)
        if not transform:
            return None
        for index, (fx, fy) in enumerate(self._state.flags):
            flag_point = rendering.map_point(fx, fy, transform, size.height())
            if (flag_point - point).manhattanLength() <= 8:
                return index
        return None
