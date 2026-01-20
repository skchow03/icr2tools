from __future__ import annotations

from PyQt5 import QtCore, QtGui

from sg_viewer.preview.hover_detection import find_hovered_unconnected_node


class InteractionState:
    def __init__(self) -> None:
        self._is_panning = False
        self._last_mouse_pos: QtCore.QPoint | None = None
        self._press_pos: QtCore.QPoint | None = None
        self._hovered_endpoint: tuple[int, str] | None = None

    @property
    def hovered_endpoint(self) -> tuple[int, str] | None:
        return self._hovered_endpoint

    def reset(self) -> None:
        self._is_panning = False
        self._last_mouse_pos = None
        self._press_pos = None
        self._hovered_endpoint = None

    def stop_panning(self) -> None:
        self._is_panning = False
        self._last_mouse_pos = None
        self._press_pos = None

    def on_mouse_press(self, event: QtGui.QMouseEvent, context) -> None:
        if context.handle_creation_mouse_press(event):
            return

        if context.delete_section_active and event.button() == QtCore.Qt.LeftButton:
            self._is_panning = False
            self._last_mouse_pos = None
            self._press_pos = event.pos()
            event.accept()
            return

        if context.creation_active:
            event.accept()
            return

        if context.split_section_mode:
            self._is_panning = False
            self._last_mouse_pos = None
            self._press_pos = None
            event.accept()
            return

        if context.interaction.handle_mouse_press(event):
            context.log_debug(
                "mousePressEvent handled by interaction at %s", event.pos()
            )
            return

        if (
            event.button() == QtCore.Qt.LeftButton
            and context.controller.current_transform(context.widget_size()) is not None
            and not context.interaction.is_dragging_node
            and not context.interaction.is_dragging_section
        ):
            self._is_panning = True
            self._last_mouse_pos = event.pos()
            self._press_pos = event.pos()
            context.set_user_transform_active()
            context.log_debug("mousePressEvent starting pan at %s", event.pos())
            event.accept()

    def on_mouse_move(self, event: QtGui.QMouseEvent, context) -> None:
        if context.handle_creation_mouse_move(event.pos()):
            event.accept()
            return

        if context.creation_active:
            event.accept()
            return

        if context.delete_section_active:
            event.accept()
            return

        if context.split_section_mode:
            context.update_split_hover(event.pos())
            event.accept()
            return

        if context.interaction.handle_mouse_move(event):
            context.request_repaint()
            return

        if self._is_panning and self._last_mouse_pos is not None:
            widget_size = context.widget_size()
            transform = context.controller.current_transform(widget_size)
            if transform:
                state = context.transform_state
                center = state.view_center or context.controller.default_center()
                if center is not None:
                    scale, _ = transform
                    delta = event.pos() - self._last_mouse_pos
                    self._last_mouse_pos = event.pos()
                    context.pan_view((delta.x(), delta.y()), scale, center)
                    context.request_repaint()
            event.accept()
            return

        creation_context = context.creation_context()
        if creation_context is not None:
            hover = find_hovered_unconnected_node(
                (event.pos().x(), event.pos().y()),
                creation_context,
            )

            if hover != self._hovered_endpoint:
                self._hovered_endpoint = hover
                context.request_repaint()

    def on_mouse_release(self, event: QtGui.QMouseEvent, context) -> None:
        if context.handle_creation_mouse_release(event):
            return

        if context.split_section_mode:
            if event.button() == QtCore.Qt.LeftButton and context.split_hover_point is not None:
                context.commit_split()
            self._press_pos = None
            event.accept()
            return

        if event.button() == QtCore.Qt.LeftButton:
            if context.delete_section_active:
                if (
                    self._press_pos is not None
                    and (event.pos() - self._press_pos).manhattanLength() < 6
                ):
                    context.handle_delete_click(event.pos())
                self._press_pos = None
                event.accept()
                return
            if context.split_section_mode:
                self._press_pos = None
                event.accept()
                return
            if context.creation_active:
                event.accept()
                return
            if context.interaction.handle_mouse_release(event):
                context.log_debug(
                    "mouseReleaseEvent handled by interaction at %s", event.pos()
                )
                return
            self._is_panning = False
            self._last_mouse_pos = None
            if (
                self._press_pos is not None
                and (event.pos() - self._press_pos).manhattanLength() < 6
            ):
                context.log_debug(
                    "mouseReleaseEvent treating as click (press=%s, release=%s, delta=%s)",
                    self._press_pos,
                    event.pos(),
                    (event.pos() - self._press_pos).manhattanLength(),
                )
                context.handle_click(event.pos())
            else:
                context.log_debug(
                    "mouseReleaseEvent ending pan without click (press=%s, release=%s, delta=%s)",
                    self._press_pos,
                    event.pos(),
                    0
                    if self._press_pos is None
                    else (event.pos() - self._press_pos).manhattanLength(),
                )
            self._press_pos = None
