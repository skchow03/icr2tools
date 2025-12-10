from __future__ import annotations

from PyQt5 import QtWidgets


class BackgroundImageDialog(QtWidgets.QDialog):
    def __init__(
        self,
        parent: QtWidgets.QWidget | None,
        pixels_to_500ths: float,
        origin_u: float,
        origin_v: float,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Background Image Settings")

        self._scale_field = QtWidgets.QDoubleSpinBox()
        self._scale_field.setRange(0.01, 1_000_000.0)
        self._scale_field.setDecimals(4)
        self._scale_field.setValue(pixels_to_500ths)
        self._scale_field.setSuffix(" 500ths/px")

        self._origin_u_field = QtWidgets.QDoubleSpinBox()
        self._origin_u_field.setRange(-1_000_000_000_000.0, 1_000_000_000_000.0)
        self._origin_u_field.setDecimals(0)
        self._origin_u_field.setSingleStep(1)
        self._origin_u_field.setValue(origin_u)

        self._origin_v_field = QtWidgets.QDoubleSpinBox()
        self._origin_v_field.setRange(-1_000_000_000_000.0, 1_000_000_000_000.0)
        self._origin_v_field.setDecimals(0)
        self._origin_v_field.setSingleStep(1)
        self._origin_v_field.setValue(origin_v)

        form = QtWidgets.QFormLayout()
        form.addRow("500ths per pixel:", self._scale_field)
        form.addRow("U at pixel 0,0:", self._origin_u_field)
        form.addRow("V at pixel 0,0:", self._origin_v_field)

        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout()
        layout.addLayout(form)
        layout.addWidget(button_box)
        self.setLayout(layout)

    def get_values(self) -> tuple[float, float, float]:
        return (
            float(self._scale_field.value()),
            float(self._origin_u_field.value()),
            float(self._origin_v_field.value()),
        )
