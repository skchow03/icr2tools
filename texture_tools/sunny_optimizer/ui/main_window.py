from __future__ import annotations

import time
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
        self.spinbox.setToolTip(
            "Per-texture color budget: maximum optimized palette entries this texture can claim."
        )
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
        self.reset_view()
        self.layout().setCurrentWidget(self._view)
        self.fit_to_view()

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

    def fit_to_view(self) -> None:
        if self._base_pixmap.isNull():
            return
        self._view.fitInView(self._scene.sceneRect(), QtCore.Qt.KeepAspectRatio)
        self.view_changed.emit()

    def reset_view(self) -> None:
        self._view.resetTransform()
        self._view.horizontalScrollBar().setValue(0)
        self._view.verticalScrollBar().setValue(0)
        self.view_changed.emit()

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
    SORT_BY_NAME = "Name"
    SORT_BY_COLOR_COUNT = "Color count"
    SORT_BY_BUDGET = "Budget"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Texture Tools - Sunny Optimizer")
        self.resize(1400, 800)

        self.preview_max_dim = 512
        self.texture_images: dict[str, np.ndarray] = {}
        self.texture_color_counts: dict[str, int] = {}
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
        self.setAcceptDrops(True)

    def _show_drop_message(self, message: str) -> None:
        self.statusBar().showMessage(message, 5000)

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent) -> None:
        if self._classify_drop(event.mimeData().urls()) is not None:
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QtGui.QDropEvent) -> None:
        action = self._classify_drop(event.mimeData().urls())
        if action is None:
            self._show_drop_message("Drop rejected: provide a texture folder, palette .pcx, or image file.")
            event.ignore()
            return
        kind, path = action
        if kind == "folder":
            self._load_folder(path)
            self._show_drop_message(f"Loaded texture folder: {path}")
        elif kind == "palette":
            self._last_sunny_palette_path = path.resolve()
            self.settings.last_sunny_palette = str(self._last_sunny_palette_path)
            self._save_settings()
            self._show_drop_message(f"Palette set for optimization: {path.name}")
        elif kind == "image":
            self._load_folder(path.parent)
            self._show_drop_message(f"Loaded texture folder from image drop: {path.parent}")
        event.acceptProposedAction()

    def _classify_drop(self, urls) -> tuple[str, Path] | None:
        local_paths = [Path(url.toLocalFile()) for url in urls if url.isLocalFile()]
        if len(local_paths) != 1:
            return None
        path = local_paths[0]
        if path.is_dir():
            return ("folder", path)
        suffix = path.suffix.lower()
        if path.is_file() and suffix == ".pcx":
            return ("palette", path)
        if path.is_file() and suffix in {".png", ".jpg", ".jpeg", ".bmp"}:
            return ("image", path)
        return None

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget()
        root = QtWidgets.QHBoxLayout(central)

        left_panel = QtWidgets.QVBoxLayout()
        folder_controls = QtWidgets.QHBoxLayout()
        self.folder_btn = QtWidgets.QPushButton("Select Texture Images Folder")
        self.folder_btn.clicked.connect(self.select_folder)
        self.refresh_folder_btn = QtWidgets.QPushButton("Refresh Folder")
        self.refresh_folder_btn.clicked.connect(self.refresh_folder)
        self.search_box = QtWidgets.QLineEdit()
        self.search_box.setPlaceholderText("Search textures by name...")
        self.search_box.textChanged.connect(self._refresh_texture_list)
        self.sort_combo = QtWidgets.QComboBox()
        self.sort_combo.addItems([self.SORT_BY_NAME, self.SORT_BY_COLOR_COUNT, self.SORT_BY_BUDGET])
        self.sort_combo.currentTextChanged.connect(self._refresh_texture_list)
        self.texture_list = QtWidgets.QListWidget()
        self.texture_list.currentItemChanged.connect(self._on_current_item_changed)
        self.batch_actions_combo = QtWidgets.QComboBox()
        self.batch_actions_combo.addItems(
            [
                "Set all budgets equally",
                "Normalize budgets",
                "Apply value to selected textures only",
            ]
        )
        self.batch_budget_spinbox = QtWidgets.QSpinBox()
        self.batch_budget_spinbox.setRange(1, OPTIMIZED_SLOTS)
        self.batch_budget_spinbox.setValue(OPTIMIZED_SLOTS)
        self.apply_batch_btn = QtWidgets.QPushButton("Apply Batch Action")
        self.apply_batch_btn.clicked.connect(self._apply_batch_action)
        self.dirt_checkbox = QtWidgets.QCheckBox("Include dirt colors in optimization")
        self.dirt_checkbox.setToolTip(
            "Enable this if your textures include dirt/brown tones that should be reserved in the optimized palette."
        )

        folder_controls.addWidget(self.folder_btn)
        folder_controls.addWidget(self.refresh_folder_btn)
        filter_controls = QtWidgets.QHBoxLayout()
        filter_controls.addWidget(QtWidgets.QLabel("Search:"))
        filter_controls.addWidget(self.search_box, 1)
        filter_controls.addWidget(QtWidgets.QLabel("Sort by:"))
        filter_controls.addWidget(self.sort_combo)
        batch_controls = QtWidgets.QHBoxLayout()
        batch_controls.addWidget(self.batch_actions_combo, 1)
        batch_controls.addWidget(QtWidgets.QLabel("Budget value:"))
        batch_controls.addWidget(self.batch_budget_spinbox)
        batch_controls.addWidget(self.apply_batch_btn)
        left_panel.addLayout(folder_controls)
        left_panel.addLayout(filter_controls)
        preset_controls = QtWidgets.QHBoxLayout()
        preset_controls.addWidget(QtWidgets.QLabel("Presets:"))
        preset_controls.addWidget(self.preset_combo, 1)
        preset_controls.addWidget(self.save_preset_btn)
        preset_controls.addWidget(self.load_preset_btn)
        preset_controls.addWidget(self.delete_preset_btn)
        left_panel.addLayout(preset_controls)
        left_panel.addLayout(batch_controls)
        left_panel.addWidget(self.texture_list, 1)
        left_panel.addWidget(self.dirt_checkbox)

        center_panel = QtWidgets.QVBoxLayout()
        preview_hint = QtWidgets.QLabel(
            "Scroll to zoom, drag to pan, click pixel to inspect palette index."
        )
        preview_hint.setWordWrap(True)
        self.orig_label = ZoomableImageLabel("Original RGB")
        self.orig_label.setMinimumSize(300, 250)
        self.orig_fit_btn = QtWidgets.QPushButton("Fit Original")
        self.orig_fit_btn.clicked.connect(self.orig_label.fit_to_view)
        self.orig_reset_btn = QtWidgets.QPushButton("Reset Original")
        self.orig_reset_btn.clicked.connect(self.orig_label.reset_view)
        orig_view_controls = QtWidgets.QHBoxLayout()
        orig_view_controls.addWidget(self.orig_fit_btn)
        orig_view_controls.addWidget(self.orig_reset_btn)
        orig_view_controls.addStretch(1)
        self.orig_unique_colors_label = QtWidgets.QLabel("Original unique colors: —")
        self.quant_label = ZoomableImageLabel("Quantized Preview")
        self.quant_label.setMinimumSize(300, 250)
        self.quant_fit_btn = QtWidgets.QPushButton("Fit Quantized")
        self.quant_fit_btn.clicked.connect(self.quant_label.fit_to_view)
        self.quant_reset_btn = QtWidgets.QPushButton("Reset Quantized")
        self.quant_reset_btn.clicked.connect(self.quant_label.reset_view)
        quant_view_controls = QtWidgets.QHBoxLayout()
        quant_view_controls.addWidget(self.quant_fit_btn)
        quant_view_controls.addWidget(self.quant_reset_btn)
        quant_view_controls.addStretch(1)
        self.highlight_checkbox = QtWidgets.QCheckBox("Highlight selected palette index in preview")
        self.highlight_checkbox.setChecked(True)
        self.highlight_checkbox.toggled.connect(self._refresh_current_preview)
        self.paletted_unique_colors_label = QtWidgets.QLabel("Paletted unique colors: —")
        self.quant_label.image_clicked.connect(self._on_quantized_preview_clicked)
        self.orig_label.view_changed.connect(lambda: self._sync_preview_views(self.orig_label, self.quant_label))
        self.quant_label.view_changed.connect(lambda: self._sync_preview_views(self.quant_label, self.orig_label))
        center_panel.addWidget(preview_hint)
        center_panel.addWidget(self.orig_label, 1)
        center_panel.addLayout(orig_view_controls)
        center_panel.addWidget(self.orig_unique_colors_label)
        center_panel.addWidget(self.quant_label, 1)
        center_panel.addLayout(quant_view_controls)
        center_panel.addWidget(self.highlight_checkbox)
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
        self.compute_btn = QtWidgets.QPushButton("Generate Optimized Palette")
        self.compute_btn.clicked.connect(self.compute_palette)
        self.compute_hint_label = QtWidgets.QLabel()
        self.compute_hint_label.setWordWrap(True)
        self.save_btn = QtWidgets.QPushButton("Save Palette")
        self.save_btn.clicked.connect(self.save_palette_dialog)
        self.save_hint_label = QtWidgets.QLabel()
        self.save_hint_label.setWordWrap(True)
        self.compute_progress = QtWidgets.QProgressBar()
        self.compute_progress.setRange(0, 100)
        self.compute_progress.setValue(0)
        self.compute_progress.setFormat("Idle")
        self.compute_progress.setTextVisible(True)

        right_panel.addWidget(self.palette_label)
        right_panel.addWidget(self.palette_details_label)
        right_panel.addWidget(self.compute_btn)
        right_panel.addWidget(self.compute_hint_label)
        right_panel.addWidget(self.compute_progress)
        right_panel.addWidget(self.save_btn)
        right_panel.addWidget(self.save_hint_label)
        right_panel.addStretch(1)

        root.addLayout(left_panel, 3)
        root.addLayout(center_panel, 4)
        root.addLayout(right_panel, 2)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Ready")
        self._refresh_palette_view()
        self._update_action_states()
        self._restore_last_texture_folder()
        self._refresh_preset_combo()

    def _refresh_preset_combo(self) -> None:
        current = self.preset_combo.currentText()
        presets = self.settings.presets_for_tool("sunny_optimizer")
        self.preset_combo.clear()
        self.preset_combo.addItems(sorted(presets.keys()))
        default_name = self.settings.default_preset_for_tool("sunny_optimizer")
        target = current or default_name
        if target:
            idx = self.preset_combo.findText(target)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)

    def _collect_preset_values(self) -> dict[str, str]:
        return {
            "palette_path": str(self._last_sunny_palette_path) if self._last_sunny_palette_path else "",
            "include_dirt": str(self.dirt_checkbox.isChecked()),
            "batch_budget": str(self.batch_budget_spinbox.value()),
            "batch_mode": self.batch_actions_combo.currentText(),
        }

    def _save_preset_dialog(self) -> None:
        name, ok = QtWidgets.QInputDialog.getText(self, "Save preset", "Preset name:")
        if not ok or not name.strip():
            return
        preset_name = name.strip()
        values = self._collect_preset_values()
        if self.loaded_texture_folder is not None:
            values["texture_budgets"] = ",".join(f"{k}:{v}" for k, v in sorted(self.per_texture_budget.items()))
        self.settings.set_preset_for_tool("sunny_optimizer", preset_name, values)
        self.settings.set_default_preset("sunny_optimizer", preset_name)
        self._save_settings()
        self._refresh_preset_combo()

    def _load_selected_preset(self) -> None:
        name = self.preset_combo.currentText().strip()
        if not name:
            return
        preset = self.settings.presets_for_tool("sunny_optimizer").get(name, {})
        palette_path = preset.get("palette_path", "")
        if palette_path:
            self._last_sunny_palette_path = Path(palette_path)
            self.settings.last_sunny_palette = palette_path
        self.dirt_checkbox.setChecked(preset.get("include_dirt", "False").lower() == "true")
        self.batch_actions_combo.setCurrentText(preset.get("batch_mode", self.batch_actions_combo.currentText()))
        try:
            self.batch_budget_spinbox.setValue(int(preset.get("batch_budget", str(self.batch_budget_spinbox.value()))))
        except ValueError:
            pass
        self.settings.set_default_preset("sunny_optimizer", name)
        self._save_settings()

    def _delete_selected_preset(self) -> None:
        name = self.preset_combo.currentText().strip()
        if not name:
            return
        self.settings.delete_preset_for_tool("sunny_optimizer", name)
        if self.settings.default_preset_for_tool("sunny_optimizer") == name:
            self.settings.default_presets.pop("sunny_optimizer", None)
        self._save_settings()
        self._refresh_preset_combo()

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
        self.texture_color_counts.clear()
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
            self.texture_color_counts[path.name] = self._count_unique_rgb_colors(arr)
            budget = saved_budgets.get(path.name, equal_budget)
            budget = max(1, min(OPTIMIZED_SLOTS, int(budget)))
            self.per_texture_budget[path.name] = budget
        self._refresh_texture_list()

        self.loaded_texture_folder = resolved_folder
        self.settings.last_texture_folder = str(resolved_folder)
        self._save_settings()
        self._update_action_states()

    def _on_budget_changed(self, texture_name: str, budget: int) -> None:
        self.per_texture_budget[texture_name] = budget
        self._persist_current_folder_budgets()
        if self.sort_combo.currentText() == self.SORT_BY_BUDGET:
            self._refresh_texture_list()

    def _sorted_texture_names(self) -> list[str]:
        texture_names = list(self.texture_images.keys())
        sort_mode = self.sort_combo.currentText()
        if sort_mode == self.SORT_BY_COLOR_COUNT:
            texture_names.sort(
                key=lambda n: (-self.texture_color_counts.get(n, 0), n.lower())
            )
        elif sort_mode == self.SORT_BY_BUDGET:
            texture_names.sort(key=lambda n: (-self.per_texture_budget.get(n, 0), n.lower()))
        else:
            texture_names.sort(key=str.lower)
        return texture_names

    def _refresh_texture_list(self) -> None:
        selected_texture = ""
        current = self.texture_list.currentItem()
        if current is not None:
            widget = self.texture_list.itemWidget(current)
            if widget is not None:
                selected_texture = widget.texture_name
        query = self.search_box.text().strip().lower()
        self.texture_list.clear()
        for texture_name in self._sorted_texture_names():
            if query and query not in texture_name.lower():
                continue
            item = QtWidgets.QListWidgetItem(self.texture_list)
            widget = TextureBudgetItemWidget(texture_name, self.per_texture_budget[texture_name])
            widget.budget_changed.connect(self._on_budget_changed)
            tooltip = f"Unique colors: {self.texture_color_counts.get(texture_name, 0)}"
            item.setToolTip(tooltip)
            widget.setToolTip(tooltip)
            item.setSizeHint(widget.sizeHint())
            self.texture_list.addItem(item)
            self.texture_list.setItemWidget(item, widget)
        if self.texture_list.count() == 0:
            self.orig_label.clear_base_pixmap("Original RGB")
            self.quant_label.clear_base_pixmap("Quantized Preview")
            return
        for row in range(self.texture_list.count()):
            item = self.texture_list.item(row)
            widget = self.texture_list.itemWidget(item)
            if widget is not None and widget.texture_name == selected_texture:
                self.texture_list.setCurrentRow(row)
                return
        self.texture_list.setCurrentRow(0)

    def _apply_batch_action(self) -> None:
        if not self.texture_images:
            QtWidgets.QMessageBox.information(self, "No textures", "Load textures before applying batch actions.")
            return
        mode = self.batch_actions_combo.currentText()
        if mode == "Set all budgets equally":
            equal_budget = max(1, OPTIMIZED_SLOTS // max(1, len(self.texture_images)))
            for texture_name in self.texture_images:
                self.per_texture_budget[texture_name] = equal_budget
        elif mode == "Normalize budgets":
            total_colors = sum(max(1, self.texture_color_counts.get(name, 1)) for name in self.texture_images)
            allocated = 0
            names = sorted(self.texture_images.keys())
            for idx, texture_name in enumerate(names):
                if idx == len(names) - 1:
                    budget = max(1, OPTIMIZED_SLOTS - allocated)
                else:
                    portion = self.texture_color_counts.get(texture_name, 1) / max(1, total_colors)
                    budget = max(1, int(round(portion * OPTIMIZED_SLOTS)))
                    allocated += budget
                self.per_texture_budget[texture_name] = min(OPTIMIZED_SLOTS, budget)
        else:
            selected_items = self.texture_list.selectedItems()
            if not selected_items:
                QtWidgets.QMessageBox.information(self, "No selection", "Select one or more textures first.")
                return
            budget_value = int(self.batch_budget_spinbox.value())
            for item in selected_items:
                widget = self.texture_list.itemWidget(item)
                if widget is not None:
                    self.per_texture_budget[widget.texture_name] = budget_value
        self._persist_current_folder_budgets()
        self._refresh_texture_list()

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

    def _update_action_states(self) -> None:
        folder_ok = self.loaded_texture_folder is not None and self.loaded_texture_folder.exists() and self.loaded_texture_folder.is_dir()
        has_textures = folder_ok and bool(self.texture_images)
        has_quantized_results = bool(self.quantized_images)

        self.compute_btn.setEnabled(has_textures)
        self.save_btn.setEnabled(has_quantized_results)

        if has_textures:
            self.compute_hint_label.setText("Step 2: Click Generate Optimized Palette when you are ready.")
        elif not folder_ok:
            self.compute_hint_label.setText("Missing: valid texture folder path.")
        else:
            self.compute_hint_label.setText("Missing: texture images (.png/.jpg/.jpeg/.bmp) in selected folder.")

        if has_quantized_results:
            self.save_hint_label.setText("Step 3: Save palette to write your optimized .pcx file.")
        else:
            self.save_hint_label.setText("Step 3: Save is enabled after a palette has been computed.")

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
            quant_display = self._build_highlighted_quantized_preview(texture_name, quant)
            self.quant_label.set_base_pixmap(self._to_pixmap(quant_display))
            if indexed is None:
                self.paletted_unique_colors_label.setText("Paletted unique colors: —")
            else:
                self.paletted_unique_colors_label.setText(
                    f"Paletted unique colors: {self._count_unique_palette_indices(indexed)}"
                )

    def _build_highlighted_quantized_preview(self, texture_name: str, quant: np.ndarray) -> np.ndarray:
        indexed = self.indexed_images.get(texture_name)
        if (
            indexed is None
            or self.selected_palette_index is None
            or not self.highlight_checkbox.isChecked()
        ):
            return quant
        if indexed.shape[:2] != quant.shape[:2]:
            return quant
        mask = indexed == self.selected_palette_index
        if not np.any(mask):
            return quant
        result = quant.copy()
        result[mask] = np.array([255, 255, 255], dtype=np.uint8)
        result[~mask] = (result[~mask] * 0.35).astype(np.uint8)
        return result

    def _refresh_current_preview(self) -> None:
        current = self.texture_list.currentItem()
        if current is None:
            return
        widget = self.texture_list.itemWidget(current)
        if widget is None:
            return
        self._update_preview(widget.texture_name)

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

        step_total = 4
        started_at = time.perf_counter()

        def set_progress(step_num: int, message: str, percent: int) -> None:
            elapsed = time.perf_counter() - started_at
            self.compute_progress.setValue(percent)
            self.compute_progress.setFormat(f"Step {step_num}/{step_total}: {message} ({elapsed:.1f}s)")

        self.compute_btn.setEnabled(False)
        set_progress(1, "Loading base palette", 10)
        QtWidgets.QApplication.processEvents()

        try:
            fixed_palette = load_sunny_palette(palette_path)
            resolved_palette = Path(palette_path).resolve()
            self._last_sunny_palette_path = resolved_palette
            self.settings.last_sunny_palette = str(resolved_palette)
            self._persist_current_folder_budgets()
            set_progress(2, "Preparing optimizer", 30)
            QtWidgets.QApplication.processEvents()

            optimizer = SunnyPaletteOptimizer(
                rgb_images=self.texture_images,
                per_texture_color_budget=self.per_texture_budget,
                fixed_palette=fixed_palette,
                dirt_present=self.dirt_checkbox.isChecked(),
            )

            set_progress(3, "Computing optimized palette", 65)
            QtWidgets.QApplication.processEvents()

            self.current_palette = optimizer.compute_palette()

            set_progress(4, "Building quantized previews", 90)
            QtWidgets.QApplication.processEvents()

            self.indexed_images, self.quantized_images = optimizer.compute_quantized_images(self.current_palette)
            self.selected_palette_index = None
        except Exception as exc:  # prototype surface
            self.compute_progress.setValue(0)
            elapsed = time.perf_counter() - started_at
            self.compute_progress.setFormat(f"Failure after {elapsed:.1f}s")
            palette_filename = Path(palette_path).name if palette_path else "<unknown>"
            QtWidgets.QMessageBox.critical(
                self,
                "Optimization failed",
                f"Failed to load palette from {palette_filename}: {exc}",
            )
            return
        finally:
            self._update_action_states()

        total_elapsed = time.perf_counter() - started_at
        self.compute_progress.setValue(100)
        self.compute_progress.setFormat(f"Success in {total_elapsed:.1f}s")

        self._refresh_palette_view()
        current = self.texture_list.currentItem()
        if current is None:
            return
        widget = self.texture_list.itemWidget(current)
        if widget is not None:
            self._update_preview(widget.texture_name)
        self._update_action_states()


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
        self._refresh_current_preview()

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
        self._refresh_current_preview()

    def save_palette_dialog(self) -> None:
        if not self.quantized_images:
            self._update_action_states()
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save optimized palette",
            "sunny_optimized.pcx",
            "PCX files (*.pcx *.PCX);;All files (*)",
        )
        if not path:
            return
        save_palette(path, self.current_palette)
        output_path = Path(path).resolve()
        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle("Palette saved")
        msg.setText(f"Saved optimized palette:\n{output_path}")
        open_location_btn = msg.addButton("Open location", QtWidgets.QMessageBox.ActionRole)
        msg.addButton(QtWidgets.QMessageBox.Ok)
        msg.exec_()
        if msg.clickedButton() is open_location_btn:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(output_path.parent)))


def main() -> None:
    import sys

    app = QtWidgets.QApplication(sys.argv)
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
