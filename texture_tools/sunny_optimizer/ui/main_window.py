from __future__ import annotations

from pathlib import Path

import numpy as np

try:
    from PyQt5 import QtCore, QtGui, QtWidgets
except ImportError:  # pragma: no cover
    from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore

from texture_tools.sunny_optimizer.model import OPTIMIZED_SLOTS, SunnyPaletteOptimizer
from texture_tools.sunny_optimizer.palette import load_sunny_palette, save_palette, visualize_palette
from texture_tools.sunny_optimizer.ui.settings import SunnyOptimizerSettings


class TextureBudgetItemWidget(QtWidgets.QWidget):
    budget_changed = QtCore.pyqtSignal(str, int)

    def __init__(self, texture_name: str, initial_budget: int, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.texture_name = texture_name
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        label = QtWidgets.QLabel(texture_name)
        self.spinbox = QtWidgets.QSpinBox()
        self.spinbox.setRange(1, OPTIMIZED_SLOTS)
        self.spinbox.setValue(initial_budget)
        self.spinbox.valueChanged.connect(self._emit_change)
        layout.addWidget(label, 1)
        layout.addWidget(self.spinbox)

    def _emit_change(self, value: int) -> None:
        self.budget_changed.emit(self.texture_name, int(value))


class PannableGraphicsView(QtWidgets.QGraphicsView):
    clicked = QtCore.pyqtSignal(QtCore.QPointF)
    view_changed = QtCore.pyqtSignal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        self.setDragMode(QtWidgets.QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorViewCenter)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        zoom_factor = 1.1 if event.angleDelta().y() > 0 else 1 / 1.1
        self.scale(zoom_factor, zoom_factor)
        self.view_changed.emit()
        event.accept()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            scene_pos = self.mapToScene(event.pos())
            self.clicked.emit(scene_pos)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        super().mouseReleaseEvent(event)
        if event.button() == QtCore.Qt.LeftButton:
            self.view_changed.emit()

    def scrollContentsBy(self, dx: int, dy: int) -> None:
        super().scrollContentsBy(dx, dy)
        if dx or dy:
            self.view_changed.emit()


class ZoomableImageLabel(QtWidgets.QWidget):
    image_clicked = QtCore.pyqtSignal(QtCore.QPoint)
    view_changed = QtCore.pyqtSignal()

    def __init__(self, placeholder_text: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._base_pixmap = QtGui.QPixmap()
        self._placeholder_text = placeholder_text
        self._scene = QtWidgets.QGraphicsScene(self)
        self._pixmap_item = QtWidgets.QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)
        self._view = PannableGraphicsView(self)
        self._view.setScene(self._scene)
        self._view.clicked.connect(self._on_view_clicked)
        self._view.view_changed.connect(self.view_changed)

        self._placeholder = QtWidgets.QLabel(placeholder_text)
        self._placeholder.setAlignment(QtCore.Qt.AlignCenter)

        layout = QtWidgets.QStackedLayout(self)
        layout.addWidget(self._placeholder)
        layout.addWidget(self._view)
        layout.setCurrentWidget(self._placeholder)

    def setMinimumSize(self, minw: int, minh: int) -> None:
        super().setMinimumSize(minw, minh)
        self._view.setMinimumSize(minw, minh)
        self._placeholder.setMinimumSize(minw, minh)

    def set_base_pixmap(self, pixmap: QtGui.QPixmap) -> None:
        self._base_pixmap = pixmap
        self._pixmap_item.setPixmap(self._base_pixmap)
        self._scene.setSceneRect(QtCore.QRectF(self._base_pixmap.rect()))
        self._view.resetTransform()
        self.layout().setCurrentWidget(self._view)
        self._view.fitInView(self._scene.sceneRect(), QtCore.Qt.KeepAspectRatio)

    def copy_view_from(self, other: ZoomableImageLabel) -> None:
        if self._base_pixmap.isNull() or other._base_pixmap.isNull():
            return
        self._view.setTransform(other._view.transform())
        self._view.horizontalScrollBar().setValue(other._view.horizontalScrollBar().value())
        self._view.verticalScrollBar().setValue(other._view.verticalScrollBar().value())

    def clear_base_pixmap(self, text: str | None = None) -> None:
        self._base_pixmap = QtGui.QPixmap()
        self._pixmap_item.setPixmap(QtGui.QPixmap())
        if text is not None:
            self._placeholder_text = text
            self._placeholder.setText(text)
        self.layout().setCurrentWidget(self._placeholder)

    def _on_view_clicked(self, scene_pos: QtCore.QPointF) -> None:
        if self._base_pixmap.isNull():
            return
        x = int(scene_pos.x())
        y = int(scene_pos.y())
        if 0 <= x < self._base_pixmap.width() and 0 <= y < self._base_pixmap.height():
            self.image_clicked.emit(QtCore.QPoint(x, y))


class ClickablePaletteLabel(QtWidgets.QLabel):
    clicked = QtCore.pyqtSignal(QtCore.QPoint)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit(event.pos())
        super().mousePressEvent(event)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Texture Tools - Sunny Optimizer")
        self.resize(1400, 800)

        self.preview_max_dim = 512
        self.texture_images: dict[str, np.ndarray] = {}
        self.per_texture_budget: dict[str, int] = {}
        self.current_palette = np.zeros((256, 3), dtype=np.uint8)
        self.quantized_images: dict[str, np.ndarray] = {}
        self.indexed_images: dict[str, np.ndarray] = {}
        self.selected_palette_index: int | None = None
        self._palette_image_size: int = 0
        self._syncing_previews = False
        self.loaded_texture_folder: Path | None = None
        self._last_sunny_palette_path: Path | None = None
        self.settings = SunnyOptimizerSettings(SunnyOptimizerSettings.default_path())
        self.settings.load()

        self._build_ui()

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        root = QtWidgets.QHBoxLayout(central)

        left_panel = QtWidgets.QVBoxLayout()
        folder_controls = QtWidgets.QHBoxLayout()
        self.folder_btn = QtWidgets.QPushButton("Select Texture Folder")
        self.folder_btn.clicked.connect(self.select_folder)
        self.refresh_folder_btn = QtWidgets.QPushButton("Refresh Folder")
        self.refresh_folder_btn.clicked.connect(self.refresh_folder)
        self.texture_list = QtWidgets.QListWidget()
        self.texture_list.currentItemChanged.connect(self._on_current_item_changed)
        self.dirt_checkbox = QtWidgets.QCheckBox("Dirt present")

        folder_controls.addWidget(self.folder_btn)
        folder_controls.addWidget(self.refresh_folder_btn)
        left_panel.addLayout(folder_controls)
        left_panel.addWidget(self.texture_list, 1)
        left_panel.addWidget(self.dirt_checkbox)

        center_panel = QtWidgets.QVBoxLayout()
        self.orig_label = ZoomableImageLabel("Original RGB")
        self.orig_label.setMinimumSize(300, 250)
        self.orig_unique_colors_label = QtWidgets.QLabel("Original unique colors: —")
        self.quant_label = ZoomableImageLabel("Quantized Preview")
        self.quant_label.setMinimumSize(300, 250)
        self.paletted_unique_colors_label = QtWidgets.QLabel("Paletted unique colors: —")
        self.quant_label.image_clicked.connect(self._on_quantized_preview_clicked)
        self.orig_label.view_changed.connect(lambda: self._sync_preview_views(self.orig_label, self.quant_label))
        self.quant_label.view_changed.connect(lambda: self._sync_preview_views(self.quant_label, self.orig_label))
        center_panel.addWidget(self.orig_label, 1)
        center_panel.addWidget(self.orig_unique_colors_label)
        center_panel.addWidget(self.quant_label, 1)
        center_panel.addWidget(self.paletted_unique_colors_label)

        right_panel = QtWidgets.QVBoxLayout()
        self.palette_label = ClickablePaletteLabel()
        self.palette_label.setMinimumSize(256, 256)
        self.palette_label.setAlignment(QtCore.Qt.AlignCenter)
        self.palette_label.setStyleSheet("background: #202020; padding: 2px;")
        self.palette_label.clicked.connect(self._on_palette_clicked)
        self.palette_details_label = QtWidgets.QLabel(
            "Palette selection: click a palette color tile to inspect index, hex, and RGB values."
        )
        self.palette_details_label.setWordWrap(True)
        self.compute_btn = QtWidgets.QPushButton("Compute Palette")
        self.compute_btn.clicked.connect(self.compute_palette)
        self.save_btn = QtWidgets.QPushButton("Save Palette")
        self.save_btn.clicked.connect(self.save_palette_dialog)
        self.compute_progress = QtWidgets.QProgressBar()
        self.compute_progress.setRange(0, 100)
        self.compute_progress.setValue(0)
        self.compute_progress.setFormat("Idle")
        self.compute_progress.setTextVisible(True)

        right_panel.addWidget(self.palette_label)
        right_panel.addWidget(self.palette_details_label)
        right_panel.addWidget(self.compute_btn)
        right_panel.addWidget(self.compute_progress)
        right_panel.addWidget(self.save_btn)
        right_panel.addStretch(1)

        root.addLayout(left_panel, 3)
        root.addLayout(center_panel, 4)
        root.addLayout(right_panel, 2)
        self.setCentralWidget(central)
        self._refresh_palette_view()
        self._restore_last_texture_folder()

    def select_folder(self) -> None:
        start_dir = self.settings.last_texture_folder if self.settings.last_texture_folder else ""
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Select RGB Texture Folder", start_dir)
        if not folder:
            return
        self._load_folder(Path(folder))

    def refresh_folder(self) -> None:
        if self.loaded_texture_folder is None:
            QtWidgets.QMessageBox.information(self, "No folder", "No folder selected yet.")
            return
        if not self.loaded_texture_folder.exists() or not self.loaded_texture_folder.is_dir():
            QtWidgets.QMessageBox.warning(self, "Folder missing", "Selected folder no longer exists.")
            return
        self._load_folder(self.loaded_texture_folder)

    def _load_folder(self, folder: Path) -> None:
        from PIL import Image

        resolved_folder = folder.resolve()

        self.texture_images.clear()
        self.per_texture_budget.clear()
        self.quantized_images.clear()
        self.indexed_images.clear()
        self.selected_palette_index = None
        self.texture_list.clear()

        image_files = [
            p
            for p in sorted(folder.iterdir())
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}
        ]
        if not image_files:
            QtWidgets.QMessageBox.warning(self, "No images", "No PNG/JPG/BMP files found in folder.")
            return

        equal_budget = max(1, OPTIMIZED_SLOTS // len(image_files))
        saved_budgets = self.settings.budgets_for_folder(resolved_folder)
        for path in image_files:
            with Image.open(path) as img:
                img = img.convert("RGB")
                img.thumbnail((self.preview_max_dim, self.preview_max_dim), Image.Resampling.NEAREST)
                arr = np.asarray(img, dtype=np.uint8)
            self.texture_images[path.name] = arr
            budget = saved_budgets.get(path.name, equal_budget)
            budget = max(1, min(OPTIMIZED_SLOTS, int(budget)))
            self.per_texture_budget[path.name] = budget

            item = QtWidgets.QListWidgetItem(self.texture_list)
            widget = TextureBudgetItemWidget(path.name, budget)
            widget.budget_changed.connect(self._on_budget_changed)
            item.setSizeHint(widget.sizeHint())
            self.texture_list.addItem(item)
            self.texture_list.setItemWidget(item, widget)

        if self.texture_list.count() > 0:
            self.texture_list.setCurrentRow(0)

        self.loaded_texture_folder = resolved_folder
        self.settings.last_texture_folder = str(resolved_folder)
        self._save_settings()

    def _on_budget_changed(self, texture_name: str, budget: int) -> None:
        self.per_texture_budget[texture_name] = budget
        self._persist_current_folder_budgets()

    def _restore_last_texture_folder(self) -> None:
        folder_text = self.settings.last_texture_folder
        if not folder_text:
            return
        folder = Path(folder_text).expanduser()
        if not folder.exists() or not folder.is_dir():
            return
        self._load_folder(folder)

    def _save_settings(self) -> None:
        self.settings.save()

    def _persist_current_folder_budgets(self) -> None:
        if self.loaded_texture_folder is None:
            return
        self.settings.set_budgets_for_folder(self.loaded_texture_folder, self.per_texture_budget)
        self._save_settings()

    def _on_current_item_changed(
        self,
        current: QtWidgets.QListWidgetItem | None,
        previous: QtWidgets.QListWidgetItem | None,
    ) -> None:
        _ = previous
        if current is None:
            return
        widget = self.texture_list.itemWidget(current)
        if widget is None:
            return
        texture_name = widget.texture_name
        self._update_preview(texture_name)

    def _to_pixmap(self, rgb_array: np.ndarray) -> QtGui.QPixmap:
        h, w, _ = rgb_array.shape
        image = QtGui.QImage(rgb_array.data, w, h, w * 3, QtGui.QImage.Format_RGB888)
        return QtGui.QPixmap.fromImage(image.copy())

    def _update_preview(self, texture_name: str) -> None:
        if not texture_name or texture_name not in self.texture_images:
            return
        orig = self.texture_images[texture_name]
        self.orig_label.set_base_pixmap(self._to_pixmap(orig))
        self.orig_unique_colors_label.setText(
            f"Original unique colors: {self._count_unique_rgb_colors(orig)}"
        )

        quant = self.quantized_images.get(texture_name)
        indexed = self.indexed_images.get(texture_name)
        if quant is None:
            self.quant_label.clear_base_pixmap("Quantized Preview")
            self.paletted_unique_colors_label.setText("Paletted unique colors: —")
        else:
            self.quant_label.set_base_pixmap(self._to_pixmap(quant))
            if indexed is None:
                self.paletted_unique_colors_label.setText("Paletted unique colors: —")
            else:
                self.paletted_unique_colors_label.setText(
                    f"Paletted unique colors: {self._count_unique_palette_indices(indexed)}"
                )

    @staticmethod
    def _count_unique_rgb_colors(rgb_array: np.ndarray) -> int:
        if rgb_array.size == 0:
            return 0
        flat = rgb_array.reshape(-1, 3)
        return int(np.unique(flat, axis=0).shape[0])

    @staticmethod
    def _count_unique_palette_indices(indexed_array: np.ndarray) -> int:
        if indexed_array.size == 0:
            return 0
        return int(np.unique(indexed_array).shape[0])

    def _refresh_palette_view(self) -> None:
        image = visualize_palette(self.current_palette, selected_index=self.selected_palette_index)
        self._palette_image_size = image.width()
        self.palette_label.setPixmap(
            QtGui.QPixmap.fromImage(image).scaled(
                self.palette_label.size(),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.FastTransformation,
            )
        )

    def _sync_preview_views(self, source: ZoomableImageLabel, target: ZoomableImageLabel) -> None:
        if self._syncing_previews:
            return
        self._syncing_previews = True
        try:
            target.copy_view_from(source)
        finally:
            self._syncing_previews = False

    def compute_palette(self) -> None:
        if not self.texture_images:
            QtWidgets.QMessageBox.warning(self, "No textures", "Load a folder with textures first.")
            return

        palette_path = ""
        if self._last_sunny_palette_path is not None and self._last_sunny_palette_path.exists():
            palette_path = str(self._last_sunny_palette_path)
        else:
            remembered = self.settings.last_sunny_palette
            if remembered:
                remembered_path = Path(remembered).expanduser()
                if remembered_path.exists():
                    palette_path = str(remembered_path)

        if not palette_path:
            selected_path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self,
                "Load SUNNY palette",
                "",
                "PCX files (*.pcx *.PCX);;All files (*)",
            )
            if not selected_path:
                return
            palette_path = selected_path

        self.compute_btn.setEnabled(False)
        self.compute_progress.setValue(5)
        self.compute_progress.setFormat("Loading base palette...")
        QtWidgets.QApplication.processEvents()

        try:
            fixed_palette = load_sunny_palette(palette_path)
            resolved_palette = Path(palette_path).resolve()
            self._last_sunny_palette_path = resolved_palette
            self.settings.last_sunny_palette = str(resolved_palette)
            self._persist_current_folder_budgets()
            self.compute_progress.setValue(20)
            self.compute_progress.setFormat("Preparing optimizer...")
            QtWidgets.QApplication.processEvents()

            optimizer = SunnyPaletteOptimizer(
                rgb_images=self.texture_images,
                per_texture_color_budget=self.per_texture_budget,
                fixed_palette=fixed_palette,
                dirt_present=self.dirt_checkbox.isChecked(),
            )

            self.compute_progress.setValue(45)
            self.compute_progress.setFormat("Computing optimized palette...")
            QtWidgets.QApplication.processEvents()

            self.current_palette = optimizer.compute_palette()

            self.compute_progress.setValue(80)
            self.compute_progress.setFormat("Building quantized previews...")
            QtWidgets.QApplication.processEvents()

            self.indexed_images, self.quantized_images = optimizer.compute_quantized_images(self.current_palette)
            self.selected_palette_index = None
        except Exception as exc:  # prototype surface
            self.compute_progress.setValue(0)
            self.compute_progress.setFormat("Failed")
            QtWidgets.QMessageBox.critical(self, "Optimization failed", str(exc))
            return
        finally:
            self.compute_btn.setEnabled(True)

        self.compute_progress.setValue(100)
        self.compute_progress.setFormat("Done")

        self._refresh_palette_view()
        current = self.texture_list.currentItem()
        if current is None:
            return
        widget = self.texture_list.itemWidget(current)
        if widget is not None:
            self._update_preview(widget.texture_name)


    def _on_quantized_preview_clicked(self, point: QtCore.QPoint) -> None:
        current = self.texture_list.currentItem()
        if current is None:
            return
        widget = self.texture_list.itemWidget(current)
        if widget is None:
            return
        texture_name = widget.texture_name
        indexed = self.indexed_images.get(texture_name)
        if indexed is None:
            return
        x, y = point.x(), point.y()
        if y < 0 or y >= indexed.shape[0] or x < 0 or x >= indexed.shape[1]:
            return
        self.selected_palette_index = int(indexed[y, x])
        self._refresh_palette_view()
        self._update_palette_details(self.selected_palette_index)

    @staticmethod
    def _rgb_to_hex(color: tuple[int, int, int]) -> str:
        return f"#{color[0]:02X}{color[1]:02X}{color[2]:02X}"

    def _update_palette_details(self, index: int) -> None:
        rgb = tuple(int(v) for v in self.current_palette[index])
        hex_code = self._rgb_to_hex(rgb)
        self.palette_details_label.setText(
            f"Palette index: {index} | Hex: {hex_code} | RGB: ({rgb[0]}, {rgb[1]}, {rgb[2]})"
        )

    def _on_palette_clicked(self, point: QtCore.QPoint) -> None:
        pixmap = self.palette_label.pixmap()
        if pixmap is None or pixmap.isNull() or self._palette_image_size <= 0:
            return
        x_offset = (self.palette_label.width() - pixmap.width()) // 2
        y_offset = (self.palette_label.height() - pixmap.height()) // 2
        x = point.x() - x_offset
        y = point.y() - y_offset
        if x < 0 or y < 0 or x >= pixmap.width() or y >= pixmap.height():
            return

        source_x = int(x * self._palette_image_size / pixmap.width())
        source_y = int(y * self._palette_image_size / pixmap.height())
        tile_size = max(1, self._palette_image_size // 16)
        col = source_x // tile_size
        row = source_y // tile_size
        if not (0 <= row < 16 and 0 <= col < 16):
            return
        index = int(row * 16 + col)
        self.selected_palette_index = index
        self._refresh_palette_view()
        self._update_palette_details(index)

    def save_palette_dialog(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save optimized palette",
            "sunny_optimized.pcx",
            "PCX files (*.pcx *.PCX);;All files (*)",
        )
        if not path:
            return
        save_palette(path, self.current_palette)


def main() -> None:
    import sys

    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
