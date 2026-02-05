from __future__ import annotations

from dataclasses import replace
from typing import Callable

from icr2_core.trk.sg_classes import SGFile
from icr2_core.trk.trk_classes import TRKFile
from sg_viewer.geometry.derived_geometry import DerivedGeometry
from sg_viewer.geometry.canonicalize import canonicalize_closed_loop
from sg_viewer.geometry.connect_curve_to_straight import (
    solve_curve_end_to_straight_start,
    solve_straight_end_to_curve_endpoint,
)
from sg_viewer.geometry.sg_geometry import update_section_geometry
from sg_viewer.geometry.topology import is_closed_loop
from sg_viewer.model.sg_document import SGDocument
from sg_viewer.models import preview_state, selection
from sg_viewer.models.preview_fsection import PreviewFSection
from sg_viewer.models.preview_state_utils import is_disconnected_endpoint
from sg_viewer.models.sg_model import PreviewData
from sg_viewer.preview.context import PreviewContext
from sg_viewer.preview.creation_controller import CreationController
from sg_viewer.preview.interaction_state import InteractionState
from sg_viewer.preview.trk_overlay_controller import TrkOverlayController
from sg_viewer.preview.transform_controller import TransformController
from sg_viewer.services.preview_background import PreviewBackground
from sg_viewer.sg_preview.view_state import SgPreviewViewState
from sg_viewer.ui.preview_editor import PreviewEditor
from sg_viewer.ui.preview_interaction import PreviewInteraction
from sg_viewer.ui.preview_section_manager import PreviewSectionManager
from sg_viewer.ui.preview_state_controller import PreviewStateController
from sg_viewer.ui.preview_viewport import PreviewViewport
from sg_viewer.ui.ux.commands import (
    ConnectSectionsCommand,
    DisconnectSectionEndCommand,
    DragNodeCommand,
    UXCommand,
)
from sg_viewer.preview.runtime_ops.base_context import Point, Transform


class _RuntimeCoreBaseMixin:
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
        self._document.elevation_changed.connect(self._on_elevation_changed)

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
        self._last_elevation_recalc_message: str | None = None

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

        self._node_status = {}  # (index, "start"|"end") -> "green" or "orange"
        self._disconnected_nodes: set[tuple[int, str]] = set()
        self._node_radius_px = 6
        self._has_unsaved_changes = False
        self._show_status = show_status or self.set_status_text
        self._sg_version = 0
        self._elevation_bounds_cache: dict[tuple[int, int], tuple[float, float] | None] = {}
        self._elevation_xsect_bounds_cache: dict[
            tuple[int, int], dict[int, tuple[float, float] | None]
        ] = {}
        self._elevation_xsect_bounds_dirty: dict[tuple[int, int], set[int]] = {}
        self._elevation_profile_cache: dict[
            tuple[int, int], tuple[list[float], list[tuple[float, float]]]
        ] = {}

        self._interaction = PreviewInteraction(
            self._context,
            self._selection,
            self._section_manager,
            self._editor,
            self.set_sections,
            self.update_drag_preview,
            self.rebuild_after_start_finish,
            self._node_radius_px,
            self._stop_panning,
            show_status=self._show_status,
            emit_command=self._execute_ux_command,
            emit_drag_state_changed=self._emit_interaction_drag_changed,
            sync_fsects_on_connection=self._sync_fsects_on_connection,
            apply_preview_to_sgfile=self.sync_preview_to_sgfile_if_loaded,
            recalculate_elevations=self.recalculate_elevations,
        )

        self._set_default_view_bounds()

        assert hasattr(self, "_editor")

    @property
    def is_interaction_dragging(self) -> bool:
        return (
            self._interaction.is_dragging_node
            or self._interaction.is_dragging_section
        )

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

    def _stop_panning(self) -> None:
        self._interaction_state.stop_panning()
        self._transform_controller.end_pan()

    def _execute_ux_command(self, command: UXCommand) -> None:
        if isinstance(command, DisconnectSectionEndCommand):
            self._disconnect_section_end(command)
            return
        if isinstance(command, ConnectSectionsCommand):
            self._connect_sections(command)
            return
        if isinstance(command, DragNodeCommand):
            self._commit_dragged_node(command)

    def _commit_dragged_node(self, command: DragNodeCommand) -> None:
        sections = list(self._section_manager.sections)
        if not (0 <= command.section < len(sections)):
            return
        self.set_sections(sections, changed_indices=[command.section])

    def _disconnect_section_end(self, command: DisconnectSectionEndCommand) -> None:
        sections = self._section_manager.sections
        sect_index = command.section
        endtype = command.end
        if not (0 <= sect_index < len(sections)):
            return

        neighbor_index = (
            sections[sect_index].previous_id if endtype == "start" else sections[sect_index].next_id
        )
        updated_sections = self._editor.disconnect_neighboring_section(
            list(sections), sect_index, endtype
        )
        self.set_sections(updated_sections)

        affected_indices = [sect_index]
        if (
            neighbor_index is not None
            and 0 <= neighbor_index < len(sections)
            and neighbor_index != sect_index
        ):
            affected_indices.append(neighbor_index)
        self.recalculate_elevations(affected_indices)

    def _connect_sections(self, command: ConnectSectionsCommand) -> None:
        sections = list(self._section_manager.sections)
        if not sections:
            return

        src_index, src_end = command.from_section, command.from_end
        tgt_index, tgt_end = command.to_section, command.to_end
        if src_index == tgt_index:
            return
        if src_index < 0 or src_index >= len(sections) or tgt_index < 0 or tgt_index >= len(sections):
            return

        src_section = sections[src_index]
        tgt_section = sections[tgt_index]
        if not is_disconnected_endpoint(sections, src_section, src_end):
            return
        if not is_disconnected_endpoint(sections, tgt_section, tgt_end):
            return

        if (
            src_section.type_name == "curve"
            and src_end == "end"
            and tgt_section.type_name == "straight"
            and tgt_end == "start"
        ):
            result = solve_curve_end_to_straight_start(src_section, tgt_section)
            if result is None:
                return
            new_curve, new_straight = result
            self._sync_fsects_on_connection((src_index, src_end), (tgt_index, tgt_end))
            self._apply_curve_straight_connection(
                curve_idx=src_index,
                curve_end=src_end,
                straight_idx=tgt_index,
                straight_end=tgt_end,
                curve=new_curve,
                straight=new_straight,
            )
            return

        if src_section.type_name == "straight" and tgt_section.type_name == "curve":
            result = solve_straight_end_to_curve_endpoint(
                src_section,
                src_end,
                tgt_section,
                tgt_end,
            )
            if result is None:
                return
            new_straight, new_curve = result
            self._sync_fsects_on_connection((src_index, src_end), (tgt_index, tgt_end))
            self._apply_curve_straight_connection(
                curve_idx=tgt_index,
                curve_end=tgt_end,
                straight_idx=src_index,
                straight_end=src_end,
                curve=new_curve,
                straight=new_straight,
            )
            return

        if src_end == "start":
            src_section = replace(src_section, previous_id=tgt_index)
        else:
            src_section = replace(src_section, next_id=tgt_index)

        if tgt_end == "start":
            tgt_section = replace(tgt_section, previous_id=src_index)
        else:
            tgt_section = replace(tgt_section, next_id=src_index)

        sections[src_index] = update_section_geometry(src_section)
        sections[tgt_index] = update_section_geometry(tgt_section)

        self._sync_fsects_on_connection((src_index, src_end), (tgt_index, tgt_end))
        self._finalize_connection_updates(
            old_sections=list(self._section_manager.sections),
            updated_sections=sections,
            changed_indices=[src_index, tgt_index],
        )

    def _apply_curve_straight_connection(
        self,
        *,
        curve_idx: int,
        curve_end: str,
        straight_idx: int,
        straight_end: str,
        curve,
        straight,
    ) -> None:
        old_sections = list(self._section_manager.sections)
        sections = list(self._section_manager.sections)

        if curve_end == "start":
            curve = replace(curve, previous_id=straight_idx)
        else:
            curve = replace(curve, next_id=straight_idx)

        if straight_end == "start":
            straight = replace(straight, previous_id=curve_idx)
        else:
            straight = replace(straight, next_id=curve_idx)

        sections[curve_idx] = update_section_geometry(curve)
        sections[straight_idx] = update_section_geometry(straight)

        self._finalize_connection_updates(
            old_sections=old_sections,
            updated_sections=sections,
            changed_indices=[curve_idx, straight_idx],
        )

    def _finalize_connection_updates(
        self,
        *,
        old_sections: list,
        updated_sections: list,
        changed_indices: list[int],
    ) -> None:
        old_closed = is_closed_loop(old_sections)
        new_closed = is_closed_loop(updated_sections)
        sections = updated_sections

        if not old_closed and new_closed:
            sections = canonicalize_closed_loop(sections, start_idx=0)
            self.set_sections(sections, changed_indices=changed_indices)
            self.sync_preview_to_sgfile_if_loaded()
            self._show_status("Closed loop detected — track direction fixed")
        else:
            self.set_sections(sections, changed_indices=changed_indices)

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

    def _update_fit_scale(self) -> None:
        if self._drag_transform_active:
            return
        self._transform_controller.update_fit_scale(
            self._section_manager.sampled_bounds, self._widget_size()
        )
