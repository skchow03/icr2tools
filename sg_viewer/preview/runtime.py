from __future__ import annotations

import logging
import math
from dataclasses import replace
from pathlib import Path
from typing import Callable, List, Tuple

import numpy as np
from PyQt5 import QtCore, QtGui

from icr2_core.trk.sg_classes import SGFile
from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import get_cline_pos
from icr2_core.sg_elevation import sample_sg_elevation
from track_viewer.geometry import project_point_to_centerline
from sg_viewer.models import preview_state, selection
from sg_viewer.preview.geometry import (
    CURVE_SOLVE_TOLERANCE as CURVE_SOLVE_TOLERANCE_DEFAULT,
)
from sg_viewer.preview.context import PreviewContext
from sg_viewer.preview.selection import build_node_positions, find_unconnected_node_hit
from sg_viewer.preview.transform import pan_transform_state, zoom_transform_state
from sg_viewer.services.preview_background import PreviewBackground
from sg_viewer.ui.elevation_profile import ElevationProfileData, ElevationSource
from sg_viewer.geometry.centerline_utils import (
    compute_centerline_normal_and_tangent,
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
from sg_viewer.models.sg_model import SectionPreview
from sg_viewer.geometry.dlong import set_start_finish
from sg_viewer.geometry.topology import is_closed_loop, loop_length
from sg_viewer.preview.interaction_state import InteractionState
from sg_viewer.preview.preview_mutations import project_point_to_polyline
from sg_viewer.preview.edit_session import apply_preview_to_sgfile


logger = logging.getLogger(__name__)

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]


class PreviewRuntime:
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
    ) -> None:
        self._context = context
        self._emit_selected_section_changed = emit_selected_section_changed
        self._emit_sections_changed = emit_sections_changed
        self._emit_new_straight_mode_changed = emit_new_straight_mode_changed
        self._emit_new_curve_mode_changed = emit_new_curve_mode_changed
        self._emit_delete_mode_changed = emit_delete_mode_changed
        self._emit_split_section_mode_changed = emit_split_section_mode_changed
        self._emit_scale_changed = emit_scale_changed
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
        self._section_manager = PreviewSectionManager(
            self._viewport.combine_bounds_with_background
        )

        self._cline: List[Point] | None = None
        self._start_finish_dlong: float | None = None
        self._start_finish_mapping: tuple[Point, Point, Point] | None = None

        self._selection = selection.SelectionManager()
        self._selection.selectionChanged.connect(self._on_selection_changed)

        self._creation_controller = CreationController()
        self._interaction_state = InteractionState()

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
        )


        self._set_default_view_bounds()

        assert hasattr(self, "_editor")


    def current_transform(self, widget_size: tuple[int, int]) -> Transform | None:
        return self._controller.current_transform(widget_size)

    def map_to_track(
        self,
        screen_pos: tuple[float, float] | Point,
        widget_size: tuple[int, int],
        widget_height: int,
        transform: Transform | None = None,
    ) -> Point | None:
        point = (
            QtCore.QPointF(*screen_pos)
            if isinstance(screen_pos, tuple)
            else QtCore.QPointF(screen_pos)
        )
        return self._controller.map_to_track(point, widget_size, widget_height, transform)

    def set_status(self, text: str) -> None:
        self._status_message = text
        self._context.request_repaint()

    def set_status_text(self, text: str) -> None:
        self.set_status(text)

    def request_repaint(self) -> None:
        self._context.request_repaint()

    def log_debug(self, message: str, *args: object) -> None:
        logger.debug(message, *args)

    def _widget_size(self) -> tuple[int, int]:
        return self._context.widget_size()

    def _widget_height(self) -> int:
        return self._context.widget_height()

    def widget_size(self) -> tuple[int, int]:
        return self._widget_size()

    @property
    def controller(self) -> PreviewStateController:
        return self._controller

    @property
    def transform_state(self) -> preview_state.TransformState:
        return self._transform_state

    @property
    def delete_section_active(self) -> bool:
        return self._delete_section_active

    @property
    def creation_active(self) -> bool:
        return self._creation_active()

    def set_user_transform_active(self) -> None:
        self._transform_state = replace(self._transform_state, user_transform_active=True)

    def pan_view(self, delta: tuple[float, float], scale: float, center: tuple[float, float]) -> None:
        self._transform_state = pan_transform_state(
            self._transform_state,
            delta,
            scale,
            center,
        )

    def _stop_panning(self) -> None:
        self._interaction_state.stop_panning()

    @staticmethod
    def _create_empty_sgfile() -> SGFile:
        header = np.array(
            [int.from_bytes(b"\x00\x00GS", "little"), 1, 1, 0, 0, 0],
            dtype=np.int32,
        )
        xsect_dlats = np.array([-300_000, 300_000], dtype=np.int32)
        num_xsects = len(xsect_dlats)
        header[5] = num_xsects
        return SGFile(header, 0, num_xsects, xsect_dlats, [])

    # ------------------------------------------------------------------
    # State delegation
    # ------------------------------------------------------------------
    @property
    def _sgfile(self) -> SGFile | None:
        return self._controller.sgfile

    @_sgfile.setter
    def _sgfile(self, value: SGFile | None) -> None:
        self._controller.sgfile = value

    @property
    def sgfile(self) -> SGFile | None:
        return self._controller.sgfile

    @property
    def document(self) -> SGDocument:
        return self._document

    @property
    def has_unsaved_changes(self) -> bool:
        return self._has_unsaved_changes

    @property
    def _trk(self) -> TRKFile | None:
        return self._controller.trk

    @_trk.setter
    def _trk(self, value: TRKFile | None) -> None:
        self._controller.trk = value

    @property
    def _sampled_centerline(self) -> list[Point]:
        return self._controller.sampled_centerline

    @_sampled_centerline.setter
    def _sampled_centerline(self, value: list[Point]) -> None:
        self._controller.sampled_centerline = value

    @property
    def _sampled_bounds(self) -> tuple[float, float, float, float] | None:
        return self._controller.sampled_bounds

    @_sampled_bounds.setter
    def _sampled_bounds(self, value: tuple[float, float, float, float] | None) -> None:
        self._controller.sampled_bounds = value

    @property
    def _track_length(self) -> float | None:
        return self._controller.track_length

    @_track_length.setter
    def _track_length(self, value: float | None) -> None:
        self._controller.track_length = value

    @property
    def _status_message(self) -> str:
        return self._controller.status_message

    @_status_message.setter
    def _status_message(self, value: str) -> None:
        self._controller.status_message = value

    @property
    def _transform_state(self) -> preview_state.TransformState:
        return self._controller.transform_state

    @_transform_state.setter
    def _transform_state(self, value: preview_state.TransformState) -> None:
        previous = self._controller.transform_state
        self._controller.transform_state = value
        if (
            value.current_scale is not None
            and value.current_scale != previous.current_scale
        ):
            if self._emit_scale_changed is not None:
                self._emit_scale_changed(value.current_scale)

    def _set_transform_state(self, value: preview_state.TransformState) -> None:
        self._transform_state = value

    @property
    def _delete_section_active(self) -> bool:
        return self._editor.delete_section_active
    
    @property
    def has_unsaved_changes(self) -> bool:
        return self._has_unsaved_changes

    def _update_fit_scale(self) -> None:
        self._viewport.update_fit_scale(
            self._section_manager.sampled_bounds, self._widget_size()
        )


    def clear(self, message: str | None = None) -> None:
        self._controller.clear(message)
        self._suppress_document_dirty = True
        self._document.set_sg_data(None)
        self._suppress_document_dirty = False
        self._cline = None
        self._section_manager.reset()
        self._sampled_centerline = []
        self._sampled_bounds = None
        self._start_finish_dlong = None
        self._start_finish_mapping = None
        self._disconnected_nodes.clear()
        self._apply_creation_update(self._creation_controller.reset())
        self.cancel_split_section()
        self._editor.reset()
        self._interaction.reset()
        self._interaction_state.reset()
        self._status_message = message or "Select an SG file to begin."
        self._selection.reset([], None, None, [])
        self._set_default_view_bounds()
        self._update_node_status()
        self._has_unsaved_changes = False
        self._update_fit_scale()
        self._context.request_repaint()

    def _set_default_view_bounds(self) -> None:
        default_bounds = self._viewport.default_bounds()
        self._section_manager.sampled_bounds = default_bounds
        self._sampled_bounds = default_bounds

    def _on_section_changed(self, section_id: int) -> None:
        _ = section_id
        self._refresh_from_document(mark_unsaved=not self._suppress_document_dirty)

    def _on_geometry_changed(self) -> None:
        self._refresh_from_document(mark_unsaved=not self._suppress_document_dirty)

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------
    def load_sg_file(self, path: Path) -> None:
        self.cancel_split_section()
        data = self._controller.load_sg_file(path)
        if data is None:
            self.clear()
            return

        self._cline = data.cline
        self._disconnected_nodes = set()
        self._apply_creation_update(self._creation_controller.reset())
        self._status_message = data.status_message
        self._selection.reset(
            [],
            None,
            None,
            [],
        )
        self._start_finish_dlong = None
        self._suppress_document_dirty = True
        self._document.set_sg_data(data.sgfile)
        self._suppress_document_dirty = False
        self._update_fit_scale()
        self._has_unsaved_changes = False
        self._context.request_repaint()

    def enable_trk_overlay(self) -> TRKFile | None:
        trk = self._controller.enable_trk_overlay()
        if trk is None:
            return None
        self._trk = trk
        self._cline = get_cline_pos(trk)
        return trk

    def start_new_track(self) -> None:
        self.clear("New track ready. Click New Straight to start drawing.")
        self._sgfile = self._create_empty_sgfile()
        self._suppress_document_dirty = True
        self._document.set_sg_data(self._sgfile)
        self._suppress_document_dirty = False
        self._set_default_view_bounds()
        self._sampled_centerline = []
        self._track_length = 0.0
        self._start_finish_dlong = None
        self._has_unsaved_changes = False
        self._update_fit_scale()
        self._context.request_repaint()

    def refresh_geometry(self) -> None:
        self._refresh_from_document(mark_unsaved=True)

    def _refresh_from_document(self, *, mark_unsaved: bool) -> None:
        self._derived_geometry.rebuild_if_needed()

        sections = self._derived_geometry.sections
        sampled_bounds = self._derived_geometry.sampled_bounds or self._viewport.default_bounds()

        self._section_manager.load_sections(
            sections=sections,
            section_endpoints=self._derived_geometry.section_endpoints,
            sampled_centerline=self._derived_geometry.sampled_centerline,
            sampled_dlongs=self._derived_geometry.sampled_dlongs,
            sampled_bounds=sampled_bounds,
            centerline_index=self._derived_geometry.centerline_index,
        )
        self._sampled_bounds = self._section_manager.sampled_bounds
        self._sampled_centerline = self._section_manager.sampled_centerline
        self._track_length = self._derived_geometry.track_length
        self._start_finish_mapping = self._derived_geometry.start_finish_mapping
        if self._track_length <= 0:
            self._start_finish_dlong = None
        elif self._start_finish_dlong is None:
            self._start_finish_dlong = 0.0

        self._update_node_status()
        self._selection.update_context(
            self._section_manager.sections,
            self._track_length,
            self._section_manager.centerline_index,
            self._section_manager.sampled_dlongs,
        )
        if mark_unsaved:
            self._has_unsaved_changes = True
            if self._emit_sections_changed is not None:
                self._emit_sections_changed()
        self._context.request_repaint()

    def load_background_image(self, path: Path) -> None:
        self._background.load_image(path)
        self._fit_view_to_background()
        self._context.request_repaint()

    def clear_background_image(self) -> None:
        self._background.clear()
        self._context.request_repaint()

    # ------------------------------------------------------------------
    # New straight creation
    # ------------------------------------------------------------------
    def begin_new_straight(self) -> bool:
        self.cancel_split_section()
        update = self._creation_controller.begin_new_straight(
            bool(self._sampled_bounds)
        )
        self._apply_creation_update(update)
        return update.handled

    def begin_new_curve(self) -> bool:
        self.cancel_split_section()
        update = self._creation_controller.begin_new_curve(bool(self._sampled_bounds))
        self._apply_creation_update(update)
        return update.handled

    def _finalize_new_straight(self) -> None:
        updated_sections, track_length, new_index, status = self._editor.finalize_new_straight(
            self._section_manager.sections, self._track_length
        )
        if new_index is None:
            return

        self._track_length = track_length
        self.set_sections(updated_sections)
        self._selection.set_selected_section(new_index)
        self._apply_creation_update(self._creation_controller.finish_straight(status))

    def _finalize_new_curve(self) -> None:
        updated_sections, track_length, new_index, status = self._editor.finalize_new_curve(
            self._section_manager.sections, self._track_length
        )
        if new_index is None:
            return

        self._track_length = track_length
        self.set_sections(updated_sections)
        self._selection.set_selected_section(new_index)
        self._apply_creation_update(self._creation_controller.finish_curve(status))

    def _next_section_start_dlong(self) -> float:
        return self._editor.next_section_start_dlong(self._section_manager.sections)

    # ------------------------------------------------------------------
    # Delete section
    # ------------------------------------------------------------------
    def begin_delete_section(self) -> bool:
        if not self._section_manager.sections:
            return False

        self._set_delete_section_active(True)
        self._status_message = "Click a section to delete it."
        self._context.request_repaint()
        return True

    def cancel_delete_section(self) -> None:
        self._set_delete_section_active(False)

    def _set_delete_section_active(self, active: bool) -> None:
        if active:
            changed = self._editor.begin_delete_section(self._section_manager.sections)
        else:
            changed = self._editor.cancel_delete_section()

        if not changed:
            return

        if active:
            self.cancel_split_section()
            self._apply_creation_update(
                self._creation_controller.deactivate_creation()
            )
        if self._emit_delete_mode_changed is not None:
            self._emit_delete_mode_changed(active)

    # ------------------------------------------------------------------
    # Split section
    # ------------------------------------------------------------------
    def begin_split_section(self) -> bool:
        if not self._section_manager.sections:
            return False

        if self._split_section_mode:
            return True

        self._split_previous_status_message = self._status_message
        self._clear_split_hover()
        self._split_section_mode = True
        self._apply_creation_update(self._creation_controller.deactivate_creation())
        self.set_status_text("Hover over a straight or curve section to choose split point.")
        if self._emit_split_section_mode_changed is not None:
            self._emit_split_section_mode_changed(True)
        self.request_repaint()
        return True

    def cancel_split_section(self) -> None:
        if not self._split_section_mode and self._split_hover_point is None:
            return

        self._exit_split_section_mode()

    def _update_split_hover(self, screen_pos: QtCore.QPoint) -> None:
        widget_size = self._widget_size()
        transform = self.current_transform(widget_size)
        if transform is None:
            self._clear_split_hover()
            return

        track_point = self.map_to_track(
            screen_pos, widget_size, self._widget_height(), transform
        )
        if track_point is None:
            self._clear_split_hover()
            return

        section_index = self._selection.find_section_at_point(
            screen_pos,
            lambda p: self.map_to_track(p, widget_size, self._widget_height(), transform),
            transform,
        )
        if section_index is None:
            self._clear_split_hover()
            return

        section = self._section_manager.sections[section_index]
        if section.type_name not in {"straight", "curve"}:
            self._clear_split_hover()
            return

        if section.type_name == "straight":
            projected = project_point_to_segment(track_point, section.start, section.end)
        else:
            projected = project_point_to_polyline(track_point, section.polyline)
        if projected is None:
            self._clear_split_hover()
            return

        self._split_hover_point = projected
        self._split_hover_section_index = section_index
        self.request_repaint()

    def _clear_split_hover(self) -> None:
        if self._split_hover_point is not None or self._split_hover_section_index is not None:
            self._split_hover_point = None
            self._split_hover_section_index = None
            self.request_repaint()

    def _commit_split(self) -> None:
        idx = self._split_hover_section_index
        point = self._split_hover_point

        if idx is None or point is None:
            return

        section = self._section_manager.sections[idx]
        if section.type_name == "curve":
            result = self._editor.split_curve_section(
                list(self._section_manager.sections), idx, point
            )
        else:
            result = self._editor.split_straight_section(
                list(self._section_manager.sections), idx, point
            )
        if result is None:
            return

        sections, track_length = result
        self._track_length = track_length
        self.set_sections(sections)
        if idx + 1 < len(sections):
            self._selection.set_selected_section(idx + 1)
        self._exit_split_section_mode("Split complete.")

    def _exit_split_section_mode(self, status_message: str | None = None) -> None:
        self._split_section_mode = False
        self._clear_split_hover()
        if status_message is not None:
            self._status_message = status_message
        elif self._split_previous_status_message is not None:
            self._status_message = self._split_previous_status_message
        self._split_previous_status_message = None
        if self._emit_split_section_mode_changed is not None:
            self._emit_split_section_mode_changed(False)
        self._show_status(self._status_message)
        self.request_repaint()

    def set_background_settings(
        self, scale_500ths_per_px: float, origin: Point
    ) -> None:
        self._background.scale_500ths_per_px = scale_500ths_per_px
        self._background.world_xy_at_image_uv_00 = origin
        self._fit_view_to_background()
        self._context.request_repaint()

    def get_background_settings(self) -> tuple[float, Point]:
        return self._background.scale_500ths_per_px, self._background.world_xy_at_image_uv_00

    def _background_bounds(self) -> tuple[float, float, float, float] | None:
        return self._background.bounds()

    def _combine_bounds_with_background(
        self, bounds: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        return self._viewport.combine_bounds_with_background(bounds)

    def _fit_view_to_background(self) -> None:
        active_bounds = self._viewport.fit_view_to_background(
            self._section_manager.sampled_bounds, self._widget_size()
        )
        if active_bounds is None:
            return

        self._section_manager.sampled_bounds = active_bounds
        self._sampled_bounds = active_bounds

    def get_background_image_path(self) -> Path | None:
        return self._background.image_path

    def has_background_image(self) -> bool:
        return self._background.image is not None

    def _update_node_status(self) -> None:
        """Update cached node colors directly from section connectivity."""
        update_node_status(self._section_manager.sections, self._node_status)

    def build_node_positions(self) -> dict[tuple[int, str], Point]:
        return build_node_positions(self._section_manager.sections)

    @property
    def background(self) -> PreviewBackground:
        return self._background

    @property
    def section_manager(self) -> PreviewSectionManager:
        return self._section_manager

    @property
    def selection_manager(self) -> selection.SelectionManager:
        return self._selection

    @property
    def interaction(self) -> PreviewInteraction:
        return self._interaction

    @property
    def creation_controller(self) -> CreationController:
        return self._creation_controller

    @property
    def node_status(self) -> dict[tuple[int, str], str]:
        return self._node_status

    @property
    def node_radius_px(self) -> int:
        return self._node_radius_px

    @property
    def hovered_endpoint(self) -> tuple[int, str] | None:
        return self._interaction_state.hovered_endpoint

    @property
    def show_curve_markers(self) -> bool:
        return self._show_curve_markers

    @property
    def show_axes(self) -> bool:
        return self._show_axes

    @property
    def start_finish_mapping(self) -> tuple[Point, Point, Point] | None:
        return self._start_finish_mapping

    @property
    def status_message(self) -> str:
        return self._status_message

    @property
    def split_section_mode(self) -> bool:
        return self._split_section_mode

    @property
    def split_hover_point(self) -> Point | None:
        return self._split_hover_point
    def _can_drag_section_node(self, section: SectionPreview) -> bool:
        return self._editor.can_drag_section_node(
            self._section_manager.sections, section
        )

    def _can_drag_section_polyline(self, section: SectionPreview, index: int | None = None) -> bool:
        return self._editor.can_drag_section_polyline(
            self._section_manager.sections, section, index
        )

    def _connected_neighbor_index(self, index: int, direction: str) -> int | None:
        return self._editor.connected_neighbor_index(
            self._section_manager.sections, index, direction
        )

    def _get_drag_chain(self, index: int | None) -> list[int] | None:
        return self._editor.get_drag_chain(self._section_manager.sections, index)

    def _can_drag_node(self, section: SectionPreview, endtype: str) -> bool:
        return self._editor.can_drag_node(
            self._section_manager.sections, section, endtype
        )

    def _creation_context(self) -> CreationEventContext | None:
        widget_size = self._widget_size()
        transform = self._controller.current_transform(widget_size)
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

    def _lock_user_transform(self) -> None:
        """Prevent auto-fit from overriding the current zoom/pan during creation."""
        state = self._transform_state
        if state.user_transform_active:
            return

        if state.current_scale is None or state.view_center is None:
            self._update_fit_scale()
            state = self._transform_state

        self._transform_state = replace(
            state,
            user_transform_active=True,
            current_scale=state.current_scale or state.fit_scale,
        )

    def _apply_creation_update(self, update: CreationUpdate) -> None:
        if update is None:
            return
        if update.stop_panning:
            self._stop_panning()
        if update.status_changed:
            self._status_message = self._creation_controller.status_text
        if update.straight_mode_changed:
            if self._creation_controller.straight_active:
                self._set_delete_section_active(False)
                self.cancel_split_section()
                self._lock_user_transform()
            if self._emit_new_straight_mode_changed is not None:
                self._emit_new_straight_mode_changed(
                    self._creation_controller.straight_active
                )
        if update.curve_mode_changed:
            if self._creation_controller.curve_active:
                self._set_delete_section_active(False)
                self.cancel_split_section()
                self._lock_user_transform()
            if self._emit_new_curve_mode_changed is not None:
                self._emit_new_curve_mode_changed(
                    self._creation_controller.curve_active
                )
        if update.finalize_straight:
            self._finalize_new_straight()
        if update.finalize_curve:
            self._finalize_new_curve()
        if update.repaint:
            self._context.request_repaint()

    def _creation_active(self) -> bool:
        return self._creation_controller.straight_active or self._creation_controller.curve_active

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

    def update_split_hover(self, pos: QtCore.QPoint) -> None:
        self._update_split_hover(pos)

    def commit_split(self) -> None:
        self._commit_split()

    def handle_delete_click(self, pos: QtCore.QPoint) -> bool:
        return self._handle_delete_click(pos)

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
        transform = self._controller.current_transform(widget_size)
        state = self._transform_state
        new_state = zoom_transform_state(
            state,
            event.angleDelta().y(),
            (event.pos().x(), event.pos().y()),
            widget_size,
            self._widget_height(),
            transform,
            self._controller.clamp_scale,
            self._controller.default_center,
            lambda p: self._controller.map_to_track(
                QtCore.QPointF(*p), widget_size, self._widget_height(), transform
            ),
        )
        if new_state is None:
            return
        self._transform_state = new_state
        self._context.request_repaint()
        event.accept()

    def on_mouse_press(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        self._interaction_state.on_mouse_press(event, self)

    def on_mouse_move(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        self._interaction_state.on_mouse_move(event, self)

    def on_mouse_release(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        self._interaction_state.on_mouse_release(event, self)
    def on_leave(self, event: QtCore.QEvent) -> None:  # noqa: D401
        _ = event
        self._clear_split_hover()

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _handle_click(self, pos: QtCore.QPoint) -> None:
        if self._delete_section_active and self._handle_delete_click(pos):
            return

        widget_size = self._widget_size()
        transform = self._controller.current_transform(widget_size)
        logger.debug(
            "Handling click at screen %s with widget size %s and transform %s",
            pos,
            widget_size,
            transform,
        )
        self._selection.handle_click(
            pos,
            lambda p: self._controller.map_to_track(p, widget_size, self._widget_height(), transform),
            transform,
        )

    def _on_selection_changed(self, selection_value: object) -> None:
        if self._emit_selected_section_changed is not None:
            self._emit_selected_section_changed(selection_value)
        self._context.request_repaint()

    def _handle_delete_click(self, pos: QtCore.QPoint) -> bool:
        widget_size = self._widget_size()
        transform = self._controller.current_transform(widget_size)
        if transform is None:
            return False

        selection_index = self._selection.find_section_at_point(
            pos,
            lambda p: self._controller.map_to_track(p, widget_size, self._widget_height(), transform),
            transform,
        )
        if selection_index is None:
            self._status_message = "Click a section to delete it."
            self._context.request_repaint()
            return False

        self._delete_section(selection_index)
        return True

    def _delete_section(self, index: int) -> None:
        new_sections, track_length, status = self._editor.delete_section(
            list(self._section_manager.sections), index
        )
        if not status:
            return

        self._track_length = track_length
        self.set_sections(new_sections)
        self._selection.set_selected_section(None)
        self._status_message = status
        self._set_delete_section_active(False)

    def get_section_set(self) -> tuple[list[SectionPreview], float | None]:
        track_length = float(self._track_length) if self._track_length is not None else None
        return list(self._section_manager.sections), track_length

    def track_length_message(self) -> str:
        sections = self._section_manager.sections
        if not sections or not is_closed_loop(sections):
            return "Complete the loop to show track length"

        try:
            total_length = loop_length(sections)
        except ValueError:
            return "Complete the loop to show track length"

        miles = total_length / (500.0 * 12 * 5280)
        return f"Track length: {total_length:.0f} DLONG (500ths) — {miles:.3f} miles"

    def scale_track_to_length(self, target_length: float) -> str | None:
        """Scale the current closed loop to ``target_length`` DLONG (500ths)."""

        sections = self._section_manager.sections
        if not sections or not is_closed_loop(sections):
            return None

        try:
            current_length = loop_length(sections)
        except ValueError:
            return None

        if current_length <= 0:
            return None

        factor = target_length / current_length
        if math.isclose(factor, 1.0, rel_tol=1e-9):
            return "Track already at desired length."

        scaled_sections = [scale_section(sect, factor) for sect in sections]
        scaled_start_finish = self._start_finish_dlong
        if scaled_start_finish is not None:
            scaled_start_finish *= factor

        self.set_sections(scaled_sections, start_finish_dlong=scaled_start_finish)

        return f"Scaled track by {factor:.3f}× to {target_length:.0f} DLONG."

    def _current_start_finish_dlong(self) -> float | None:
        if self._track_length is None or self._track_length <= 0:
            return None

        if self._start_finish_dlong is not None:
            return float(self._start_finish_dlong) % float(self._track_length)

        if (
            self._start_finish_mapping is None
            or self._section_manager.centerline_index is None
            or not self._section_manager.sampled_dlongs
        ):
            return None

        track_length = self._track_length
        if track_length is None and self._section_manager.sampled_dlongs:
            track_length = self._section_manager.sampled_dlongs[-1]

        if track_length is None or track_length <= 0:
            return None

        (cx, cy), _, _ = self._start_finish_mapping
        _, nearest_dlong, _ = project_point_to_centerline(
            (cx, cy),
            self._section_manager.centerline_index,
            self._section_manager.sampled_dlongs,
            track_length,
        )
        return nearest_dlong

    def set_sections(self, sections: list[SectionPreview], start_finish_dlong: float | None = None) -> None:
        self._clear_split_hover()

        preserved_start_finish_dlong = start_finish_dlong
        if preserved_start_finish_dlong is None:
            preserved_start_finish_dlong = self._start_finish_dlong
        if preserved_start_finish_dlong is None:
            preserved_start_finish_dlong = self._current_start_finish_dlong()

        needs_rebuild = self._section_manager.set_sections(sections)

        self._sampled_bounds = self._section_manager.sampled_bounds
        self._sampled_centerline = self._section_manager.sampled_centerline
        if self._section_manager.sampled_dlongs:
            self._track_length = self._section_manager.sampled_dlongs[-1]
        self._update_start_finish_mapping(preserved_start_finish_dlong)

        if needs_rebuild:
            self._update_fit_scale()

        self._update_node_status()


        self._selection.update_context(
            self._section_manager.sections,
            self._track_length,
            self._section_manager.centerline_index,
            self._section_manager.sampled_dlongs,
        )
        if preserved_start_finish_dlong is not None and self._track_length:
            self._start_finish_dlong = float(preserved_start_finish_dlong) % float(self._track_length)
        self._has_unsaved_changes = True
        if self._emit_sections_changed is not None:
            self._emit_sections_changed()
        self._context.request_repaint()

    def rebuild_after_start_finish(self, sections: list[SectionPreview]) -> None:
        (
            cline,
            sampled_dlongs,
            sampled_bounds,
            centerline_index,
        ) = rebuild_centerline_from_sections(sections)

        track_length = sampled_dlongs[-1] if sampled_dlongs else 0.0

        self._section_manager.load_sections(
            sections=sections,
            section_endpoints=[(sect.start, sect.end) for sect in sections],
            sampled_centerline=cline,
            sampled_dlongs=sampled_dlongs,
            sampled_bounds=sampled_bounds or (0.0, 0.0, 0.0, 0.0),
            centerline_index=centerline_index,
        )
        self._sampled_bounds = self._section_manager.sampled_bounds
        self._sampled_centerline = self._section_manager.sampled_centerline
        self._track_length = track_length
        self._start_finish_mapping = None
        self._start_finish_dlong = 0.0 if track_length > 0 else None

        previous_block_state = self._selection.blockSignals(True)
        try:
            self._selection.reset(
                self._section_manager.sections,
                self._track_length,
                self._section_manager.centerline_index,
                self._section_manager.sampled_dlongs,
            )
            self._update_node_status()
            self._update_start_finish_mapping(0.0 if track_length > 0 else None)
        finally:
            self._selection.blockSignals(previous_block_state)

        self._has_unsaved_changes = True
        if self._emit_sections_changed is not None:
            self._emit_sections_changed()
        self._selection.set_selected_section(
            0 if self._section_manager.sections else None
        )


    def _compute_start_finish_mapping_from_samples(
        self, start_dlong: float | None
    ) -> tuple[Point, Point, Point] | None:
        if (
            start_dlong is None
            or self._track_length is None
            or self._track_length <= 0
        ):
            return None

        points = self._section_manager.sampled_centerline
        dlongs = self._section_manager.sampled_dlongs
        if len(points) < 2 or len(points) != len(dlongs):
            return None

        target = float(start_dlong) % float(self._track_length)

        for idx in range(len(dlongs) - 1):
            seg_start = points[idx]
            seg_end = points[idx + 1]
            seg_span = dlongs[idx + 1] - dlongs[idx]
            if seg_span <= 0:
                continue
            if not (dlongs[idx] <= target <= dlongs[idx + 1]):
                continue

            fraction = (target - dlongs[idx]) / seg_span
            cx = seg_start[0] + (seg_end[0] - seg_start[0]) * fraction
            cy = seg_start[1] + (seg_end[1] - seg_start[1]) * fraction

            dx = seg_end[0] - seg_start[0]
            dy = seg_end[1] - seg_start[1]
            length = math.hypot(dx, dy)
            if length == 0:
                return None

            tangent = (dx / length, dy / length)
            normal = (-tangent[1], tangent[0])
            return (cx, cy), normal, tangent

        start = points[0]
        end = points[1]
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        length = math.hypot(dx, dy)
        if length == 0:
            return None

        tangent = (dx / length, dy / length)
        normal = (-tangent[1], tangent[0])
        return start, normal, tangent

    def _update_start_finish_mapping(self, start_dlong: float | None) -> None:
        mapping = self._compute_start_finish_mapping_from_samples(start_dlong)

        if mapping is None and start_dlong is not None:
            if (
                self._trk is not None
                and self._cline is not None
                and self._track_length
                and self._track_length > 0
            ):
                mapping = compute_centerline_normal_and_tangent(
                    self._trk, self._cline, self._track_length, start_dlong
                )

        if mapping is None:
            mapping = compute_start_finish_mapping_from_centerline(
                self._section_manager.sampled_centerline
            )

        self._start_finish_mapping = mapping
        if start_dlong is not None and self._track_length:
            self._start_finish_dlong = float(start_dlong) % float(self._track_length)

    def apply_preview_to_sgfile(self) -> SGFile:
        if self._sgfile is None:
            raise ValueError("No SG file loaded.")
        return apply_preview_to_sgfile(self._sgfile, self._section_manager.sections)

    def recalculate_dlongs(self) -> bool:
        try:
            sgfile = self.apply_preview_to_sgfile()
        except ValueError:
            return False

        if self._document.sg_data is None:
            self._document.set_sg_data(sgfile)

        self._document.rebuild_dlongs(0, 0)
        return True

    def save_sg(self, path: Path) -> None:
        """Write the current SG (and any edits) to ``path``."""

        sgfile = self.apply_preview_to_sgfile()

        sgfile.output_sg(str(path))
        self._has_unsaved_changes = False

    def get_section_headings(self) -> list[selection.SectionHeadingData]:
        return self._selection.get_section_headings()

    def get_xsect_metadata(self) -> list[tuple[int, float]]:
        if self._sgfile is None:
            return []
        return [(idx, float(dlat)) for idx, dlat in enumerate(self._sgfile.xsect_dlats)]

    def get_section_range(self, index: int) -> tuple[float, float] | None:
        if (
            not self._section_manager.sections
            or index < 0
            or index >= len(self._section_manager.sections)
        ):
            return None
        start = float(self._section_manager.sections[index].start_dlong)
        end = start + float(self._section_manager.sections[index].length)
        return start, end

    def build_elevation_profile(
        self,
        xsect_index: int,
        samples_per_section: int = 24,
        show_trk: bool = False,
    ) -> ElevationProfileData | None:
        _ = show_trk
        if (
            self._sgfile is None
            or self._track_length is None
            or xsect_index < 0
            or xsect_index >= self._sgfile.num_xsects
        ):
            return None

        def _xsect_label(dlat_value: float) -> str:
            return f"X-Section {xsect_index} (DLAT {dlat_value:.0f})"

        if xsect_index >= len(self._sgfile.xsect_dlats):
            return None

        dlat_value = float(self._sgfile.xsect_dlats[xsect_index])

        if self._track_length <= 0:
            track_length = float(self._track_length or 0.0)
            track_length = track_length if track_length > 0 else 1.0
            return ElevationProfileData(
                dlongs=[0.0, track_length],
                sg_altitudes=[0.0, 0.0],
                trk_altitudes=None,
                section_ranges=[],
                track_length=track_length,
                xsect_label=_xsect_label(dlat_value),
                sources=(ElevationSource.SG,),
            )

        dlongs: list[float] = []
        section_ranges: list[tuple[float, float]] = []
        sg_altitudes = sample_sg_elevation(
            self._sgfile,
            xsect_index,
            resolution=samples_per_section,
        )
        trk_altitudes: list[float] | None = None
        sources = (ElevationSource.SG,)

        for sg_sect in self._sgfile.sects:
            sg_length = float(sg_sect.length)
            if sg_length <= 0:
                continue
            start_dlong = float(sg_sect.start_dlong)
            section_ranges.append((start_dlong, start_dlong + sg_length))

            for step in range(samples_per_section + 1):
                fraction = step / samples_per_section
                dlong = start_dlong + fraction * sg_length
                dlongs.append(dlong)

        return ElevationProfileData(
            dlongs=dlongs,
            sg_altitudes=sg_altitudes,
            trk_altitudes=trk_altitudes,
            section_ranges=section_ranges,
            track_length=float(self._track_length),
            xsect_label=_xsect_label(dlat_value),
            sources=sources,
        )

    # ------------------------------------------------------------------
    # Public controls
    # ------------------------------------------------------------------
    def set_trk_comparison(self, trk: TRKFile | None) -> None:
        self._trk = trk

    def set_show_curve_markers(self, visible: bool) -> None:
        self._show_curve_markers = visible
        self._context.request_repaint()

    def set_show_axes(self, visible: bool) -> None:
        self._show_axes = visible
        self._context.request_repaint()

    def activate_set_start_finish_mode(self) -> None:
        """Backward-compatible alias for setting start/finish."""
        self.set_start_finish_at_selected_section()

    def set_start_finish_at_selected_section(self) -> None:
        if not self._section_manager.sections:
            return

        selected_index = self._selection.selected_section_index
        if selected_index is None:
            self._show_status("Select a section to set start/finish")
            return

        if not is_closed_loop(self._section_manager.sections):
            self._show_status("Track must be closed to set start/finish")
            return

        try:
            new_sections = set_start_finish(
                self._section_manager.sections, selected_index
            )
        except ValueError:
            self._show_status("Track must be closed to set start/finish")
            return
        except RuntimeError:
            self._show_status("Invalid loop topology; cannot set start/finish")
            return

        self.rebuild_after_start_finish(new_sections)
        self._show_status("Start/finish set to selected section (now section 0)")

    def select_next_section(self) -> None:
        if not self._selection.sections:
            return

        if self._selection.selected_section_index is None:
            self._selection.set_selected_section(0)
            return

        next_index = (self._selection.selected_section_index + 1) % len(self._selection.sections)
        self._selection.set_selected_section(next_index)

    def select_previous_section(self) -> None:
        if not self._selection.sections:
            return

        if self._selection.selected_section_index is None:
            self._selection.set_selected_section(len(self._selection.sections) - 1)
            return

        prev_index = (self._selection.selected_section_index - 1) % len(self._selection.sections)
        self._selection.set_selected_section(prev_index)
