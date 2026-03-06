from __future__ import annotations

from PyQt5 import QtCore, QtWidgets

from sg_viewer.services.trackside_objects import (
    ROTATION_POINT_BOTTOM_LEFT,
    ROTATION_POINT_BOTTOM_RIGHT,
    ROTATION_POINT_CENTER,
    ROTATION_POINT_TOP_LEFT,
    ROTATION_POINT_TOP_RIGHT,
    TracksideObject,
    normalize_rotation_point,
    normalize_trackside_filename,
)


class TracksideObjectAttributesDialog(QtWidgets.QDialog):
    objectUpdated = QtCore.pyqtSignal(int, object)

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("TSO Attributes")
        self.setModal(False)
        self.setWindowModality(QtCore.Qt.NonModal)
        self._row_index: int | None = None

        form = QtWidgets.QFormLayout()
        self._filename_edit = QtWidgets.QLineEdit()
        self._x_spin = QtWidgets.QSpinBox()
        self._y_spin = QtWidgets.QSpinBox()
        self._z_spin = QtWidgets.QSpinBox()
        self._yaw_slider = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self._yaw_spin = QtWidgets.QSpinBox()
        self._pitch_spin = QtWidgets.QSpinBox()
        self._tilt_spin = QtWidgets.QSpinBox()
        self._description_edit = QtWidgets.QLineEdit()
        self._bbox_length_spin = QtWidgets.QSpinBox()
        self._bbox_width_spin = QtWidgets.QSpinBox()
        self._rotation_point_combo = QtWidgets.QComboBox()

        for spin in (
            self._x_spin,
            self._y_spin,
            self._z_spin,
            self._pitch_spin,
            self._tilt_spin,
        ):
            spin.setRange(-1_000_000_000, 1_000_000_000)
        self._yaw_spin.setRange(-1800, 1800)
        self._yaw_slider.setRange(-1800, 1800)
        self._yaw_slider.setSingleStep(1)
        self._yaw_slider.setPageStep(10)
        self._yaw_slider.setTickInterval(100)
        self._yaw_slider.setTickPosition(QtWidgets.QSlider.TicksBelow)
        self._yaw_slider.valueChanged.connect(self._yaw_spin.setValue)
        self._yaw_spin.valueChanged.connect(self._yaw_slider.setValue)

        for spin in (self._bbox_length_spin, self._bbox_width_spin):
            spin.setRange(0, 1_000_000_000)

        self._rotation_point_combo.addItem("Center", ROTATION_POINT_CENTER)
        self._rotation_point_combo.addItem("Top-left corner", ROTATION_POINT_TOP_LEFT)
        self._rotation_point_combo.addItem("Top-right corner", ROTATION_POINT_TOP_RIGHT)
        self._rotation_point_combo.addItem("Bottom-left corner", ROTATION_POINT_BOTTOM_LEFT)
        self._rotation_point_combo.addItem("Bottom-right corner", ROTATION_POINT_BOTTOM_RIGHT)

        yaw_layout = QtWidgets.QHBoxLayout()
        yaw_layout.setContentsMargins(0, 0, 0, 0)
        yaw_layout.addWidget(self._yaw_slider)
        yaw_layout.addWidget(self._yaw_spin)
        yaw_widget = QtWidgets.QWidget()
        yaw_widget.setLayout(yaw_layout)

        form.addRow("Filename", self._filename_edit)
        form.addRow("X (500ths)", self._x_spin)
        form.addRow("Y (500ths)", self._y_spin)
        form.addRow("Z (500ths)", self._z_spin)
        form.addRow("Yaw (tenths)", yaw_widget)
        form.addRow("Pitch (tenths)", self._pitch_spin)
        form.addRow("Tilt (tenths)", self._tilt_spin)
        form.addRow("Description", self._description_edit)
        form.addRow("BBox Length", self._bbox_length_spin)
        form.addRow("BBox Width", self._bbox_width_spin)
        form.addRow("Rotation point", self._rotation_point_combo)

        buttons = QtWidgets.QDialogButtonBox()
        apply_button = buttons.addButton("Apply", QtWidgets.QDialogButtonBox.ApplyRole)
        close_button = buttons.addButton(QtWidgets.QDialogButtonBox.Close)
        apply_button.clicked.connect(self._apply_changes)
        close_button.clicked.connect(self.close)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def edit_object(self, row_index: int, obj: TracksideObject) -> None:
        self._row_index = row_index
        self._filename_edit.setText(normalize_trackside_filename(obj.filename))
        self._x_spin.setValue(int(obj.x))
        self._y_spin.setValue(int(obj.y))
        self._z_spin.setValue(int(obj.z))
        self._yaw_spin.setValue(int(obj.yaw))
        self._pitch_spin.setValue(int(obj.pitch))
        self._tilt_spin.setValue(int(obj.tilt))
        self._description_edit.setText(obj.description)
        self._bbox_length_spin.setValue(int(obj.bbox_length))
        self._bbox_width_spin.setValue(int(obj.bbox_width))
        rotation_point = normalize_rotation_point(obj.rotation_point)
        index = self._rotation_point_combo.findData(rotation_point)
        self._rotation_point_combo.setCurrentIndex(index if index >= 0 else 0)
        self.setWindowTitle(f"TSO Attributes — __TSO{row_index}")

    def _apply_changes(self) -> None:
        if self._row_index is None:
            return
        filename = normalize_trackside_filename(self._filename_edit.text())
        if not filename:
            QtWidgets.QMessageBox.warning(self, "TSO Attributes", "Filename is required.")
            return
        obj = TracksideObject(
            filename=filename,
            x=int(self._x_spin.value()),
            y=int(self._y_spin.value()),
            z=int(self._z_spin.value()),
            yaw=int(self._yaw_spin.value()),
            pitch=int(self._pitch_spin.value()),
            tilt=int(self._tilt_spin.value()),
            description=self._description_edit.text().strip(),
            bbox_length=int(self._bbox_length_spin.value()),
            bbox_width=int(self._bbox_width_spin.value()),
            rotation_point=normalize_rotation_point(str(self._rotation_point_combo.currentData() or "")),
        )
        self.objectUpdated.emit(int(self._row_index), obj)
