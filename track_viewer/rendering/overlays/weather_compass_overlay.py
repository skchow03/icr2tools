"""Weather compass overlay rendering."""
from __future__ import annotations

from PyQt5 import QtCore, QtGui

from track_viewer.common.weather_compass import (
    heading_adjust_to_turns,
    turns_to_unit_vector,
    wind_variation_to_turns,
)
from track_viewer.model.track_preview_model import TrackPreviewModel
from track_viewer.model.view_state import TrackPreviewViewState
from track_viewer.rendering.primitives.mapping import Transform


class WeatherCompassOverlay:
    """Render the wind direction compass indicator."""

    def draw(
        self,
        painter: QtGui.QPainter,
        model: TrackPreviewModel,
        state: TrackPreviewViewState,
        transform: Transform,
        viewport_height: int,
    ) -> None:
        if not state.show_weather_compass:
            return
        size = painter.viewport().size()
        center = state.weather_compass_center(size)
        radius = state.weather_compass_radius(size)
        turns = state.weather_compass_turns()
        heading_adjust = (
            state.wind2_heading_adjust
            if state.weather_compass_source == "wind2"
            else state.wind_heading_adjust
        )
        heading_turns = (
            heading_adjust_to_turns(heading_adjust)
            if heading_adjust is not None
            else None
        )
        dx, dy = turns_to_unit_vector(turns)
        tip = QtCore.QPointF(center.x() + dx * radius, center.y() + dy * radius)
        handle_radius = state.weather_compass_handle_radius(size)
        painter.save()
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        outline_pen = QtGui.QPen(QtGui.QColor("#7f8c8d"))
        outline_pen.setWidth(1)
        line_color = QtGui.QColor("#7fe7f2")
        line_pen = QtGui.QPen(line_color)
        line_pen.setWidth(2)
        painter.setPen(line_pen)
        painter.drawLine(center, tip)
        painter.setBrush(line_color)
        painter.drawEllipse(tip, handle_radius, handle_radius)
        painter.setPen(outline_pen)
        painter.setBrush(QtCore.Qt.NoBrush)
        painter.drawEllipse(center, radius, radius)
        if heading_turns is not None:
            heading_dx, heading_dy = turns_to_unit_vector(heading_turns)
            heading_tip = QtCore.QPointF(
                center.x() + heading_dx * radius,
                center.y() + heading_dy * radius,
            )
            heading_color = QtGui.QColor("#44d468")
            heading_pen = QtGui.QPen(heading_color)
            heading_pen.setWidth(2)
            painter.setPen(heading_pen)
            painter.drawLine(center, heading_tip)
            painter.setBrush(heading_color)
            painter.drawEllipse(heading_tip, handle_radius * 0.85, handle_radius * 0.85)
        variation = state.weather_compass_variation()
        if variation:
            delta_turns = wind_variation_to_turns(variation)
            dashed_pen = QtGui.QPen(line_color)
            dashed_pen.setWidth(1)
            dashed_pen.setStyle(QtCore.Qt.DashLine)
            painter.setPen(dashed_pen)
            for offset in (-delta_turns, delta_turns):
                offset_turns = (turns + offset) % 1.0
                vx, vy = turns_to_unit_vector(offset_turns)
                offset_tip = QtCore.QPointF(
                    center.x() + vx * radius, center.y() + vy * radius
                )
                painter.drawLine(center, offset_tip)
        painter.setPen(line_color)
        label_turns = heading_turns if heading_turns is not None else 0.0
        nx, ny = turns_to_unit_vector(label_turns)
        tangent = QtCore.QPointF(-ny, nx)
        arrow_length = max(6.0, handle_radius * 1.2)
        arrow_width = arrow_length * 0.6
        tip_distance = radius + handle_radius * 0.4
        tip = QtCore.QPointF(
            center.x() + nx * tip_distance,
            center.y() + ny * tip_distance,
        )
        base_distance = tip_distance - arrow_length
        base_center = QtCore.QPointF(
            center.x() + nx * base_distance,
            center.y() + ny * base_distance,
        )
        arrow = QtGui.QPolygonF(
            [
                tip,
                QtCore.QPointF(
                    base_center.x() + tangent.x() * (arrow_width / 2.0),
                    base_center.y() + tangent.y() * (arrow_width / 2.0),
                ),
                QtCore.QPointF(
                    base_center.x() - tangent.x() * (arrow_width / 2.0),
                    base_center.y() - tangent.y() * (arrow_width / 2.0),
                ),
            ]
        )
        painter.setBrush(line_color)
        painter.drawPolygon(arrow)
        painter.setBrush(QtCore.Qt.NoBrush)

        label_font = QtGui.QFont(painter.font())
        label_font.setPixelSize(8)
        label_font.setBold(True)
        painter.setFont(label_font)
        painter.setRenderHint(QtGui.QPainter.TextAntialiasing, True)
        metrics = QtGui.QFontMetrics(label_font)
        label = "N"
        label_width = metrics.horizontalAdvance(label)
        label_offset = handle_radius + metrics.height()
        label_center = QtCore.QPointF(
            center.x() + nx * (radius + label_offset),
            center.y() + ny * (radius + label_offset),
        )
        ascent = metrics.ascent()
        descent = metrics.descent()
        label_pos = QtCore.QPointF(
            round(label_center.x() - label_width / 2),
            round(label_center.y() + (ascent - descent) / 2),
        )
        painter.drawText(label_pos, label)
        painter.restore()
