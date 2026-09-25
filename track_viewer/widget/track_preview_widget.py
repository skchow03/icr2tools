"""Qt widget that hosts the track preview surface and input wiring.

This module lives in the UI layer. It owns the preview widget instance,
creates the coordinator, and forwards Qt events into the input router.
It does not load track data, mutate model state directly, or perform any
rendering beyond handing a QPainter to the coordinator.
"""
from __future__ import annotations

from PyQt5 import QtCore, QtGui, QtWidgets

from track_viewer.preview_api import TrackPreviewApi
from track_viewer.preview_coordinator import PreviewCoordinator
from track_viewer.preview_input_router import PreviewInputRouter


class TrackPreviewWidget(QtWidgets.QOpenGLWidget):
    """UI widget that wires preview paint and input events.

    The widget owns transient UI collaborators (coordinator, API, input router)
    and remains mutable for the lifetime of the window. It does not persist
    data; state changes flow through the coordinator and models.
    """

    cursorPositionChanged = QtCore.pyqtSignal(object)
    selectedFlagChanged = QtCore.pyqtSignal(object)
    camerasChanged = QtCore.pyqtSignal(list, list)
    selectedCameraChanged = QtCore.pyqtSignal(object, object)
    cameraPositionChanged = QtCore.pyqtSignal(int)
    activeLpLineChanged = QtCore.pyqtSignal(str)
    aiLineLoaded = QtCore.pyqtSignal(str)
    lpRecordSelected = QtCore.pyqtSignal(str, int)
    lpCurveEdited = QtCore.pyqtSignal(str)
    diagramClicked = QtCore.pyqtSignal()
    weatherCompassHeadingAdjustChanged = QtCore.pyqtSignal(str, int)
    weatherCompassWindDirectionChanged = QtCore.pyqtSignal(str, int)

    def __init__(self) -> None:
        super().__init__()
        self.setMinimumSize(320, 240)
        self.setAutoFillBackground(False)
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
            camera_position_changed=self.cameraPositionChanged.emit,
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

    def configure_lp_curve_edit(self, enabled: bool, influence_feet: float = 180.0) -> None:
        controller = self._coordinator.mouse_controller
        if not enabled:
            edited = controller.end_curve_drag()
            if edited:
                self.lpCurveEdited.emit(edited)
        controller.curve_edit_enabled = bool(enabled)
        controller.curve_influence_feet = float(influence_feet)
        if enabled:
            # A click that misses an LP record must not fall through into map
            # panning, including when a pan began before this mode was enabled.
            controller.cancel_view_pan()
        self.setCursor(
            QtCore.Qt.CrossCursor if enabled else QtCore.Qt.ArrowCursor
        )

    # ------------------------------------------------------------------
    # Qt events
    # ------------------------------------------------------------------
    def paintGL(self) -> None:  # noqa: D401 - Qt signature
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), self.palette().color(QtGui.QPalette.Window))
        self._coordinator.paint(painter, self.size())
        painter.end()

    def resizeEvent(self, event) -> None:  # noqa: D401 - Qt signature
        self._input_router.handle_resize(self.size())
        super().resizeEvent(event)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:  # noqa: D401 - Qt signature
        if self._coordinator.mouse_controller.curve_edit_enabled:
            event.accept()
            return
        if self._input_router.handle_wheel(event, self.size()):
            event.accept()
            return
        super().wheelEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401 - Qt signature
        controller = self._coordinator.mouse_controller
        if controller.curve_edit_enabled:
            if event.button() == QtCore.Qt.LeftButton:
                controller.begin_curve_drag(event.pos(), self.size())
            # Do not forward missed clicks to the normal pan/camera/flag
            # handlers. While editing, the track transform is locked.
            event.accept()
            return
        if self._input_router.handle_mouse_press(event, self.size()):
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401 - Qt signature
        controller = self._coordinator.mouse_controller
        if controller.curve_edit_enabled:
            if controller.curve_drag_active:
                controller.update_curve_drag(event.pos(), self.size())
            event.accept()
            return
        handled = self._input_router.handle_mouse_move(event, self.size())
        if handled:
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401 - Qt signature
        controller = self._coordinator.mouse_controller
        if controller.curve_edit_enabled:
            if event.button() == QtCore.Qt.LeftButton and controller.curve_drag_active:
                edited = controller.end_curve_drag()
                if edited:
                    self.lpCurveEdited.emit(edited)
            event.accept()
            return
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
