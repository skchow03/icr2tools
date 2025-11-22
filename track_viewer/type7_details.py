"""Type 7 parameter display widget."""
from __future__ import annotations

from typing import Optional

from PyQt5 import QtCore, QtWidgets

from icr2_core.cam.helpers import CameraPosition


class Type7Details(QtWidgets.QGroupBox):
    """Displays Type 7 parameters in a read-only form."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__("Type 7 parameters", parent)
        self._camera: Optional[CameraPosition] = None

        layout = QtWidgets.QFormLayout()
        layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)

        self._z_rotation = self._create_readonly_field()
        self._vertical_rotation = self._create_readonly_field()
        self._tilt = self._create_readonly_field()
        self._zoom = self._create_readonly_field()

        layout.addRow("Z-axis rotation", self._z_rotation)
        layout.addRow("Vertical rotation", self._vertical_rotation)
        layout.addRow("Tilt", self._tilt)
        layout.addRow("Zoom", self._zoom)

        self.setLayout(layout)
        self.setEnabled(False)

    def set_camera(
        self, index: Optional[int], camera: Optional[CameraPosition]
    ) -> None:
        self._camera = camera
        if camera is None or camera.camera_type != 7 or camera.type7 is None:
            self._clear_fields()
            self.setEnabled(False)
            return

        params = camera.type7
        self._z_rotation.setText(str(params.z_axis_rotation))
        self._vertical_rotation.setText(str(params.vertical_rotation))
        self._tilt.setText(str(params.tilt))
        self._zoom.setText(str(params.zoom))
        self.setEnabled(True)

    def _clear_fields(self) -> None:
        for field in (self._z_rotation, self._vertical_rotation, self._tilt, self._zoom):
            field.clear()

    def _create_readonly_field(self) -> QtWidgets.QLineEdit:
        field = QtWidgets.QLineEdit()
        field.setReadOnly(True)
        field.setFocusPolicy(QtCore.Qt.ClickFocus)
        return field
