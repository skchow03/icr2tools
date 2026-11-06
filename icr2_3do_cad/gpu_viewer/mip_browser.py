"""Non-modal, read-only MIP texture / Papyrus U,V coordinate reference.

Uses the *resolved* MIP paths from the current GPU atlas, not a directory
scan, and the same decoded level-zero indices and active 256-color palette
as the viewport. U and V are zero-based texel coordinates (U right, V down),
not normalized 0..1 texture coordinates.
"""
from __future__ import annotations

from pathlib import Path
import math

import numpy as np

from PySide6.QtCore import QPoint, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QGraphicsScene, QGraphicsView,
    QSplitter, QVBoxLayout, QWidget,
)

from texture_preview import TextureError, load_mip


def mip_rgb_image(path, palette):
    """Decode level-zero MIP into a self-owned Qt image in viewport colors."""
    indexed = np.asarray(load_mip(path)[0], dtype=np.uint8)
    colors = np.asarray(palette, dtype=np.uint8)
    if indexed.ndim != 2 or colors.shape != (256, 3):
        raise ValueError("Expected indexed MIP and RGB 256-color palette")
    rgb = np.ascontiguousarray(colors[indexed])
    h, w = indexed.shape
    # QImage otherwise points into a NumPy temporary that may be freed.
    return QImage(
        rgb.data, w, h, w * 3, QImage.Format.Format_RGB888).copy()


class MipCanvas(QGraphicsView):
    """Nearest-neighbor texel zoom, pan, and exact clicked texel coordinates."""

    pixelClicked = Signal(int, int)
    pixelHovered = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mipUVCanvas")
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._item = None
        self._marker = None
        self._width = 0
        self._height = 0
        self._zoom = 1.0
        self._pan_last = None
        self.setRenderHints(QPainter.RenderHint(0))
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.BoundingRectViewportUpdate)
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(
            QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setBackgroundBrush(QColor("#1A2030"))
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)

    @property
    def zoom(self):
        return self._zoom

    def clear_image(self):
        self._scene.clear()
        self._item = self._marker = None
        self._width = self._height = 0
        self._zoom = 1.0
        self.resetTransform()

    def set_image(self, image):
        self.clear_image()
        if image.isNull():
            return
        self._width = image.width()
        self._height = image.height()
        pixmap = QPixmap.fromImage(image)
        self._item = self._scene.addPixmap(pixmap)
        self._item.setTransformationMode(
            Qt.TransformationMode.FastTransformation)
        self._scene.setSceneRect(QRectF(
            0, 0, self._width, self._height))
        self.fit_image()

    def fit_image(self):
        if self._item is None:
            return
        self.fitInView(self._item, Qt.AspectRatioMode.KeepAspectRatio)
        self._zoom = self.transform().m11()
        self.viewport().update()

    def zoom_by(self, factor, *, at_mouse=False):
        if self._item is None or factor <= 0:
            return
        # A tiny MIP can need >100x zoom just to fill a normal window.
        # Never make a Zoom In action shrink a fitted 2x2 or 4x3 image.
        target = min(4096.0, max(0.0625, self._zoom * factor))
        if abs(target - self._zoom) < 1e-9:
            return
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
            if at_mouse else QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.scale(target / self._zoom, target / self._zoom)
        self._zoom = target
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.viewport().update()

    def actual_size(self):
        if self._item is None:
            return
        self.resetTransform()
        self._zoom = 1.0

    def texel_at(self, viewport_point):
        """Return the integer top-left-origin texel under a viewport pixel."""
        if self._item is None:
            return None
        position = self.mapToScene(viewport_point)
        u = math.floor(position.x())
        v = math.floor(position.y())
        if not (0 <= u < self._width and 0 <= v < self._height):
            return None
        return u, v

    def mark_texel(self, u, v):
        if not (0 <= u < self._width and 0 <= v < self._height):
            return
        if self._marker is None:
            pen = QPen(QColor("#FFE143"))
            pen.setCosmetic(True)
            pen.setWidth(2)
            self._marker = self._scene.addRect(
                QRectF(u, v, 1, 1), pen)
            self._marker.setZValue(10)
        else:
            self._marker.setRect(QRectF(u, v, 1, 1))

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120.0
        if self._item is not None and steps:
            self.zoom_by(1.25 ** steps, at_mouse=True)
            event.accept()
        else:
            super().wheelEvent(event)

    def mousePressEvent(self, event):
        # Middle-drag and Shift+left drag pan; ordinary left clicks always
        # pick UV, even while the image is zoomed.
        pan = (event.button() == Qt.MouseButton.MiddleButton or
               (event.button() == Qt.MouseButton.LeftButton and
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier))
        if pan:
            self._pan_last = event.position().toPoint()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            point = self.texel_at(event.position().toPoint())
            if point is not None:
                self.mark_texel(*point)
                self.pixelClicked.emit(*point)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        position = event.position().toPoint()
        if self._pan_last is not None:
            delta = position - self._pan_last
            self._pan_last = position
            self.horizontalScrollBar().setValue(
                self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        point = self.texel_at(position)
        if point is not None:
            self.pixelHovered.emit(*point)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._pan_last is not None:
            self._pan_last = None
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def drawForeground(self, painter, rect):
        # Pixel boundaries help at high zoom without storing a second image
        # or generating a 4096x4096 overlay.
        if self._item is None or self._zoom < 12:
            return
        start_x = max(0, int(math.floor(rect.left())))
        end_x = min(self._width, int(math.ceil(rect.right())))
        start_y = max(0, int(math.floor(rect.top())))
        end_y = min(self._height, int(math.ceil(rect.bottom())))
        pen = QPen(QColor(235, 245, 255, 60))
        pen.setCosmetic(True)
        painter.setPen(pen)
        for x in range(start_x, end_x + 1):
            painter.drawLine(x, start_y, x, end_y)
        for y in range(start_y, end_y + 1):
            painter.drawLine(start_x, y, end_x, y)


class MipUVBrowser(QDialog):
    """List all resolved model MIPs and inspect one at a time alongside CAD."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mipUVBrowser")
        self.setWindowTitle("MIP Texture Browser — U,V Reference")
        self.setWindowFlag(Qt.WindowType.Window, True)
        self.setModal(False)
        self.resize(1050, 720)
        self._palette = None
        self._selection = None
        self._current_path = None

        layout = QVBoxLayout(self)
        self.summary = QLabel("Open a model to browse its MIP textures.")
        self.summary.setObjectName("mipBrowserSummary")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.mips = QListWidget()
        self.mips.setObjectName("mipBrowserTextureList")
        self.mips.setMinimumWidth(210)
        self.mips.currentItemChanged.connect(self._selected_mip)
        splitter.addWidget(self.mips)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        controls = QHBoxLayout()
        self.details = QLabel("Choose a MIP from the list")
        self.details.setObjectName("mipBrowserImageDetails")
        controls.addWidget(self.details, 1)
        self.canvas = MipCanvas()
        for label, action in (
                ("−", lambda: self.canvas.zoom_by(0.8)),
                ("+", lambda: self.canvas.zoom_by(1.25)),
                ("100%", self.canvas.actual_size),
                ("Fit", self.canvas.fit_image)):
            button = QPushButton(label)
            button.setToolTip(
                "Zoom out" if label == "−" else
                "Zoom in" if label == "+" else
                "Actual MIP pixel size" if label == "100%" else
                "Fit entire image")
            button.clicked.connect(action)
            controls.addWidget(button)
        right_layout.addLayout(controls)
        right_layout.addWidget(self.canvas, 1)
        coords = QHBoxLayout()
        self.coordinates = QLineEdit()
        self.coordinates.setObjectName("mipBrowserUVCoordinates")
        self.coordinates.setReadOnly(True)
        self.coordinates.setPlaceholderText("Click a texel for U,V")
        self.coordinates.setToolTip(
            "Papyrus raw texel coordinates; U right, V down; 0,0 at upper left")
        coords.addWidget(self.coordinates, 1)
        self.hover = QLabel("")
        self.hover.setMinimumWidth(125)
        coords.addWidget(self.hover)
        self.copy_button = QPushButton("Copy U,V")
        self.copy_button.setEnabled(False)
        self.copy_button.clicked.connect(self.copy_uv)
        coords.addWidget(self.copy_button)
        right_layout.addLayout(coords)
        self.canvas.pixelClicked.connect(self._clicked)
        self.canvas.pixelHovered.connect(
            lambda u, v: self.hover.setText(f"Hover: {u}, {v}"))
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)
        instructions = QLabel(
            "Mouse wheel: zoom at cursor  •  Middle-drag or Shift+left-drag: pan"
            "  •  Left-click: select exact 0-based U,V  •  Yellow box: chosen texel")
        instructions.setWordWrap(True)
        layout.addWidget(instructions)

    @property
    def selected_uv(self):
        return self._selection

    def set_model_textures(self, atlas, palette, model_name):
        """Refresh on model/palette/recompile, retaining a still-valid selection."""
        previous_path = self._current_path
        self._palette = np.asarray(palette, dtype=np.uint8).copy()
        paths = tuple(getattr(atlas, "loaded_paths", ()) or ())
        self.mips.blockSignals(True)
        self.mips.clear()
        for path in paths:
            entry = QListWidgetItem(Path(path).name)
            entry.setData(Qt.ItemDataRole.UserRole, str(path))
            entry.setToolTip(str(path))
            self.mips.addItem(entry)
        self.mips.blockSignals(False)

        missing = tuple(getattr(atlas, "missing_names", ()) or ())
        errors = tuple(getattr(atlas, "errors", ()) or ())
        self.summary.setText(
            f"{model_name} — {len(paths)} loaded MIP texture(s)"
            + (f"  |  {len(missing)} missing: {', '.join(missing[:5])}"
               if missing else "")
            + (f"  |  {len(errors)} decode/atlas error(s)"
               if errors else ""))
        self.summary.setToolTip("\n".join((*missing, *errors)))

        next_row = 0 if paths else -1
        if previous_path:
            for row, path in enumerate(paths):
                if str(path).casefold() == previous_path.casefold():
                    next_row = row
                    break
        if next_row >= 0:
            self.mips.setCurrentRow(next_row)
        else:
            self._selected_mip(None)

    def _selected_mip(self, item, previous=None):
        self._selection = None
        self.coordinates.clear()
        self.copy_button.setEnabled(False)
        self.hover.clear()
        self.canvas.clear_image()
        self._current_path = None
        if item is None or self._palette is None:
            self.details.setText("No resolved MIP texture selected")
            return
        path = str(item.data(Qt.ItemDataRole.UserRole))
        self._current_path = path
        try:
            image = mip_rgb_image(path, self._palette)
        except (OSError, TextureError, ValueError) as error:
            self.details.setText(f"{Path(path).name} — cannot open: {error}")
            return
        self.canvas.set_image(image)
        self.details.setText(
            f"{Path(path).name} — {image.width()} × {image.height()} texels")
        self.details.setToolTip(path)
        # Ensure Fit uses the final splitter size after the dialog is shown.
        QTimer.singleShot(0, self.canvas.fit_image)

    def _clicked(self, u, v):
        self._selection = (int(u), int(v))
        self.coordinates.setText(
            f"U = {u}    V = {v}    (texel 0,0 is top-left)")
        self.copy_button.setEnabled(True)

    def copy_uv(self):
        if self._selection is not None:
            u, v = self._selection
            QApplication.clipboard().setText(f"{u}, {v}")
