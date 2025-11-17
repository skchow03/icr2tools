import os
from PyQt5 import QtWidgets, QtCore
from icr2timing.core.config import Config


class TrackSelector(QtWidgets.QWidget):
    """
    Simple dropdown listing all track folders under <ICR2 folder>/TRACKS.
    Auto-populates based on the game_exe path in settings.ini.
    Emits signal track_selected(str) when user picks one.
    """

    track_selected = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.label = QtWidgets.QLabel("Track:")
        self.combo = QtWidgets.QComboBox()
        self.btn_refresh = QtWidgets.QPushButton("Refresh")

        layout.addWidget(self.label)
        layout.addWidget(self.combo, 1)
        layout.addWidget(self.btn_refresh)

        self.combo.currentTextChanged.connect(self._on_selected)
        self.btn_refresh.clicked.connect(self.populate_tracks)

        self.populate_tracks()

    # --------------------------------------
    # Populate list of tracks from EXE path
    # --------------------------------------
    def populate_tracks(self):
        cfg = Config.current()
        exe_path = cfg.game_exe
        self.combo.clear()

        if not exe_path or not os.path.exists(exe_path):
            self.combo.addItem("(No EXE set)")
            return

        exe_dir = os.path.dirname(exe_path)
        tracks_dir = os.path.join(exe_dir, "TRACKS")

        if not os.path.isdir(tracks_dir):
            self.combo.addItem("(No TRACKS folder found)")
            return

        track_names = [
            name for name in os.listdir(tracks_dir)
            if os.path.isdir(os.path.join(tracks_dir, name))
        ]
        track_names.sort(key=str.lower)

        if not track_names:
            self.combo.addItem("(No tracks found)")
        else:
            self.combo.addItems(track_names)

    # --------------------------------------
    # When user selects a track
    # --------------------------------------
    def _on_selected(self, text: str):
        if not text or text.startswith("("):
            return
        self.track_selected.emit(text)
