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
from sg_viewer.ui.altitude_units import units_from_500ths, units_to_500ths
from sg_viewer.ui.presentation.units_presenter import (
    measurement_unit_decimals,
    measurement_unit_label,
    measurement_unit_step,
)


class TracksideObjectAttributesDialog(QtWidgets.QDialog):
    objectUpdated = QtCore.pyqtSignal(int, object)
    objectPreviewUpdated = QtCore.pyqtSignal(int, object)
    previewEnded = QtCore.pyqtSignal()

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("TSO Attributes")
        self.setModal(False)
        self.setWindowModality(QtCore.Qt.NonModal)
        self._row_index: int | None = None
        self._applying_changes = False
        self._measurement_unit = "500ths"

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
        self._bbox_length_spin = QtWidgets.QDoubleSpinBox()
        self._bbox_width_spin = QtWidgets.QDoubleSpinBox()
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
        self._yaw_spin.valueChanged.connect(self._emit_preview_update)

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
        self._bbox_length_label = QtWidgets.QLabel()
        self._bbox_width_label = QtWidgets.QLabel()
        form.addRow(self._bbox_length_label, self._bbox_length_spin)
        form.addRow(self._bbox_width_label, self._bbox_width_spin)
        form.addRow("Rotation point", self._rotation_point_combo)

        buttons = QtWidgets.QDialogButtonBox()
        apply_button = buttons.addButton("Apply", QtWidgets.QDialogButtonBox.ApplyRole)
        close_button = buttons.addButton(QtWidgets.QDialogButtonBox.Close)
        apply_button.clicked.connect(self._apply_changes)
        close_button.clicked.connect(self.close)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)
        self.set_measurement_unit(self._measurement_unit)

    def set_measurement_unit(self, unit: str) -> None:
        previous_unit = self._measurement_unit
        bbox_length_500ths = units_to_500ths(float(self._bbox_length_spin.value()), previous_unit)
        bbox_width_500ths = units_to_500ths(float(self._bbox_width_spin.value()), previous_unit)

        self._measurement_unit = unit
        unit_label = measurement_unit_label(unit)
        decimals = max(4, measurement_unit_decimals(unit))
        step = measurement_unit_step(unit)
        self._bbox_length_label.setText(f"BBox Length ({unit_label})")
        self._bbox_width_label.setText(f"BBox Width ({unit_label})")
        for spin in (self._bbox_length_spin, self._bbox_width_spin):
            spin.setDecimals(decimals)
            spin.setSingleStep(step)

        self._bbox_length_spin.setValue(units_from_500ths(float(bbox_length_500ths), unit))
        self._bbox_width_spin.setValue(units_from_500ths(float(bbox_width_500ths), unit))

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
        self._bbox_length_spin.setValue(units_from_500ths(float(obj.bbox_length), self._measurement_unit))
        self._bbox_width_spin.setValue(units_from_500ths(float(obj.bbox_width), self._measurement_unit))
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
            bbox_length=max(0, units_to_500ths(float(self._bbox_length_spin.value()), self._measurement_unit)),
            bbox_width=max(0, units_to_500ths(float(self._bbox_width_spin.value()), self._measurement_unit)),
            rotation_point=normalize_rotation_point(str(self._rotation_point_combo.currentData() or "")),
        )
        self._applying_changes = True
        self.objectUpdated.emit(int(self._row_index), obj)
        self._applying_changes = False

    def _emit_preview_update(self) -> None:
        if self._row_index is None:
            return
        filename = normalize_trackside_filename(self._filename_edit.text())
        if not filename:
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
            bbox_length=max(0, units_to_500ths(float(self._bbox_length_spin.value()), self._measurement_unit)),
            bbox_width=max(0, units_to_500ths(float(self._bbox_width_spin.value()), self._measurement_unit)),
            rotation_point=normalize_rotation_point(str(self._rotation_point_combo.currentData() or "")),
        )
        self.objectPreviewUpdated.emit(int(self._row_index), obj)

    def closeEvent(self, event: QtCore.QEvent) -> None:
        if not self._applying_changes:
            self.previewEnded.emit()
        super().closeEvent(event)
