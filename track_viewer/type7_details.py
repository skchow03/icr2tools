"""Type 7 parameter display and editing widget."""
from __future__ import annotations

from typing import Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.cam.helpers import CameraPosition
from track_viewer.ui_loader import load_ui


class Type7Details(QtWidgets.QGroupBox):
    """Displays Type 7 parameters and allows editing of extra fields."""

    parametersChanged = QtCore.pyqtSignal()

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        super().__init__(parent)
        load_ui(self, "type7_details.ui")
        self._camera: Optional[CameraPosition] = None
        self._controls: dict[str, tuple[QtWidgets.QLineEdit, QtWidgets.QSlider]] = {}

        self._register_integer_control(
            "z_axis_rotation", self.z_axis_rotation_field, self.z_axis_rotation_slider
        )
        self._register_integer_control(
            "vertical_rotation",
            self.vertical_rotation_field,
            self.vertical_rotation_slider,
        )
        self._register_integer_control("tilt", self.tilt_field, self.tilt_slider)
        self._register_integer_control("zoom", self.zoom_field, self.zoom_slider)
        self._register_integer_control(
            "unknown1", self.unknown1_field, self.unknown1_slider
        )
        self._register_integer_control(
            "unknown2", self.unknown2_field, self.unknown2_slider
        )
        self._register_integer_control(
            "unknown3", self.unknown3_field, self.unknown3_slider
        )
        self._register_integer_control(
            "unknown4", self.unknown4_field, self.unknown4_slider
        )

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
        for attr, (field, slider) in self._controls.items():
            value = getattr(params, attr)
            with QtCore.QSignalBlocker(field):
                field.setText(str(value))
            with QtCore.QSignalBlocker(slider):
                slider.setValue(int(value))
        self.setEnabled(True)
        self.setVisible(True)

    def _clear_fields(self) -> None:
        for field, slider in self._controls.values():
            with QtCore.QSignalBlocker(field):
                field.clear()
            with QtCore.QSignalBlocker(slider):
                slider.setValue(slider.minimum())

    def _register_integer_control(
        self, attr: str, field: QtWidgets.QLineEdit, slider: QtWidgets.QSlider
    ) -> None:
        field.setValidator(QtGui.QIntValidator(-2**31, 2**31 - 1, field))
        field.editingFinished.connect(
            lambda f=field, a=attr: self._handle_field_changed(f, a)
        )
        slider.setRange(-2**31, 2**31 - 1)
        slider.setSingleStep(1)
        slider.valueChanged.connect(
            lambda value, a=attr: self._handle_slider_changed(value, a)
        )

        self._controls[attr] = (field, slider)

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
        slider = self._controls[attr][1]
        with QtCore.QSignalBlocker(slider):
            slider.setValue(value)
        self.parametersChanged.emit()

    def _handle_slider_changed(self, value: int, attr: str) -> None:
        if self._camera is None or self._camera.type7 is None:
            return
        setattr(self._camera.type7, attr, value)
        field = self._controls[attr][0]
        with QtCore.QSignalBlocker(field):
            field.setText(str(value))
        self.parametersChanged.emit()

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
        slider = self._controls[attr][1]
        with QtCore.QSignalBlocker(slider):
            slider.setValue(int(value))
