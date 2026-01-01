"""Widgets for editing PIT parameters from the track TXT file."""
from __future__ import annotations

from PyQt5 import QtCore, QtWidgets

from track_viewer.pit_models import PIT_PARAMETER_DEFINITIONS, PitParameters


class PitParametersEditor(QtWidgets.QFrame):
    """Form-based editor for PIT lane parameters."""

    parametersChanged = QtCore.pyqtSignal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._inputs: dict[str, QtWidgets.QAbstractSpinBox] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        form_layout = QtWidgets.QFormLayout()
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(6)

        for field, label, tooltip, is_integer in PIT_PARAMETER_DEFINITIONS:
            if is_integer:
                input_widget: QtWidgets.QAbstractSpinBox = QtWidgets.QSpinBox()
                input_widget.setRange(-1_000_000_000, 1_000_000_000)
                input_widget.setSingleStep(1)
            else:
                input_widget = QtWidgets.QDoubleSpinBox()
                input_widget.setDecimals(2)
                input_widget.setRange(-1_000_000_000.0, 1_000_000_000.0)
                input_widget.setSingleStep(1.0)
            input_widget.setToolTip(tooltip)
            if hasattr(input_widget, "valueChanged"):
                input_widget.valueChanged.connect(self.parametersChanged.emit)
            self._inputs[field] = input_widget
            label_widget = QtWidgets.QLabel(label)
            label_widget.setToolTip(tooltip)
            form_layout.addRow(label_widget, input_widget)

        layout.addLayout(form_layout)
        self.setLayout(layout)

    def set_parameters(self, parameters: PitParameters | None) -> None:
        enabled = parameters is not None
        for field, _, _, is_integer in PIT_PARAMETER_DEFINITIONS:
            widget = self._inputs[field]
            with QtCore.QSignalBlocker(widget):
                widget.setEnabled(enabled)
                if not enabled:
                    if isinstance(widget, QtWidgets.QDoubleSpinBox):
                        widget.setValue(0.0)
                    else:
                        widget.setValue(0)
                    continue
                value = getattr(parameters, field)
                if is_integer:
                    widget.setValue(int(value))
                else:
                    widget.setValue(float(value))

    def parameters(self) -> PitParameters | None:
        if not all(widget.isEnabled() for widget in self._inputs.values()):
            return None
        values: list[float] = []
        for field, _, _, is_integer in PIT_PARAMETER_DEFINITIONS:
            widget = self._inputs[field]
            if is_integer:
                values.append(float(widget.value()))
            else:
                values.append(float(widget.value()))
        return PitParameters.from_values(values)
