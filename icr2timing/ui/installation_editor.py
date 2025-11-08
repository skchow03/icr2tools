from __future__ import annotations

from typing import Optional

from PyQt5 import QtWidgets

from icr2timing.core.installations import Installation


class InstallationEditorDialog(QtWidgets.QDialog):
    """Dialog used to create or edit an installation entry."""

    SUPPORTED_VERSIONS = ["REND32A", "DOS", "WINDY"]

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None, installation: Optional[Installation] = None):
        super().__init__(parent)

        self._installation = installation
        self.setWindowTitle("Add Installation" if installation is None else "Edit Installation")

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()

        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("My ICR2 Setup")

        self.exe_edit = QtWidgets.QLineEdit()
        self.exe_edit.setPlaceholderText("Path to CART.EXE or INDYCAR.EXE")
        browse_btn = QtWidgets.QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_for_exe)
        exe_row = QtWidgets.QHBoxLayout()
        exe_row.addWidget(self.exe_edit, 1)
        exe_row.addWidget(browse_btn)

        self.version_combo = QtWidgets.QComboBox()
        self.version_combo.addItems(self.SUPPORTED_VERSIONS)

        self.keywords_edit = QtWidgets.QLineEdit()
        self.keywords_edit.setPlaceholderText("Keywords to match window titles")

        form.addRow("Name", self.name_edit)
        form.addRow("Executable", exe_row)
        form.addRow("Version", self.version_combo)
        form.addRow("Window keywords", self.keywords_edit)
        layout.addLayout(form)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        if installation:
            self.name_edit.setText(installation.name)
            self.exe_edit.setText(installation.exe_path)
            version = installation.version.upper()
            idx = max(0, self.version_combo.findText(version))
            self.version_combo.setCurrentIndex(idx)
            self.keywords_edit.setText(", ".join(installation.keywords))

    # ------------------------------------------------------------------
    def _browse_for_exe(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select INDYCAR.EXE or CART.EXE",
            "",
            "Executable Files (*.exe);;All Files (*)",
        )
        if path:
            self.exe_edit.setText(path)

    # ------------------------------------------------------------------
    def accept(self):
        name = self.name_edit.text().strip()
        exe = self.exe_edit.text().strip()
        if not name:
            QtWidgets.QMessageBox.warning(self, "Installation", "Please provide a name for this installation.")
            return
        if not exe:
            QtWidgets.QMessageBox.warning(self, "Installation", "Please select the executable path.")
            return
        super().accept()

    # ------------------------------------------------------------------
    def keywords(self) -> list[str]:
        raw = self.keywords_edit.text()
        return [k.strip() for k in raw.split(",") if k.strip()]

    def result_payload(self) -> dict:
        return {
            "name": self.name_edit.text().strip(),
            "exe_path": self.exe_edit.text().strip(),
            "version": self.version_combo.currentText().upper(),
            "keywords": self.keywords(),
        }

