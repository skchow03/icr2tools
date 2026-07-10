from __future__ import annotations

from typing import TypeAlias

from PyQt5 import QtCore, QtWidgets

from sg_viewer.ui.altitude_units import units_from_500ths, units_to_500ths
from sg_viewer.ui.presentation.units_presenter import measurement_unit_decimals, measurement_unit_label
from sg_viewer.services.tsd_objects import (
    TsdDashedLinesObject,
    TsdDoubleSolidLineObject,
    TsdPitStallsObject,
    TsdTransverseLineObject,
    TsdZebraCrossingObject,
)

TsdObjectPayload: TypeAlias = (
    TsdZebraCrossingObject
    | TsdTransverseLineObject
    | TsdDoubleSolidLineObject
    | TsdDashedLinesObject
    | TsdPitStallsObject
)


class _DistanceSpinBox(QtWidgets.QDoubleSpinBox):
    def __init__(self, unit: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._unit = unit
        self.setDecimals(measurement_unit_decimals(unit))
        self.setSingleStep(1.0)

    def setRange(self, minimum: float, maximum: float) -> None:  # noqa: N802 - Qt override
        super().setRange(
            units_from_500ths(float(minimum), self._unit),
            units_from_500ths(float(maximum), self._unit),
        )

    def setValue(self, value: float) -> None:  # noqa: N802 - Qt override
        super().setValue(units_from_500ths(float(value), self._unit))

    def value_500ths(self) -> int:
        return units_to_500ths(float(super().value()), self._unit)


def _measurement_unit_for_parent(parent: QtWidgets.QWidget) -> str:
    widget: QtWidgets.QWidget | None = parent
    while widget is not None:
        current_unit = getattr(widget, "current_measurement_unit", None)
        if callable(current_unit):
            return str(current_unit())
        combo = getattr(widget, "measurement_units_combo", None)
        if combo is not None:
            if callable(combo):
                combo = combo()
            current_data = getattr(combo, "currentData", None)
            if callable(current_data):
                return str(current_data())
        widget = widget.parentWidget()
    return "500ths"


def _create_distance_spin(parent: QtWidgets.QWidget) -> _DistanceSpinBox:
    return _DistanceSpinBox(_measurement_unit_for_parent(parent), parent)


def _distance_value_500ths(spin: _DistanceSpinBox) -> int:
    return spin.value_500ths()


class TsdObjectDialog:
    def __init__(
        self,
        parent: QtWidgets.QWidget,
        controller: object,
        *,
        object_count: int,
        selected_section_index: int | None,
        existing: TsdObjectPayload | None = None,
    ) -> None:
        self._parent = parent
        self._controller = controller
        self._object_count = object_count
        self._selected_section_index = selected_section_index
        self._existing = existing

    def get_payload(
        self,
        *,
        existing: TsdZebraCrossingObject | TsdTransverseLineObject | TsdDoubleSolidLineObject | TsdDashedLinesObject | TsdPitStallsObject | None = None,
    ) -> TsdZebraCrossingObject | TsdTransverseLineObject | TsdDoubleSolidLineObject | TsdDashedLinesObject | TsdPitStallsObject | None:
        existing = self._existing
        dialog = QtWidgets.QDialog(self._parent)
        dialog.setModal(False)
        dialog.setWindowModality(QtCore.Qt.NonModal)
        dialog.setWindowTitle("TSD Object Attributes")
        layout = QtWidgets.QFormLayout(dialog)
        type_combo = QtWidgets.QComboBox(dialog)
        type_combo.addItem("Zebra crossing", userData="zebra_crossing")
        type_combo.addItem("Transverse Line", userData="transverse_line")
        type_combo.addItem("Double Solid Line", userData="double_solid_line")
        type_combo.addItem("Dashed Lines", userData="dashed_lines")
        type_combo.addItem("Pit Stalls", userData="pit_stalls")
        default_index = self._object_count + 1
        default_name = "TSD Object"
        if isinstance(existing, TsdZebraCrossingObject):
            default_name = f"Zebra Crossing {default_index}"
            type_combo.setCurrentIndex(0)
            type_combo.setEnabled(False)
        elif isinstance(existing, TsdTransverseLineObject):
            default_name = f"Transverse Line {default_index}"
            type_combo.setCurrentIndex(1)
            type_combo.setEnabled(False)
        elif isinstance(existing, TsdDoubleSolidLineObject):
            default_name = f"Double Solid Line {default_index}"
            type_combo.setCurrentIndex(2)
            type_combo.setEnabled(False)
        elif isinstance(existing, TsdDashedLinesObject):
            default_name = f"Dashed Lines {default_index}"
            type_combo.setCurrentIndex(3)
            type_combo.setEnabled(False)
        elif isinstance(existing, TsdPitStallsObject):
            default_name = f"Pit Stalls {default_index}"
            type_combo.setCurrentIndex(4)
            type_combo.setEnabled(False)
        name_edit = QtWidgets.QLineEdit(existing.name if existing else default_name, dialog)
        start_dlong_spin = _create_distance_spin(dialog)
        start_dlong_spin.setRange(-2_000_000_000, 2_000_000_000)
        start_dlong_spin.setValue(existing.start_dlong if isinstance(existing, TsdZebraCrossingObject) else 0)
        right_dlat_spin = _create_distance_spin(dialog)
        right_dlat_spin.setRange(-2_000_000_000, 2_000_000_000)
        right_dlat_spin.setValue(existing.right_dlat if isinstance(existing, TsdZebraCrossingObject) else -20000)
        left_dlat_spin = _create_distance_spin(dialog)
        left_dlat_spin.setRange(-2_000_000_000, 2_000_000_000)
        left_dlat_spin.setValue(existing.left_dlat if isinstance(existing, TsdZebraCrossingObject) else 20000)
        stripe_width_spin = _create_distance_spin(dialog)
        stripe_width_spin.setRange(1, 2_000_000_000)
        stripe_width_spin.setValue(existing.stripe_width_500ths if isinstance(existing, TsdZebraCrossingObject) else 4000)
        stripe_length_spin = _create_distance_spin(dialog)
        stripe_length_spin.setRange(1, 2_000_000_000)
        stripe_length_spin.setValue(existing.stripe_length_500ths if isinstance(existing, TsdZebraCrossingObject) else 28000)
        stripe_spacing_spin = _create_distance_spin(dialog)
        stripe_spacing_spin.setRange(0, 2_000_000_000)
        stripe_spacing_spin.setValue(existing.stripe_spacing_500ths if isinstance(existing, TsdZebraCrossingObject) else 3000)
        right_margin_spin = _create_distance_spin(dialog)
        right_margin_spin.setRange(0, 2_000_000_000)
        right_margin_spin.setValue(existing.right_margin_500ths if isinstance(existing, TsdZebraCrossingObject) else 0)
        left_margin_spin = _create_distance_spin(dialog)
        left_margin_spin.setRange(0, 2_000_000_000)
        left_margin_spin.setValue(existing.left_margin_500ths if isinstance(existing, TsdZebraCrossingObject) else 0)
        transverse_line_enabled = QtWidgets.QCheckBox("Draw at crosswalk ends", dialog)
        transverse_line_enabled.setChecked(
            isinstance(existing, TsdZebraCrossingObject)
            and int(existing.transverse_line_thickness_500ths) > 0
        )
        transverse_line_thickness_spin = _create_distance_spin(dialog)
        transverse_line_thickness_spin.setRange(1, 2_000_000_000)
        transverse_line_thickness_spin.setValue(
            existing.transverse_line_thickness_500ths
            if isinstance(existing, TsdZebraCrossingObject) and int(existing.transverse_line_thickness_500ths) > 0
            else 4000
        )
        adjusted_dlong_spin = _create_distance_spin(dialog)
        adjusted_dlong_spin.setRange(-2_000_000_000, 2_000_000_000)
        adjusted_dlong_spin.setValue(existing.adjusted_dlong if isinstance(existing, TsdTransverseLineObject) else 0)
        start_adjusted_dlong_spin = _create_distance_spin(dialog)
        start_adjusted_dlong_spin.setRange(-2_000_000_000, 2_000_000_000)
        start_adjusted_dlong_spin.setValue(
            existing.start_adjusted_dlong if isinstance(existing, TsdDoubleSolidLineObject) else 0
        )
        end_adjusted_dlong_spin = _create_distance_spin(dialog)
        end_adjusted_dlong_spin.setRange(-2_000_000_000, 2_000_000_000)
        end_adjusted_dlong_spin.setValue(
            existing.end_adjusted_dlong if isinstance(existing, TsdDoubleSolidLineObject) else 20000
        )
        dlat_spin = _create_distance_spin(dialog)
        dlat_spin.setRange(-2_000_000_000, 2_000_000_000)
        dlat_spin.setValue(existing.dlat if isinstance(existing, TsdDoubleSolidLineObject) else 0)
        right_dlat_bound_spin = _create_distance_spin(dialog)
        right_dlat_bound_spin.setRange(-2_000_000_000, 2_000_000_000)
        right_dlat_bound_spin.setValue(
            existing.right_dlat_bound if isinstance(existing, TsdTransverseLineObject) else -20000
        )
        left_dlat_bound_spin = _create_distance_spin(dialog)
        left_dlat_bound_spin.setRange(-2_000_000_000, 2_000_000_000)
        left_dlat_bound_spin.setValue(
            existing.left_dlat_bound if isinstance(existing, TsdTransverseLineObject) else 20000
        )
        line_width_spin = _create_distance_spin(dialog)
        line_width_spin.setRange(1, 2_000_000_000)
        line_width_spin.setValue(
            existing.line_width_500ths
            if isinstance(existing, (TsdTransverseLineObject, TsdDoubleSolidLineObject))
            else 5000
        )
        dashed_line_thickness_spin = _create_distance_spin(dialog)
        dashed_line_thickness_spin.setRange(1, 2_000_000_000)
        dashed_line_thickness_spin.setValue(
            existing.line_thickness_500ths if isinstance(existing, TsdDashedLinesObject) else 3000
        )
        dashed_start_dlong_spin = _create_distance_spin(dialog)
        dashed_start_dlong_spin.setRange(-2_000_000_000, 2_000_000_000)
        dashed_start_dlong_spin.setValue(
            existing.start_adjusted_dlong if isinstance(existing, TsdDashedLinesObject) else 0
        )
        dashed_end_dlong_spin = _create_distance_spin(dialog)
        dashed_end_dlong_spin.setRange(-2_000_000_000, 2_000_000_000)
        dashed_end_dlong_spin.setValue(
            existing.end_adjusted_dlong if isinstance(existing, TsdDashedLinesObject) else 20000
        )
        dashed_start_dlat_spin = _create_distance_spin(dialog)
        dashed_start_dlat_spin.setRange(-2_000_000_000, 2_000_000_000)
        dashed_start_dlat_spin.setValue(
            existing.start_dlat if isinstance(existing, TsdDashedLinesObject) else 0
        )
        dashed_end_dlat_spin = _create_distance_spin(dialog)
        dashed_end_dlat_spin.setRange(-2_000_000_000, 2_000_000_000)
        dashed_end_dlat_spin.setValue(
            existing.end_dlat if isinstance(existing, TsdDashedLinesObject) else 0
        )
        dashed_line_length_spin = _create_distance_spin(dialog)
        dashed_line_length_spin.setRange(1, 2_000_000_000)
        dashed_line_length_spin.setValue(
            existing.line_length_500ths if isinstance(existing, TsdDashedLinesObject) else 60000
        )
        dashed_gap_ratio_spin = QtWidgets.QDoubleSpinBox(dialog)
        dashed_gap_ratio_spin.setRange(0.0, 1_000_000.0)
        dashed_gap_ratio_spin.setDecimals(3)
        dashed_gap_ratio_spin.setSingleStep(0.1)
        dashed_gap_ratio_spin.setValue(
            existing.gap_to_line_ratio if isinstance(existing, TsdDashedLinesObject) else 3.0
        )
        pit_stalls_start_dlong_spin = _create_distance_spin(dialog)
        pit_stalls_start_dlong_spin.setRange(-2_000_000_000, 2_000_000_000)
        pit_stalls_start_dlong_spin.setValue(existing.start_dlong if isinstance(existing, TsdPitStallsObject) else 0)
        pit_stalls_left_dlat_spin = _create_distance_spin(dialog)
        pit_stalls_left_dlat_spin.setRange(-2_000_000_000, 2_000_000_000)
        pit_stalls_left_dlat_spin.setValue(existing.left_dlat if isinstance(existing, TsdPitStallsObject) else 20000)
        pit_stalls_right_dlat_spin = _create_distance_spin(dialog)
        pit_stalls_right_dlat_spin.setRange(-2_000_000_000, 2_000_000_000)
        pit_stalls_right_dlat_spin.setValue(existing.right_dlat if isinstance(existing, TsdPitStallsObject) else -20000)
        pit_stalls_line_thickness_spin = _create_distance_spin(dialog)
        pit_stalls_line_thickness_spin.setRange(1, 2_000_000_000)
        pit_stalls_line_thickness_spin.setValue(
            existing.line_thickness_500ths if isinstance(existing, TsdPitStallsObject) else 2000
        )
        pit_stalls_spacing_spin = _create_distance_spin(dialog)
        pit_stalls_spacing_spin.setRange(0, 2_000_000_000)
        pit_stalls_spacing_spin.setValue(existing.dlong_spacing_500ths if isinstance(existing, TsdPitStallsObject) else 4000)
        pit_stalls_line_count_spin = QtWidgets.QSpinBox(dialog)
        pit_stalls_line_count_spin.setRange(1, 2_000_000_000)
        pit_stalls_line_count_spin.setValue(existing.line_count if isinstance(existing, TsdPitStallsObject) else 12)
        pit_stalls_left_border_checkbox = QtWidgets.QCheckBox("Draw left longitudinal border", dialog)
        pit_stalls_left_border_checkbox.setChecked(
            isinstance(existing, TsdPitStallsObject) and bool(existing.draw_left_border)
        )
        pit_stalls_right_border_checkbox = QtWidgets.QCheckBox("Draw right longitudinal border", dialog)
        pit_stalls_right_border_checkbox.setChecked(
            isinstance(existing, TsdPitStallsObject) and bool(existing.draw_right_border)
        )
        pit_stalls_border_color_spin = QtWidgets.QSpinBox(dialog)
        pit_stalls_border_color_spin.setRange(-2_000_000_000, 2_000_000_000)
        pit_stalls_border_color_spin.setValue(
            existing.border_color_index if isinstance(existing, TsdPitStallsObject) else 36
        )
        pit_stalls_border_thickness_spin = _create_distance_spin(dialog)
        pit_stalls_border_thickness_spin.setRange(1, 2_000_000_000)
        pit_stalls_border_thickness_spin.setValue(
            existing.border_line_thickness_500ths if isinstance(existing, TsdPitStallsObject) else 500
        )
        color_spin = QtWidgets.QSpinBox(dialog)
        color_spin.setRange(-2_000_000_000, 2_000_000_000)
        color_spin.setValue(existing.color_index if existing else 36)
        transverse_line_color_spin = QtWidgets.QSpinBox(dialog)
        transverse_line_color_spin.setRange(-2_000_000_000, 2_000_000_000)
        transverse_line_color_spin.setValue(
            existing.transverse_line_color_index if isinstance(existing, TsdZebraCrossingObject) else 36
        )
        unit_label = measurement_unit_label(_measurement_unit_for_parent(self._parent))
        layout.addRow("Type", type_combo)
        layout.addRow("Name", name_edit)
        layout.addRow(f"Start DLONG ({unit_label})", start_dlong_spin)
        layout.addRow(f"Right DLAT ({unit_label})", right_dlat_spin)
        layout.addRow(f"Left DLAT ({unit_label})", left_dlat_spin)
        layout.addRow(f"Stripe Width ({unit_label})", stripe_width_spin)
        layout.addRow(f"Stripe Length ({unit_label})", stripe_length_spin)
        layout.addRow(f"Stripe Spacing ({unit_label})", stripe_spacing_spin)
        layout.addRow(f"Right Margin from Bound ({unit_label})", right_margin_spin)
        layout.addRow(f"Left Margin from Bound ({unit_label})", left_margin_spin)
        layout.addRow("End Transverse Lines", transverse_line_enabled)
        layout.addRow(f"End Line Thickness ({unit_label})", transverse_line_thickness_spin)
        layout.addRow(f"Adjusted DLONG ({unit_label})", adjusted_dlong_spin)
        layout.addRow(f"Start Adjusted DLONG ({unit_label})", start_adjusted_dlong_spin)
        layout.addRow(f"End Adjusted DLONG ({unit_label})", end_adjusted_dlong_spin)
        layout.addRow(f"DLAT ({unit_label})", dlat_spin)
        layout.addRow(f"Right DLAT Bound ({unit_label})", right_dlat_bound_spin)
        layout.addRow(f"Left DLAT Bound ({unit_label})", left_dlat_bound_spin)
        layout.addRow(f"Line Width ({unit_label})", line_width_spin)
        layout.addRow(f"Dashed Line Thickness ({unit_label})", dashed_line_thickness_spin)
        layout.addRow(f"Dashed Start DLONG ({unit_label})", dashed_start_dlong_spin)
        layout.addRow(f"Dashed End DLONG ({unit_label})", dashed_end_dlong_spin)
        layout.addRow(f"Dashed Start DLAT ({unit_label})", dashed_start_dlat_spin)
        layout.addRow(f"Dashed End DLAT ({unit_label})", dashed_end_dlat_spin)
        layout.addRow(f"Dashed Line Length ({unit_label})", dashed_line_length_spin)
        layout.addRow("Gap-to-Line Ratio", dashed_gap_ratio_spin)
        layout.addRow(f"Pit Start DLONG ({unit_label})", pit_stalls_start_dlong_spin)
        layout.addRow(f"Pit Left DLAT ({unit_label})", pit_stalls_left_dlat_spin)
        layout.addRow(f"Pit Right DLAT ({unit_label})", pit_stalls_right_dlat_spin)
        layout.addRow(f"Pit Line Thickness ({unit_label})", pit_stalls_line_thickness_spin)
        layout.addRow(f"Pit Line DLONG Spacing ({unit_label})", pit_stalls_spacing_spin)
        layout.addRow("Pit Number of Lines", pit_stalls_line_count_spin)
        layout.addRow("Pit Left Border", pit_stalls_left_border_checkbox)
        layout.addRow("Pit Right Border", pit_stalls_right_border_checkbox)
        layout.addRow("Pit Border Color", pit_stalls_border_color_spin)
        layout.addRow(f"Pit Border Thickness ({unit_label})", pit_stalls_border_thickness_spin)
        layout.addRow("Stripe Color", color_spin)
        layout.addRow("End Line Color", transverse_line_color_spin)
        zebra_only_fields = (
            start_dlong_spin,
            right_dlat_spin,
            left_dlat_spin,
            stripe_width_spin,
            stripe_length_spin,
            stripe_spacing_spin,
            right_margin_spin,
            left_margin_spin,
            transverse_line_enabled,
            transverse_line_thickness_spin,
            transverse_line_color_spin,
        )
        transverse_only_fields = (
            adjusted_dlong_spin,
            right_dlat_bound_spin,
            left_dlat_bound_spin,
            line_width_spin,
        )
        double_solid_only_fields = (
            start_adjusted_dlong_spin,
            end_adjusted_dlong_spin,
            dlat_spin,
            line_width_spin,
        )
        dashed_lines_only_fields = (
            dashed_line_thickness_spin,
            dashed_start_dlong_spin,
            dashed_end_dlong_spin,
            dashed_start_dlat_spin,
            dashed_end_dlat_spin,
            dashed_line_length_spin,
            dashed_gap_ratio_spin,
        )
        pit_stalls_only_fields = (
            pit_stalls_start_dlong_spin,
            pit_stalls_left_dlat_spin,
            pit_stalls_right_dlat_spin,
            pit_stalls_line_thickness_spin,
            pit_stalls_spacing_spin,
            pit_stalls_line_count_spin,
            pit_stalls_left_border_checkbox,
            pit_stalls_right_border_checkbox,
            pit_stalls_border_color_spin,
            pit_stalls_border_thickness_spin,
        )

        def _set_row_visible(field: QtWidgets.QWidget, visible: bool) -> None:
            label = layout.labelForField(field)
            if label is not None:
                label.setVisible(visible)
            field.setVisible(visible)

        def _sync_tsd_object_field_visibility() -> None:
            object_type = str(type_combo.currentData())
            is_transverse = object_type == "transverse_line"
            is_double_solid = object_type == "double_solid_line"
            is_dashed_lines = object_type == "dashed_lines"
            is_pit_stalls = object_type == "pit_stalls"
            for field in zebra_only_fields:
                _set_row_visible(field, object_type == "zebra_crossing")
            for field in transverse_only_fields:
                _set_row_visible(field, is_transverse)
            for field in double_solid_only_fields:
                _set_row_visible(field, is_double_solid)
            for field in dashed_lines_only_fields:
                _set_row_visible(field, is_dashed_lines)
            for field in pit_stalls_only_fields:
                _set_row_visible(field, is_pit_stalls)
            transverse_line_thickness_spin.setEnabled(
                object_type == "zebra_crossing" and transverse_line_enabled.isChecked()
            )
            transverse_line_color_spin.setEnabled(
                object_type == "zebra_crossing" and transverse_line_enabled.isChecked()
            )

        type_combo.currentIndexChanged.connect(_sync_tsd_object_field_visibility)
        transverse_line_enabled.toggled.connect(_sync_tsd_object_field_visibility)
        _sync_tsd_object_field_visibility()

        def _build_tsd_object_from_form() -> (
            TsdZebraCrossingObject | TsdTransverseLineObject | TsdDoubleSolidLineObject | TsdDashedLinesObject | TsdPitStallsObject
        ):
            object_type = str(type_combo.currentData())
            if object_type == "pit_stalls":
                name = name_edit.text().strip() or f"Pit Stalls {default_index}"
                return TsdPitStallsObject(
                    name=name,
                    start_dlong=_distance_value_500ths(pit_stalls_start_dlong_spin),
                    left_dlat=_distance_value_500ths(pit_stalls_left_dlat_spin),
                    right_dlat=_distance_value_500ths(pit_stalls_right_dlat_spin),
                    line_thickness_500ths=_distance_value_500ths(pit_stalls_line_thickness_spin),
                    dlong_spacing_500ths=_distance_value_500ths(pit_stalls_spacing_spin),
                    color_index=color_spin.value(),
                    line_count=pit_stalls_line_count_spin.value(),
                    draw_left_border=pit_stalls_left_border_checkbox.isChecked(),
                    draw_right_border=pit_stalls_right_border_checkbox.isChecked(),
                    border_color_index=pit_stalls_border_color_spin.value(),
                    border_line_thickness_500ths=_distance_value_500ths(pit_stalls_border_thickness_spin),
                    command="Detail",
                )
            if object_type == "double_solid_line":
                name = name_edit.text().strip() or f"Double Solid Line {default_index}"
                return TsdDoubleSolidLineObject(
                    name=name,
                    start_adjusted_dlong=_distance_value_500ths(start_adjusted_dlong_spin),
                    end_adjusted_dlong=_distance_value_500ths(end_adjusted_dlong_spin),
                    dlat=_distance_value_500ths(dlat_spin),
                    line_width_500ths=_distance_value_500ths(line_width_spin),
                    color_index=color_spin.value(),
                    command="Detail",
                )
            if object_type == "dashed_lines":
                name = name_edit.text().strip() or f"Dashed Lines {default_index}"
                return TsdDashedLinesObject(
                    name=name,
                    start_adjusted_dlong=_distance_value_500ths(dashed_start_dlong_spin),
                    end_adjusted_dlong=_distance_value_500ths(dashed_end_dlong_spin),
                    start_dlat=_distance_value_500ths(dashed_start_dlat_spin),
                    end_dlat=_distance_value_500ths(dashed_end_dlat_spin),
                    line_thickness_500ths=_distance_value_500ths(dashed_line_thickness_spin),
                    line_length_500ths=_distance_value_500ths(dashed_line_length_spin),
                    gap_to_line_ratio=dashed_gap_ratio_spin.value(),
                    color_index=color_spin.value(),
                    command="Detail",
                )
            if object_type == "transverse_line":
                name = name_edit.text().strip() or f"Transverse Line {default_index}"
                section_index = (
                    existing.section_index
                    if isinstance(existing, TsdTransverseLineObject)
                    else self._selected_section_index
                ) or 0
                return TsdTransverseLineObject(
                    name=name,
                    section_index=section_index,
                    adjusted_dlong=_distance_value_500ths(adjusted_dlong_spin),
                    line_width_500ths=_distance_value_500ths(line_width_spin),
                    right_dlat_bound=_distance_value_500ths(right_dlat_bound_spin),
                    left_dlat_bound=_distance_value_500ths(left_dlat_bound_spin),
                    color_index=color_spin.value(),
                    command="Detail",
                )
            name = name_edit.text().strip() or f"Zebra Crossing {default_index}"
            return TsdZebraCrossingObject(
                name=name,
                start_dlong=_distance_value_500ths(start_dlong_spin),
                right_dlat=_distance_value_500ths(right_dlat_spin),
                left_dlat=_distance_value_500ths(left_dlat_spin),
                stripe_width_500ths=_distance_value_500ths(stripe_width_spin),
                stripe_length_500ths=_distance_value_500ths(stripe_length_spin),
                stripe_spacing_500ths=_distance_value_500ths(stripe_spacing_spin),
                right_margin_500ths=_distance_value_500ths(right_margin_spin),
                left_margin_500ths=_distance_value_500ths(left_margin_spin),
                transverse_line_thickness_500ths=(
                    _distance_value_500ths(transverse_line_thickness_spin) if transverse_line_enabled.isChecked() else 0
                ),
                color_index=color_spin.value(),
                transverse_line_color_index=(
                    transverse_line_color_spin.value() if transverse_line_enabled.isChecked() else color_spin.value()
                ),
                command="Detail",
            )

        def _set_tsd_object_form_values(
            obj: TsdZebraCrossingObject | TsdTransverseLineObject | TsdDoubleSolidLineObject | TsdDashedLinesObject | TsdPitStallsObject,
        ) -> None:
            with QtCore.QSignalBlocker(type_combo):
                type_value = (
                    "pit_stalls"
                    if isinstance(obj, TsdPitStallsObject)
                    else
                    "double_solid_line"
                    if isinstance(obj, TsdDoubleSolidLineObject)
                    else "dashed_lines"
                    if isinstance(obj, TsdDashedLinesObject)
                    else "transverse_line"
                    if isinstance(obj, TsdTransverseLineObject)
                    else "zebra_crossing"
                )
                type_index = type_combo.findData(type_value)
                if type_index >= 0:
                    type_combo.setCurrentIndex(type_index)
            with QtCore.QSignalBlocker(name_edit):
                name_edit.setText(obj.name)
            with QtCore.QSignalBlocker(start_dlong_spin):
                start_dlong_spin.setValue(obj.start_dlong if isinstance(obj, TsdZebraCrossingObject) else 0)
            with QtCore.QSignalBlocker(right_dlat_spin):
                right_dlat_spin.setValue(obj.right_dlat if isinstance(obj, TsdZebraCrossingObject) else -20000)
            with QtCore.QSignalBlocker(left_dlat_spin):
                left_dlat_spin.setValue(obj.left_dlat if isinstance(obj, TsdZebraCrossingObject) else 20000)
            with QtCore.QSignalBlocker(stripe_width_spin):
                stripe_width_spin.setValue(
                    obj.stripe_width_500ths if isinstance(obj, TsdZebraCrossingObject) else 4000
                )
            with QtCore.QSignalBlocker(stripe_length_spin):
                stripe_length_spin.setValue(
                    obj.stripe_length_500ths if isinstance(obj, TsdZebraCrossingObject) else 28000
                )
            with QtCore.QSignalBlocker(stripe_spacing_spin):
                stripe_spacing_spin.setValue(
                    obj.stripe_spacing_500ths if isinstance(obj, TsdZebraCrossingObject) else 3000
                )
            with QtCore.QSignalBlocker(right_margin_spin):
                right_margin_spin.setValue(obj.right_margin_500ths if isinstance(obj, TsdZebraCrossingObject) else 0)
            with QtCore.QSignalBlocker(left_margin_spin):
                left_margin_spin.setValue(obj.left_margin_500ths if isinstance(obj, TsdZebraCrossingObject) else 0)
            with QtCore.QSignalBlocker(transverse_line_enabled):
                transverse_line_enabled.setChecked(
                    isinstance(obj, TsdZebraCrossingObject) and int(obj.transverse_line_thickness_500ths) > 0
                )
            with QtCore.QSignalBlocker(transverse_line_thickness_spin):
                transverse_line_thickness_spin.setValue(
                    obj.transverse_line_thickness_500ths if isinstance(obj, TsdZebraCrossingObject) else 2500
                )
            with QtCore.QSignalBlocker(transverse_line_color_spin):
                transverse_line_color_spin.setValue(
                    obj.transverse_line_color_index if isinstance(obj, TsdZebraCrossingObject) else 36
                )
            with QtCore.QSignalBlocker(adjusted_dlong_spin):
                adjusted_dlong_spin.setValue(obj.adjusted_dlong if isinstance(obj, TsdTransverseLineObject) else 0)
            with QtCore.QSignalBlocker(start_adjusted_dlong_spin):
                start_adjusted_dlong_spin.setValue(
                    obj.start_adjusted_dlong if isinstance(obj, TsdDoubleSolidLineObject) else 0
                )
            with QtCore.QSignalBlocker(end_adjusted_dlong_spin):
                end_adjusted_dlong_spin.setValue(
                    obj.end_adjusted_dlong if isinstance(obj, TsdDoubleSolidLineObject) else 20000
                )
            with QtCore.QSignalBlocker(dlat_spin):
                dlat_spin.setValue(obj.dlat if isinstance(obj, TsdDoubleSolidLineObject) else 0)
            with QtCore.QSignalBlocker(right_dlat_bound_spin):
                right_dlat_bound_spin.setValue(
                    obj.right_dlat_bound if isinstance(obj, TsdTransverseLineObject) else -20000
                )
            with QtCore.QSignalBlocker(left_dlat_bound_spin):
                left_dlat_bound_spin.setValue(
                    obj.left_dlat_bound if isinstance(obj, TsdTransverseLineObject) else 20000
                )
            with QtCore.QSignalBlocker(line_width_spin):
                line_width_spin.setValue(
                    obj.line_width_500ths
                    if isinstance(obj, (TsdTransverseLineObject, TsdDoubleSolidLineObject))
                    else 5000
                )
            with QtCore.QSignalBlocker(dashed_line_thickness_spin):
                dashed_line_thickness_spin.setValue(
                    obj.line_thickness_500ths if isinstance(obj, TsdDashedLinesObject) else 3000
                )
            with QtCore.QSignalBlocker(dashed_start_dlong_spin):
                dashed_start_dlong_spin.setValue(
                    obj.start_adjusted_dlong if isinstance(obj, TsdDashedLinesObject) else 0
                )
            with QtCore.QSignalBlocker(dashed_end_dlong_spin):
                dashed_end_dlong_spin.setValue(
                    obj.end_adjusted_dlong if isinstance(obj, TsdDashedLinesObject) else 20000
                )
            with QtCore.QSignalBlocker(dashed_start_dlat_spin):
                dashed_start_dlat_spin.setValue(
                    obj.start_dlat if isinstance(obj, TsdDashedLinesObject) else 0
                )
            with QtCore.QSignalBlocker(dashed_end_dlat_spin):
                dashed_end_dlat_spin.setValue(
                    obj.end_dlat if isinstance(obj, TsdDashedLinesObject) else 0
                )
            with QtCore.QSignalBlocker(dashed_line_length_spin):
                dashed_line_length_spin.setValue(
                    obj.line_length_500ths if isinstance(obj, TsdDashedLinesObject) else 60000
                )
            with QtCore.QSignalBlocker(dashed_gap_ratio_spin):
                dashed_gap_ratio_spin.setValue(
                    obj.gap_to_line_ratio if isinstance(obj, TsdDashedLinesObject) else 3.0
                )
            with QtCore.QSignalBlocker(pit_stalls_start_dlong_spin):
                pit_stalls_start_dlong_spin.setValue(obj.start_dlong if isinstance(obj, TsdPitStallsObject) else 0)
            with QtCore.QSignalBlocker(pit_stalls_left_dlat_spin):
                pit_stalls_left_dlat_spin.setValue(obj.left_dlat if isinstance(obj, TsdPitStallsObject) else 20000)
            with QtCore.QSignalBlocker(pit_stalls_right_dlat_spin):
                pit_stalls_right_dlat_spin.setValue(obj.right_dlat if isinstance(obj, TsdPitStallsObject) else -20000)
            with QtCore.QSignalBlocker(pit_stalls_line_thickness_spin):
                pit_stalls_line_thickness_spin.setValue(
                    obj.line_thickness_500ths if isinstance(obj, TsdPitStallsObject) else 2000
                )
            with QtCore.QSignalBlocker(pit_stalls_spacing_spin):
                pit_stalls_spacing_spin.setValue(
                    obj.dlong_spacing_500ths if isinstance(obj, TsdPitStallsObject) else 4000
                )
            with QtCore.QSignalBlocker(pit_stalls_line_count_spin):
                pit_stalls_line_count_spin.setValue(obj.line_count if isinstance(obj, TsdPitStallsObject) else 12)
            with QtCore.QSignalBlocker(pit_stalls_left_border_checkbox):
                pit_stalls_left_border_checkbox.setChecked(
                    bool(obj.draw_left_border) if isinstance(obj, TsdPitStallsObject) else False
                )
            with QtCore.QSignalBlocker(pit_stalls_right_border_checkbox):
                pit_stalls_right_border_checkbox.setChecked(
                    bool(obj.draw_right_border) if isinstance(obj, TsdPitStallsObject) else False
                )
            with QtCore.QSignalBlocker(pit_stalls_border_color_spin):
                pit_stalls_border_color_spin.setValue(
                    obj.border_color_index if isinstance(obj, TsdPitStallsObject) else 36
                )
            with QtCore.QSignalBlocker(pit_stalls_border_thickness_spin):
                pit_stalls_border_thickness_spin.setValue(
                    obj.border_line_thickness_500ths if isinstance(obj, TsdPitStallsObject) else 500
                )
            with QtCore.QSignalBlocker(color_spin):
                color_spin.setValue(obj.color_index)
            _sync_tsd_object_field_visibility()

        def _candidate_tsd_objects(
            preview_object: TsdZebraCrossingObject | TsdTransverseLineObject | TsdDoubleSolidLineObject | TsdDashedLinesObject | TsdPitStallsObject,
        ) -> list[TsdZebraCrossingObject | TsdTransverseLineObject | TsdDoubleSolidLineObject | TsdDashedLinesObject | TsdPitStallsObject]:
            edit_row = self._controller._editing_tsd_object_index
            if edit_row is not None and 0 <= edit_row < len(self._controller._tsd_objects):
                objects = list(self._controller._tsd_objects)
                objects[edit_row] = preview_object
                return objects
            return [*self._controller._tsd_objects, preview_object]

        def _warn_if_excessive_tsd_lines(
            preview_object: TsdZebraCrossingObject | TsdTransverseLineObject | TsdDoubleSolidLineObject | TsdDashedLinesObject | TsdPitStallsObject,
        ) -> bool:
            line_count = sum(len(obj.generated_lines()) for obj in _candidate_tsd_objects(preview_object))
            if line_count <= 1000:
                return True
            answer = QtWidgets.QMessageBox.warning(
                dialog,
                "Large TSD line count",
                (
                    f"Committing this change would produce {line_count} TSD lines.\n\n"
                    "This can slow the editor. Commit this value anyway?"
                ),
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                QtWidgets.QMessageBox.No,
            )
            return answer == QtWidgets.QMessageBox.Yes

        def _live_preview_tsd_object(*, require_confirmation: bool = False) -> bool:
            preview_object = _build_tsd_object_from_form()
            if require_confirmation and not _warn_if_excessive_tsd_lines(preview_object):
                return False
            edit_row = self._controller._editing_tsd_object_index
            if edit_row is not None and 0 <= edit_row < len(self._controller._tsd_objects):
                self._controller._tsd_objects[edit_row] = preview_object
            else:
                self._controller._tsd_object_dialog_preview_object = preview_object
            self._controller._refresh_tsd_preview_lines()
            return True

        committed_preview_object = _build_tsd_object_from_form()

        def _commit_tsd_object_preview_change() -> None:
            nonlocal committed_preview_object
            if _live_preview_tsd_object(require_confirmation=True):
                committed_preview_object = _build_tsd_object_from_form()
                return
            _set_tsd_object_form_values(committed_preview_object)
            _live_preview_tsd_object(require_confirmation=False)

        preview_controls: tuple[QtWidgets.QWidget, ...] = (
            type_combo,
            name_edit,
            start_dlong_spin,
            right_dlat_spin,
            left_dlat_spin,
            stripe_width_spin,
            stripe_length_spin,
            stripe_spacing_spin,
            right_margin_spin,
            left_margin_spin,
            transverse_line_enabled,
            transverse_line_thickness_spin,
            transverse_line_color_spin,
            adjusted_dlong_spin,
            start_adjusted_dlong_spin,
            end_adjusted_dlong_spin,
            dlat_spin,
            right_dlat_bound_spin,
            left_dlat_bound_spin,
            line_width_spin,
            dashed_line_thickness_spin,
            dashed_start_dlong_spin,
            dashed_end_dlong_spin,
            dashed_start_dlat_spin,
            dashed_end_dlat_spin,
            dashed_line_length_spin,
            dashed_gap_ratio_spin,
            pit_stalls_start_dlong_spin,
            pit_stalls_left_dlat_spin,
            pit_stalls_right_dlat_spin,
            pit_stalls_line_thickness_spin,
            pit_stalls_spacing_spin,
            pit_stalls_line_count_spin,
            pit_stalls_left_border_checkbox,
            pit_stalls_right_border_checkbox,
            pit_stalls_border_color_spin,
            pit_stalls_border_thickness_spin,
            color_spin,
        )
        for control in preview_controls:
            if isinstance(control, QtWidgets.QLineEdit):
                control.editingFinished.connect(_commit_tsd_object_preview_change)
            elif isinstance(control, QtWidgets.QCheckBox):
                control.toggled.connect(lambda *_args: _commit_tsd_object_preview_change())
            elif isinstance(control, QtWidgets.QComboBox):
                control.currentIndexChanged.connect(lambda *_args: _commit_tsd_object_preview_change())
            elif isinstance(control, QtWidgets.QDoubleSpinBox):
                control.editingFinished.connect(_commit_tsd_object_preview_change)
            elif isinstance(control, QtWidgets.QSpinBox):
                control.editingFinished.connect(_commit_tsd_object_preview_change)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addRow(buttons)
        _live_preview_tsd_object(require_confirmation=False)
        wait_loop = QtCore.QEventLoop(dialog)
        dialog.finished.connect(wait_loop.quit)
        dialog.show()
        wait_loop.exec()
        if dialog.result() != QtWidgets.QDialog.Accepted:
            return None
        return _build_tsd_object_from_form()

