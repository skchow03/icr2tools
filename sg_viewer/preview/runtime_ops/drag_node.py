from __future__ import annotations

from PyQt5 import QtCore, QtGui

from sg_viewer.model.preview_state_utils import update_node_status
from sg_viewer.preview.creation_controller import (
    CreationEvent,
    CreationEventContext,
)
from sg_viewer.preview.interaction_state import InteractionInputs, MouseIntent
from sg_viewer.preview.runtime_ops.base import Point, logger
from sg_viewer.preview.selection import build_node_positions, find_unconnected_node_hit


class _RuntimeCoreDragNodeMixin:
    def _update_node_status(self) -> None:
        """Update cached node colors directly from section connectivity."""
        update_node_status(self._section_manager.sections, self._node_status)

    def build_node_positions(self) -> dict[tuple[int, str], Point]:
        return build_node_positions(self._section_manager.sections)

    @property
    def node_status(self) -> dict[tuple[int, str], str]:
        return self._node_status

    @property
    def node_radius_px(self) -> int:
        return self._node_radius_px

    @property
    def hovered_endpoint(self) -> tuple[int, str] | None:
        return self._interaction_state.hovered_endpoint

    def _creation_context(self) -> CreationEventContext | None:
        widget_size = self._widget_size()
        transform = self.current_transform(widget_size)
        if transform is None:
            return None

        def map_to_track(point: tuple[float, float]) -> Point | None:
            return self._controller.map_to_track(
                QtCore.QPointF(*point), widget_size, self._widget_height(), transform
            )

        def find_unconnected_node(
            point: tuple[float, float],
        ) -> tuple[int, str, Point, tuple[float, float] | None] | None:
            return find_unconnected_node_hit(
                point,
                self._section_manager.sections,
                transform,
                self._widget_height(),
                self._node_radius_px,
            )

        return CreationEventContext(
            map_to_track=map_to_track, find_unconnected_node=find_unconnected_node
        )

    def _creation_active(self) -> bool:
        return (
            self._creation_controller.straight_active
            or self._creation_controller.curve_active
        )

    def _handle_creation_mouse_press(self, event: QtGui.QMouseEvent) -> bool:
        context = self._creation_context()
        if context is None:
            return False

        button = "left" if event.button() == QtCore.Qt.LeftButton else None
        creation_event = CreationEvent(
            pos=(event.pos().x(), event.pos().y()), button=button
        )
        update = self._creation_controller.handle_mouse_press(creation_event, context)
        self._apply_creation_update(update)
        return update.handled

    def _handle_creation_mouse_move(self, pos: QtCore.QPoint) -> bool:
        context = self._creation_context()
        if context is None:
            return False

        update = self._creation_controller.handle_mouse_move(
            (pos.x(), pos.y()), context
        )
        self._apply_creation_update(update)
        return update.handled

    def _handle_creation_mouse_release(self, event: QtGui.QMouseEvent) -> bool:
        context = self._creation_context()
        if context is None:
            return False

        button = "left" if event.button() == QtCore.Qt.LeftButton else None
        creation_event = CreationEvent(
            pos=(event.pos().x(), event.pos().y()), button=button
        )
        update = self._creation_controller.handle_mouse_release(creation_event, context)
        self._apply_creation_update(update)
        return update.handled

    def handle_creation_mouse_press(self, event: QtGui.QMouseEvent) -> bool:
        return self._handle_creation_mouse_press(event)

    def handle_creation_mouse_move(self, pos: QtCore.QPoint) -> bool:
        return self._handle_creation_mouse_move(pos)

    def handle_creation_mouse_release(self, event: QtGui.QMouseEvent) -> bool:
        return self._handle_creation_mouse_release(event)

    def creation_context(self) -> CreationEventContext | None:
        return self._creation_context()

    def handle_click(self, pos: QtCore.QPoint) -> None:
        self._handle_click(pos)

    # ------------------------------------------------------------------
    # Input events
    # ------------------------------------------------------------------
    def on_resize(self, event: QtGui.QResizeEvent) -> None:  # noqa: D401
        _ = event
        self._update_fit_scale()
        self._context.request_repaint()

    def on_wheel(self, event: QtGui.QWheelEvent) -> None:  # noqa: D401
        widget_size = self._widget_size()
        transform = self.current_transform(widget_size)
        if not self._transform_controller.on_wheel(
            event,
            widget_size=widget_size,
            widget_height=self._widget_height(),
            transform=transform,
        ):
            return
        self._request_interaction_repaint()
        event.accept()

    def on_mouse_press(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if self._handle_creation_mouse_press(event):
            return

        inputs = self._interaction_inputs()
        if (
            not inputs.delete_section_active
            and not inputs.creation_active
            and not inputs.split_section_mode
            and self._interaction.handle_mouse_press(event)
        ):
            self.log_debug(
                "mousePressEvent handled by interaction at %s", event.pos()
            )
            return

        intent = self._interaction_state.on_mouse_press(event, inputs)
        self._apply_mouse_intent(intent, event)

    def on_mouse_move(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if self._handle_creation_mouse_move(event.pos()):
            event.accept()
            return

        inputs = self._interaction_inputs()
        if inputs.creation_active:
            event.accept()
            return

        if inputs.delete_section_active:
            event.accept()
            return

        if inputs.split_section_mode:
            intent = self._interaction_state.on_mouse_move(event, inputs)
            self._apply_mouse_intent(intent, event)
            return

        if self._interaction.handle_mouse_move(event):
            self._request_interaction_repaint()
            return

        intent = self._interaction_state.on_mouse_move(
            event, inputs, self._creation_context()
        )
        self._apply_mouse_intent(intent, event)

    def on_mouse_release(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if self._handle_creation_mouse_release(event):
            return

        inputs = self._interaction_inputs(
            has_split_hover_point=self._split_hover_point is not None
        )

        if inputs.split_section_mode:
            intent = self._interaction_state.on_mouse_release(event, inputs)
            self._apply_mouse_intent(intent, event)
            return

        if inputs.delete_section_active and event.button() == QtCore.Qt.LeftButton:
            intent = self._interaction_state.on_mouse_release(event, inputs)
            self._apply_mouse_intent(intent, event)
            return

        if inputs.creation_active:
            event.accept()
            return

        if self._interaction.handle_mouse_release(event):
            self.log_debug(
                "mouseReleaseEvent handled by interaction at %s", event.pos()
            )
            return

        intent = self._interaction_state.on_mouse_release(event, inputs)
        self._apply_mouse_intent(intent, event)

    def on_leave(self, event: QtCore.QEvent) -> None:  # noqa: D401
        _ = event
        self._clear_split_hover()

    def _interaction_inputs(
        self, *, has_split_hover_point: bool = False
    ) -> InteractionInputs:
        widget_size = self._widget_size()
        transform = self.current_transform(widget_size)
        return InteractionInputs(
            creation_active=self.creation_active,
            delete_section_active=self.delete_section_active,
            split_section_mode=self.split_section_mode,
            transform_available=transform is not None,
            interaction_dragging_node=self._interaction.is_dragging_node,
            interaction_dragging_section=self._interaction.is_dragging_section,
            has_split_hover_point=has_split_hover_point,
        )

    def _apply_mouse_intent(self, intent: MouseIntent, event: QtGui.QMouseEvent) -> None:
        if intent.kind == "start_pan":
            if intent.payload is not None:
                self._transform_controller.begin_pan(intent.payload)
                event.accept()
            return
        if intent.kind == "update_pan":
            if intent.payload is not None and self._transform_controller.update_pan(
                intent.payload
            ):
                self._request_interaction_repaint()
                event.accept()
            return
        if intent.kind == "stop_pan":
            self._transform_controller.end_pan()
            if intent.payload is not None:
                self._handle_click(intent.payload)
            event.accept()
            return
        if intent.kind == "prepare_delete":
            event.accept()
            return
        if intent.kind == "delete_click":
            if intent.payload is not None:
                self._handle_delete_click(intent.payload)
            event.accept()
            return
        if intent.kind == "update_split_hover":
            if intent.payload is not None:
                self._update_split_hover(intent.payload)
            event.accept()
            return
        if intent.kind == "commit_split":
            self._commit_split()
            event.accept()
            return
        if intent.kind == "hover_changed":
            self._context.request_repaint()
            return
        if intent.kind == "consume":
            event.accept()

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _handle_click(self, pos: QtCore.QPoint) -> None:
        if self._delete_section_active and self._handle_delete_click(pos):
            return

        widget_size = self._widget_size()
        transform = self.current_transform(widget_size)
        logger.debug(
            "Handling click at screen %s with widget size %s and transform %s",
            pos,
            widget_size,
            transform,
        )
        self._selection.handle_click(
            pos,
            lambda p: self._controller.map_to_track(
                p, widget_size, self._widget_height(), transform
            ),
            transform,
        )
