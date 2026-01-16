"""Track map preview dialog."""
from __future__ import annotations

from typing import Callable

from PyQt5 import QtCore, QtGui, QtWidgets


class TrackMapPreviewDialog(QtWidgets.QDialog):
    """Dialog that previews a track map with zoom and fit controls."""

    _ZOOM_LEVELS = [50, 75, 100, 125, 150, 200, 250, 300]

    def __init__(
        self,
        parent: QtWidgets.QWidget,
        pixmap: QtGui.QPixmap,
        rebuild_pixmap: Callable[[bool, int], QtGui.QPixmap] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        self.setWindowTitle("Track Map Preview")
        self._pixmap = pixmap
        self._rebuild_pixmap = rebuild_pixmap
        self._flip_marker = False
        self._rotation_steps = 0

        self._fit_checkbox = QtWidgets.QCheckBox("Fit to window")
        self._fit_checkbox.setChecked(True)
        self._fit_checkbox.toggled.connect(self._handle_fit_toggled)

        zoom_label = QtWidgets.QLabel("Zoom")
        self._zoom_combo = QtWidgets.QComboBox()
        for zoom in self._ZOOM_LEVELS:
            self._zoom_combo.addItem(f"{zoom}%")
        self._zoom_combo.setCurrentText("100%")
        self._zoom_combo.currentIndexChanged.connect(self._handle_zoom_changed)
        self._zoom_combo.setEnabled(False)

        self._flip_button = QtWidgets.QPushButton("Flip Start/Finish")
        self._flip_button.clicked.connect(self._handle_flip_clicked)

        self._rotate_button = QtWidgets.QPushButton("Rotate Clockwise")
        self._rotate_button.clicked.connect(self._handle_rotate_clicked)

        controls_layout = QtWidgets.QHBoxLayout()
        controls_layout.addWidget(self._fit_checkbox)
        controls_layout.addSpacing(12)
        controls_layout.addWidget(zoom_label)
        controls_layout.addWidget(self._zoom_combo)
        controls_layout.addSpacing(12)
        controls_layout.addWidget(self._flip_button)
        controls_layout.addWidget(self._rotate_button)
        controls_layout.addStretch()

        self._label = QtWidgets.QLabel()
        self._label.setAlignment(QtCore.Qt.AlignCenter)
        self._label.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Ignored
        )

        self._scroll_area = QtWidgets.QScrollArea()
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setWidget(self._label)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(controls_layout)
        layout.addWidget(self._scroll_area)

        self._set_initial_size()
        self._update_pixmap()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        QtCore.QTimer.singleShot(0, self._update_pixmap)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        if self._fit_checkbox.isChecked():
            self._update_pixmap()

    def _set_initial_size(self) -> None:
        screen = self.screen()
        geometry = (
            screen.availableGeometry()
            if screen is not None
            else QtWidgets.QApplication.primaryScreen().availableGeometry()
        )
        max_width = int(geometry.width() * 0.8)
        max_height = int(geometry.height() * 0.8)
        target_width = min(max_width, max(480, self._pixmap.width()))
        target_height = min(max_height, max(360, self._pixmap.height()))
        self.resize(target_width, target_height)

    def _current_zoom_factor(self) -> float:
        text = self._zoom_combo.currentText().rstrip("%")
        zoom = int(text) if text else 100
        return zoom / 100.0

    def _handle_fit_toggled(self, checked: bool) -> None:
        self._zoom_combo.setEnabled(not checked)
        self._update_pixmap()

    def _handle_zoom_changed(self) -> None:
        if not self._fit_checkbox.isChecked():
            self._update_pixmap()

    def _handle_flip_clicked(self) -> None:
        self._flip_marker = not self._flip_marker
        if self._rebuild_pixmap is None:
            return
        self._pixmap = self._rebuild_pixmap(self._flip_marker, self._rotation_steps)
        self._update_pixmap()

    def _handle_rotate_clicked(self) -> None:
        self._rotation_steps = (self._rotation_steps + 1) % 4
        if self._rebuild_pixmap is None:
            return
        self._pixmap = self._rebuild_pixmap(self._flip_marker, self._rotation_steps)
        self._update_pixmap()

    def _update_pixmap(self) -> None:
        if self._pixmap.isNull():
            return
        if self._fit_checkbox.isChecked():
            size = self._scroll_area.viewport().size()
            if size.width() <= 0 or size.height() <= 0:
                return
            scaled = self._pixmap.scaled(
                size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.FastTransformation
            )
        else:
            zoom = self._current_zoom_factor()
            scaled_size = QtCore.QSize(
                max(1, int(self._pixmap.width() * zoom)),
                max(1, int(self._pixmap.height() * zoom)),
            )
            scaled = self._pixmap.scaled(
                scaled_size,
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.FastTransformation,
            )
        self._label.setPixmap(scaled)
        self._label.resize(scaled.size())
