from __future__ import annotations

from collections.abc import Mapping, Sequence

from PyQt5 import QtGui, QtWidgets

from sg_viewer.replacecolors import DEFAULT_TRACK3D_COLORS


class Track3DColorDefinitionsDialog(QtWidgets.QDialog):
    """Edit .3D polygon color indices and preview swatches."""

    def __init__(
        self,
        colors: Mapping[str, int],
        palette: Sequence[QtGui.QColor] | None,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("3D Polygon Color Defaults")
        self.resize(640, 760)

        self._palette = list(palette) if palette is not None else []
        self._spin_boxes: dict[str, QtWidgets.QSpinBox] = {}
        self._swatches: dict[str, QtWidgets.QLabel] = {}

        layout = QtWidgets.QVBoxLayout(self)
        description = QtWidgets.QLabel(
            "Set the palette index for each polygon type. Swatches use loaded SUNNY.PCX colors when available."
        )
        description.setWordWrap(True)
        layout.addWidget(description)

        table = QtWidgets.QTableWidget(len(DEFAULT_TRACK3D_COLORS), 3, self)
        table.setHorizontalHeaderLabels(["Polygon Type", "Color Index", "Swatch"])
        table.verticalHeader().setVisible(False)
        table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)

        for row, (name, default_index) in enumerate(DEFAULT_TRACK3D_COLORS.items()):
            resolved_index = int(colors.get(name, default_index))
            name_item = QtWidgets.QTableWidgetItem(name)
            table.setItem(row, 0, name_item)

            spin = QtWidgets.QSpinBox(table)
            spin.setRange(0, 255)
            spin.setValue(resolved_index)
            spin.valueChanged.connect(lambda _value, key=name: self._update_swatch(key))
            table.setCellWidget(row, 1, spin)
            self._spin_boxes[name] = spin

            swatch = QtWidgets.QLabel(table)
            swatch.setFixedSize(52, 20)
            swatch.setFrameShape(QtWidgets.QFrame.Box)
            swatch.setFrameShadow(QtWidgets.QFrame.Plain)
            swatch.setToolTip("Palette swatch for selected index")
            table.setCellWidget(row, 2, swatch)
            self._swatches[name] = swatch

        self._table = table
        layout.addWidget(table, stretch=1)

        reset_button = QtWidgets.QPushButton("Reset to defaults", self)
        reset_button.clicked.connect(self._reset_defaults)
        layout.addWidget(reset_button)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        for key in self._spin_boxes:
            self._update_swatch(key)

    def selected_colors(self) -> dict[str, int]:
        return {name: int(spin.value()) for name, spin in self._spin_boxes.items()}

    def _reset_defaults(self) -> None:
        for name, default_index in DEFAULT_TRACK3D_COLORS.items():
            self._spin_boxes[name].setValue(int(default_index))

    def _update_swatch(self, name: str) -> None:
        spin = self._spin_boxes[name]
        swatch = self._swatches[name]
        index = int(spin.value())
        if 0 <= index < len(self._palette):
            color = self._palette[index]
            swatch.setStyleSheet(
                "background-color: rgb(%d, %d, %d); border: 1px solid #555;" % (
                    color.red(),
                    color.green(),
                    color.blue(),
                )
            )
            swatch.setToolTip(
                f"Index {index}: rgb({color.red()}, {color.green()}, {color.blue()})"
            )
            return
        swatch.setStyleSheet("background-color: #8a8a8a; border: 1px solid #555;")
        swatch.setToolTip(f"Index {index}: palette unavailable")
