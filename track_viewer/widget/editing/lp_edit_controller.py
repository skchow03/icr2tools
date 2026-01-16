"""LP editing logic for the track preview widget."""
from __future__ import annotations

from PyQt5 import QtCore

from track_viewer.model.lp_editing_session import LPChange, LPEditingSession
from track_viewer.model.track_preview_model import TrackPreviewModel
from track_viewer.model.view_state import TrackPreviewViewState
from track_viewer.widget.interaction import InteractionCallbacks, PreviewIntent


class LpEditController:
    """Handles LP record selection."""

    def __init__(
        self,
        model: TrackPreviewModel,
        state: TrackPreviewViewState,
        session: LPEditingSession,
        callbacks: InteractionCallbacks,
    ) -> None:
        self._model = model
        self._state = state
        self._session = session
        self._callbacks = callbacks

    def select_lp_record_at_point(
        self, point: QtCore.QPointF, size: QtCore.QSize
    ) -> bool:
        transform = self._state.current_transform(self._model.bounds, size)
        cursor_track = self._state.map_to_track(point, self._model.bounds, size)
        changes, selection = self._session.select_record_at_point(
            (point.x(), point.y()),
            cursor_track=cursor_track,
            transform=transform,
            viewport_height=size.height(),
        )
        if not changes:
            return False
        if selection is not None:
            self._callbacks.lp_record_selected(selection[0], selection[1])
        self._emit_changes(changes)
        return True

    def _emit_changes(self, changes: set[LPChange]) -> None:
        if LPChange.SELECTION in changes:
            self._callbacks.state_changed(PreviewIntent.SELECTION_CHANGED)
        if changes & {LPChange.DATA, LPChange.VISIBILITY}:
            self._callbacks.state_changed(PreviewIntent.OVERLAY_CHANGED)
