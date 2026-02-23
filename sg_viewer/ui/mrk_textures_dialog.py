from __future__ import annotations

from dataclasses import dataclass

from PyQt5 import QtCore, QtGui, QtWidgets


@dataclass(frozen=True)
class MrkTextureDefinition:
    texture_name: str
    mip_name: str
    upper_left_u: int
    upper_left_v: int
    lower_right_u: int
    lower_right_v: int
    highlight_color: str = "#FFFF00"


class MrkTexturesDialog(QtWidgets.QDialog):
    def __init__(
        self,
        parent: QtWidgets.QWidget | None,
        definitions: tuple[MrkTextureDefinition, ...],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("MRK Texture Definitions")

        self._table = QtWidgets.QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(["Texture name", "MIP filename", "UL U", "UL V", "LR U", "LR V", "Color"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)

        add_button = QtWidgets.QPushButton("Add")
        remove_button = QtWidgets.QPushButton("Remove")
        add_button.clicked.connect(self._add_empty_row)
        remove_button.clicked.connect(self._remove_selected_row)

        button_row = QtWidgets.QHBoxLayout()
        button_row.addWidget(add_button)
        button_row.addWidget(remove_button)
        button_row.addStretch()

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(
            QtWidgets.QLabel(
                "Define reusable textures for MRK entries."
                " Each texture has a user-facing texture name, a MIP filename (without extension), and UV bounds."
            )
        )
        layout.addWidget(self._table)
        layout.addLayout(button_row)
        layout.addWidget(buttons)
        self.setLayout(layout)

        for definition in definitions:
            self._append_row(definition)

    def texture_definitions(self) -> tuple[MrkTextureDefinition, ...]:
        definitions: list[MrkTextureDefinition] = []
        seen_names: set[str] = set()
        for row in range(self._table.rowCount()):
            texture_name = self._item_text(row, 0)
            if not texture_name:
                raise ValueError(f"Row {row + 1}: texture name is required")
            if texture_name in seen_names:
                raise ValueError(f"Row {row + 1}: duplicate texture name {texture_name!r}")
            seen_names.add(texture_name)
            mip_name = self._item_text(row, 1)
            if not mip_name:
                raise ValueError(f"Row {row + 1}: MIP filename is required")
            color_value = self._item_text(row, 6) or "#FFFF00"
            color = QtGui.QColor(color_value)
            if not color.isValid():
                raise ValueError(f"Row {row + 1}: invalid color {color_value!r}")
            definitions.append(
                MrkTextureDefinition(
                    texture_name=texture_name,
                    mip_name=mip_name,
                    upper_left_u=self._item_int(row, 2),
                    upper_left_v=self._item_int(row, 3),
                    lower_right_u=self._item_int(row, 4),
                    lower_right_v=self._item_int(row, 5),
                    highlight_color=color.name().upper(),
                )
            )
        return tuple(definitions)

    def _item_text(self, row: int, column: int) -> str:
        item = self._table.item(row, column)
        return "" if item is None else item.text().strip()

    def _item_int(self, row: int, column: int) -> int:
        raw = self._item_text(row, column)
        if not raw:
            raise ValueError(f"Row {row + 1}, column {column + 1}: value is required")
        try:
            return int(raw)
        except ValueError as exc:
            raise ValueError(
                f"Row {row + 1}, column {column + 1}: expected integer, got {raw!r}"
            ) from exc

    def _append_row(self, definition: MrkTextureDefinition | None = None) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        values = [
            "" if definition is None else definition.texture_name,
            "" if definition is None else definition.mip_name,
            "0" if definition is None else str(definition.upper_left_u),
            "0" if definition is None else str(definition.upper_left_v),
            "0" if definition is None else str(definition.lower_right_u),
            "0" if definition is None else str(definition.lower_right_v),
            "#FFFF00" if definition is None else definition.highlight_color,
        ]
        for column, value in enumerate(values):
            item = QtWidgets.QTableWidgetItem(value)
            if 2 <= column <= 5:
                item.setTextAlignment(int(QtCore.Qt.AlignCenter))
            self._table.setItem(row, column, item)
        self._set_color_cell(row, values[6])

    def _add_empty_row(self) -> None:
        self._append_row()
        self._table.selectRow(self._table.rowCount() - 1)

    def _remove_selected_row(self) -> None:
        selected_rows = self._table.selectionModel().selectedRows()
        if not selected_rows:
            return
        self._table.removeRow(selected_rows[0].row())

    def _set_color_cell(self, row: int, color_value: str) -> None:
        color = QtGui.QColor(color_value)
        if not color.isValid():
            color = QtGui.QColor("#FFFF00")
        button = QtWidgets.QPushButton(color.name().upper())
        button.setStyleSheet(
            "QPushButton {"
            f"background-color: {color.name()};"
            "border: 1px solid #444;"
            "padding: 2px 6px;"
            "}"
        )
        button.clicked.connect(lambda _checked=False, r=row: self._pick_row_color(r))
        self._table.setCellWidget(row, 6, button)
        self._table.item(row, 6).setText(color.name().upper())

    def _pick_row_color(self, row: int) -> None:
        item = self._table.item(row, 6)
        initial = QtGui.QColor(item.text() if item is not None else "#FFFF00")
        if not initial.isValid():
            initial = QtGui.QColor("#FFFF00")
        picked = QtWidgets.QColorDialog.getColor(initial, self, "Pick Highlight Color")
        if not picked.isValid():
            return
        self._set_color_cell(row, picked.name().upper())


class MrkTexturePatternDialog(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget | None, available_mips: list[str], pattern: list[str]) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Texture Pattern")
        self._available = [mip for mip in available_mips if mip]

        self._combo = QtWidgets.QComboBox()
        self._combo.addItems(self._available)
        add_button = QtWidgets.QPushButton("Add")
        remove_button = QtWidgets.QPushButton("Remove Selected")
        add_button.clicked.connect(self._add_selected)
        remove_button.clicked.connect(self._remove_selected)

        self._list = QtWidgets.QListWidget()
        self._list.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        for mip in pattern:
            if mip in self._available:
                self._list.addItem(mip)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(self._combo)
        row.addWidget(add_button)
        row.addWidget(remove_button)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(QtWidgets.QLabel("Build the wall texture list in order. Entries must use predefined textures."))
        layout.addLayout(row)
        layout.addWidget(self._list)
        layout.addWidget(buttons)
        self.setLayout(layout)

    def selected_pattern(self) -> list[str]:
        return [self._list.item(index).text() for index in range(self._list.count())]

    def _add_selected(self) -> None:
        if self._combo.count() == 0:
            return
        self._list.addItem(self._combo.currentText())

    def _remove_selected(self) -> None:
        row = self._list.currentRow()
        if row < 0:
            return
        self._list.takeItem(row)
