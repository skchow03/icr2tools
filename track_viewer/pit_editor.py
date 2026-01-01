"""Widgets for editing PIT parameters from the track TXT file."""
from __future__ import annotations

from PyQt5 import QtCore, QtWidgets

from track_viewer.pit_models import (
    PIT_DLONG_LINE_INDICES,
    PIT_PARAMETER_DEFINITIONS,
    PitParameters,
)


class PitParametersEditor(QtWidgets.QFrame):
    """Form-based editor for PIT lane parameters."""

    parametersChanged = QtCore.pyqtSignal()
    pitVisibilityChanged = QtCore.pyqtSignal(set)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._inputs: dict[str, QtWidgets.QAbstractSpinBox] = {}
        self._pit_visibility_checkboxes: dict[int, QtWidgets.QCheckBox] = {}
        self._build_ui()

    def _build_ui(self) -> None:
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        layout = QtWidgets.QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        form_layout = QtWidgets.QFormLayout()
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(6)

        for index, (field, label, tooltip, _is_integer) in enumerate(
            PIT_PARAMETER_DEFINITIONS
        ):
            input_widget: QtWidgets.QAbstractSpinBox = QtWidgets.QSpinBox()
            input_widget.setRange(-1_000_000_000, 1_000_000_000)
            input_widget.setSingleStep(1)
            input_widget.setToolTip(tooltip)
            if hasattr(input_widget, "valueChanged"):
                input_widget.valueChanged.connect(self.parametersChanged.emit)
            self._inputs[field] = input_widget
            label_widget = QtWidgets.QLabel(f"{index}: {label}")
            label_widget.setToolTip(tooltip)
            form_layout.addRow(label_widget, input_widget)

        layout.addLayout(form_layout)
        layout.addWidget(self._build_visibility_controls())
        self.setLayout(layout)

    def _build_visibility_controls(self) -> QtWidgets.QWidget:
        group = QtWidgets.QGroupBox("Pit DLONG line visibility")
        group.setToolTip(
            "Toggle which PIT DLONG parameters are drawn on the track diagram."
        )
        group_layout = QtWidgets.QVBoxLayout()
        group_layout.setContentsMargins(6, 6, 6, 6)
        group_layout.setSpacing(4)
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        columns = 4
        for idx, param_index in enumerate(PIT_DLONG_LINE_INDICES):
            checkbox = QtWidgets.QCheckBox(f"Index {param_index}")
            checkbox.setChecked(True)
            checkbox.toggled.connect(self._handle_pit_visibility_changed)
            self._pit_visibility_checkboxes[param_index] = checkbox
            row = idx // columns
            col = idx % columns
            grid.addWidget(checkbox, row, col)
        group_layout.addLayout(grid)
        group.setLayout(group_layout)
        return group

    def _handle_pit_visibility_changed(self, _checked: bool) -> None:
        self.pitVisibilityChanged.emit(self.pit_visible_indices())

    def set_parameters(self, parameters: PitParameters | None) -> None:
        enabled = parameters is not None
        for field, _, _, _is_integer in PIT_PARAMETER_DEFINITIONS:
            widget = self._inputs[field]
            with QtCore.QSignalBlocker(widget):
                widget.setEnabled(enabled)
                if not enabled:
                    widget.setValue(0)
                    continue
                value = getattr(parameters, field)
                widget.setValue(int(round(value)))

    def parameters(self) -> PitParameters | None:
        if not all(widget.isEnabled() for widget in self._inputs.values()):
            return None
        values: list[float] = []
        for field, _, _, _is_integer in PIT_PARAMETER_DEFINITIONS:
            widget = self._inputs[field]
            values.append(float(widget.value()))
        return PitParameters.from_values(values)

    def pit_visible_indices(self) -> set[int]:
        return {
            index
            for index, checkbox in self._pit_visibility_checkboxes.items()
            if checkbox.isChecked()
        }

    def set_pit_visible_indices(self, indices: set[int]) -> None:
        for index, checkbox in self._pit_visibility_checkboxes.items():
            with QtCore.QSignalBlocker(checkbox):
                checkbox.setChecked(index in indices)
