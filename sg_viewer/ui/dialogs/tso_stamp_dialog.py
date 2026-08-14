from __future__ import annotations

from PyQt5 import QtCore, QtWidgets


class TsoStampDialog(QtWidgets.QDialog):
    """Collect a stamp list and manage the lists saved with the project."""

    def __init__(
        self,
        parent: QtWidgets.QWidget | None,
        stamp_lists: list[tuple[str, ...]],
        initial_text: str,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Stamp TSOs")
        self.resize(520, 330)

        layout = QtWidgets.QVBoxLayout(self)
        explanation = QtWidgets.QLabel(
            "Stamp mode places one item at each map click. The item is chosen "
            "randomly from the comma-separated list below; repeated filenames "
            "therefore increase an item's chance of being selected."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)

        layout.addWidget(QtWidgets.QLabel("Filenames (comma separated):"))
        self.filename_edit = QtWidgets.QLineEdit(initial_text)
        layout.addWidget(self.filename_edit)

        layout.addWidget(QtWidgets.QLabel("Previously used stamp lists:"))
        self.saved_lists = QtWidgets.QListWidget()
        for filenames in stamp_lists:
            self.saved_lists.addItem(", ".join(filenames))
        self.saved_lists.itemSelectionChanged.connect(self._use_selected_list)
        self.saved_lists.itemDoubleClicked.connect(lambda _item: self.accept())
        layout.addWidget(self.saved_lists)

        remove_button = QtWidgets.QPushButton("Remove selected list")
        remove_button.clicked.connect(self._remove_selected_list)
        layout.addWidget(remove_button, alignment=QtCore.Qt.AlignLeft)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _use_selected_list(self) -> None:
        item = self.saved_lists.currentItem()
        if item is not None:
            self.filename_edit.setText(item.text())

    def _remove_selected_list(self) -> None:
        row = self.saved_lists.currentRow()
        if row >= 0:
            self.saved_lists.takeItem(row)

    def remaining_lists(self) -> list[str]:
        return [
            self.saved_lists.item(row).text() for row in range(self.saved_lists.count())
        ]

    @classmethod
    def get_stamp_list(
        cls,
        parent: QtWidgets.QWidget | None,
        stamp_lists: list[tuple[str, ...]],
        initial_text: str,
    ) -> tuple[str, bool, list[str]]:
        dialog = cls(parent, stamp_lists, initial_text)
        accepted = dialog.exec_() == QtWidgets.QDialog.Accepted
        return dialog.filename_edit.text(), accepted, dialog.remaining_lists()
