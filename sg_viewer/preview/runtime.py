from __future__ import annotations

import logging
import math
from dataclasses import replace
from pathlib import Path
from typing import Callable, List, Tuple

from PyQt5 import QtCore, QtGui

from icr2_core.trk.sg_classes import SGFile
from icr2_core.sg_elevation import sample_sg_elevation
from sg_viewer.models import preview_state, selection
from sg_viewer.preview.geometry import (
    CURVE_SOLVE_TOLERANCE as CURVE_SOLVE_TOLERANCE_DEFAULT,
)
from sg_viewer.preview.context import PreviewContext
from sg_viewer.preview.preview_defaults import create_empty_sgfile
from sg_viewer.preview.preview_mutations import project_point_to_polyline
from sg_viewer.preview.trk_overlay_controller import TrkOverlayController
from sg_viewer.preview.transform_controller import TransformController
from sg_viewer.preview.selection import build_node_positions, find_unconnected_node_hit
from sg_viewer.services.preview_background import PreviewBackground
from sg_viewer.sg_preview.view_state import SgPreviewViewState
from sg_viewer.ui.elevation_profile import ElevationProfileData, ElevationSource
from sg_viewer.geometry.centerline_utils import (
    compute_start_finish_mapping_from_centerline,
)
from sg_viewer.geometry.derived_geometry import DerivedGeometry
from sg_viewer.geometry.picking import project_point_to_segment
from sg_viewer.geometry.sg_geometry import (
    scale_section,
    rebuild_centerline_from_sections,
)
from sg_viewer.model.sg_document import SGDocument
from sg_viewer.ui.preview_editor import PreviewEditor
from sg_viewer.preview.creation_controller import CreationController, CreationEvent, CreationEventContext, CreationUpdate
from sg_viewer.ui.preview_interaction import PreviewInteraction
from sg_viewer.ui.preview_state_controller import PreviewStateController
from sg_viewer.ui.preview_section_manager import PreviewSectionManager
from sg_viewer.ui.preview_viewport import PreviewViewport
from sg_viewer.models.preview_state_utils import update_node_status
from sg_viewer.models.sg_model import PreviewData, SectionPreview
from sg_viewer.models.preview_fsection import PreviewFSection
from sg_viewer.geometry.dlong import set_start_finish
from sg_viewer.geometry.topology import is_closed_loop, loop_length
from sg_viewer.preview.interaction_state import InteractionInputs, InteractionState, MouseIntent
from sg_viewer.preview.edit_session import apply_preview_to_sgfile
from sg_viewer.preview.runtime_ops import PreviewRuntimeOps


logger = logging.getLogger(__name__)

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]


class PreviewRuntime(PreviewRuntimeOps):
    """Preview interaction and data model logic."""

    CURVE_SOLVE_TOLERANCE = CURVE_SOLVE_TOLERANCE_DEFAULT  # inches

    def __init__(
        self,
        context: PreviewContext,
        sg_document: SGDocument,
        show_status: Callable[[str], None] | None = None,
        emit_selected_section_changed: Callable[[object], None] | None = None,
        emit_sections_changed: Callable[[], None] | None = None,
        emit_new_straight_mode_changed: Callable[[bool], None] | None = None,
        emit_new_curve_mode_changed: Callable[[bool], None] | None = None,
        emit_delete_mode_changed: Callable[[bool], None] | None = None,
        emit_split_section_mode_changed: Callable[[bool], None] | None = None,
        emit_scale_changed: Callable[[float], None] | None = None,
        emit_interaction_drag_changed: Callable[[bool], None] | None = None,
    ) -> None:
        self._context = context
        self._emit_selected_section_changed = emit_selected_section_changed
        self._emit_sections_changed = emit_sections_changed
        self._emit_new_straight_mode_changed = emit_new_straight_mode_changed
        self._emit_new_curve_mode_changed = emit_new_curve_mode_changed
        self._emit_delete_mode_changed = emit_delete_mode_changed
        self._emit_split_section_mode_changed = emit_split_section_mode_changed
        self._emit_scale_changed = emit_scale_changed
        self._emit_interaction_drag_changed = emit_interaction_drag_changed
        self._document = sg_document
        self._derived_geometry = DerivedGeometry(self._document)
        self._suppress_document_dirty = False

        self._document.section_changed.connect(self._on_section_changed)
        self._document.geometry_changed.connect(self._on_geometry_changed)

        self._controller = PreviewStateController()

        self._background = PreviewBackground()
        self._viewport = PreviewViewport(
            background=self._background,
            get_transform_state=lambda: self._transform_state,
            set_transform_state=self._set_transform_state,
        )
        self._transform_controller = TransformController(
            viewport=self._viewport,
            get_state=lambda: self._transform_state,
            set_state=self._set_transform_state,
            map_to_track_cb=self._map_to_track_cb,
        )
        self._section_manager = PreviewSectionManager(
            self._viewport.combine_bounds_with_background
        )

        self._preview_data: PreviewData | None = None
        self._trk_overlay = TrkOverlayController()
        self._start_finish_dlong: float | None = None
        self._start_finish_mapping: tuple[Point, Point, Point] | None = None

        self._sg_preview_model = None
        self._sg_preview_view_state = SgPreviewViewState()
        self._show_sg_fsects = False
        self._show_xsect_dlat_line = False
        self._selected_xsect_index: int | None = None
        self._fsects_by_section: list[list[PreviewFSection]] = []

        self._selection = selection.SelectionManager()
        self._selection.selectionChanged.connect(self._on_selection_changed)

        self._creation_controller = CreationController()
        self._interaction_state = InteractionState()

        self._drag_transform: Transform | None = None
        self._drag_transform_active = False

        self._split_section_mode = False
        self._split_previous_status_message: str | None = None
        self._split_hover_point: Point | None = None
        self._split_hover_section_index: int | None = None


        self._straight_creation = self._creation_controller.straight_interaction
        self._curve_creation = self._creation_controller.curve_interaction

        self._editor = PreviewEditor(
            self._controller,
            self._selection,
            self._straight_creation,
            self._curve_creation,
        )


        self._show_curve_markers = True
        self._show_axes = False

        self._node_status = {}   # (index, "start"|"end") -> "green" or "orange"
        self._disconnected_nodes: set[tuple[int, str]] = set()
        self._node_radius_px = 6
        self._has_unsaved_changes = False
        self._show_status = show_status or self.set_status_text

        self._interaction = PreviewInteraction(
            self._context,
            self._selection,
            self._section_manager,
            self._editor,
            self.set_sections,
            self.rebuild_after_start_finish,
            self._node_radius_px,
            self._stop_panning,
            show_status=self._show_status,
            emit_drag_state_changed=self._emit_interaction_drag_changed,
            sync_fsects_on_connection=self._sync_fsects_on_connection,
        )


        self._set_default_view_bounds()

        assert hasattr(self, "_editor")

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
        self._context.request_repaint()
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
            self._context.request_repaint()
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

        was_dragging_node = self._interaction.is_dragging_node
        if self._interaction.handle_mouse_release(event):
            if was_dragging_node:
                self._recalculate_elevations_after_drag()
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
                self._context.request_repaint()
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
