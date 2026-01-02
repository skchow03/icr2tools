"""Flag editing logic for the track preview widget."""
from __future__ import annotations

from PyQt5 import QtCore

from track_viewer.model.track_preview_model import TrackPreviewModel
from track_viewer.model.view_state import TrackPreviewViewState
from track_viewer.widget.interaction import InteractionCallbacks
from track_viewer.widget.selection.selection_controller import SelectionController


class FlagEditController:
    """Handles adding, dragging, and removing flags."""

    def __init__(
        self,
        model: TrackPreviewModel,
        state: TrackPreviewViewState,
        selection: SelectionController,
        callbacks: InteractionCallbacks,
    ) -> None:
        self._model = model
        self._state = state
        self._selection = selection
        self._callbacks = callbacks

    def handle_flag_press(self, point: QtCore.QPointF, size: QtCore.QSize) -> bool:
        flag_index = self._selection.flag_at_point(point, size)
        if flag_index is None:
            return False
        self._state.dragging_flag_index = flag_index
        self._state.is_panning = False
        self._state.dragged_during_press = False
        self._selection.set_selected_flag(flag_index)
        return True

    def update_flag_position(self, point: QtCore.QPointF, size: QtCore.QSize) -> None:
        if self._state.dragging_flag_index is None:
            return
        coords = self._state.map_to_track(point, self._model.bounds, size)
        if coords is None:
            return
        index = self._state.dragging_flag_index
        if index < 0 or index >= len(self._state.flags):
            return
        self._state.flags[index] = coords
        self._callbacks.selected_flag_changed(coords)
        self._callbacks.update()

    def end_flag_drag(self) -> None:
        self._state.dragging_flag_index = None

    def remove_flag_at_point(self, point: QtCore.QPointF, size: QtCore.QSize) -> bool:
        flag_index = self._selection.flag_at_point(point, size)
        if flag_index is None:
            return False
        del self._state.flags[flag_index]
        if self._state.selected_flag is not None:
            if self._state.selected_flag == flag_index:
                self._selection.set_selected_flag(None)
                return True
            if self._state.selected_flag > flag_index:
                self._selection.set_selected_flag(self._state.selected_flag - 1)
                return True
        self._callbacks.update()
        return True

    def add_flag(self, coords: tuple[float, float]) -> None:
        self._state.flags.append(coords)
        self._selection.set_selected_flag(len(self._state.flags) - 1)
