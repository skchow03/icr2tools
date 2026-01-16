"""AI control widgets for the track viewer tabs."""
from __future__ import annotations

from PyQt5 import QtCore, QtWidgets


class AiControlsWidget(QtWidgets.QWidget):
    """Composite widget for AI visualization controls."""

    def __init__(self, window: QtWidgets.QWidget) -> None:
        super().__init__()
        self._window = window
        self._build_ui()

    def _build_ui(self) -> None:
        window = self._window
        window._ai_gradient_button = QtWidgets.QCheckBox(
            "Show AI Speed Gradient"
        )
        window._ai_gradient_button.toggled.connect(
            window._toggle_ai_gradient
        )

        window._ai_acceleration_button = QtWidgets.QCheckBox(
            "Show AI Acceleration Gradient"
        )
        window._ai_acceleration_button.toggled.connect(
            window._toggle_ai_acceleration_gradient
        )

        window._accel_window_label = QtWidgets.QLabel()
        window._accel_window_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        window._accel_window_slider.setRange(1, 12)
        window._accel_window_slider.setSingleStep(1)
        window._accel_window_slider.setPageStep(1)
        window._accel_window_slider.setValue(
            window.preview_api.ai_acceleration_window()
        )
        window._accel_window_slider.setFixedWidth(120)
        window._accel_window_slider.valueChanged.connect(
            window._handle_accel_window_changed
        )
        window._update_accel_window_label(window._accel_window_slider.value())

        window._ai_width_label = QtWidgets.QLabel()
        window._ai_width_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        window._ai_width_slider.setRange(1, 8)
        window._ai_width_slider.setSingleStep(1)
        window._ai_width_slider.setPageStep(1)
        window._ai_width_slider.setValue(window.preview_api.ai_line_width())
        window._ai_width_slider.setFixedWidth(120)
        window._ai_width_slider.valueChanged.connect(
            window._handle_ai_line_width_changed
        )
        window._update_ai_line_width_label(window._ai_width_slider.value())

        window._ai_color_mode = "none"
        window._update_ai_color_mode("none")

        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        ai_speed_layout = QtWidgets.QHBoxLayout()
        ai_speed_layout.addWidget(window._ai_gradient_button)
        ai_speed_layout.addStretch(1)
        ai_speed_layout.addWidget(window._ai_width_label)
        ai_speed_layout.addWidget(window._ai_width_slider)
        layout.addLayout(ai_speed_layout)

        accel_layout = QtWidgets.QHBoxLayout()
        accel_layout.addWidget(window._ai_acceleration_button)
        accel_layout.addStretch(1)
        accel_layout.addWidget(window._accel_window_label)
        accel_layout.addWidget(window._accel_window_slider)
        layout.addLayout(accel_layout)

        self.setLayout(layout)
