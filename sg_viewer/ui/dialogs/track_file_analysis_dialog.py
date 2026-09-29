"""Window used to display a track-folder file analysis."""

from __future__ import annotations

from pathlib import Path

from PyQt5 import QtCore, QtWidgets

from sg_viewer.services.track_file_analyzer import TrackFileAnalysis


class TrackFileAnalysisDialog(QtWidgets.QDialog):
    def __init__(self, analysis: TrackFileAnalysis, parent=None) -> None:
        super().__init__(parent)
        self._analysis = analysis
        self.setWindowTitle(f"Track File Analysis — {analysis.track_name}")
        self.setWindowModality(False)
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        self.resize(760, 620)

        layout = QtWidgets.QVBoxLayout(self)
        summary = QtWidgets.QLabel(self)
        summary.setObjectName("trackFileAnalysisSummary")
        summary.setText(
            "<b>Track folder is complete.</b>"
            if analysis.is_complete
            else "<b>Track folder is incomplete.</b> Missing items are listed below."
        )
        layout.addWidget(summary)

        self.report_text = QtWidgets.QPlainTextEdit(self)
        self.report_text.setObjectName("trackFileAnalysisReport")
        self.report_text.setReadOnly(True)
        self.report_text.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.report_text.setPlainText(analysis.format_report())
        layout.addWidget(self.report_text, 1)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close, self)
        save_button = buttons.addButton("Save Report…", QtWidgets.QDialogButtonBox.ActionRole)
        save_button.clicked.connect(self._save_report)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

    def _save_report(self) -> None:
        default_path = self._analysis.folder / f"{self._analysis.track_name}_file_analysis.txt"
        selected, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "Save Track File Analysis",
            str(default_path),
            "Text files (*.txt);;All files (*)",
        )
        if not selected:
            return
        try:
            Path(selected).write_text(self._analysis.format_report(), encoding="utf-8")
        except OSError as exc:
            QtWidgets.QMessageBox.critical(self, "Save Track File Analysis", str(exc))
