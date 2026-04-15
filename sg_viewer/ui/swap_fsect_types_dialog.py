from __future__ import annotations

from PyQt5 import QtWidgets

from sg_viewer.ui.fsection_type_utils import fsect_type_options


class SwapFsectTypesDialog(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Swap Fsect Types")
        self.setModal(True)

        form_layout = QtWidgets.QFormLayout()

        self._source_combo = QtWidgets.QComboBox()
        self._target_combo = QtWidgets.QComboBox()
        for label, surface_type, type2 in fsect_type_options():
            payload = (int(surface_type), int(type2))
            self._source_combo.addItem(label, payload)
            self._target_combo.addItem(label, payload)

        self._source_combo.setCurrentIndex(0)
        self._target_combo.setCurrentIndex(4)

        form_layout.addRow("Swap this type:", self._source_combo)
        form_layout.addRow("To this type:", self._target_combo)

        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)

        info_label = QtWidgets.QLabel(
            "This will update all matching Fsects across every section."
        )
        info_label.setWordWrap(True)

        layout = QtWidgets.QVBoxLayout()
        layout.addWidget(info_label)
        layout.addLayout(form_layout)
        layout.addWidget(button_box)
        self.setLayout(layout)

    def source_type(self) -> tuple[int, int]:
        selection = self._source_combo.currentData()
        if (
            isinstance(selection, tuple)
            and len(selection) == 2
            and all(isinstance(value, int) for value in selection)
        ):
            return selection
        return (0, 0)

    def target_type(self) -> tuple[int, int]:
        selection = self._target_combo.currentData()
        if (
            isinstance(selection, tuple)
            and len(selection) == 2
            and all(isinstance(value, int) for value in selection)
        ):
            return selection
        return (0, 0)
