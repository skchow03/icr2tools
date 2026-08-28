from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

try:
    from PyQt5 import QtCore, QtGui, QtWidgets
except ImportError:  # pragma: no cover
    from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore

from texture_tools.sunny_optimizer.palette import load_sunny_palette, save_palette, visualize_palette
from texture_tools.sunny_optimizer.ui.settings import SunnyOptimizerSettings


# Stable range in sunny_optimizer.model: OPTIMIZED_START=176, OPTIMIZED_END=245.
# Keep local to avoid importing the heavy optimizer module at window creation time.
OPTIMIZED_SLOTS = 70
OPTIMIZED_START = 176


def _get_optimizer_class():
    from texture_tools.sunny_optimizer.model import SunnyPaletteOptimizer

    return SunnyPaletteOptimizer

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
    resized = QtCore.pyqtSignal()

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(256, 256)

    def minimumSizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(96, 96)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self.resized.emit()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit(event.pos())
        super().mousePressEvent(event)


class MainWindow(QtWidgets.QMainWindow):
    SORT_BY_NAME = "Name"
    SORT_BY_COLOR_COUNT = "Color count"
    SORT_BY_BUDGET = "Budget"
    RECENT_TEXTURE_FOLDER_KEY = "sunny_optimizer:texture_folder"
    RECENT_PALETTE_KEY = "sunny_optimizer:palette"
    FOLDER_SETTINGS_FILENAME = "sunny_optimizer.json"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Texture Tools - Sunny Optimizer")
        self.resize(1400, 800)

        self.preview_max_dim = 512
        self.texture_images: dict[str, np.ndarray] = {}
        self.texture_color_counts: dict[str, int] = {}
        self.per_texture_budget: dict[str, int] = {}
        self.per_texture_required_unique_colors: dict[str, int] = {}
        self.current_palette = np.zeros((256, 3), dtype=np.uint8)
        self.quantized_images: dict[str, np.ndarray] = {}
        self.indexed_images: dict[str, np.ndarray] = {}
        self.selected_palette_index: int | None = None
        self._palette_image_size: int = 0
        self._optimization_preview_palette: np.ndarray | None = None
        self._syncing_previews = False
        self.loaded_texture_folder: Path | None = None
        self._last_sunny_palette_path: Path | None = None
        self.settings = SunnyOptimizerSettings(SunnyOptimizerSettings.default_path())
        self.settings.load()

        self._build_ui()
        self.setAcceptDrops(True)

    def _show_drop_message(self, message: str) -> None:
        self.statusBar().showMessage(message, 5000)

    def _set_inline_status(self, message: str, *, level: str = "info", next_action: str | None = None) -> None:
        level_styles = {
            "info": "#0b3d91",
            "warning": "#8a6d3b",
            "error": "#a94442",
            "success": "#2d6a4f",
        }
        color = level_styles.get(level, level_styles["info"])
        action_text = f" Next: {next_action}" if next_action else ""
        self.inline_status_label.setText(f"{message}{action_text}")
        self.inline_status_label.setStyleSheet(
            f"background: #f8f9fa; border: 1px solid {color}; color: {color}; padding: 6px; border-radius: 4px;"
        )
        self.inline_status_label.setVisible(True)
        self.inline_action_row.setVisible(True)
        self._update_action_states()

    def _clear_inline_status(self) -> None:
        self.inline_status_label.setVisible(False)
        self.inline_action_row.setVisible(False)

    def _prompt_for_palette_path(self) -> str:
        selected_path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Load SUNNY palette",
            "",
            "PCX files (*.pcx *.PCX);;All files (*)",
        )
        if not selected_path:
            return ""
        resolved_palette = Path(selected_path).resolve()
        self._set_palette_path(str(resolved_palette))
        return str(resolved_palette)

    def _select_base_palette(self) -> str:
        resolved_palette = self._prompt_for_palette_path()
        if not resolved_palette:
            return ""
        self._update_action_states()
        return resolved_palette

    def _focus_palette_selection(self) -> None:
        self._select_base_palette()

    def _focus_folder_selection(self) -> None:
        self.select_folder()

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
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(12)
        self.setStyleSheet(
            """
            QFrame#sectionCard { background: #f8f9fb; border: 1px solid #d9dce3; border-radius: 8px; }
            QLabel#sectionTitle { font-weight: 700; margin-bottom: 4px; }
            QPushButton[primary="true"] { background: #2b6de6; color: white; font-weight: 700; padding: 6px 12px; border-radius: 6px; }
            QPushButton[primary="true"]:disabled { background: #9ab7f1; color: #eef3ff; }
            QPushButton[secondary="true"] { background: #f1f3f6; color: #374151; border: 1px solid #d1d5db; padding: 5px 10px; border-radius: 6px; }
            """
        )

        self.inline_status_label = QtWidgets.QLabel("")
        self.inline_status_label.setWordWrap(True)
        self.inline_status_label.setVisible(False)
        self.inline_action_row = QtWidgets.QWidget()
        inline_actions = QtWidgets.QHBoxLayout(self.inline_action_row)
        inline_actions.setContentsMargins(0, 0, 0, 0)
        self.inline_fix_folder_btn = QtWidgets.QPushButton("Select Texture Folder")
        self.inline_fix_folder_btn.clicked.connect(self._focus_folder_selection)
        self.inline_fix_palette_btn = QtWidgets.QPushButton("Select Palette (.pcx)")
        self.inline_fix_palette_btn.clicked.connect(self._focus_palette_selection)
        self.palette_recent_btn = QtWidgets.QToolButton()
        self.palette_recent_btn.setText("▼")
        self.palette_recent_btn.setToolTip("Recent palettes")
        self.palette_recent_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.palette_recent_btn.pressed.connect(self._show_recent_palette_menu)
        self.inline_dismiss_btn = QtWidgets.QPushButton("Dismiss")
        self.inline_dismiss_btn.clicked.connect(self._clear_inline_status)
        self.inline_action_row.setVisible(False)
        inline_actions.addWidget(self.inline_fix_folder_btn)
        inline_actions.addWidget(self.inline_fix_palette_btn)
        inline_actions.addWidget(self.palette_recent_btn)
        inline_actions.addStretch(1)
        inline_actions.addWidget(self.inline_dismiss_btn)

        left_panel = QtWidgets.QVBoxLayout()
        left_panel.setSpacing(10)
        left_panel.addWidget(self.inline_status_label)
        left_panel.addWidget(self.inline_action_row)
        folder_controls = QtWidgets.QHBoxLayout()
        self.folder_path_label = QtWidgets.QLabel("No folder selected")
        self.folder_path_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.folder_path_label.setStyleSheet("color: #4b5563;")
        self.folder_path_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.folder_btn = QtWidgets.QPushButton("Browse…")
        self.folder_btn.clicked.connect(self.select_folder)
        self.refresh_folder_btn = QtWidgets.QPushButton("Refresh Folder")
        self.refresh_folder_btn.clicked.connect(self.refresh_folder)
        self.texture_list = QtWidgets.QTableWidget(0, 5)
        self.texture_list.setHorizontalHeaderLabels(
            [
                "File name",
                "Original",
                "Budget",
                "Required",
                "Paletted",
            ]
        )
        self.texture_list.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.texture_list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.texture_list.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.texture_list.verticalHeader().setVisible(False)
        header = self.texture_list.horizontalHeader()
        # Keep every column within the left pane.  ResizeToContents lets the
        # numeric column headings establish a combined minimum wider than the
        # pane, which leaves the file-name column (and users) horizontally
        # scrolled.  Stretching the sections shares the available viewport
        # width instead, while the item tooltips retain the full values.
        for column in range(self.texture_list.columnCount()):
            header.setSectionResizeMode(column, QtWidgets.QHeaderView.Stretch)
        self.texture_list.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.texture_list.currentCellChanged.connect(self._on_current_cell_changed)
        self.dirt_checkbox = QtWidgets.QCheckBox("Include dirt colors in optimization")
        self.dirt_checkbox.setToolTip(
            "Reserve the game-standard dirt colors #b29a71 and #9e825d in the "
            "optimized palette."
        )

        folder_controls.addWidget(self.folder_path_label, 1)
        folder_controls.addWidget(self.folder_btn)
        folder_controls.addWidget(self.refresh_folder_btn)
        top_card = QtWidgets.QFrame()
        top_card.setObjectName("sectionCard")
        top_card_layout = QtWidgets.QVBoxLayout(top_card)
        top_card_layout.setContentsMargins(10, 10, 10, 10)
        top_card_layout.setSpacing(8)
        top_title = QtWidgets.QLabel("Texture source")
        top_title.setObjectName("sectionTitle")
        top_card_layout.addWidget(top_title)
        top_card_layout.addLayout(folder_controls)
        left_panel.addWidget(top_card)
        left_panel.addWidget(self.texture_list, 1)

        center_panel = QtWidgets.QVBoxLayout()
        center_panel.setSpacing(10)
        preview_hint = QtWidgets.QLabel(
            "Scroll to zoom, drag to pan, click pixel to inspect palette index."
        )
        preview_hint.setWordWrap(True)
        self.orig_label = ZoomableImageLabel("Original RGB")
        self.orig_label.setMinimumSize(300, 250)
        self.quant_label = ZoomableImageLabel("Quantized Preview")
        self.quant_label.setMinimumSize(300, 250)
        self.fit_previews_btn = QtWidgets.QPushButton("Fit")
        self.fit_previews_btn.clicked.connect(self._fit_previews)
        self.reset_previews_btn = QtWidgets.QPushButton("Reset")
        self.reset_previews_btn.clicked.connect(self._reset_previews)
        self.highlight_checkbox = QtWidgets.QCheckBox("Highlight selected palette index in preview")
        self.highlight_checkbox.setChecked(True)
        self.highlight_checkbox.toggled.connect(self._refresh_current_preview)
        self.quant_label.image_clicked.connect(self._on_quantized_preview_clicked)
        self.orig_label.view_changed.connect(lambda: self._sync_preview_views(self.orig_label, self.quant_label))
        self.quant_label.view_changed.connect(lambda: self._sync_preview_views(self.quant_label, self.orig_label))
        center_panel.addWidget(preview_hint)
        previews = QtWidgets.QHBoxLayout()
        original_pane = QtWidgets.QVBoxLayout()
        original_pane.addWidget(self.orig_label, 1)
        quantized_pane = QtWidgets.QVBoxLayout()
        quantized_pane.addWidget(self.quant_label, 1)
        previews.addLayout(original_pane, 1)
        previews.addLayout(quantized_pane, 1)
        center_panel.addLayout(previews, 1)
        preview_controls = QtWidgets.QHBoxLayout()
        preview_controls.addWidget(self.fit_previews_btn)
        preview_controls.addWidget(self.reset_previews_btn)
        preview_controls.addStretch(1)
        center_panel.addLayout(preview_controls)
        right_panel = QtWidgets.QVBoxLayout()
        right_panel.setSpacing(10)
        self.palette_label = ClickablePaletteLabel()
        self.palette_label.setMinimumSize(96, 96)
        self.palette_label.setSizePolicy(
            QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred
        )
        self.palette_label.setAlignment(QtCore.Qt.AlignCenter)
        self.palette_label.setStyleSheet("background: #202020; padding: 2px;")
        self.palette_label.clicked.connect(self._on_palette_clicked)
        self.palette_label.resized.connect(self._refresh_palette_view)
        self.palette_details_label = QtWidgets.QLabel(
            "Palette selection: click a palette color tile to inspect index, hex, and RGB values."
        )
        self.palette_details_label.setWordWrap(True)
        palette_preview_card = QtWidgets.QFrame()
        palette_preview_card.setObjectName("sectionCard")
        palette_preview_layout = QtWidgets.QVBoxLayout(palette_preview_card)
        palette_preview_title = QtWidgets.QLabel("Palette")
        palette_preview_title.setObjectName("sectionTitle")
        palette_preview_layout.addWidget(palette_preview_title)
        palette_preview_layout.addWidget(self.palette_label, 1)
        palette_preview_layout.addWidget(self.palette_details_label)
        palette_preview_layout.addWidget(self.highlight_checkbox)
        center_panel.addWidget(palette_preview_card)
        self.compute_btn = QtWidgets.QPushButton("Generate Optimized Palette")
        self.compute_btn.setProperty("primary", True)
        self.compute_btn.clicked.connect(self.compute_palette)
        self.compute_hint_label = QtWidgets.QLabel()
        self.compute_hint_label.setWordWrap(True)
        self.save_btn = QtWidgets.QPushButton("Save Palette")
        self.save_btn.setProperty("secondary", True)
        self.save_btn.clicked.connect(self.save_palette_dialog)
        self.save_hint_label = QtWidgets.QLabel()
        self.save_hint_label.setWordWrap(True)
        self.compute_progress_label = QtWidgets.QLabel("Idle")
        self.compute_progress_label.setWordWrap(True)
        self.compute_progress_label.setStyleSheet("color: #4b5563;")
        self.compute_progress = QtWidgets.QProgressBar()
        self.compute_progress.setRange(0, 100)
        self.compute_progress.setValue(0)
        self.compute_progress.setFormat("%p%")
        self.compute_progress.setTextVisible(False)
        self.optimization_log = QtWidgets.QPlainTextEdit()
        self.optimization_log.setReadOnly(True)
        self.optimization_log.setPlaceholderText("Optimization log will appear here")
        self.optimization_log.setMaximumBlockCount(200)
        self.optimization_log.setMinimumHeight(120)
        palette_source_card = QtWidgets.QFrame()
        palette_source_card.setObjectName("sectionCard")
        palette_source_layout = QtWidgets.QVBoxLayout(palette_source_card)
        palette_source_layout.setContentsMargins(10, 10, 10, 10)
        palette_source_layout.setSpacing(8)
        palette_source_title = QtWidgets.QLabel("Base SUNNY palette (.pcx)")
        palette_source_title.setObjectName("sectionTitle")
        palette_source_layout.addWidget(palette_source_title)
        palette_path_row = QtWidgets.QHBoxLayout()
        self.palette_path_label = QtWidgets.QLabel("No palette selected")
        self.palette_path_label.setToolTip("No palette selected")
        self.palette_path_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self.palette_path_label.setStyleSheet("color: #4b5563;")
        self.palette_path_label.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        self.palette_path_browse_btn = QtWidgets.QPushButton("Browse…")
        self.palette_path_browse_btn.clicked.connect(self._select_base_palette)
        self.palette_path_recent_btn = QtWidgets.QToolButton()
        self.palette_path_recent_btn.setText("▼")
        self.palette_path_recent_btn.setToolTip("Recent palettes")
        self.palette_path_recent_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.palette_path_recent_btn.pressed.connect(self._show_recent_palette_menu)
        palette_path_row.addWidget(self.palette_path_label, 1)
        palette_path_row.addWidget(self.palette_path_browse_btn)
        palette_path_row.addWidget(self.palette_path_recent_btn)
        palette_source_layout.addLayout(palette_path_row)

        right_panel.addWidget(palette_source_card)
        right_panel.addWidget(self.dirt_checkbox)
        right_panel.addWidget(self.compute_btn)
        right_panel.addWidget(self.compute_hint_label)
        right_panel.addWidget(self.compute_progress_label)
        right_panel.addWidget(self.compute_progress)
        right_panel.addWidget(QtWidgets.QLabel("Optimization log"))
        right_panel.addWidget(self.optimization_log)
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

    def select_folder(self) -> None:
        start_dir = self.settings.last_texture_folder if self.settings.last_texture_folder else ""
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Select RGB Texture Folder", start_dir)
        if not folder:
            return
        self._load_folder(Path(folder))

    def _show_recent_palette_menu(self) -> None:
        menu = QtWidgets.QMenu(self.inline_fix_palette_btn)
        values = self.settings.get_recent_paths(self.RECENT_PALETTE_KEY)
        if not values:
            action = menu.addAction("No recent palettes")
            action.setEnabled(False)
        for value in values:
            action = menu.addAction(value)
            action.triggered.connect(lambda _checked=False, v=value: self._set_palette_path(v))
        self.inline_fix_palette_btn.setMenu(menu)
        if hasattr(self, "palette_path_recent_btn"):
            self.palette_path_recent_btn.setMenu(menu)

    def _set_palette_path(self, palette_path: str) -> None:
        resolved_palette = Path(palette_path).expanduser()
        self._last_sunny_palette_path = resolved_palette
        self.settings.last_sunny_palette = str(resolved_palette)
        self.settings.push_recent_path(self.RECENT_PALETTE_KEY, str(resolved_palette))
        self._save_settings()
        if hasattr(self, "palette_path_label"):
            self.palette_path_label.setText(str(resolved_palette))
            self.palette_path_label.setToolTip(str(resolved_palette))

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
        self.per_texture_required_unique_colors.clear()
        self.quantized_images.clear()
        self.indexed_images.clear()
        self.selected_palette_index = None
        self.texture_list.setRowCount(0)

        image_files = [
            p
            for p in sorted(folder.iterdir())
            if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".bmp"}
        ]
        if not image_files:
            QtWidgets.QMessageBox.warning(self, "No images", "No PNG/JPG/BMP files found in folder.")
            return

        equal_budget = max(1, OPTIMIZED_SLOTS // len(image_files))
        saved_budgets, saved_required_counts = self._read_folder_settings(resolved_folder)
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
            max_required = min(OPTIMIZED_SLOTS, self.texture_color_counts[path.name])
            required_count = saved_required_counts.get(path.name, 0)
            self.per_texture_required_unique_colors[path.name] = max(
                0, min(max_required, int(required_count))
            )
        self._refresh_texture_list()

        self.loaded_texture_folder = resolved_folder
        self.folder_path_label.setText(str(resolved_folder))
        self.folder_path_label.setToolTip(str(resolved_folder))
        self.settings.last_texture_folder = str(resolved_folder)
        self.settings.push_recent_path(self.RECENT_TEXTURE_FOLDER_KEY, str(resolved_folder))
        self._save_settings()
        self._write_folder_settings()
        self._update_action_states()

    def _on_budget_changed(self, texture_name: str, budget: int) -> None:
        self.per_texture_budget[texture_name] = budget
        self._persist_current_folder_budgets()

    def _on_required_unique_changed(self, texture_name: str, required_count: int) -> None:
        self.per_texture_required_unique_colors[texture_name] = required_count
        self._persist_current_folder_budgets()
        self.quantized_images.clear()
        self.indexed_images.clear()
        self.selected_palette_index = None
        self._update_action_states()

    def _sorted_texture_names(self) -> list[str]:
        return sorted(self.texture_images, key=str.lower)

    def _refresh_texture_list(self) -> None:
        selected_texture = self._current_texture_name()
        self.texture_list.setRowCount(0)
        for row, texture_name in enumerate(self._sorted_texture_names()):
            self.texture_list.insertRow(row)
            paletted_unique_color_count = self._paletted_unique_color_count(texture_name)
            file_item = QtWidgets.QTableWidgetItem(texture_name)
            file_item.setData(QtCore.Qt.UserRole, texture_name)
            original_item = QtWidgets.QTableWidgetItem(
                str(self.texture_color_counts.get(texture_name, 0))
            )
            paletted_item = QtWidgets.QTableWidgetItem(
                str(paletted_unique_color_count) if paletted_unique_color_count is not None else "—"
            )
            for column, item in ((0, file_item), (1, original_item), (4, paletted_item)):
                item.setFlags(item.flags() & ~QtCore.Qt.ItemIsEditable)
                self.texture_list.setItem(row, column, item)

            budget_edit = QtWidgets.QLineEdit(str(self.per_texture_budget[texture_name]))
            budget_edit.setValidator(QtGui.QIntValidator(1, OPTIMIZED_SLOTS, budget_edit))
            budget_edit.setToolTip(
                "Per-texture color budget: maximum optimized palette entries this texture can claim."
            )
            budget_edit.editingFinished.connect(
                lambda name=texture_name, edit=budget_edit: self._commit_budget_edit(name, edit)
            )
            self.texture_list.setCellWidget(row, 2, budget_edit)

            max_required = min(OPTIMIZED_SLOTS, self.texture_color_counts.get(texture_name, 0))
            required_edit = QtWidgets.QLineEdit(
                str(self.per_texture_required_unique_colors.get(texture_name, 0))
            )
            required_edit.setValidator(QtGui.QIntValidator(0, max_required, required_edit))
            required_edit.setToolTip(
                "Required paletted unique colors: the optimizer tries to make the quantized "
                "texture use at least this many palette indices."
            )
            required_edit.editingFinished.connect(
                lambda name=texture_name, edit=required_edit: self._commit_required_edit(name, edit)
            )
            self.texture_list.setCellWidget(row, 3, required_edit)
            paletted_tooltip = (
                str(paletted_unique_color_count) if paletted_unique_color_count is not None else "—"
            )
            tooltip = (
                f"Original unique colors: {self.texture_color_counts.get(texture_name, 0)}\n"
                "Required paletted unique colors: "
                f"{self.per_texture_required_unique_colors.get(texture_name, 0) or '—'}\n"
                f"Paletted unique colors: {paletted_tooltip}"
            )
            for column in (0, 1, 4):
                self.texture_list.item(row, column).setToolTip(tooltip)
        if self.texture_list.rowCount() == 0:
            self.orig_label.clear_base_pixmap("Original RGB")
            self.quant_label.clear_base_pixmap("Quantized Preview")
            return
        for row in range(self.texture_list.rowCount()):
            if self.texture_list.item(row, 0).text() == selected_texture:
                self.texture_list.selectRow(row)
                return
        self.texture_list.selectRow(0)

    def _commit_budget_edit(self, texture_name: str, edit: QtWidgets.QLineEdit) -> None:
        if edit.hasAcceptableInput():
            self._on_budget_changed(texture_name, int(edit.text()))
        else:
            edit.setText(str(self.per_texture_budget[texture_name]))

    def _commit_required_edit(self, texture_name: str, edit: QtWidgets.QLineEdit) -> None:
        if edit.hasAcceptableInput():
            self._on_required_unique_changed(texture_name, int(edit.text()))
        else:
            edit.setText(str(self.per_texture_required_unique_colors.get(texture_name, 0)))

    def _current_texture_name(self) -> str:
        row = self.texture_list.currentRow()
        if row < 0:
            return ""
        item = self.texture_list.item(row, 0)
        return item.text() if item is not None else ""

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
        self.settings.set_required_unique_colors_for_folder(
            self.loaded_texture_folder, self.per_texture_required_unique_colors
        )
        self._save_settings()
        self._write_folder_settings()

    def _read_folder_settings(self, folder: Path) -> tuple[dict[str, int], dict[str, int]]:
        """Load per-image values from the portable JSON file, falling back to old settings."""
        budgets = self.settings.budgets_for_folder(folder)
        required = self.settings.required_unique_colors_for_folder(folder)
        settings_path = folder / self.FOLDER_SETTINGS_FILENAME
        if not settings_path.is_file():
            return budgets, required
        try:
            payload = json.loads(settings_path.read_text(encoding="utf-8"))
            images = payload.get("images", [])
            budgets = {str(item["file"]): int(item["budget"]) for item in images}
            required = {str(item["file"]): int(item.get("required", 0)) for item in images}
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            self.statusBar().showMessage(f"Could not read {settings_path.name}; using saved defaults.", 5000)
        return budgets, required

    def _write_folder_settings(self) -> None:
        """Refresh the selected folder's image manifest and optimization values."""
        if self.loaded_texture_folder is None:
            return
        payload = {
            "images": [
                {
                    "file": name,
                    "budget": self.per_texture_budget[name],
                    "required": self.per_texture_required_unique_colors.get(name, 0),
                }
                for name in sorted(self.texture_images, key=str.lower)
            ]
        }
        settings_path = self.loaded_texture_folder / self.FOLDER_SETTINGS_FILENAME
        try:
            settings_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            self.statusBar().showMessage(f"Could not write {settings_path.name}: {exc}", 5000)

    def _update_action_states(self) -> None:
        folder_ok = self.loaded_texture_folder is not None and self.loaded_texture_folder.exists() and self.loaded_texture_folder.is_dir()
        has_textures = folder_ok and bool(self.texture_images)
        has_palette_path = self._last_sunny_palette_path is not None and self._last_sunny_palette_path.exists()
        has_quantized_results = bool(self.quantized_images)
        has_inline_error = self.inline_status_label.isVisible()

        self.compute_btn.setEnabled(has_textures and has_palette_path)
        self.save_btn.setEnabled(has_quantized_results)
        if has_textures and has_palette_path:
            self.compute_hint_label.setText("Step 2: Click Generate Optimized Palette when you are ready.")
        elif has_textures:
            self.compute_hint_label.setText("Missing: select a base SUNNY .pcx palette.")
        elif not folder_ok:
            self.compute_hint_label.setText("Missing: valid texture folder path.")
        else:
            self.compute_hint_label.setText("Missing: texture images (.png/.jpg/.jpeg/.bmp) in selected folder.")

        if has_quantized_results:
            self.save_hint_label.setText("Step 3: Save palette to write your optimized .pcx file.")
        else:
            self.save_hint_label.setText("Step 3: Save is enabled after a palette has been computed.")

    def _on_current_cell_changed(
        self, current_row: int, current_column: int, previous_row: int, previous_column: int
    ) -> None:
        _ = current_column, previous_row, previous_column
        if current_row < 0:
            return
        item = self.texture_list.item(current_row, 0)
        if item is not None:
            self._update_preview(item.text())

    def _to_pixmap(self, rgb_array: np.ndarray) -> QtGui.QPixmap:
        h, w, _ = rgb_array.shape
        image = QtGui.QImage(rgb_array.data, w, h, w * 3, QtGui.QImage.Format_RGB888)
        return QtGui.QPixmap.fromImage(image.copy())

    def _update_preview(self, texture_name: str) -> None:
        if not texture_name or texture_name not in self.texture_images:
            return
        orig = self.texture_images[texture_name]
        self.orig_label.set_base_pixmap(self._to_pixmap(orig))

        quant = self.quantized_images.get(texture_name)
        if quant is None:
            self.quant_label.clear_base_pixmap("Quantized Preview")
        else:
            quant_display = self._build_highlighted_quantized_preview(texture_name, quant)
            self.quant_label.set_base_pixmap(self._to_pixmap(quant_display))

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
        texture_name = self._current_texture_name()
        if texture_name:
            self._update_preview(texture_name)


    def _paletted_unique_color_count(self, texture_name: str) -> int | None:
        indexed = self.indexed_images.get(texture_name)
        if indexed is None:
            return None
        return self._count_unique_palette_indices(indexed)

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

    def _compute_palette_usage_counts(self) -> np.ndarray:
        counts = np.zeros(256, dtype=np.int64)
        for indexed_image in self.indexed_images.values():
            indices = np.asarray(indexed_image, dtype=np.int64).ravel()
            if indices.size == 0:
                continue
            valid_indices = indices[(0 <= indices) & (indices < 256)]
            if valid_indices.size == 0:
                continue
            counts += np.bincount(valid_indices, minlength=256)[:256]
        return counts

    def _refresh_palette_view(self) -> None:
        is_optimizing = self._optimization_preview_palette is not None
        palette = self._optimization_preview_palette if is_optimizing else self.current_palette
        usage_counts = self._compute_palette_usage_counts() if self.indexed_images and not is_optimizing else None
        image = visualize_palette(
            palette,
            selected_index=None if is_optimizing else self.selected_palette_index,
            usage_counts=usage_counts,
        )
        self._palette_image_size = image.width()
        self.palette_label.setPixmap(
            QtGui.QPixmap.fromImage(image).scaled(
                self.palette_label.size(),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.FastTransformation,
            )
        )

    def _show_optimization_palette_preview(
        self, fixed_palette: np.ndarray, candidate_colors: np.ndarray, message: str
    ) -> None:
        """Fill the optimized range with live, real clustering candidates."""
        colors = np.asarray(candidate_colors, dtype=np.uint8).reshape(-1, 3)
        if colors.size == 0:
            return
        preview = np.asarray(fixed_palette, dtype=np.uint8).copy()
        slot_count = OPTIMIZED_SLOTS - (2 if self.dirt_checkbox.isChecked() else 0)
        # Repeat early candidates so the whole reserved range stays lively; as more
        # groups arrive, each tile converges toward a distinct optimized color.
        tiled = np.resize(colors, (slot_count, 3))
        preview[OPTIMIZED_START : OPTIMIZED_START + slot_count] = tiled
        self._optimization_preview_palette = preview
        self.palette_details_label.setText(f"Optimizing: {message}")
        self._refresh_palette_view()
        QtWidgets.QApplication.processEvents()

    def _fit_previews(self) -> None:
        self.orig_label.fit_to_view()
        self._sync_preview_views(self.orig_label, self.quant_label)

    def _reset_previews(self) -> None:
        self.orig_label.reset_view()
        self._sync_preview_views(self.orig_label, self.quant_label)

    def _sync_preview_views(self, source: ZoomableImageLabel, target: ZoomableImageLabel) -> None:
        if self._syncing_previews:
            return
        self._syncing_previews = True
        try:
            target.copy_view_from(source)
        finally:
            self._syncing_previews = False

    def _append_optimization_log(self, message: str, percent: int, elapsed: float) -> None:
        clamped_percent = min(100, max(0, int(percent)))
        self.optimization_log.appendPlainText(
            f"[{elapsed:6.1f}s | {clamped_percent:3d}%] {message}"
        )
        self.optimization_log.verticalScrollBar().setValue(
            self.optimization_log.verticalScrollBar().maximum()
        )

    def compute_palette(self) -> None:
        if not self.texture_images:
            self._set_inline_status(
                "No textures are loaded.",
                level="warning",
                next_action="Select a texture folder.",
            )
            return

        palette_path = str(self._last_sunny_palette_path) if self._last_sunny_palette_path is not None else ""
        if palette_path and not Path(palette_path).exists():
            palette_path = ""
        if not palette_path:
            palette_path = self._prompt_for_palette_path()
            if not palette_path:
                self._set_inline_status(
                    "No base palette is selected.",
                    level="warning",
                    next_action="Select a base palette.",
                )
                self._update_action_states()
                return

        step_total = 4
        started_at = time.perf_counter()
        logged_messages: set[str] = set()
        self.optimization_log.clear()

        def set_progress(step_num: int, message: str, percent: int) -> None:
            elapsed = time.perf_counter() - started_at
            clamped_percent = min(100, max(0, int(percent)))
            progress_text = f"Step {step_num}/{step_total}: {message} ({elapsed:.1f}s)"
            self.compute_progress_label.setText(progress_text)
            self.compute_progress.setToolTip(progress_text)
            self.compute_progress.setValue(clamped_percent)
            if message and message not in logged_messages:
                logged_messages.add(message)
                self._append_optimization_log(message, clamped_percent, elapsed)
            QtWidgets.QApplication.processEvents()

        def make_phase_progress(
            step_num: int,
            start_percent: int,
            end_percent: int,
        ):
            span = end_percent - start_percent

            def update(message: str, fraction: float) -> None:
                percent = start_percent + round(span * min(1.0, max(0.0, fraction)))
                set_progress(step_num, message, percent)

            return update

        self.compute_btn.setEnabled(False)
        set_progress(1, "Loading base palette", 10)

        try:
            fixed_palette = load_sunny_palette(palette_path)
            self._optimization_preview_palette = fixed_palette.copy()
            self.palette_details_label.setText(
                "Optimizing: gathering texture colors into candidate groups…"
            )
            self._refresh_palette_view()
            resolved_palette = Path(palette_path).resolve()
            self._set_palette_path(str(resolved_palette))
            self._persist_current_folder_budgets()
            set_progress(2, "Preparing optimizer", 30)
            QtWidgets.QApplication.processEvents()

            optimizer_class = _get_optimizer_class()
            optimizer = optimizer_class(
                rgb_images=self.texture_images,
                per_texture_color_budget=self.per_texture_budget,
                fixed_palette=fixed_palette,
                per_texture_required_unique_colors=self.per_texture_required_unique_colors,
                dirt_present=self.dirt_checkbox.isChecked(),
                progress_callback=make_phase_progress(3, 30, 85),
                palette_preview_callback=lambda colors, message: self._show_optimization_palette_preview(
                    fixed_palette, colors, message
                ),
            )

            set_progress(3, "Starting optimized palette computation", 30)

            self.current_palette = optimizer.compute_palette()

            set_progress(4, "Building quantized previews", 85)
            optimizer.progress_callback = make_phase_progress(4, 85, 98)

            self.indexed_images, self.quantized_images = optimizer.compute_quantized_images(
                self.current_palette
            )
            self.selected_palette_index = None
        except Exception as exc:  # prototype surface
            self._optimization_preview_palette = None
            self.palette_details_label.setText(
                "Optimization stopped. The previous palette is shown."
            )
            self._refresh_palette_view()
            self.compute_progress.setValue(0)
            elapsed = time.perf_counter() - started_at
            failure_text = f"Failure after {elapsed:.1f}s"
            self.compute_progress_label.setText(failure_text)
            self.compute_progress.setToolTip(failure_text)
            palette_filename = Path(palette_path).name if palette_path else "<unknown>"
            self._set_inline_status(
                f"Optimization failed for {palette_filename}: {exc}",
                level="error",
                next_action="Pick a valid .pcx palette, then generate the optimized palette.",
            )
            return
        finally:
            self._update_action_states()

        self._clear_inline_status()
        self._optimization_preview_palette = None
        self.palette_details_label.setText(
            "Optimized palette ready. Click a color tile to inspect index, hex, and RGB values."
        )
        total_elapsed = time.perf_counter() - started_at
        self.compute_progress.setValue(100)
        success_text = f"Success in {total_elapsed:.1f}s"
        self.compute_progress_label.setText(success_text)
        self.compute_progress.setToolTip(success_text)

        self._refresh_texture_list()
        self._refresh_palette_view()
        texture_name = self._current_texture_name()
        if texture_name:
            self._update_preview(texture_name)
        self._update_action_states()


    def _on_quantized_preview_clicked(self, point: QtCore.QPoint) -> None:
        texture_name = self._current_texture_name()
        if not texture_name:
            return
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
        detail_parts = [
            f"Palette index: {index}",
            f"Hex: {hex_code}",
            f"RGB: ({rgb[0]}, {rgb[1]}, {rgb[2]})",
        ]
        if self.indexed_images:
            usage_counts = self._compute_palette_usage_counts()
            total_indexed_pixels = int(usage_counts.sum())
            usage_count = int(usage_counts[index])
            usage_percent = (
                usage_count / total_indexed_pixels * 100 if total_indexed_pixels else 0.0
            )
            detail_parts.append(
                f"Usage: {usage_count} pixels ({usage_percent:.2f}% of indexed pixels)"
            )
        self.palette_details_label.setText(" | ".join(detail_parts))

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
