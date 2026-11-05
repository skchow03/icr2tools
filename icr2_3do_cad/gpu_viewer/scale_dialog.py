"""Uniform model-scale prompt for the editable N3 GPU Viewer."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QVBoxLayout,
)

from gpu_viewer.source_scale import scale_multiplier


class ScaleModelDialog(QDialog):
    """Explicit scale direction and decimal operand, no changes until Apply."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Scale .3D model")
        self.setMinimumWidth(420)
        outer = QVBoxLayout(self)
        introduction = QLabel(
            "Scale the entire model uniformly about the origin (0, 0, 0). "
            "All vertex XYZ coordinates are updated. Related inline plane "
            "points, DYNAMIC positions, sprite sizes and SWITCH DISTANCE "
            "thresholds are adjusted to keep the scene consistent.")
        introduction.setWordWrap(True)
        outer.addWidget(introduction)

        form = QFormLayout()
        self.operation = QComboBox()
        self.operation.addItem("Multiply coordinates by", "multiply")
        self.operation.addItem("Divide coordinates by", "divide")
        form.addRow("Operation:", self.operation)
        self.factor = QLineEdit("2")
        self.factor.setObjectName("scaleFactor")
        self.factor.setPlaceholderText("e.g. 2, 0.5, 6000")
        form.addRow("Value:", self.factor)
        outer.addLayout(form)

        self.preview = QLabel()
        self.preview.setObjectName("scalePreview")
        self.preview.setWordWrap(True)
        outer.addWidget(self.preview)
        details = QLabel(
            "Texture UVs, polygon colors, rotations and material names are "
            "left unchanged. External .3DO objects are not resized. "
            "The change is a single Undo operation; saving is separate.")
        details.setWordWrap(True)
        outer.addWidget(details)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.apply_button.setText("Scale model")
        self.apply_button.setObjectName("applyScale")
        self.cancel_button = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        self.cancel_button.setDefault(True)
        self.cancel_button.setAutoDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        self.factor.textChanged.connect(self._update_preview)
        self.operation.currentIndexChanged.connect(self._update_preview)
        self._update_preview()

    @property
    def factor_text(self):
        return self.factor.text().strip()

    @property
    def divide(self):
        return self.operation.currentData() == "divide"

    def _update_preview(self):
        try:
            effective = scale_multiplier(self.factor_text, divide=self.divide)
            if effective == 1:
                raise ValueError("Enter a value other than 1.")
            self.preview.setText(
                f"Coordinates will be multiplied by {effective}. "
                "An integer-valued N3 model will retain integer Papyrus "
                "coordinates (rounded when needed).")
            self.apply_button.setEnabled(True)
        except ValueError as exc:
            self.preview.setText(str(exc))
            self.apply_button.setEnabled(False)
