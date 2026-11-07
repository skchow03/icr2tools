"""Qt-composited, mouse-transparent move gizmo over the CAD OpenGL viewport.

QPainter glyphs are intentionally drawn in a child QWidget, never inside
paintGL, to avoid known Qt/OpenGL glyph corruption on some drivers. Picking
and dragging remain owned by GLViewport; overlay is visual feedback only.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush, QPolygonF
from PySide6.QtWidgets import QWidget

from source_inspection import raw_point_screen_position
from vertex_move import AXIS_COLORS


class VertexMoveOverlay(QWidget):
    def __init__(self, viewport):
        super().__init__(viewport)
        self.viewport = viewport
        self.setObjectName("cadVertexMoveGizmo")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAutoFillBackground(False)
        self.hide()

    def paintEvent(self, event):
        viewport = self.viewport
        handles = viewport._move_handles(preview=True)
        if not handles:
            return
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            painter.setFont(QFont("Sans Serif", 9, QFont.Weight.Bold))
            raw_preview = viewport._move_preview_xyz
            if raw_preview is not None and viewport._mesh is not None:
                start = viewport._move_original_xyz
                projection, view = viewport._projection_and_view()
                original = raw_point_screen_position(
                    viewport._mesh, start, projection @ view,
                    self.width(), self.height())
                drawn = next(iter(handles.values())).center
                if original is not None:
                    painter.setPen(QPen(
                        QColor("#ffeab0"), 2, Qt.PenStyle.DashLine))
                    painter.drawLine(QPointF(*original), QPointF(*drawn))
                    painter.setPen(QPen(QColor("#ffeab0"), 1))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawEllipse(QPointF(*original), 5.5, 5.5)

            # Thick dark outlines keep the handles usable over any palette,
            # wireframe or tracing reference image.
            for axis in ("X", "Y", "Z"):
                h = handles.get(axis)
                if h is None:
                    continue
                color = QColor(AXIS_COLORS[axis])
                emphasized = (viewport._move_active_axis == axis or
                              viewport._move_hover_axis == axis)
                width = 4.6 if emphasized else 3.2
                origin = QPointF(*h.center)
                tip = QPointF(*h.tip)
                painter.setPen(QPen(QColor(10, 15, 24, 235), width+3,
                                    Qt.PenStyle.SolidLine,
                                    Qt.PenCapStyle.RoundCap))
                painter.drawLine(origin, tip)
                painter.setPen(QPen(color, width,
                                    Qt.PenStyle.SolidLine,
                                    Qt.PenCapStyle.RoundCap))
                painter.drawLine(origin, tip)
                ux, uy = h.direction
                side = (-uy, ux)
                arrow = QPolygonF([
                    tip,
                    QPointF(h.tip[0]-ux*13+side[0]*6,
                            h.tip[1]-uy*13+side[1]*6),
                    QPointF(h.tip[0]-ux*13-side[0]*6,
                            h.tip[1]-uy*13-side[1]*6),
                ])
                painter.setPen(QPen(QColor(10, 15, 24), 1.2))
                painter.setBrush(QBrush(color))
                painter.drawPolygon(arrow)
                text_at = QPointF(h.tip[0]+ux*12+4, h.tip[1]+uy*12-2)
                painter.setPen(QPen(QColor(10, 15, 24), 3.4))
                painter.drawText(text_at+QPointF(1, 1), axis)
                painter.setPen(color)
                painter.drawText(text_at, axis)
            center = next(iter(handles.values())).center
            painter.setBrush(QBrush(QColor("#ffe6a0")))
            painter.setPen(QPen(QColor("#131b2b"), 2))
            painter.drawEllipse(QPointF(*center), 5, 5)

            if raw_preview is not None:
                # Tooltip follows the moved point, without a costly 3DO
                # recompile on every mouse-move event.
                label = ("XYZ: " +
                         ", ".join(f"{int(value):,}" for value in raw_preview))
                font = QFont("Consolas", 9)
                painter.setFont(font)
                metrics = painter.fontMetrics()
                x = min(max(8, center[0]+14),
                        max(8, self.width()-metrics.horizontalAdvance(label)-22))
                y = min(max(24, center[1]-35), self.height()-12)
                rect = metrics.boundingRect(label).adjusted(-7,-4,7,4)
                rect.moveTopLeft(QPointF(x,y).toPoint())
                painter.setPen(QPen(QColor("#f5d17d"), 1))
                painter.setBrush(QBrush(QColor(18, 26, 39, 230)))
                painter.drawRoundedRect(rect, 4, 4)
                painter.setPen(QColor("#ffffff"))
                painter.drawText(
                    QPointF(x, y+metrics.ascent()), label)
        finally:
            painter.end()
