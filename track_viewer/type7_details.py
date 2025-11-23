"""Type 7 parameter display and editing widget."""
from __future__ import annotations

from typing import Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.cam.helpers import CameraPosition


class Type7Details(QtWidgets.QGroupBox):
    """Displays Type 7 parameters and allows editing of extra fields."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__("Type 7 parameters", parent)
        self._camera: Optional[CameraPosition] = None
        self._field_attrs: dict[QtWidgets.QLineEdit, str] = {}

        layout = QtWidgets.QFormLayout()
        layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.ExpandingFieldsGrow)

        self._z_rotation = self._create_integer_field("z_axis_rotation")
        self._vertical_rotation = self._create_integer_field("vertical_rotation")
        self._tilt = self._create_integer_field("tilt")
        self._zoom = self._create_integer_field("zoom")
        self._unknown1 = self._create_integer_field("unknown1")
        self._unknown2 = self._create_integer_field("unknown2")
        self._unknown3 = self._create_integer_field("unknown3")
        self._unknown4 = self._create_integer_field("unknown4")

        layout.addRow("Z-axis rotation", self._z_rotation)
        layout.addRow("Vertical rotation", self._vertical_rotation)
        layout.addRow("Tilt", self._tilt)
        layout.addRow("Zoom", self._zoom)
        layout.addRow("Unknown 1", self._unknown1)
        layout.addRow("Unknown 2", self._unknown2)
        layout.addRow("Unknown 3", self._unknown3)
        layout.addRow("Unknown 4", self._unknown4)

        self.setLayout(layout)
        self.setEnabled(False)
        self.setVisible(False)

    def set_camera(
        self, index: Optional[int], camera: Optional[CameraPosition]
    ) -> None:
        self._camera = camera
        if camera is None or camera.camera_type != 7 or camera.type7 is None:
            self._clear_fields()
            self.setEnabled(False)
            self.setVisible(False)
            return

        params = camera.type7
        for field, attr in self._field_attrs.items():
            value = getattr(params, attr)
            with QtCore.QSignalBlocker(field):
                field.setText(str(value))
        self.setEnabled(True)
        self.setVisible(True)

    def _clear_fields(self) -> None:
        for field in self._field_attrs:
            field.clear()

    def _create_integer_field(self, attr: str) -> QtWidgets.QLineEdit:
        field = QtWidgets.QLineEdit()
        field.setValidator(QtGui.QIntValidator(-2**31, 2**31 - 1, field))
        field.editingFinished.connect(
            lambda f=field, a=attr: self._handle_field_changed(f, a)
        )
        self._field_attrs[field] = attr
        return field

    def _handle_field_changed(self, field: QtWidgets.QLineEdit, attr: str) -> None:
        if self._camera is None or self._camera.type7 is None:
            return

        text = field.text().strip()
        try:
            value = int(text)
        except ValueError:
            self._restore_field(field, attr)
            return

        setattr(self._camera.type7, attr, value)

    def _restore_field(self, field: QtWidgets.QLineEdit, attr: str) -> None:
        if self._camera is None or self._camera.type7 is None:
            field.clear()
            return
        params = self._camera.type7
        value = getattr(params, attr, None)
        if value is None:
            return
        with QtCore.QSignalBlocker(field):
            field.setText(str(value))
