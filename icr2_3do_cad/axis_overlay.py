"""Mouse-transparent CAD orientation overlay, composited by Qt.

QPainter is intentionally *outside* paintGL: the application's existing
GL/QPainter glyph issue is avoided, while vertex picking, screenshots from
the GL framebuffer, and exported assets remain unmodified.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QBrush
from PySide6.QtWidgets import QWidget

from axis_guides import (
    AXIS_COLORS, guide_anchor, orientation_axes, projected_axis_guides,
)


class AxisGuideOverlay(QWidget):
    def __init__(self, viewport):
        super().__init__(viewport)
        self.viewport = viewport
        self.setObjectName("cadAxisGuideOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAutoFillBackground(False)
        self.show()

    def paintEvent(self, event):
        viewport = self.viewport
        if not (viewport.axis_guides_enabled or
                viewport.orientation_gizmo_enabled):
            return
        # Same view as OpenGL model/picking, including track banking and
        # fixed-camera orientation. Never mutate the viewport camera.
        projection, view = viewport._projection_and_view()
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            if viewport.axis_guides_enabled and viewport._mesh is not None:
                self._paint_guides(painter, projection, view)
            if viewport.orientation_gizmo_enabled:
                self._paint_gizmo(painter, view)
        finally:
            painter.end()

    def _paint_guides(self, painter, projection, view):
        v = self.viewport
        try:
            anchor = guide_anchor(
                v.axis_guide_anchor, view, v.distance,
                v._mesh.center, v._mesh.scale)
            # The lines exceed the zoomed view by a large factor, then clip
            # cleanly at the 3D frustum, including in perspective mode.
            span = max(v.distance, v.half_height, 1.) * 32.
            guides = projected_axis_guides(
                projection, view, anchor, span, self.width(), self.height())
        except (ValueError, OverflowError, FloatingPointError):
            return

        # Negative directions: faint dashed guides. Positive XYZ directions:
        # more prominent solid strokes, with directional labels.
        for label, halves in guides.items():
            color = QColor(AXIS_COLORS[label])
            negative = halves["negative"]
            positive = halves["positive"]
            if negative is not None:
                faded = QColor(color)
                faded.setAlpha(100)
                pen = QPen(faded, 1.6, Qt.PenStyle.DashLine)
                pen.setDashPattern((5., 5.))
                painter.setPen(pen)
                painter.drawLine(QPointF(*negative[0]), QPointF(*negative[1]))
            if positive is not None:
                solid = QColor(color)
                solid.setAlpha(185)
                painter.setPen(QPen(
                    solid, 2.3, Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap))
                painter.drawLine(QPointF(*positive[0]), QPointF(*positive[1]))
                ax, ay = positive[0]
                bx, by = positive[1]
                dx, dy = bx-ax, by-ay
                length = math.hypot(dx, dy)
                if length > 27.:
                    # Put labels near the camera's view focus, never in the
                    # screen-edge margin where they would be cut off.
                    fraction = min(.84, 84. / length)
                    tx = ax + dx * fraction
                    ty = ay + dy * fraction
                    if (12 < tx < self.width()-12 and
                            12 < ty < self.height()-12):
                        self._axis_label(painter, label, tx+5, ty-5, color)

    @staticmethod
    def _axis_label(painter, label, x, y, color):
        font = QFont("Sans Serif", 10)
        font.setBold(True)
        painter.setFont(font)
        painter.setPen(QPen(QColor(8, 11, 17, 235), 3))
        # Use a short dark backing for contrast over textured geometry.
        painter.drawText(QPointF(x+1, y+1), label)
        painter.setPen(color)
        painter.drawText(QPointF(x, y), label)

    def _paint_gizmo(self, painter, view):
        cx, cy = 69., float(self.height()) - 72.
        painter.setPen(QPen(QColor(151, 163, 184, 145), 1))
        painter.setBrush(QBrush(QColor(16, 23, 35, 220)))
        painter.drawEllipse(QPointF(cx, cy), 59., 59.)
        painter.setFont(QFont("Sans Serif", 8))
        painter.setPen(QColor("#b5bfca"))
        painter.drawText(QPointF(cx-10., cy-40.), "XYZ")

        axes = orientation_axes(view, center=(cx, cy), radius=34.)
        # Back-facing axes first, foreground axes last; the triad responds
        # to camera orbit, canonical Front/Side/Top and track banking.
        for label in sorted("XYZ", key=lambda a: axes[a][2]):
            x, y, _ = axes[label]
            color = QColor(AXIS_COLORS[label])
            painter.setPen(QPen(
                color, 2.8, Qt.PenStyle.SolidLine,
                Qt.PenCapStyle.RoundCap))
            dx, dy = x-cx, y-cy
            distance = math.hypot(dx, dy)
            if distance >= 7.:
                painter.drawLine(QPointF(cx, cy), QPointF(x, y))
                painter.setBrush(color)
                painter.drawEllipse(QPointF(x, y), 3.5, 3.5)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                off_x = 6. if dx >= 0 else -15.
                off_y = -6. if dy <= 0 else 14.
                self._axis_label(painter, label, x+off_x, y+off_y, color)
            else:
                # Axis points nearly along the camera: circle/dot conveys
                # end-on direction rather than silently disappearing.
                painter.setBrush(color)
                painter.drawEllipse(QPointF(cx, cy), 5., 5.)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                self._axis_label(painter, label, cx+7., cy-10., color)
        painter.setBrush(QBrush(QColor(240, 244, 250)))
        painter.setPen(QPen(QColor(10, 15, 25), 1))
        painter.drawEllipse(QPointF(cx, cy), 3., 3.)
