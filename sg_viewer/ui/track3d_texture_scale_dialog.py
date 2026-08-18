"""Options dialog for scaling track .3D texture coordinates."""

from PyQt5 import QtWidgets


class Track3DTextureScaleDialog(QtWidgets.QDialog):
    """Collect the MIP, scale factor, and coordinate axes in one dialog."""

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Scale Track Texture Resolution")

        self.mip_name_edit = QtWidgets.QLineEdit()
        self.factor_spin = QtWidgets.QDoubleSpinBox()
        self.factor_spin.setRange(0.000001, 1_000_000.0)
        self.factor_spin.setDecimals(6)
        self.factor_spin.setValue(2.0)

        self.scale_u_checkbox = QtWidgets.QCheckBox("Scale U")
        self.scale_v_checkbox = QtWidgets.QCheckBox("Scale V")
        self.scale_u_checkbox.setChecked(True)
        self.scale_v_checkbox.setChecked(True)
        axes = QtWidgets.QHBoxLayout()
        axes.addWidget(self.scale_u_checkbox)
        axes.addWidget(self.scale_v_checkbox)
        axes.addStretch()

        form = QtWidgets.QFormLayout(self)
        form.addRow("MIP file name:", self.mip_name_edit)
        form.addRow("Texture coordinate scale factor:", self.factor_spin)
        form.addRow("Coordinates:", axes)

        self.buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        form.addRow(self.buttons)

        self.mip_name_edit.textChanged.connect(self._update_ok_button)
        self.scale_u_checkbox.toggled.connect(self._update_ok_button)
        self.scale_v_checkbox.toggled.connect(self._update_ok_button)
        self._update_ok_button()

    def _update_ok_button(self) -> None:
        self.buttons.button(QtWidgets.QDialogButtonBox.Ok).setEnabled(
            bool(self.mip_name.strip()) and (self.scale_u or self.scale_v)
        )

    @property
    def mip_name(self) -> str:
        return self.mip_name_edit.text().strip()

    @property
    def factor(self) -> float:
        return self.factor_spin.value()

    @property
    def scale_u(self) -> bool:
        return self.scale_u_checkbox.isChecked()

    @property
    def scale_v(self) -> bool:
        return self.scale_v_checkbox.isChecked()
