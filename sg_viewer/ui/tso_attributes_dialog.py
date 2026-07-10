from __future__ import annotations

from PyQt5 import QtCore, QtWidgets

from sg_viewer.io.track3d_parser import calculate_track3d_xy_bounding_box
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
        self._is_sprite_checkbox = QtWidgets.QCheckBox("Sprite object")
        self._sprite_width_spin = QtWidgets.QDoubleSpinBox()
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

        for spin in (
            self._bbox_length_spin,
            self._bbox_width_spin,
            self._sprite_width_spin,
        ):
            spin.setRange(0, 1_000_000_000)

        self._rotation_point_combo.addItem("Center", ROTATION_POINT_CENTER)
        self._rotation_point_combo.addItem("Top-left corner", ROTATION_POINT_TOP_LEFT)
        self._rotation_point_combo.addItem("Top-right corner", ROTATION_POINT_TOP_RIGHT)
        self._rotation_point_combo.addItem(
            "Bottom-left corner", ROTATION_POINT_BOTTOM_LEFT
        )
        self._rotation_point_combo.addItem(
            "Bottom-right corner", ROTATION_POINT_BOTTOM_RIGHT
        )

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
        bbox_length_layout = QtWidgets.QHBoxLayout()
        bbox_length_layout.setContentsMargins(0, 0, 0, 0)
        bbox_length_layout.addWidget(self._bbox_length_spin)
        self._bbox_from_3d_button = QtWidgets.QPushButton("Load from .3D…")
        bbox_length_layout.addWidget(self._bbox_from_3d_button)
        bbox_length_widget = QtWidgets.QWidget()
        bbox_length_widget.setLayout(bbox_length_layout)
        form.addRow(self._bbox_length_label, bbox_length_widget)
        form.addRow(self._bbox_width_label, self._bbox_width_spin)
        self._bbox_from_3d_button.clicked.connect(self._load_bbox_from_track3d)
        self._sprite_width_label = QtWidgets.QLabel()
        form.addRow("Shape", self._is_sprite_checkbox)
        form.addRow(self._sprite_width_label, self._sprite_width_spin)
        form.addRow("Rotation point", self._rotation_point_combo)
        self._is_sprite_checkbox.toggled.connect(self._update_shape_controls)

        self._matching_filename_note = QtWidgets.QLabel(
            "BBox, sprite, and rotation point fields apply to all TSOs with the "
            "same filename."
        )
        self._matching_filename_note.setWordWrap(True)

        buttons = QtWidgets.QDialogButtonBox()
        apply_button = buttons.addButton("Apply", QtWidgets.QDialogButtonBox.ApplyRole)
        close_button = buttons.addButton(QtWidgets.QDialogButtonBox.Close)
        apply_button.clicked.connect(self._apply_changes)
        close_button.clicked.connect(self.close)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self._matching_filename_note)
        layout.addWidget(buttons)
        self.set_measurement_unit(self._measurement_unit)

    def set_measurement_unit(self, unit: str) -> None:
        previous_unit = self._measurement_unit
        bbox_length_500ths = units_to_500ths(
            float(self._bbox_length_spin.value()), previous_unit
        )
        bbox_width_500ths = units_to_500ths(
            float(self._bbox_width_spin.value()), previous_unit
        )
        sprite_width_500ths = units_to_500ths(
            float(self._sprite_width_spin.value()), previous_unit
        )

        self._measurement_unit = unit
        unit_label = measurement_unit_label(unit)
        decimals = max(4, measurement_unit_decimals(unit))
        step = measurement_unit_step(unit)
        self._bbox_length_label.setText(f"BBox Length ({unit_label})")
        self._bbox_width_label.setText(f"BBox Width ({unit_label})")
        self._sprite_width_label.setText(f"Sprite Width ({unit_label})")
        for spin in (
            self._bbox_length_spin,
            self._bbox_width_spin,
            self._sprite_width_spin,
        ):
            spin.setDecimals(decimals)
            spin.setSingleStep(step)

        self._bbox_length_spin.setValue(
            units_from_500ths(float(bbox_length_500ths), unit)
        )
        self._bbox_width_spin.setValue(
            units_from_500ths(float(bbox_width_500ths), unit)
        )
        self._sprite_width_spin.setValue(
            units_from_500ths(float(sprite_width_500ths), unit)
        )
        self._update_shape_controls()

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
        self._bbox_length_spin.setValue(
            units_from_500ths(float(obj.bbox_length), self._measurement_unit)
        )
        self._bbox_width_spin.setValue(
            units_from_500ths(float(obj.bbox_width), self._measurement_unit)
        )
        self._is_sprite_checkbox.setChecked(bool(obj.is_sprite))
        self._sprite_width_spin.setValue(
            units_from_500ths(float(obj.sprite_width), self._measurement_unit)
        )
        rotation_point = normalize_rotation_point(obj.rotation_point)
        index = self._rotation_point_combo.findData(rotation_point)
        self._rotation_point_combo.setCurrentIndex(index if index >= 0 else 0)
        self._update_shape_controls()
        self.setWindowTitle(f"TSO Attributes — __TSO{row_index}")

    def _load_bbox_from_track3d(self) -> None:
        path, _selected_filter = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Open .3D File",
            "",
            "ICR2 3D Files (*.3D *.3d);;All Files (*)",
        )
        if not path:
            return
        try:
            bbox = calculate_track3d_xy_bounding_box(path)
        except (OSError, ValueError) as exc:
            QtWidgets.QMessageBox.warning(
                self, "Load BBox from .3D", f"Could not read bounding box:\n{exc}"
            )
            return

        selected_values = self._confirm_track3d_bbox_units(bbox)
        if selected_values is None:
            return

        length_value, width_value = selected_values
        self._bbox_length_spin.setValue(length_value)
        self._bbox_width_spin.setValue(width_value)
        self._apply_changes()

    def _confirm_track3d_bbox_units(self, bbox) -> tuple[float, float] | None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("Use .3D Bounding Box")

        unit_combo = QtWidgets.QComboBox(dialog)
        unit_options = (
            ("500ths", "500ths"),
            ("Feet", "feet"),
            ("Inches", "inch"),
            ("Meters", "meter"),
        )
        for label, unit in unit_options:
            unit_combo.addItem(label, unit)

        current_index = unit_combo.findData(self._measurement_unit)
        unit_combo.setCurrentIndex(current_index if current_index >= 0 else 0)

        extents_label = QtWidgets.QLabel(
            "The selected .3D file contains these X/Y extents:\n\n"
            f"Minimum X: {bbox.min_x:g}\n"
            f"Maximum X: {bbox.max_x:g}\n"
            f"Minimum Y: {bbox.min_y:g}\n"
            f"Maximum Y: {bbox.max_y:g}"
        )
        extents_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

        result_label = QtWidgets.QLabel()
        result_label.setWordWrap(True)

        def update_result_label() -> None:
            source_unit = str(unit_combo.currentData() or "500ths")
            length_value, width_value = self._track3d_bbox_values_for_source_unit(
                bbox, source_unit
            )
            display_unit_label = measurement_unit_label(self._measurement_unit)
            result_label.setText(
                f"Set BBox Length to {length_value:g} {display_unit_label} and "
                f"BBox Width to {width_value:g} {display_unit_label} for this object?"
            )

        unit_combo.currentIndexChanged.connect(update_result_label)
        update_result_label()

        form = QtWidgets.QFormLayout()
        form.addRow(".3D file units", unit_combo)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)

        layout = QtWidgets.QVBoxLayout(dialog)
        layout.addWidget(extents_label)
        layout.addLayout(form)
        layout.addWidget(result_label)
        layout.addWidget(buttons)

        if dialog.exec_() != QtWidgets.QDialog.Accepted:
            return None

        source_unit = str(unit_combo.currentData() or "500ths")
        return self._track3d_bbox_values_for_source_unit(bbox, source_unit)

    def _track3d_bbox_values_for_source_unit(
        self, bbox, source_unit: str
    ) -> tuple[float, float]:
        length_500ths = units_to_500ths(float(bbox.length), source_unit)
        width_500ths = units_to_500ths(float(bbox.width), source_unit)
        return (
            units_from_500ths(float(length_500ths), self._measurement_unit),
            units_from_500ths(float(width_500ths), self._measurement_unit),
        )

    def _apply_changes(self) -> None:
        obj = self._build_object_from_form()
        if obj is None or self._row_index is None:
            return
        self._applying_changes = True
        self.objectUpdated.emit(int(self._row_index), obj)
        self._applying_changes = False

    def _build_object_from_form(
        self, *, warn_on_missing_filename: bool = True
    ) -> TracksideObject | None:
        if self._row_index is None:
            return None
        filename = normalize_trackside_filename(self._filename_edit.text())
        if not filename:
            if warn_on_missing_filename:
                QtWidgets.QMessageBox.warning(
                    self, "TSO Attributes", "Filename is required."
                )
            return None
        return TracksideObject(
            filename=filename,
            x=int(self._x_spin.value()),
            y=int(self._y_spin.value()),
            z=int(self._z_spin.value()),
            yaw=int(self._yaw_spin.value()),
            pitch=int(self._pitch_spin.value()),
            tilt=int(self._tilt_spin.value()),
            description=self._description_edit.text().strip(),
            bbox_length=max(
                0,
                units_to_500ths(
                    float(self._bbox_length_spin.value()), self._measurement_unit
                ),
            ),
            bbox_width=max(
                0,
                units_to_500ths(
                    float(self._bbox_width_spin.value()), self._measurement_unit
                ),
            ),
            rotation_point=normalize_rotation_point(
                str(self._rotation_point_combo.currentData() or "")
            ),
            is_sprite=bool(self._is_sprite_checkbox.isChecked()),
            sprite_width=max(
                0,
                units_to_500ths(
                    float(self._sprite_width_spin.value()), self._measurement_unit
                ),
            ),
        )

    def _update_shape_controls(self) -> None:
        is_sprite = bool(self._is_sprite_checkbox.isChecked())
        for widget in (
            self._bbox_length_label,
            self._bbox_length_spin,
            self._bbox_from_3d_button,
            self._bbox_width_label,
            self._bbox_width_spin,
            self._rotation_point_combo,
        ):
            widget.setEnabled(not is_sprite)
        self._sprite_width_label.setEnabled(is_sprite)
        self._sprite_width_spin.setEnabled(is_sprite)

    def _emit_preview_update(self) -> None:
        obj = self._build_object_from_form(warn_on_missing_filename=False)
        if obj is None or self._row_index is None:
            return
        self.objectPreviewUpdated.emit(int(self._row_index), obj)

    def closeEvent(self, event: QtCore.QEvent) -> None:
        if not self._applying_changes:
            self.previewEnded.emit()
        super().closeEvent(event)
