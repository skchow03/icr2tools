from __future__ import annotations

from pathlib import Path

import numpy as np

try:
    from PyQt5 import QtCore, QtGui, QtWidgets
except ImportError:  # pragma: no cover
    from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore

from sunny_optimizer.model import OPTIMIZED_SLOTS, SunnyPaletteOptimizer
from sunny_optimizer.palette import load_sunny_palette, save_palette, visualize_palette


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


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SUNNY Palette Optimizer Prototype")
        self.resize(1400, 800)

        self.preview_max_dim = 512
        self.texture_images: dict[str, np.ndarray] = {}
        self.per_texture_budget: dict[str, int] = {}
        self.current_palette = np.zeros((256, 3), dtype=np.uint8)
        self.quantized_images: dict[str, np.ndarray] = {}

        self._build_ui()

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        root = QtWidgets.QHBoxLayout(central)

        left_panel = QtWidgets.QVBoxLayout()
        self.folder_btn = QtWidgets.QPushButton("Select Texture Folder")
        self.folder_btn.clicked.connect(self.select_folder)
        self.texture_list = QtWidgets.QListWidget()
        self.texture_list.currentTextChanged.connect(self._update_preview)
        self.dirt_checkbox = QtWidgets.QCheckBox("Dirt present")

        left_panel.addWidget(self.folder_btn)
        left_panel.addWidget(self.texture_list, 1)
        left_panel.addWidget(self.dirt_checkbox)

        center_panel = QtWidgets.QVBoxLayout()
        self.orig_label = QtWidgets.QLabel("Original RGB")
        self.orig_label.setAlignment(QtCore.Qt.AlignCenter)
        self.orig_label.setMinimumSize(300, 250)
        self.quant_label = QtWidgets.QLabel("Quantized Preview")
        self.quant_label.setAlignment(QtCore.Qt.AlignCenter)
        self.quant_label.setMinimumSize(300, 250)
        center_panel.addWidget(self.orig_label, 1)
        center_panel.addWidget(self.quant_label, 1)

        right_panel = QtWidgets.QVBoxLayout()
        self.palette_label = QtWidgets.QLabel()
        self.palette_label.setMinimumSize(256, 256)
        self.palette_label.setAlignment(QtCore.Qt.AlignCenter)
        self.compute_btn = QtWidgets.QPushButton("Compute Palette")
        self.compute_btn.clicked.connect(self.compute_palette)
        self.save_btn = QtWidgets.QPushButton("Save Palette")
        self.save_btn.clicked.connect(self.save_palette_dialog)

        right_panel.addWidget(self.palette_label)
        right_panel.addWidget(self.compute_btn)
        right_panel.addWidget(self.save_btn)
        right_panel.addStretch(1)

        root.addLayout(left_panel, 3)
        root.addLayout(center_panel, 4)
        root.addLayout(right_panel, 2)
        self.setCentralWidget(central)
        self._refresh_palette_view()

    def select_folder(self) -> None:
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Select RGB Texture Folder")
        if not folder:
            return
        self._load_folder(Path(folder))

    def _load_folder(self, folder: Path) -> None:
        from PIL import Image

        self.texture_images.clear()
        self.per_texture_budget.clear()
        self.quantized_images.clear()
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
        for path in image_files:
            with Image.open(path) as img:
                img = img.convert("RGB")
                img.thumbnail((self.preview_max_dim, self.preview_max_dim), Image.Resampling.LANCZOS)
                arr = np.asarray(img, dtype=np.uint8)
            self.texture_images[path.name] = arr
            self.per_texture_budget[path.name] = equal_budget

            item = QtWidgets.QListWidgetItem(self.texture_list)
            widget = TextureBudgetItemWidget(path.name, equal_budget)
            widget.budget_changed.connect(self._on_budget_changed)
            item.setSizeHint(widget.sizeHint())
            self.texture_list.addItem(item)
            self.texture_list.setItemWidget(item, widget)

        if self.texture_list.count() > 0:
            self.texture_list.setCurrentRow(0)

    def _on_budget_changed(self, texture_name: str, budget: int) -> None:
        self.per_texture_budget[texture_name] = budget

    def _to_pixmap(self, rgb_array: np.ndarray) -> QtGui.QPixmap:
        h, w, _ = rgb_array.shape
        image = QtGui.QImage(rgb_array.data, w, h, w * 3, QtGui.QImage.Format_RGB888)
        return QtGui.QPixmap.fromImage(image.copy())

    def _update_preview(self, texture_name: str) -> None:
        if not texture_name or texture_name not in self.texture_images:
            return
        orig = self.texture_images[texture_name]
        self.orig_label.setPixmap(self._to_pixmap(orig).scaled(self.orig_label.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

        quant = self.quantized_images.get(texture_name)
        if quant is None:
            self.quant_label.setText("Quantized Preview")
            self.quant_label.setPixmap(QtGui.QPixmap())
        else:
            self.quant_label.setPixmap(self._to_pixmap(quant).scaled(self.quant_label.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self._update_preview(self.texture_list.currentItem().text() if self.texture_list.currentItem() else "")

    def _refresh_palette_view(self) -> None:
        image = visualize_palette(self.current_palette)
        self.palette_label.setPixmap(QtGui.QPixmap.fromImage(image).scaled(self.palette_label.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.FastTransformation))

    def compute_palette(self) -> None:
        if not self.texture_images:
            QtWidgets.QMessageBox.warning(self, "No textures", "Load a folder with textures first.")
            return

        palette_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load SUNNY palette",
            "",
            "PCX files (*.pcx *.PCX);;All files (*)",
        )
        if not palette_path:
            return

        try:
            fixed_palette = load_sunny_palette(palette_path)
            optimizer = SunnyPaletteOptimizer(
                rgb_images=self.texture_images,
                per_texture_color_budget=self.per_texture_budget,
                fixed_palette=fixed_palette,
                dirt_present=self.dirt_checkbox.isChecked(),
            )
            self.current_palette = optimizer.compute_palette()
            _, self.quantized_images = optimizer.compute_quantized_images(self.current_palette)
        except Exception as exc:  # prototype surface
            QtWidgets.QMessageBox.critical(self, "Optimization failed", str(exc))
            return

        self._refresh_palette_view()
        self._update_preview(self.texture_list.currentItem().text() if self.texture_list.currentItem() else "")

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
