"""Dialog for the 2-color track map preview controls."""

from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets

from track_viewer.rendering.track_map_renderer import (
    build_trk_map_image,
    compute_fit_scale,
)


class TrackMapPreviewDialog(QtWidgets.QDialog):
    """Preview dialog for the 2-color track map render."""

    def __init__(self, centerline: list[tuple[float, float]], parent=None) -> None:
        super().__init__(parent)
        self._centerline = centerline
        self._width = 183
        self._height = 86
        self._margin = 6

        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        self.setWindowTitle("Track Map Preview")

        self._image_label = QtWidgets.QLabel()
        self._image_label.setAlignment(QtCore.Qt.AlignCenter)
        self._image_label.setFrameShape(QtWidgets.QFrame.Box)

        self._rotation_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._rotation_slider.setRange(-180, 180)
        self._rotation_spin = QtWidgets.QSpinBox()
        self._rotation_spin.setRange(-180, 180)

        self._scale_spin = QtWidgets.QDoubleSpinBox()
        self._scale_spin.setDecimals(2)
        self._scale_spin.setRange(0.05, 10.0)
        self._scale_spin.setSingleStep(0.05)

        self._scale_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._scale_slider.setRange(5, 1000)
        self._scale_slider.setSingleStep(5)

        self._display_scale_spin = QtWidgets.QSpinBox()
        self._display_scale_spin.setRange(1, 6)
        self._display_scale_spin.setValue(2)

        fit_button = QtWidgets.QPushButton("Fit")
        fit_button.clicked.connect(self._handle_fit)

        self._rotation_slider.valueChanged.connect(self._rotation_spin.setValue)
        self._rotation_spin.valueChanged.connect(self._rotation_slider.setValue)
        self._rotation_spin.valueChanged.connect(self._refresh_image)

        self._scale_slider.valueChanged.connect(self._handle_scale_slider)
        self._scale_spin.valueChanged.connect(self._handle_scale_spin)

        self._display_scale_spin.valueChanged.connect(self._refresh_image)

        controls_layout = QtWidgets.QFormLayout()
        rotation_layout = QtWidgets.QHBoxLayout()
        rotation_layout.addWidget(self._rotation_slider)
        rotation_layout.addWidget(self._rotation_spin)
        controls_layout.addRow("Rotation", rotation_layout)

        scale_layout = QtWidgets.QHBoxLayout()
        scale_layout.addWidget(self._scale_slider)
        scale_layout.addWidget(self._scale_spin)
        scale_layout.addWidget(fit_button)
        controls_layout.addRow("Scale", scale_layout)

        controls_layout.addRow("Display size", self._display_scale_spin)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(controls_layout)
        layout.addWidget(self._image_label)
        self.setLayout(layout)

        self._set_initial_scale()
        self._refresh_image()

    def _set_initial_scale(self) -> None:
        fit_scale = compute_fit_scale(
            self._centerline,
            self._width,
            self._height,
            self._margin,
            angle_deg=0.0,
        )
        self._ensure_scale_range(fit_scale)
        self._scale_spin.setValue(max(fit_scale, 0.05))
        self._scale_slider.setValue(int(self._scale_spin.value() * 100))

    def _handle_fit(self) -> None:
        angle = float(self._rotation_spin.value())
        fit_scale = compute_fit_scale(
            self._centerline,
            self._width,
            self._height,
            self._margin,
            angle_deg=angle,
        )
        self._ensure_scale_range(fit_scale)
        self._scale_spin.setValue(max(fit_scale, 0.05))

    def _handle_scale_slider(self, value: int) -> None:
        scale = max(value / 100.0, 0.05)
        if abs(self._scale_spin.value() - scale) > 1e-3:
            self._scale_spin.setValue(scale)
        self._refresh_image()

    def _handle_scale_spin(self, value: float) -> None:
        slider_value = int(value * 100)
        if self._scale_slider.value() != slider_value:
            self._scale_slider.setValue(slider_value)
        self._refresh_image()

    def _ensure_scale_range(self, target_scale: float) -> None:
        max_scale = max(self._scale_spin.maximum(), target_scale * 1.25, 10.0)
        slider_max = max(5, int(max_scale * 100))
        if self._scale_spin.maximum() != max_scale:
            self._scale_spin.setMaximum(max_scale)
        if self._scale_slider.maximum() != slider_max:
            self._scale_slider.setMaximum(slider_max)

    def _refresh_image(self) -> None:
        scale = float(self._scale_spin.value())
        angle = float(self._rotation_spin.value())
        image = build_trk_map_image(
            self._centerline,
            width=self._width,
            height=self._height,
            margin=self._margin,
            scale=scale,
            angle_deg=angle,
        )
        pixmap = QtGui.QPixmap.fromImage(image)
        display_scale = self._display_scale_spin.value()
        if display_scale != 1:
            pixmap = pixmap.scaled(
                pixmap.width() * display_scale,
                pixmap.height() * display_scale,
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.FastTransformation,
            )
        self._image_label.setPixmap(pixmap)
        self._image_label.setFixedSize(pixmap.size())
        self.adjustSize()
