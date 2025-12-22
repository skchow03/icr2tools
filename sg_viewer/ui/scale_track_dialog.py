from __future__ import annotations

from PyQt5 import QtWidgets


class ScaleTrackDialog(QtWidgets.QDialog):
    """Dialog for scaling a closed-loop track to a desired length."""

    def __init__(self, parent: QtWidgets.QWidget | None, current_length_500ths: float) -> None:
        super().__init__(parent)
        self.setWindowTitle("Scale Track to Length")

        miles = current_length_500ths / (500.0 * 12 * 5280)

        self._current_label = QtWidgets.QLabel(
            f"Current length: {current_length_500ths:.0f} DLONG (500ths) — {miles:.3f} miles"
        )
        self._length_500ths = QtWidgets.QDoubleSpinBox()
        self._length_500ths.setRange(1.0, 1_000_000_000.0)
        self._length_500ths.setDecimals(2)
        self._length_500ths.setValue(current_length_500ths)

        self._length_miles = QtWidgets.QDoubleSpinBox()
        self._length_miles.setRange(0.001, 10_000.0)
        self._length_miles.setDecimals(3)
        self._length_miles.setValue(miles)

        self._length_500ths.valueChanged.connect(self._sync_miles_from_500ths)
        self._length_miles.valueChanged.connect(self._sync_500ths_from_miles)

        form = QtWidgets.QFormLayout()
        form.addRow(self._current_label)
        form.addRow("Desired length (DLONG 500ths):", self._length_500ths)
        form.addRow("Desired length (miles):", self._length_miles)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def get_target_length(self) -> float:
        """Return the desired length in DLONG (500ths of a foot)."""

        return float(self._length_500ths.value())

    def _sync_miles_from_500ths(self, value: float) -> None:
        miles = value / (500.0 * 12 * 5280)
        self._length_miles.blockSignals(True)
        self._length_miles.setValue(miles)
        self._length_miles.blockSignals(False)

    def _sync_500ths_from_miles(self, value: float) -> None:
        dlongs = value * 500.0 * 12 * 5280
        self._length_500ths.blockSignals(True)
        self._length_500ths.setValue(dlongs)
        self._length_500ths.blockSignals(False)
