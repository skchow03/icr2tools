from __future__ import annotations

from typing import Callable

from PyQt5 import QtCore, QtGui, QtWidgets

from sg_viewer.model.sg_document import SGDocument
from sg_viewer.preview.context import Point, Transform
from sg_viewer.preview.runtime import PreviewRuntime
from sg_viewer.ui.preview_presenter import PreviewPresenter


class PreviewWidgetQt(QtWidgets.QWidget):
    selectedSectionChanged = QtCore.pyqtSignal(object)
    sectionsChanged = QtCore.pyqtSignal()
    newStraightModeChanged = QtCore.pyqtSignal(bool)
    newCurveModeChanged = QtCore.pyqtSignal(bool)
    deleteModeChanged = QtCore.pyqtSignal(bool)
    splitSectionModeChanged = QtCore.pyqtSignal(bool)
    scaleChanged = QtCore.pyqtSignal(float)
    interactionDragChanged = QtCore.pyqtSignal(bool)

    def __init__(
        self,
        parent: QtWidgets.QWidget | None = None,
        show_status: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setMinimumSize(640, 480)
        self.setMouseTracking(True)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)

        palette = self.palette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor("black"))
        self.setPalette(palette)

        self._document = SGDocument()
        self._runtime = PreviewRuntime(
            context=self,
            sg_document=self._document,
            show_status=show_status,
            emit_selected_section_changed=self.selectedSectionChanged.emit,
            emit_sections_changed=self.sectionsChanged.emit,
            emit_new_straight_mode_changed=self.newStraightModeChanged.emit,
            emit_new_curve_mode_changed=self.newCurveModeChanged.emit,
            emit_delete_mode_changed=self.deleteModeChanged.emit,
            emit_split_section_mode_changed=self.splitSectionModeChanged.emit,
            emit_scale_changed=self.scaleChanged.emit,
            emit_interaction_drag_changed=self.interactionDragChanged.emit,
        )
        self._presenter = PreviewPresenter(
            context=self,
            runtime=self._runtime,
            background_color=self.palette().color(QtGui.QPalette.Window),
        )
        self._throttled_repaint_timer = QtCore.QTimer(self)
        self._throttled_repaint_timer.setSingleShot(True)
        self._throttled_repaint_timer.timeout.connect(self.update)

    def __getattr__(self, name: str):
        return getattr(self._runtime, name)

    def current_transform(self, widget_size: tuple[int, int]) -> Transform | None:
        return self._runtime.current_transform(widget_size)

    def begin_drag_transform(self, transform: Transform) -> None:
        self._runtime.begin_drag_transform(transform)

    def end_drag_transform(self) -> None:
        self._runtime.end_drag_transform()

    def map_to_track(
        self,
        screen_pos: tuple[float, float] | Point,
        widget_size: tuple[int, int],
        widget_height: int,
        transform: Transform | None = None,
    ) -> Point | None:
        return self._runtime.map_to_track(screen_pos, widget_size, widget_height, transform)

    def set_status(self, text: str) -> None:
        self._runtime.set_status(text)

    def set_status_text(self, text: str) -> None:
        self._runtime.set_status_text(text)

    def request_repaint(self) -> None:
        self.update()

    def request_repaint_throttled(self, min_interval_ms: int = 33) -> None:
        interval_ms = max(1, int(min_interval_ms))
        if self._throttled_repaint_timer.isActive():
            return
        self._throttled_repaint_timer.start(interval_ms)

    def widget_size(self) -> tuple[int, int]:
        return (self.width(), self.height())

    def widget_height(self) -> int:
        return self.height()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: D401
        super().resizeEvent(event)
        self._runtime.on_resize(event)

    def paintEvent(self, event: QtGui.QPaintEvent) -> None:  # noqa: D401
        _ = event
        painter = QtGui.QPainter(self)
        self._presenter.paint(painter)

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        self._runtime.on_mouse_press(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        self._runtime.on_mouse_move(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        self._runtime.on_mouse_release(event)

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:  # noqa: D401
        self._runtime.on_wheel(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:  # noqa: D401
        self._runtime.on_leave(event)
        super().leaveEvent(event)

    def set_preview_color(self, key: str, color: QtGui.QColor) -> None:
        self._presenter.set_preview_color(key, color)
        self.update()

    def preview_color(self, key: str) -> QtGui.QColor:
        return self._presenter.preview_color(key)
