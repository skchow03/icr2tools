"""Camera editing logic for the track preview widget."""
from __future__ import annotations

from PyQt5 import QtCore

from track_viewer.model.track_preview_model import TrackPreviewModel
from track_viewer.model.view_state import TrackPreviewViewState
from track_viewer.widget.interaction import InteractionCallbacks, PreviewIntent
from track_viewer.widget.selection.selection_controller import SelectionController


class CameraEditController:
    """Handles camera drag and creation operations."""

    def __init__(
        self,
        model: TrackPreviewModel,
        camera_service,
        state: TrackPreviewViewState,
        selection: SelectionController,
        callbacks: InteractionCallbacks,
    ) -> None:
        self._model = model
        self._camera_service = camera_service
        self._state = state
        self._selection = selection
        self._callbacks = callbacks

    def handle_camera_press(self, point: QtCore.QPointF, size: QtCore.QSize) -> bool:
        if not self._state.camera_selection_enabled:
            return False
        camera_index = self._selection.camera_at_point(point, size)
        if camera_index is None:
            return False
        if camera_index != self._state.selected_camera:
            self._selection.set_selected_camera(camera_index)
            return True
        coords = self._state.map_to_track(point, self._model.bounds, size)
        if coords is None:
            return False
        if camera_index < 0 or camera_index >= len(self._camera_service.cameras):
            return False
        cam = self._camera_service.cameras[camera_index]
        self._state.dragging_camera_index = camera_index
        self._state.camera_dragged = False
        self._state.camera_drag_offset = (cam.x - coords[0], cam.y - coords[1])
        self._state.is_panning = False
        self._state.dragged_during_press = False
        self._selection.emit_selected_camera()
        return True

    def select_camera_at_point(self, point: QtCore.QPointF, size: QtCore.QSize) -> bool:
        if not self._state.camera_selection_enabled:
            return False
        camera_index = self._selection.camera_at_point(point, size)
        if camera_index is None:
            return False
        if camera_index == self._state.selected_camera:
            self._selection.emit_selected_camera()
        else:
            self._selection.set_selected_camera(camera_index)
        return True

    def update_camera_position(self, point: QtCore.QPointF, size: QtCore.QSize) -> None:
        if self._state.dragging_camera_index is None:
            return
        coords = self._state.map_to_track(point, self._model.bounds, size)
        if coords is None:
            return
        index = self._state.dragging_camera_index
        if index < 0 or index >= len(self._camera_service.cameras):
            return
        cam = self._camera_service.cameras[index]
        offset = self._state.camera_drag_offset or (0.0, 0.0)
        new_x = int(round(coords[0] + offset[0]))
        new_y = int(round(coords[1] + offset[1]))
        if new_x == cam.x and new_y == cam.y:
            return
        cam.x = new_x
        cam.y = new_y
        self._state.camera_dragged = True
        self._selection.emit_selected_camera()
        self._callbacks.state_changed(PreviewIntent.CAMERA_CHANGED)

    def end_camera_drag(self) -> None:
        self._state.dragging_camera_index = None
        self._state.camera_dragged = False
        self._state.camera_drag_offset = None

    def add_type6_camera(self) -> tuple[bool, str, int | None]:
        return self._camera_service.add_type6_camera(
            self._state.selected_camera, self._model.track_length
        )

    def add_type7_camera(self) -> tuple[bool, str, int | None]:
        return self._camera_service.add_type7_camera(
            self._state.selected_camera, self._model.track_length
        )
