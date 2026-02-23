from __future__ import annotations

from dataclasses import dataclass

from PyQt5 import QtCore, QtWidgets


@dataclass(frozen=True)
class MrkTextureDefinition:
    mip_name: str
    upper_left_u: int
    upper_left_v: int
    lower_right_u: int
    lower_right_v: int


class MrkTexturesDialog(QtWidgets.QDialog):
    def __init__(
        self,
        parent: QtWidgets.QWidget | None,
        definitions: tuple[MrkTextureDefinition, ...],
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("MRK Texture Definitions")

        self._table = QtWidgets.QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["MIP", "UL U", "UL V", "LR U", "LR V"])
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
                " Each texture uses mip filename (without extension) and UV bounds."
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
        seen_mips: set[str] = set()
        for row in range(self._table.rowCount()):
            mip_name = self._item_text(row, 0)
            if not mip_name:
                raise ValueError(f"Row {row + 1}: mip name is required")
            if mip_name in seen_mips:
                raise ValueError(f"Row {row + 1}: duplicate mip name {mip_name!r}")
            seen_mips.add(mip_name)
            definitions.append(
                MrkTextureDefinition(
                    mip_name=mip_name,
                    upper_left_u=self._item_int(row, 1),
                    upper_left_v=self._item_int(row, 2),
                    lower_right_u=self._item_int(row, 3),
                    lower_right_v=self._item_int(row, 4),
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
            "" if definition is None else definition.mip_name,
            "0" if definition is None else str(definition.upper_left_u),
            "0" if definition is None else str(definition.upper_left_v),
            "0" if definition is None else str(definition.lower_right_u),
            "0" if definition is None else str(definition.lower_right_v),
        ]
        for column, value in enumerate(values):
            item = QtWidgets.QTableWidgetItem(value)
            if column > 0:
                item.setTextAlignment(int(QtCore.Qt.AlignCenter))
            self._table.setItem(row, column, item)

    def _add_empty_row(self) -> None:
        self._append_row()
        self._table.selectRow(self._table.rowCount() - 1)

    def _remove_selected_row(self) -> None:
        selected_rows = self._table.selectionModel().selectedRows()
        if not selected_rows:
            return
        self._table.removeRow(selected_rows[0].row())

