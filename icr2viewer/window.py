"""Main window for the ICR2 Track Viewer."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import List, Optional

from PyQt5 import QtCore, QtGui, QtWidgets

from icr2_core.trk.track_loader import load_trk_from_folder
from icr2_core.trk.trk_classes import TRKFile

from .geometry import TrackWireframe, build_track_wireframe
from .track_catalog import TrackDiscoveryError, TrackMetadata, discover_tracks


TRACK_LENGTH_SCALE = 500.0 * 12.0 * 5280.0


@dataclass
class LoadedTrack:
    metadata: TrackMetadata
    trk: TRKFile
    wireframe: TrackWireframe
    length_miles: Optional[float]


class Track3DView(QtWidgets.QWidget):
    """Simple 3D viewer that renders a wireframe track with mouse controls."""

    def __init__(self, parent: Optional[QtWidgets.QWidget] = None):
        super().__init__(parent)
        self._wireframe: Optional[TrackWireframe] = None
        self._segments: List[tuple] = []
        self._centerline: List[tuple] = []
        self._center = (0.0, 0.0, 0.0)
        self._radius = 1.0
        self._zoom = 1.0
        self._yaw = math.radians(45.0)
        self._pitch = math.radians(30.0)
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._last_pos: Optional[QtCore.QPoint] = None
        self._drag_mode: Optional[str] = None
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.ClickFocus)

    def sizeHint(self) -> QtCore.QSize:  # pragma: no cover - UI hint only
        return QtCore.QSize(900, 600)

    def set_wireframe(self, wireframe: TrackWireframe | None):
        self._wireframe = wireframe
        if wireframe is None:
            self._segments = []
            self._centerline = []
            self._center = (0.0, 0.0, 0.0)
            self._radius = 1.0
        else:
            self._segments = wireframe.segments
            self._centerline = wireframe.centerline
            if wireframe.bounds:
                min_x, max_x, min_y, max_y, min_z, max_z = wireframe.bounds
                self._center = (
                    (min_x + max_x) / 2.0,
                    (min_y + max_y) / 2.0,
                    (min_z + max_z) / 2.0,
                )
                span_x = max_x - min_x
                span_y = max_y - min_y
                span_z = max_z - min_z
                self._radius = max(span_x, span_y, span_z, 1.0) / 2.0
            else:
                self._center = (0.0, 0.0, 0.0)
                self._radius = 1.0
        self.update()

    # --- Interaction -------------------------------------------------
    def wheelEvent(self, event: QtGui.QWheelEvent):  # noqa: N802
        delta = event.angleDelta().y() / 120.0
        factor = 1.15 ** delta
        self._zoom = max(0.05, min(20.0, self._zoom * factor))
        self.update()

    def mousePressEvent(self, event: QtGui.QMouseEvent):  # noqa: N802
        if event.button() == QtCore.Qt.LeftButton:
            self._drag_mode = "rotate"
        elif event.button() == QtCore.Qt.RightButton:
            self._drag_mode = "pan"
        self._last_pos = event.pos()
        event.accept()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):  # noqa: N802
        if not self._drag_mode or self._last_pos is None:
            return

        dx = event.x() - self._last_pos.x()
        dy = event.y() - self._last_pos.y()

        if self._drag_mode == "rotate":
            self._yaw += dx * 0.01
            self._pitch += dy * 0.01
            self._pitch = max(-math.pi / 2 + 0.05, min(math.pi / 2 - 0.05, self._pitch))
        elif self._drag_mode == "pan":
            self._pan_x += dx
            self._pan_y += dy

        self._last_pos = event.pos()
        self.update()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):  # noqa: N802
        self._drag_mode = None
        self._last_pos = None
        event.accept()

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent):  # noqa: N802
        self.reset_view()
        event.accept()

    def reset_view(self):
        self._zoom = 1.0
        self._yaw = math.radians(45.0)
        self._pitch = math.radians(30.0)
        self._pan_x = 0.0
        self._pan_y = 0.0
        self.update()

    # --- Rendering ---------------------------------------------------
    def paintEvent(self, event: QtGui.QPaintEvent):  # noqa: N802
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor(18, 18, 18))
        painter.setRenderHint(QtGui.QPainter.Antialiasing)

        if not self._segments:
            painter.setPen(QtGui.QPen(QtGui.QColor("#bbbbbb"), 1))
            painter.drawText(self.rect(), QtCore.Qt.AlignCenter, "Track geometry not loaded")
            return

        scale = self._compute_scale()

        grid_pen = QtGui.QPen(QtGui.QColor("#455A64"), 1)
        painter.setPen(grid_pen)
        for a, b in self._segments:
            p1 = self._project_point(a, scale)
            p2 = self._project_point(b, scale)
            painter.drawLine(p1, p2)

        if self._centerline:
            path = QtGui.QPainterPath()
            start = self._project_point(self._centerline[0], scale)
            path.moveTo(start)
            for point in self._centerline[1:]:
                path.lineTo(self._project_point(point, scale))
            painter.setPen(QtGui.QPen(QtGui.QColor("#FF7043"), 2))
            painter.drawPath(path)

    def _compute_scale(self) -> float:
        if self._radius <= 0:
            return 1.0
        base = min(self.width(), self.height()) / 2.2
        return base / self._radius * self._zoom

    def _project_point(self, point: tuple[float, float, float], scale: float) -> QtCore.QPointF:
        x = point[0] - self._center[0]
        y = point[1] - self._center[1]
        z = point[2] - self._center[2]

        # Rotate around vertical axis (Z) for yaw.
        cos_yaw = math.cos(self._yaw)
        sin_yaw = math.sin(self._yaw)
        x_rot = x * cos_yaw - y * sin_yaw
        y_rot = x * sin_yaw + y * cos_yaw
        z_rot = z

        # Rotate around horizontal axis (X) for pitch.
        cos_pitch = math.cos(self._pitch)
        sin_pitch = math.sin(self._pitch)
        y_pitch = y_rot * cos_pitch - z_rot * sin_pitch
        z_pitch = y_rot * sin_pitch + z_rot * cos_pitch

        screen_x = self.width() / 2 + x_rot * scale + self._pan_x
        screen_y = self.height() / 2 - y_pitch * scale + self._pan_y
        return QtCore.QPointF(screen_x, screen_y)


class TrackViewerWindow(QtWidgets.QMainWindow):
    """Main application window for browsing tracks."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ICR2 Track Viewer")
        self.resize(1100, 720)

        self._current_dir: Optional[str] = None
        self._tracks: List[TrackMetadata] = []
        self._loaded_track: Optional[LoadedTrack] = None

        self._build_ui()

    # --- UI construction -------------------------------------------
    def _build_ui(self):
        central = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        # Directory chooser
        dir_layout = QtWidgets.QHBoxLayout()
        dir_label = QtWidgets.QLabel("ICR2 directory:")
        self.dir_edit = QtWidgets.QLineEdit()
        browse_btn = QtWidgets.QPushButton("Browse…")
        load_btn = QtWidgets.QPushButton("Load tracks")

        dir_layout.addWidget(dir_label)
        dir_layout.addWidget(self.dir_edit, 1)
        dir_layout.addWidget(browse_btn)
        dir_layout.addWidget(load_btn)

        # Track selector
        track_layout = QtWidgets.QHBoxLayout()
        track_label = QtWidgets.QLabel("Track:")
        self.track_combo = QtWidgets.QComboBox()
        self.track_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        track_layout.addWidget(track_label)
        track_layout.addWidget(self.track_combo, 1)

        # Information labels
        info_layout = QtWidgets.QGridLayout()
        info_layout.setColumnStretch(1, 1)
        name_label = QtWidgets.QLabel("Name:")
        self.name_value = QtWidgets.QLabel("—")
        length_label = QtWidgets.QLabel("Length:")
        self.length_value = QtWidgets.QLabel("—")
        info_layout.addWidget(name_label, 0, 0)
        info_layout.addWidget(self.name_value, 0, 1)
        info_layout.addWidget(length_label, 1, 0)
        info_layout.addWidget(self.length_value, 1, 1)

        # 3D view
        self.view = Track3DView()

        # Status label
        self.status_label = QtWidgets.QLabel()
        self.status_label.setStyleSheet("color: #90CAF9;")

        layout.addLayout(dir_layout)
        layout.addLayout(track_layout)
        layout.addLayout(info_layout)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.status_label)

        self.setCentralWidget(central)

        browse_btn.clicked.connect(self._choose_directory)
        load_btn.clicked.connect(self._load_directory)
        self.track_combo.currentIndexChanged.connect(self._on_track_selected)

    # --- Directory selection ---------------------------------------
    def _choose_directory(self):
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self,
            "Select IndyCar Racing II directory",
            self.dir_edit.text() or os.getcwd(),
        )
        if path:
            self.dir_edit.setText(path)
            self._load_directory()

    def _load_directory(self):
        path = self.dir_edit.text().strip()
        if not path:
            return
        try:
            tracks = discover_tracks(path)
        except TrackDiscoveryError as exc:
            QtWidgets.QMessageBox.warning(self, "Tracks not found", str(exc))
            self._set_status(str(exc))
            self.track_combo.clear()
            self.view.set_wireframe(None)
            self.name_value.setText("—")
            self.length_value.setText("—")
            return

        if not tracks:
            msg = "No tracks with TRK/DAT files found in the TRACKS directory."
            QtWidgets.QMessageBox.information(self, "No tracks", msg)
            self._set_status(msg)
            self.track_combo.clear()
            self.view.set_wireframe(None)
            self.name_value.setText("—")
            self.length_value.setText("—")
            return

        self._current_dir = path
        self._tracks = tracks
        self.track_combo.blockSignals(True)
        self.track_combo.clear()
        for track in tracks:
            self.track_combo.addItem(track.display_name, track)
        self.track_combo.blockSignals(False)
        self.track_combo.setCurrentIndex(0)
        self._set_status(f"Loaded {len(tracks)} track(s).")
        self._on_track_selected(0)

    # --- Track loading ---------------------------------------------
    def _on_track_selected(self, index: int):
        if index < 0:
            return
        metadata = self.track_combo.itemData(index)
        if not isinstance(metadata, TrackMetadata):
            return
        self._load_track(metadata)

    def _load_track(self, metadata: TrackMetadata):
        try:
            trk = load_trk_from_folder(metadata.path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Track load failed", str(exc))
            self._set_status(f"Failed to load {metadata.display_name}: {exc}")
            self.view.set_wireframe(None)
            return

        wireframe = build_track_wireframe(trk)
        self.view.set_wireframe(wireframe)

        length_miles = _compute_track_length_miles(trk, metadata.txt_length_miles)

        self._loaded_track = LoadedTrack(
            metadata=metadata,
            trk=trk,
            wireframe=wireframe,
            length_miles=length_miles,
        )

        self.name_value.setText(metadata.display_name)
        if length_miles:
            self.length_value.setText(f"{length_miles:.3f} mi")
        elif metadata.txt_length_miles:
            self.length_value.setText(f"{metadata.txt_length_miles:.3f} mi (from TXT)")
        else:
            self.length_value.setText("—")

        self._set_status(
            f"Loaded track '{metadata.display_name}'. Double-click the view to reset the camera."
        )

    def _set_status(self, message: str):
        self.status_label.setText(message)


def _compute_track_length_miles(trk: TRKFile, fallback: Optional[float]) -> Optional[float]:
    try:
        if trk.trklength and trk.trklength > 0:
            return float(trk.trklength) / TRACK_LENGTH_SCALE
    except Exception:
        pass
    return fallback
