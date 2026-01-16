"""UI overlays for the track preview (text, guidance, cursor)."""
from __future__ import annotations

from PyQt5 import QtCore, QtGui

from track_viewer.model.lp_editing_session import LPEditingSession
from track_viewer.model.track_preview_model import TrackPreviewModel
from track_viewer.model.view_state import TrackPreviewViewState
from track_viewer.rendering.base.centerline_renderer import CenterlineRenderer


class UiOverlay:
    """Render screen-space UI overlays for the track preview."""

    def __init__(
        self, lp_session: LPEditingSession, centerline_renderer: CenterlineRenderer
    ) -> None:
        self._lp_session = lp_session
        self._centerline_renderer = centerline_renderer

    def draw_status(
        self,
        painter: QtGui.QPainter,
        model: TrackPreviewModel,
        state: TrackPreviewViewState,
    ) -> None:
        """Render textual status in the upper-left corner."""
        painter.setPen(QtGui.QPen(QtGui.QColor("white")))
        y = 20
        if model.track_length is not None:
            track_length_text = (
                f"Track length: {int(round(model.track_length))} DLONG"
            )
            painter.drawText(12, y, track_length_text)
            y += 16
        painter.drawText(12, y, state.status_message)
        y += 16
        if state.nearest_projection_line:
            if state.nearest_projection_line == "center-line":
                line_label = "Center line"
            elif state.nearest_projection_line == "replay-lap":
                if model.replay_lap_label:
                    line_label = f"Replay lap ({model.replay_lap_label})"
                else:
                    line_label = "Replay lap"
            else:
                line_label = f"{state.nearest_projection_line} line"
            painter.drawText(12, y, line_label)
            y += 16
        if state.nearest_projection_dlong is not None:
            dlong_text = f"DLONG: {int(round(state.nearest_projection_dlong))}"
            painter.drawText(12, y, dlong_text)
            y += 16
        if (
            state.nearest_projection_line == "center-line"
            and state.nearest_projection_dlong is not None
        ):
            for line in self._centerline_renderer.centerline_section_info(
                model, state, state.nearest_projection_dlong
            ):
                painter.drawText(12, y, line)
                y += 16
        if state.nearest_projection_dlat is not None:
            dlat_text = f"DLAT: {int(round(state.nearest_projection_dlat))}"
            painter.drawText(12, y, dlat_text)
            y += 16
        if state.nearest_projection_speed is not None:
            speed_text = f"Speed: {state.nearest_projection_speed:.1f} mph"
            painter.drawText(12, y, speed_text)
            y += 16
        if state.nearest_projection_acceleration is not None:
            accel_text = (
                f"Accel: {state.nearest_projection_acceleration:+.3f} ft/s²"
            )
            painter.drawText(12, y, accel_text)
            y += 16
        if state.nearest_projection_elevation is not None:
            elevation_text = (
                f"Elevation: {state.nearest_projection_elevation:.2f} (DLAT = 0)"
            )
            painter.drawText(12, y, elevation_text)

    def draw_camera_guidance(
        self, painter: QtGui.QPainter, state: TrackPreviewViewState, size: QtCore.QSize
    ) -> None:
        if not state.show_camera_guidance:
            return

        lines = [
            "LEFT-CLICK to select camera",
            "RIGHT-CLICK and drag to move selected camera",
        ]
        metrics = painter.fontMetrics()
        line_height = metrics.height()
        margin = 12
        max_width = max(metrics.horizontalAdvance(line) for line in lines)
        start_x = size.width() - margin - max_width
        start_y = margin + metrics.ascent()

        painter.setPen(QtGui.QPen(QtGui.QColor("white")))
        for line in lines:
            painter.drawText(start_x, start_y, line)
            start_y += line_height

    def draw_cursor_position(
        self, painter: QtGui.QPainter, state: TrackPreviewViewState, size: QtCore.QSize
    ) -> None:
        if state.cursor_position is None:
            return

        x, y = state.cursor_position
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

    def draw_lp_shortcut_overlay(
        self, painter: QtGui.QPainter, size: QtCore.QSize
    ) -> None:
        if not self._lp_session.lp_shortcut_active:
            return
        self._draw_lp_editing_banner(painter, size)
        metrics = painter.fontMetrics()
        line_height = metrics.height()
        margin = 12
        step_value = self._lp_session.lp_dlat_step
        lp_index_text = (
            "LP index: —"
            if self._lp_session.selected_lp_index is None
            else f"LP index: {self._lp_session.selected_lp_index}"
        )
        lines = [
            "LP arrow-key editing active:",
            "UP - next LP record",
            "DOWN - previous LP record",
            "D - next LP record",
            "A - previous LP record",
            "PGUP - copy to next LP record",
            "PGDN - copy to previous LP record",
            f"LEFT - increase DLAT by {step_value}",
            f"RIGHT - decrease DLAT by {step_value}",
            "W - increase speed by 1 mph",
            "S - decrease speed by 1 mph",
            lp_index_text,
        ]
        max_width = max(metrics.horizontalAdvance(line) for line in lines)
        start_x = size.width() - margin - max_width
        start_y = margin + metrics.ascent()
        painter.setPen(QtGui.QPen(QtGui.QColor("white")))
        for line in lines:
            painter.drawText(start_x, start_y, line)
            start_y += line_height

    def _draw_lp_editing_banner(
        self, painter: QtGui.QPainter, size: QtCore.QSize
    ) -> None:
        if not self._lp_session.lp_editing_tab_active:
            return
        lp_name = self._lp_session.active_lp_line
        if not lp_name or lp_name == "center-line":
            return
        painter.save()
        font = painter.font()
        font.setBold(True)
        font.setPointSize(max(font.pointSize() + 4, 14))
        painter.setFont(font)
        painter.setPen(QtGui.QPen(QtGui.QColor("#ffeb3b")))
        metrics = painter.fontMetrics()
        height = metrics.height()
        margin = 10
        banner_rect = QtCore.QRect(0, margin, size.width(), height + 4)
        painter.drawText(
            banner_rect,
            QtCore.Qt.AlignHCenter | QtCore.Qt.AlignTop,
            f"LP editing mode - {lp_name}",
        )
        painter.restore()
