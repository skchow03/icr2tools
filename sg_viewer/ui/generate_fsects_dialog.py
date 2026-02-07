from __future__ import annotations

from PyQt5 import QtWidgets


class GenerateFsectsDialog(QtWidgets.QDialog):
    def __init__(
        self,
        parent: QtWidgets.QWidget,
        *,
        unit_label: str,
        decimals: int,
        step: float,
        track_width: float,
        left_grass_width: float,
        right_grass_width: float,
        grass_surface_type: int,
        wall_surface_type: int,
        fence_enabled: bool,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Generate Fsects")

        layout = QtWidgets.QFormLayout(self)

        self._template_combo = QtWidgets.QComboBox(self)
        self._template_combo.addItem("Oval", "oval")
        self._template_combo.addItem("Road Course", "road_course")
        self._template_combo.addItem("Street Circuit", "street")
        layout.addRow("Template:", self._template_combo)

        suffix = f" {unit_label}"
        self._track_width_spin = QtWidgets.QDoubleSpinBox(self)
        self._track_width_spin.setDecimals(decimals)
        self._track_width_spin.setSingleStep(step)
        self._track_width_spin.setRange(0.0, 100000.0)
        self._track_width_spin.setValue(track_width)
        self._track_width_spin.setSuffix(suffix)
        layout.addRow("Track width:", self._track_width_spin)

        self._grass_type_combo = QtWidgets.QComboBox(self)
        self._grass_type_combo.addItem("Grass", 0)
        self._grass_type_combo.addItem("Dry Grass", 1)
        self._grass_type_combo.addItem("Sand", 3)
        self._grass_type_combo.addItem("Dirt", 2)
        grass_index = max(
            0,
            self._grass_type_combo.findData(grass_surface_type),
        )
        self._grass_type_combo.setCurrentIndex(grass_index)
        layout.addRow("Grass type:", self._grass_type_combo)

        self._right_grass_spin = QtWidgets.QDoubleSpinBox(self)
        self._right_grass_spin.setDecimals(decimals)
        self._right_grass_spin.setSingleStep(step)
        self._right_grass_spin.setRange(0.0, 100000.0)
        self._right_grass_spin.setValue(right_grass_width)
        self._right_grass_spin.setSuffix(suffix)
        layout.addRow("Right grass width:", self._right_grass_spin)

        self._left_grass_spin = QtWidgets.QDoubleSpinBox(self)
        self._left_grass_spin.setDecimals(decimals)
        self._left_grass_spin.setSingleStep(step)
        self._left_grass_spin.setRange(0.0, 100000.0)
        self._left_grass_spin.setValue(left_grass_width)
        self._left_grass_spin.setSuffix(suffix)
        layout.addRow("Left grass width:", self._left_grass_spin)

        self._wall_type_combo = QtWidgets.QComboBox(self)
        self._wall_type_combo.addItem("Wall", 7)
        self._wall_type_combo.addItem("Armco", 8)
        wall_index = max(0, self._wall_type_combo.findData(wall_surface_type))
        self._wall_type_combo.setCurrentIndex(wall_index)
        layout.addRow("Wall type:", self._wall_type_combo)

        self._fence_checkbox = QtWidgets.QCheckBox("Add fence to walls", self)
        self._fence_checkbox.setChecked(fence_enabled)
        layout.addRow(self._fence_checkbox)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self._template_combo.currentIndexChanged.connect(
            self._update_grass_width_availability
        )
        self._update_grass_width_availability()

    def template(self) -> str:
        return str(self._template_combo.currentData())

    def track_width(self) -> float:
        return float(self._track_width_spin.value())

    def grass_surface_type(self) -> int:
        return int(self._grass_type_combo.currentData())

    def left_grass_width(self) -> float:
        return float(self._left_grass_spin.value())

    def right_grass_width(self) -> float:
        return float(self._right_grass_spin.value())

    def wall_surface_type(self) -> int:
        return int(self._wall_type_combo.currentData())

    def fence_enabled(self) -> bool:
        return bool(self._fence_checkbox.isChecked())

    def _update_grass_width_availability(self) -> None:
        template = self.template()
        right_enabled = template != "oval" and template != "street"
        left_enabled = template != "street"

        self._right_grass_spin.setEnabled(right_enabled)
        self._left_grass_spin.setEnabled(left_enabled)

        if not right_enabled:
            self._right_grass_spin.setValue(0.0)
        if not left_enabled:
            self._left_grass_spin.setValue(0.0)
