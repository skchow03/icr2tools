"""Transparent, mouse-pass-through Qt overlay for all root N3 vertices.

QOpenGLWidget's raw GL state can corrupt QPainter font glyphs on some
drivers, so vertex labels are painted in a child QWidget, not paintGL.
The separately rendered selected-vertex and BSP markers retain priority.
"""
from __future__ import annotations

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from gpu_viewer.vertex_labels import project_labelled_vertices


class VertexLabelsOverlay(QWidget):
    def __init__(self, viewport):
        super().__init__(viewport)
        self.viewport = viewport
        self.setObjectName("allVertexLabelsOverlay")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setGeometry(viewport.rect())
        self.hide()
        self.last_visible_labels = ()  # lightweight diagnostic for Qt tests

    def set_display_enabled(self, enabled):
        self.setVisible(bool(enabled))
        if enabled:
            self.raise_()
            if self.viewport.visibility_banner.isVisible():
                self.viewport.visibility_banner.raise_()
            self.update()
        else:
            self.last_visible_labels = ()

    def projected_labels(self):
        view = self.viewport
        if view._mesh is None or not view.labelled_vertices:
            return ()
        projection, camera = view._projection_and_view()
        return project_labelled_vertices(
            view.labelled_vertices, view._mesh, projection @ camera,
            self.width(), self.height())

    def paintEvent(self, event):
        if not self.isVisible():
            return
        markers = self.projected_labels()
        self.last_visible_labels = markers
        if not markers:
            return
        viewport = self.viewport
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setClipRect(self.rect())
            border = QColor(viewport.colors["viewport_all_vertex_outline"])
            dot = QColor(viewport.colors["viewport_all_vertex_dot"])
            text = QColor(viewport.colors["viewport_all_vertex_text"])
            font = QFont("Consolas", 9)
            font.setStyleHint(QFont.StyleHint.Monospace)
            painter.setFont(font)
            metrics = painter.fontMetrics()

            # The selected vertex is already drawn in bright yellow in GL.
            # Avoid painting the purple dot over it, but retain its name.
            selected = (viewport.inspection_offset
                        if viewport.inspection_kind == "vertex" else None)
            bsp_points = (
                set(tuple(xyz) for xyz in viewport.inspection_points)
                if viewport.inspection_kind == "bsp" and
                viewport.inspection_points else set())
            painter.setPen(QPen(border, 1.5))
            painter.setBrush(QBrush(dot))
            for vertex in markers:
                if vertex.offset == selected or vertex.xyz in bsp_points:
                    continue
                painter.drawEllipse(QPointF(vertex.x, vertex.y), 3.8, 3.8)

            # Draw names after all dots so the glyphs remain readable on top
            # of neighboring markers. Spread labels at coincident vertices.
            coincident = {}
            for vertex in markers:
                key = (round(vertex.x / 5), round(vertex.y / 5))
                stacked = coincident.get(key, 0)
                coincident[key] = stacked + 1
                text_width = metrics.horizontalAdvance(vertex.label)
                x = max(3.0, min(vertex.x + 8, self.width() - text_width - 3))
                baseline = max(
                    metrics.ascent() + 3.0,
                    min(vertex.y - 7 + (stacked % 8) * (metrics.height() + 2),
                        self.height() - 4.0))
                # Two-pixel dark edge improves contrast over bright MIPs
                # without obscuring the polygon or the original model.
                painter.setPen(border)
                painter.drawText(QPointF(x + 1, baseline + 1), vertex.label)
                painter.setPen(text)
                painter.drawText(QPointF(x, baseline), vertex.label)
        finally:
            painter.end()
