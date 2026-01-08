"""Embedded surface preview widget for the standalone track viewer."""
from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets

from track_viewer.preview_api import TrackPreviewApi
from track_viewer.preview_coordinator import PreviewCoordinator
from track_viewer.preview_input_router import PreviewInputRouter


class TrackPreviewWidget(QtWidgets.QFrame):
    """Renders the TRK ground surface similar to the timing overlay."""

    cursorPositionChanged = QtCore.pyqtSignal(object)
    selectedFlagChanged = QtCore.pyqtSignal(object)
    camerasChanged = QtCore.pyqtSignal(list, list)
    selectedCameraChanged = QtCore.pyqtSignal(object, object)
    activeLpLineChanged = QtCore.pyqtSignal(str)
    aiLineLoaded = QtCore.pyqtSignal(str)
    lpRecordSelected = QtCore.pyqtSignal(str, int)
    diagramClicked = QtCore.pyqtSignal()
    weatherCompassHeadingAdjustChanged = QtCore.pyqtSignal(str, int)
    weatherCompassWindDirectionChanged = QtCore.pyqtSignal(str, int)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(320, 240)
        self.setAutoFillBackground(True)
        self.setMouseTracking(True)

        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(24, 24, 24))
        self.setPalette(palette)

        self._coordinator = PreviewCoordinator(
            request_repaint=self.update,
            cursor_position_changed=self.cursorPositionChanged.emit,
            selected_flag_changed=self.selectedFlagChanged.emit,
            cameras_changed=self.camerasChanged.emit,
            selected_camera_changed=self.selectedCameraChanged.emit,
            active_lp_line_changed=self.activeLpLineChanged.emit,
            ai_line_loaded=self.aiLineLoaded.emit,
            lp_record_selected=self.lpRecordSelected.emit,
            diagram_clicked=self.diagramClicked.emit,
            weather_heading_adjust_changed=self.weatherCompassHeadingAdjustChanged.emit,
            weather_wind_direction_changed=self.weatherCompassWindDirectionChanged.emit,
        )
        self.api = TrackPreviewApi(self._coordinator)
        self._input_router = PreviewInputRouter(self._coordinator)
        self._input_router.handle_resize(self.size())

    # ------------------------------------------------------------------
    # Qt events
    # ------------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: D401 - Qt signature
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), self.palette().color(QtGui.QPalette.Window))
        self._coordinator.paint(painter, self.size())

    def resizeEvent(self, event) -> None:  # noqa: D401 - Qt signature
        self._input_router.handle_resize(self.size())
        super().resizeEvent(event)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:  # noqa: D401 - Qt signature
        if self._input_router.handle_wheel(event, self.size()):
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401 - Qt signature
        if self._input_router.handle_mouse_press(event, self.size()):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401 - Qt signature
        handled = self._input_router.handle_mouse_move(event, self.size())
        if handled:
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401 - Qt signature
        if self._input_router.handle_mouse_release(event, self.size()):
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: D401 - Qt signature
        self._input_router.handle_leave()
        super().leaveEvent(event)

    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:  # noqa: D401 - Qt signature
        if self._input_router.handle_key_press(event):
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event: QtGui.QKeyEvent) -> None:  # noqa: D401 - Qt signature
        if self._input_router.handle_key_release(event):
            event.accept()
            return
        super().keyReleaseEvent(event)
