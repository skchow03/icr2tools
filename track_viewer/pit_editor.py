"""Widgets for editing PIT parameters from the track TXT file."""
from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets

from track_viewer.pit_models import (
    PIT_DLONG_LINE_INDICES,
    PIT_DLONG_LINE_COLORS,
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
        table = QtWidgets.QTableWidget()
        table.setColumnCount(4)
        table.setRowCount(len(PIT_PARAMETER_DEFINITIONS))
        table.setHorizontalHeaderLabels(["Index", "Parameter", "Value", "Visible"])
        table.horizontalHeader().setStretchLastSection(False)
        table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.Stretch
        )
        table.horizontalHeader().setSectionResizeMode(
            2, QtWidgets.QHeaderView.ResizeToContents
        )
        table.horizontalHeader().setSectionResizeMode(
            3, QtWidgets.QHeaderView.ResizeToContents
        )
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.setSizeAdjustPolicy(
            QtWidgets.QAbstractScrollArea.AdjustToContents
        )
        table.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

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
            index_item = QtWidgets.QTableWidgetItem(str(index))
            index_item.setFlags(QtCore.Qt.ItemIsEnabled)
            table.setItem(index, 0, index_item)

            label_widget = QtWidgets.QLabel(label)
            label_widget.setToolTip(tooltip)
            color = PIT_DLONG_LINE_COLORS.get(index)
            if color:
                label_widget.setStyleSheet(self._legend_style(color))
            table.setCellWidget(index, 1, label_widget)

            table.setCellWidget(index, 2, input_widget)

            if index in PIT_DLONG_LINE_INDICES:
                checkbox = QtWidgets.QCheckBox()
                checkbox.setChecked(True)
                checkbox.toggled.connect(self._handle_pit_visibility_changed)
                self._pit_visibility_checkboxes[index] = checkbox
                checkbox_container = QtWidgets.QWidget()
                checkbox_layout = QtWidgets.QHBoxLayout(checkbox_container)
                checkbox_layout.setContentsMargins(0, 0, 0, 0)
                checkbox_layout.setAlignment(QtCore.Qt.AlignCenter)
                checkbox_layout.addWidget(checkbox)
                table.setCellWidget(index, 3, checkbox_container)

        table.resizeRowsToContents()
        header_height = table.horizontalHeader().height()
        row_height = table.verticalHeader().length()
        table.setFixedHeight(
            header_height + row_height + table.frameWidth() * 2
        )
        layout.addWidget(table)
        self.setLayout(layout)

    @staticmethod
    def _legend_style(color: str) -> str:
        qcolor = QtGui.QColor(color)
        if not qcolor.isValid():
            return ""
        luminance = (
            0.299 * qcolor.red()
            + 0.587 * qcolor.green()
            + 0.114 * qcolor.blue()
        ) / 255.0
        if luminance > 0.7:
            return (
                f"color: {color}; background-color: #424242; padding: 1px 4px;"
                " border-radius: 2px;"
            )
        return f"color: {color};"

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
