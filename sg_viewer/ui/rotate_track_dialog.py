from __future__ import annotations

from PyQt5 import QtCore, QtWidgets


class RotateTrackDialog(QtWidgets.QDialog):
    """Dialog with a live slider for rotating the whole track around origin."""

    angleChanged = QtCore.pyqtSignal(float)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Rotate Track")

        self._slider = QtWidgets.QSlider(QtCore.Qt.Horizontal, self)
        self._slider.setRange(-1800, 1800)
        self._slider.setSingleStep(1)
        self._slider.setPageStep(50)
        self._slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self._slider.setTickInterval(300)

        self._angle_label = QtWidgets.QLabel(self)
        self._update_label(0.0)

        self._slider.valueChanged.connect(self._on_slider_changed)

        form = QtWidgets.QFormLayout()
        form.addRow("Rotation angle:", self._angle_label)
        form.addRow(self._slider)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def angle_degrees(self) -> float:
        return float(self._slider.value()) / 10.0

    def _on_slider_changed(self, value: int) -> None:
        angle = float(value) / 10.0
        self._update_label(angle)
        self.angleChanged.emit(angle)

    def _update_label(self, angle: float) -> None:
        self._angle_label.setText(f"{angle:+.1f}°")
