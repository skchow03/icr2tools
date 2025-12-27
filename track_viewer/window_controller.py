"""Controller layer that keeps window wiring minimal."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt5 import QtCore, QtGui, QtWidgets

from track_viewer.preview_widget import TrackPreviewWidget

if TYPE_CHECKING:  # pragma: no cover - import cycle guard for type checking
    from track_viewer.app import TrackViewerApp


class WindowController(QtCore.QObject):
    """Encapsulate installation, track and AI-line orchestration."""

    installationPathChanged = QtCore.pyqtSignal(Path)
    trackListUpdated = QtCore.pyqtSignal(list, bool, int)
    trackLengthChanged = QtCore.pyqtSignal(object)
    trkGapsAvailabilityChanged = QtCore.pyqtSignal(bool)
    aiLinesUpdated = QtCore.pyqtSignal(list, set, bool)

    def __init__(
        self,
        app_state: TrackViewerApp,
        preview_widget: TrackPreviewWidget,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self.preview_widget = preview_widget
        self._gap_results_window: QtWidgets.QDialog | None = None
        self._gap_results_text: QtWidgets.QPlainTextEdit | None = None

    # ------------------------------------------------------------------
    # Installation / track loading
    # ------------------------------------------------------------------
    def select_installation_path(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        start_dir = str(self.app_state.installation_path or Path.home())
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            parent or self.parent(),
            "Select IndyCar Racing II folder",
            start_dir,
        )
        if folder:
            self.app_state.installation_path = Path(folder)
            self.installationPathChanged.emit(self.app_state.installation_path)
            self.load_tracks()

    def load_tracks(self) -> None:
        track_root = self._tracks_root()
        self.preview_widget.clear()
        self.trackLengthChanged.emit(None)
        self.trkGapsAvailabilityChanged.emit(False)
        self.app_state.update_tracks([])

        if not track_root:
            self.trackListUpdated.emit([("(TRACKS folder not found)", None)], False, -1)
            self.aiLinesUpdated.emit([], set(), False)
            return

        folders = [
            path
            for path in sorted(track_root.iterdir(), key=lambda p: p.name.lower())
            if path.is_dir()
        ]
        self.app_state.update_tracks([folder.name for folder in folders])

        if not folders:
            self.trackListUpdated.emit([("(No track folders found)", None)], False, -1)
            self.aiLinesUpdated.emit([], set(), False)
            return

        entries = [(folder.name, folder) for folder in folders]
        self.trackListUpdated.emit(entries, True, 0)
        self.aiLinesUpdated.emit([], set(), False)

    def set_selected_track(self, folder: Optional[Path]) -> None:
        if not folder:
            self.preview_widget.clear()
            self.trackLengthChanged.emit(None)
            self.trkGapsAvailabilityChanged.emit(False)
            self.sync_ai_lines()
            return

        if not isinstance(folder, Path):
            self.preview_widget.clear("Select a valid track folder.")
            self.trackLengthChanged.emit(None)
            self.trkGapsAvailabilityChanged.emit(False)
            self.sync_ai_lines()
            return

        self.preview_widget.load_track(folder)
        self.trackLengthChanged.emit(self.preview_widget.track_length())
        self.trkGapsAvailabilityChanged.emit(self.preview_widget.trk is not None)
        self.sync_ai_lines()

    # ------------------------------------------------------------------
    # AI line helpers
    # ------------------------------------------------------------------
    def set_visible_lp_files(self, names: list[str]) -> None:
        self.preview_widget.set_visible_lp_files(names)

    def sync_ai_lines(self) -> None:
        available_files = self.preview_widget.available_lp_files()
        visible_files = set(self.preview_widget.visible_lp_files())
        enabled = self.preview_widget.trk is not None
        self.aiLinesUpdated.emit(available_files, visible_files, enabled)

    # ------------------------------------------------------------------
    # TRK gaps
    # ------------------------------------------------------------------
    def run_trk_gaps(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        success, message = self.preview_widget.run_trk_gaps()
        title = "TRK Gaps"
        if not success:
            QtWidgets.QMessageBox.warning(parent or self.parent(), title, message)
            return

        self._show_gap_results_window(parent or self.parent(), title, message)

    def _show_gap_results_window(
        self, parent: Optional[QtWidgets.QWidget], title: str, text: str
    ) -> None:
        if self._gap_results_window is None:
            self._gap_results_window = QtWidgets.QDialog(parent)
            self._gap_results_window.setModal(False)
            layout = QtWidgets.QVBoxLayout()
            self._gap_results_text = QtWidgets.QPlainTextEdit()
            self._gap_results_text.setReadOnly(True)
            close_button = QtWidgets.QPushButton("Close")
            close_button.clicked.connect(self._gap_results_window.close)
            layout.addWidget(self._gap_results_text)
            layout.addWidget(close_button, alignment=QtCore.Qt.AlignRight)
            self._gap_results_window.setLayout(layout)
            self._gap_results_window.resize(520, 420)
        if self._gap_results_text is not None:
            self._gap_results_window.setWindowTitle(title)
            self._gap_results_text.setPlainText(text)
            self._gap_results_text.moveCursor(QtGui.QTextCursor.Start)
        self._gap_results_window.show()
        self._gap_results_window.raise_()
        self._gap_results_window.activateWindow()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _tracks_root(self) -> Optional[Path]:
        if not self.app_state.installation_path:
            return None
        candidates = [
            self.app_state.installation_path / "TRACKS",
            self.app_state.installation_path / "tracks",
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.is_dir():
                return candidate
        return None
