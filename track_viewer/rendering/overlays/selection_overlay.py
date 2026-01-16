"""Selection overlays for track preview."""
from __future__ import annotations

from PyQt5 import QtGui

from track_viewer.model.lp_editing_session import LPEditingSession
from track_viewer.model.track_preview_model import TrackPreviewModel
from track_viewer.model.view_state import TrackPreviewViewState
from track_viewer.rendering import draw_lp_segment, map_point
from track_viewer.rendering.primitives.mapping import Transform


class SelectionOverlay:
    """Render selection highlights such as LP segments and projection points."""

    def __init__(self, lp_session: LPEditingSession) -> None:
        self._lp_session = lp_session

    def draw(
        self,
        painter: QtGui.QPainter,
        model: TrackPreviewModel,
        state: TrackPreviewViewState,
        transform: Transform,
        viewport_height: int,
    ) -> None:
        self.draw_projection_point(painter, state, transform, viewport_height)
        self.draw_selected_lp_segment(
            painter, model, state, transform, viewport_height
        )

    def draw_projection_point(
        self,
        painter: QtGui.QPainter,
        state: TrackPreviewViewState,
        transform: Transform,
        viewport_height: int,
    ) -> None:
        if not state.nearest_projection_point:
            return
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        highlight = map_point(
            state.nearest_projection_point[0],
            state.nearest_projection_point[1],
            transform,
            viewport_height,
        )
        pen = QtGui.QPen(QtGui.QColor("#ff5252"))
        pen.setWidth(2)
        painter.setPen(pen)
        painter.setBrush(QtGui.QBrush(QtGui.QColor("#ff5252")))
        painter.drawEllipse(highlight, 5, 5)

    def draw_selected_lp_segment(
        self,
        painter: QtGui.QPainter,
        model: TrackPreviewModel,
        state: TrackPreviewViewState,
        transform: Transform,
        viewport_height: int,
    ) -> None:
        """Highlight the selected LP record and its adjacent segment."""
        selected_line = self._lp_session.selected_lp_line
        selected_index = self._lp_session.selected_lp_index
        if (
            not selected_line
            or selected_index is None
            or selected_line not in model.visible_lp_files
        ):
            return
        records = model.ai_line_records(selected_line)
        if len(records) < 2:
            return
        index = selected_index
        if 0 <= index < len(records):
            record = records[index]
            painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
            marker = map_point(record.x, record.y, transform, viewport_height)
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
            draw_lp_segment(
                painter,
                (start_record.x, start_record.y),
                (end_record.x, end_record.y),
                transform,
                viewport_height,
            )
