"""Transparent Qt label layer over the GPU viewport.

A child QWidget is used instead of QPainter text inside paintGL: some drivers
corrupt GL-interleaved text glyphs. It is mouse-transparent, so the existing
polygon/vertex picker and orbit/zoom gestures still receive all input.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from gpu_viewer.vertex_label_data import (
    filter_vertex_labels, polygon_vertex_refs, project_vertex_labels,
)


class VertexLabelOverlay(QWidget):
    def __init__(self, viewport):
        super().__init__(viewport)
        self.viewport = viewport
        self.setObjectName("allVertexLabelsOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAutoFillBackground(False)
        self.hide()

    def paintEvent(self, event):
        viewport = self.viewport
        picker = viewport._label_vertex_picker
        if picker is None or not len(picker.offsets):
            return
        mode = viewport.vertex_label_mode
        if mode == "visible":
            # The GPU framebuffer determines which side of a car is actually
            # in front. Depth is captured after the GL scene is rendered.
            points = viewport._depth_visible_vertex_labels
        else:
            projection, view = viewport._projection_and_view()
            points = project_vertex_labels(
                picker, viewport.vertex_pointer_names, projection @ view,
                self.width(), self.height())
            if mode == "selected":
                refs = polygon_vertex_refs(
                    viewport._model, (viewport.inspection_offset,))
                if viewport.inspection_kind != "polygon":
                    refs = frozenset()
                points = filter_vertex_labels(
                    points, mode, vertex_offsets=refs)
        if not points:
            return
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
            colors = viewport.colors
            dot = QColor(colors["viewport_all_vertex_dot"])
            label = QColor(colors["viewport_all_vertex_label"])
            selected = QColor(colors["viewport_vertex_dot"])
            shadow = QColor(colors["viewport_vertex_outline"])
            selected_offset = (viewport.inspection_offset
                               if viewport.inspection_kind == "vertex" else None)

            # One batched point pass, followed by independent names. The
            # selected vertex is excluded so its larger yellow marker remains
            # legible and distinct from the smaller blue points.
            others = QPolygonF([
                QPointF(x, y) for offset, x, y, _ in points
                if offset != selected_offset
            ])
            painter.setPen(QPen(dot, 5, Qt.PenStyle.SolidLine,
                                Qt.PenCapStyle.RoundCap))
            if not others.isEmpty():
                painter.drawPoints(others)

            font = QFont("Consolas")
            font.setPointSize(9)
            painter.setFont(font)
            for offset, x, y, name in points:
                text_color = selected if offset == selected_offset else label
                baseline = QPointF(x + 7, y - 5)
                painter.setPen(shadow)
                painter.drawText(QPointF(baseline.x() + 1,
                                         baseline.y() + 1), name)
                painter.setPen(text_color)
                painter.drawText(baseline, name)
        finally:
            painter.end()
