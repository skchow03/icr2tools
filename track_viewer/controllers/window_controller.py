"""Controller layer that keeps window wiring minimal."""
from __future__ import annotations

from pathlib import Path
from typing import Optional, TYPE_CHECKING

from PyQt5 import QtCore, QtGui, QtWidgets

from track_viewer.preview_api import TrackPreviewApi
from track_viewer.model.pit_models import PitParameters
from track_viewer.services.io_service import (
    TrackIOService,
    TrackTxtLine,
    TrackTxtMetadata,
    TrackTxtResult,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle guard for type checking
    from track_viewer.widget.track_viewer_app import TrackViewerApp


class WindowController(QtCore.QObject):
    """Encapsulate installation, track and AI-line orchestration."""

    installationPathChanged = QtCore.pyqtSignal(Path)
    trackListUpdated = QtCore.pyqtSignal(list, bool, int)
    trackLengthChanged = QtCore.pyqtSignal(object)
    trkGapsAvailabilityChanged = QtCore.pyqtSignal(bool)
    aiLinesUpdated = QtCore.pyqtSignal(list, set, bool)
    trkSourceChanged = QtCore.pyqtSignal(bool)

    def __init__(
        self,
        app_state: TrackViewerApp,
        preview_api: TrackPreviewApi,
        parent: Optional[QtWidgets.QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.app_state = app_state
        self.preview_api = preview_api
        self._gap_results_window: QtWidgets.QDialog | None = None
        self._gap_results_text: QtWidgets.QPlainTextEdit | None = None
        self._io_service = TrackIOService()
        self._current_track_folder: Path | None = None
        self._track_txt_result: TrackTxtResult | None = None

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
            self.set_installation_path(Path(folder))

    def set_installation_path(self, path: Path) -> None:
        self.app_state.set_installation_path(path)
        if self.app_state.installation_path is None:
            return
        self.installationPathChanged.emit(self.app_state.installation_path)
        self.load_tracks()

    def load_tracks(self) -> None:
        track_root = self._tracks_root()
        self.preview_api.clear()
        self.trackLengthChanged.emit(None)
        self.trkGapsAvailabilityChanged.emit(False)
        self.trkSourceChanged.emit(False)
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
        self.trackListUpdated.emit(entries, True, -1)
        self.aiLinesUpdated.emit([], set(), False)

    def set_selected_track(self, folder: Optional[Path]) -> None:
        self._current_track_folder = folder if isinstance(folder, Path) else None
        if not folder:
            self.preview_api.clear()
            self.trackLengthChanged.emit(None)
            self.trkGapsAvailabilityChanged.emit(False)
            self.trkSourceChanged.emit(False)
            self.sync_ai_lines()
            return

        if not isinstance(folder, Path):
            self.preview_api.clear("Select a valid track folder.")
            self.trackLengthChanged.emit(None)
            self.trkGapsAvailabilityChanged.emit(False)
            self.trkSourceChanged.emit(False)
            self.sync_ai_lines()
            return

        self.preview_api.load_track(folder)
        self.trackLengthChanged.emit(self.preview_api.track_length())
        self.trkGapsAvailabilityChanged.emit(self.preview_api.trk is not None)
        self.trkSourceChanged.emit(False)
        self.sync_ai_lines()

    def load_trk_wip(self, trk_path: Path) -> None:
        self._current_track_folder = None
        self._track_txt_result = None
        self.preview_api.load_trk_file(trk_path)
        self.trackLengthChanged.emit(self.preview_api.track_length())
        self.trkGapsAvailabilityChanged.emit(self.preview_api.trk is not None)
        self.trkSourceChanged.emit(True)
        self.aiLinesUpdated.emit([], set(), False)

    # ------------------------------------------------------------------
    # Track TXT and replay loading
    # ------------------------------------------------------------------
    @property
    def current_track_folder(self) -> Path | None:
        return self._current_track_folder

    @property
    def track_txt_result(self) -> TrackTxtResult | None:
        return self._track_txt_result

    def load_track_txt(self, folder: Path | None) -> TrackTxtResult | None:
        self._current_track_folder = folder if isinstance(folder, Path) else None
        if self._current_track_folder is None:
            self._track_txt_result = None
            return None
        self._track_txt_result = self._io_service.load_track_txt(
            self._current_track_folder
        )
        return self._track_txt_result

    def load_replay_paths(self, folder: Path | None) -> list[Path]:
        if folder is None:
            return []
        return sorted(
            [
                path
                for path in folder.iterdir()
                if path.is_file() and path.suffix.lower() == ".rpy"
            ],
            key=lambda path: path.name.lower(),
        )

    def save_pit_params(
        self,
        pit_params: PitParameters | None,
        pit2_params: PitParameters | None,
        lines: list[TrackTxtLine],
        require_pit2: bool,
    ) -> tuple[bool, str, TrackTxtResult | None]:
        if self._current_track_folder is None:
            return False, "No track is currently loaded.", None
        if pit_params is None:
            return False, "No PIT parameters are available to save.", None
        if require_pit2 and pit2_params is None:
            return False, "No PIT2 parameters are available to save.", None
        message = self._io_service.save_track_txt(
            self._current_track_folder, pit_params, pit2_params, None, lines
        )
        refreshed = self.load_track_txt(self._current_track_folder)
        return True, message, refreshed

    def save_track_txt(
        self,
        pit_params: PitParameters | None,
        pit2_params: PitParameters | None,
        metadata: TrackTxtMetadata,
        lines: list[TrackTxtLine],
    ) -> tuple[bool, str, TrackTxtResult | None]:
        if self._current_track_folder is None:
            return False, "No track is currently loaded.", None
        message = self._io_service.save_track_txt(
            self._current_track_folder,
            pit_params,
            pit2_params,
            metadata,
            lines,
        )
        refreshed = self.load_track_txt(self._current_track_folder)
        return True, message, refreshed

    # ------------------------------------------------------------------
    # AI line helpers
    # ------------------------------------------------------------------
    def set_visible_lp_files(self, names: list[str]) -> None:
        self.preview_api.set_visible_lp_files(names)

    def sync_ai_lines(self) -> None:
        available_files = self.preview_api.available_lp_files()
        visible_files = set(self.preview_api.visible_lp_files())
        enabled = self.preview_api.trk is not None
        self.aiLinesUpdated.emit(available_files, visible_files, enabled)

    # ------------------------------------------------------------------
    # TRK gaps
    # ------------------------------------------------------------------
    def run_trk_gaps(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        success, message = self.preview_api.run_trk_gaps()
        title = "TRK Gaps"
        if not success:
            QtWidgets.QMessageBox.warning(parent or self.parent(), title, message)
            return

        self._show_gap_results_window(parent or self.parent(), title, message)

    def convert_trk_to_sg(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        track_path = self.preview_api.track_path()
        trk_file_path = self.preview_api.trk_file_path()
        if track_path is None and trk_file_path is None:
            QtWidgets.QMessageBox.warning(
                parent or self.parent(), "TRK to SG", "No track is currently loaded."
            )
            return

        if track_path is not None:
            default_output = track_path / f"{track_path.name}.sg"
        else:
            default_output = trk_file_path.with_suffix(".sg")
        output_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            parent or self.parent(),
            "Save SG file",
            str(default_output),
            "SG Files (*.sg)",
        )
        if not output_path:
            return

        success, message = self.preview_api.convert_trk_to_sg(Path(output_path))
        if success:
            QtWidgets.QMessageBox.information(
                parent or self.parent(), "TRK to SG", message
            )
            return

        QtWidgets.QMessageBox.warning(parent or self.parent(), "TRK to SG", message)

    def convert_trk_to_csv(self, parent: Optional[QtWidgets.QWidget] = None) -> None:
        track_path = self.preview_api.track_path()
        trk_file_path = self.preview_api.trk_file_path()
        if track_path is None and trk_file_path is None:
            QtWidgets.QMessageBox.warning(
                parent or self.parent(), "TRK to CSV", "No track is currently loaded."
            )
            return

        start_dir = (
            str(track_path) if track_path is not None else str(trk_file_path.parent)
        )
        output_path = QtWidgets.QFileDialog.getExistingDirectory(
            parent or self.parent(),
            "Select folder to export CSV files",
            start_dir,
        )
        if not output_path:
            return

        success, message = self.preview_api.convert_trk_to_csv(Path(output_path))
        if success:
            QtWidgets.QMessageBox.information(
                parent or self.parent(), "TRK to CSV", message
            )
            return

        QtWidgets.QMessageBox.warning(parent or self.parent(), "TRK to CSV", message)

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
