from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from PyQt5 import QtCore, QtGui

from sg_viewer.preview.hover_detection import find_hovered_unconnected_node


@dataclass(frozen=True)
class InteractionInputs:
    creation_active: bool
    delete_section_active: bool
    split_section_mode: bool
    transform_available: bool
    interaction_dragging_node: bool
    interaction_dragging_section: bool
    has_split_hover_point: bool = False


@dataclass(frozen=True)
class MouseIntent:
    kind: Literal[
        "start_pan",
        "update_pan",
        "stop_pan",
        "prepare_delete",
        "delete_click",
        "update_split_hover",
        "commit_split",
        "hover_changed",
        "consume",
        "noop",
    ]
    payload: object | None = None


class InteractionState:
    def __init__(self) -> None:
        self._is_panning = False
        self._press_pos: QtCore.QPoint | None = None
        self._hovered_endpoint: tuple[int, str] | None = None

    @property
    def hovered_endpoint(self) -> tuple[int, str] | None:
        return self._hovered_endpoint

    def reset(self) -> None:
        self._is_panning = False
        self._press_pos = None
        self._hovered_endpoint = None

    def stop_panning(self) -> None:
        self._is_panning = False
        self._press_pos = None

    def on_mouse_press(self, event: QtGui.QMouseEvent, inputs: InteractionInputs) -> MouseIntent:
        if inputs.delete_section_active and event.button() == QtCore.Qt.LeftButton:
            self._is_panning = False
            self._press_pos = event.pos()
            return MouseIntent(kind="prepare_delete")

        if inputs.creation_active or inputs.split_section_mode:
            self._is_panning = False
            self._press_pos = None
            return MouseIntent(kind="consume")

        if event.button() != QtCore.Qt.LeftButton:
            return MouseIntent(kind="noop")

        if (
            inputs.transform_available
            and not inputs.interaction_dragging_node
            and not inputs.interaction_dragging_section
        ):
            self._is_panning = True
            self._press_pos = event.pos()
            return MouseIntent(kind="start_pan", payload=(event.pos().x(), event.pos().y()))

        return MouseIntent(kind="noop")

    def on_mouse_move(
        self,
        event: QtGui.QMouseEvent,
        inputs: InteractionInputs,
        creation_context=None,
    ) -> MouseIntent:
        if inputs.creation_active or inputs.delete_section_active:
            return MouseIntent(kind="consume")

        if inputs.split_section_mode:
            return MouseIntent(kind="update_split_hover", payload=event.pos())

        if self._is_panning:
            return MouseIntent(kind="update_pan", payload=(event.pos().x(), event.pos().y()))

        if creation_context is not None:
            hover = find_hovered_unconnected_node(
                (event.pos().x(), event.pos().y()),
                creation_context,
            )

            if hover != self._hovered_endpoint:
                self._hovered_endpoint = hover
                return MouseIntent(kind="hover_changed")

        return MouseIntent(kind="noop")

    def on_mouse_release(self, event: QtGui.QMouseEvent, inputs: InteractionInputs) -> MouseIntent:
        if inputs.split_section_mode:
            if event.button() == QtCore.Qt.LeftButton and inputs.has_split_hover_point:
                self._press_pos = None
                return MouseIntent(kind="commit_split")
            self._press_pos = None
            return MouseIntent(kind="consume")

        if event.button() == QtCore.Qt.LeftButton:
            if inputs.delete_section_active:
                if (
                    self._press_pos is not None
                    and (event.pos() - self._press_pos).manhattanLength() < 6
                ):
                    self._press_pos = None
                    return MouseIntent(kind="delete_click", payload=event.pos())
                self._press_pos = None
                return MouseIntent(kind="consume")
            if inputs.creation_active:
                self._press_pos = None
                return MouseIntent(kind="consume")

            if self._is_panning:
                click_pos = None
                if (
                    self._press_pos is not None
                    and (event.pos() - self._press_pos).manhattanLength() < 6
                ):
                    click_pos = event.pos()

                self._is_panning = False
                self._press_pos = None
                return MouseIntent(kind="stop_pan", payload=click_pos)

        self._press_pos = None
        return MouseIntent(kind="noop")
