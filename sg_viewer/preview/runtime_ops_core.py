from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Callable, Tuple

from PyQt5 import QtCore, QtGui

from icr2_core.trk.sg_classes import SGFile
from icr2_core.trk.trk_classes import TRKFile
from sg_viewer.model.sg_document import SGDocument
from sg_viewer.models import preview_state, selection
from sg_viewer.models.preview_state_utils import update_node_status
from sg_viewer.models.preview_fsection import PreviewFSection
from sg_viewer.models.sg_model import PreviewData, SectionPreview
from sg_viewer.preview.context import PreviewContext
from sg_viewer.preview.creation_controller import (
    CreationController,
    CreationEvent,
    CreationEventContext,
    CreationUpdate,
)
from sg_viewer.preview.interaction_state import (
    InteractionInputs,
    InteractionState,
    MouseIntent,
)
from sg_viewer.preview.preview_defaults import create_empty_sgfile
from sg_viewer.preview.selection import build_node_positions, find_unconnected_node_hit
from sg_viewer.preview.trk_overlay_controller import TrkOverlayController
from sg_viewer.preview.transform_controller import TransformController
from sg_viewer.services.preview_background import PreviewBackground
from sg_viewer.sg_preview.transform import ViewTransform
from sg_viewer.sg_preview.view_state import SgPreviewViewState
from sg_viewer.ui.preview_editor import PreviewEditor
from sg_viewer.ui.preview_interaction import PreviewInteraction
from sg_viewer.ui.preview_section_manager import PreviewSectionManager
from sg_viewer.ui.preview_state_controller import PreviewStateController
from sg_viewer.ui.preview_viewport import PreviewViewport
from sg_viewer.geometry.derived_geometry import DerivedGeometry
from sg_viewer.geometry.dlong import set_start_finish
from sg_viewer.geometry.topology import is_closed_loop, loop_length


logger = logging.getLogger(__name__)

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]


class _RuntimeCoreMixin:
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
        self._drag_active = False
        self._cached_preview_model = None

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

        self._interaction = PreviewInteraction(
            self._context,
            self._selection,
            self._section_manager,
            self._editor,
            self.set_sections,
            self.rebuild_after_start_finish,
            self._document,
            self._node_radius_px,
            self._stop_panning,
            show_status=self._show_status,
            sync_fsects_on_connection=self._sync_fsects_on_connection,
        )

        self._set_default_view_bounds()

        assert hasattr(self, "_editor")

    def _validate_section_fsects_alignment(self) -> None:
        if len(self._section_manager.sections) != len(self._fsects_by_section):
            raise RuntimeError(
                "Section/Fsect desync: "
                f"{len(self._section_manager.sections)} sections vs "
                f"{len(self._fsects_by_section)} fsect blocks"
            )

    def _fsect_edge_profile(
        self, source_index: int, endtype: str
    ) -> list[PreviewFSection]:
        if endtype not in {"start", "end"}:
            return []
        if not (0 <= source_index < len(self._fsects_by_section)):
            return []

        edge_profile: list[PreviewFSection] = []
        for fsect in self._fsects_by_section[source_index]:
            edge_value = fsect.end_dlat if endtype == "end" else fsect.start_dlat
            edge_profile.append(
                PreviewFSection(
                    start_dlat=edge_value,
                    end_dlat=edge_value,
                    surface_type=fsect.surface_type,
                    type2=fsect.type2,
                )
            )
        return edge_profile

    def _apply_fsect_edge_profile(
        self, index: int, endtype: str, edge_profile: list[PreviewFSection]
    ) -> None:
        if (
            not edge_profile
            or endtype not in {"start", "end"}
            or not (0 <= index < len(self._fsects_by_section))
        ):
            return

        current = self._fsects_by_section[index]
        if not current or len(current) != len(edge_profile):
            self._fsects_by_section[index] = copy.deepcopy(edge_profile)
            return

        updated: list[PreviewFSection] = []
        for existing, edge in zip(current, edge_profile):
            if endtype == "start":
                updated.append(
                    PreviewFSection(
                        start_dlat=edge.start_dlat,
                        end_dlat=existing.end_dlat,
                        surface_type=edge.surface_type,
                        type2=edge.type2,
                    )
                )
            else:
                updated.append(
                    PreviewFSection(
                        start_dlat=existing.start_dlat,
                        end_dlat=edge.end_dlat,
                        surface_type=edge.surface_type,
                        type2=edge.type2,
                    )
                )
        self._fsects_by_section[index] = updated

    def _sync_fsects_on_connection(
        self, source: tuple[int, str], target: tuple[int, str]
    ) -> None:
        source_index, source_end = source
        target_index, target_end = target
        if source_end not in {"start", "end"} or target_end not in {"start", "end"}:
            return

        edge_profile = self._fsect_edge_profile(target_index, target_end)
        self._apply_fsect_edge_profile(source_index, source_end, edge_profile)

    def _insert_fsects_by_section(
        self,
        index: int,
        source_index: int | None = None,
        source_endtype: str | None = None,
    ) -> None:
        if source_index is not None and 0 <= source_index < len(self._fsects_by_section):
            if source_endtype in {"start", "end"}:
                self._fsects_by_section.insert(
                    index,
                    self._fsect_edge_profile(source_index, source_endtype),
                )
            else:
                self._fsects_by_section.insert(
                    index, copy.deepcopy(self._fsects_by_section[source_index])
                )
        else:
            self._fsects_by_section.insert(index, [])

    def _closed_loop_order(self, sections: list[SectionPreview]) -> list[int]:
        if not is_closed_loop(sections):
            return []
        order: list[int] = []
        visited: set[int] = set()
        index = 0
        while index not in visited:
            visited.add(index)
            order.append(index)
            index = sections[index].next_id
        return order

    def _split_fsects_by_section(self, index: int) -> None:
        original_fsects = (
            self._fsects_by_section[index] if index < len(self._fsects_by_section) else []
        )
        self._fsects_by_section[index] = copy.deepcopy(original_fsects)
        self._fsects_by_section.insert(index + 1, copy.deepcopy(original_fsects))

    def _delete_fsects_by_section(self, index: int) -> None:
        if 0 <= index < len(self._fsects_by_section):
            self._fsects_by_section.pop(index)

    def current_transform(self, widget_size: tuple[int, int]) -> Transform | None:
        if self._drag_transform_active:
            return self._drag_transform
        return self._controller.current_transform(widget_size)

    def begin_drag_transform(self, transform: Transform) -> None:
        self._drag_transform = transform
        self._drag_transform_active = True

    def end_drag_transform(self) -> None:
        self._drag_transform = None
        self._drag_transform_active = False

    def map_to_track(
        self,
        screen_pos: tuple[float, float] | Point,
        widget_size: tuple[int, int],
        widget_height: int,
        transform: Transform | None = None,
    ) -> Point | None:
        if transform is None and self._drag_transform_active:
            transform = self._drag_transform
        point = (
            QtCore.QPointF(*screen_pos)
            if isinstance(screen_pos, tuple)
            else QtCore.QPointF(screen_pos)
        )
        return self._controller.map_to_track(point, widget_size, widget_height, transform)

    def _map_to_track_cb(
        self,
        point: Point,
        widget_size: tuple[int, int],
        widget_height: int,
        transform: Transform | None,
    ) -> Point | None:
        return self._controller.map_to_track(
            QtCore.QPointF(*point), widget_size, widget_height, transform
        )

    @property
    def preview_fsections(self) -> list[PreviewFSection]:
        if self._preview_data is None:
            return []
        return list(self._preview_data.fsections)

    def get_section_fsects(
        self, section_index: int | None
    ) -> list[PreviewFSection]:
        if section_index is None:
            return []
        if section_index < 0 or section_index >= len(self._fsects_by_section):
            return []
        return list(self._fsects_by_section[section_index])

    def set_status(self, text: str) -> None:
        self._status_message = text
        self._context.request_repaint()

    def set_status_text(self, text: str) -> None:
        self.set_status(text)

    def request_repaint(self) -> None:
        self._context.request_repaint()

    def request_rebuild(self) -> None:
        self._sg_preview_model = self._build_sg_preview_model()
        self._context.request_repaint()

    def begin_drag(self) -> None:
        self._drag_active = True

    def end_drag(self) -> None:
        self._drag_active = False
        self._cached_preview_model = None
        self.request_rebuild()

    def update_fsection_type(
        self,
        section_index: int,
        fsect_index: int,
        *,
        surface_type: int,
        type2: int,
    ) -> None:
        if section_index < 0 or section_index >= len(self._fsects_by_section):
            return
        fsects = list(self._fsects_by_section[section_index])
        if fsect_index < 0 or fsect_index >= len(fsects):
            return
        current = fsects[fsect_index]
        if (
            current.surface_type == surface_type
            and current.type2 == type2
        ):
            return
        fsects[fsect_index] = PreviewFSection(
            start_dlat=current.start_dlat,
            end_dlat=current.end_dlat,
            surface_type=surface_type,
            type2=type2,
        )
        self._fsects_by_section[section_index] = fsects
        self._has_unsaved_changes = True
        if self._emit_sections_changed is not None:
            self._emit_sections_changed()
        if not self.refresh_fsections_preview():
            self._context.request_repaint()

    def update_fsection_dlat(
        self,
        section_index: int,
        fsect_index: int,
        *,
        start_dlat: float | None = None,
        end_dlat: float | None = None,
    ) -> None:
        if section_index < 0 or section_index >= len(self._fsects_by_section):
            return
        fsects = list(self._fsects_by_section[section_index])
        if fsect_index < 0 or fsect_index >= len(fsects):
            return
        current = fsects[fsect_index]
        new_start = current.start_dlat if start_dlat is None else float(start_dlat)
        new_end = current.end_dlat if end_dlat is None else float(end_dlat)
        if (
            current.start_dlat == new_start
            and current.end_dlat == new_end
        ):
            return
        fsects[fsect_index] = PreviewFSection(
            start_dlat=new_start,
            end_dlat=new_end,
            surface_type=current.surface_type,
            type2=current.type2,
        )
        self._fsects_by_section[section_index] = fsects
        self._has_unsaved_changes = True
        if self._emit_sections_changed is not None:
            self._emit_sections_changed()
        if not self.refresh_fsections_preview():
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

    def _stop_panning(self) -> None:
        self._interaction_state.stop_panning()
        self._transform_controller.end_pan()

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

    def enable_trk_overlay(self) -> TRKFile | None:
        trk = self._trk_overlay.enable(self._preview_data)
        self._trk = trk
        return trk

    def start_new_track(self) -> None:
        self.clear("New track ready. Click New Straight to start drawing.")
        self._sgfile = create_empty_sgfile()
        self._preview_data = None
        self._trk_overlay.disable(None)
        self._suppress_document_dirty = True
        self._document.set_sg_data(self._sgfile)
        self._suppress_document_dirty = False
        self._set_default_view_bounds()
        self._sampled_centerline = []
        self._track_length = 0.0
        self._start_finish_dlong = None
        self._fsects_by_section = []
        self._has_unsaved_changes = False
        self._update_fit_scale()
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
        was_closed = is_closed_loop(self._section_manager.sections)
        updated_sections, track_length, new_index, status = (
            self._editor.finalize_new_straight(
                self._section_manager.sections, self._track_length
            )
        )
        if new_index is None:
            return

        self._track_length = track_length
        source_index = None
        source_endtype = None
        connection = self._creation_controller.straight_interaction.connection
        if connection is not None:
            source_index, source_endtype = connection
        self._insert_fsects_by_section(new_index, source_index, source_endtype)
        if not was_closed and is_closed_loop(updated_sections):
            order = self._closed_loop_order(updated_sections)
            if order and len(order) == len(self._fsects_by_section):
                self._fsects_by_section = [self._fsects_by_section[i] for i in order]
                if new_index in order:
                    new_index = order.index(new_index)
            updated_sections = set_start_finish(updated_sections, 0)
        self.set_sections(updated_sections)
        self._validate_section_fsects_alignment()
        self._selection.set_selected_section(new_index)
        self._apply_creation_update(self._creation_controller.finish_straight(status))

    def _finalize_new_curve(self) -> None:
        was_closed = is_closed_loop(self._section_manager.sections)
        updated_sections, track_length, new_index, status = self._editor.finalize_new_curve(
            self._section_manager.sections, self._track_length
        )
        if new_index is None:
            return

        self._track_length = track_length
        source_index = None
        source_endtype = None
        connection = self._creation_controller.curve_interaction.connection
        if connection is not None:
            source_index, source_endtype = connection
        self._insert_fsects_by_section(new_index, source_index, source_endtype)
        if not was_closed and is_closed_loop(updated_sections):
            order = self._closed_loop_order(updated_sections)
            if order and len(order) == len(self._fsects_by_section):
                self._fsects_by_section = [self._fsects_by_section[i] for i in order]
                if new_index in order:
                    new_index = order.index(new_index)
            updated_sections = set_start_finish(updated_sections, 0)
        self.set_sections(updated_sections)
        self._validate_section_fsects_alignment()
        self._selection.set_selected_section(new_index)
        self._apply_creation_update(self._creation_controller.finish_curve(status))

    def _next_section_start_dlong(self) -> float:
        return self._editor.next_section_start_dlong(self._section_manager.sections)

    def set_background_settings(
        self, scale_500ths_per_px: float, origin: Point
    ) -> None:
        self._background.scale_500ths_per_px = scale_500ths_per_px
        self._background.world_xy_at_image_uv_00 = origin
        self._fit_view_to_background()
        self._context.request_repaint()

    def get_background_settings(self) -> tuple[float, Point]:
        return (
            self._background.scale_500ths_per_px,
            self._background.world_xy_at_image_uv_00,
        )

    def _background_bounds(self) -> tuple[float, float, float, float] | None:
        return self._background.bounds()

    def _combine_bounds_with_background(
        self, bounds: tuple[float, float, float, float]
    ) -> tuple[float, float, float, float]:
        return self._viewport.combine_bounds_with_background(bounds)

    def _fit_view_to_background(self) -> None:
        if self._drag_transform_active:
            return
        active_bounds = self._transform_controller.fit_view_to_background(
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
    def show_sg_fsects(self) -> bool:
        return self._show_sg_fsects

    @property
    def show_xsect_dlat_line(self) -> bool:
        return self._show_xsect_dlat_line

    @property
    def selected_xsect_dlat(self) -> float | None:
        if self._selected_xsect_index is None or self._sgfile is None:
            return None
        if self._selected_xsect_index < 0:
            return None
        if self._selected_xsect_index >= len(self._sgfile.xsect_dlats):
            return None
        return float(self._sgfile.xsect_dlats[self._selected_xsect_index])

    @property
    def start_finish_mapping(self) -> tuple[Point, Point, Point] | None:
        return self._start_finish_mapping

    @property
    def status_message(self) -> str:
        return self._status_message

    @property
    def sg_preview_model(self):
        return self._sg_preview_model

    @property
    def sg_preview_view_state(self) -> SgPreviewViewState:
        return self._sg_preview_view_state

    def sg_preview_transform(self, widget_height: int) -> ViewTransform | None:
        widget_size = self._widget_size()
        transform = self.current_transform(widget_size)
        if transform is None:
            return None
        scale, offsets = transform
        return ViewTransform(scale=scale, offset=(offsets[0], widget_height - offsets[1]))

    @property
    def split_section_mode(self) -> bool:
        return self._split_section_mode

    @property
    def split_hover_point(self) -> Point | None:
        return self._split_hover_point

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
                self._transform_controller.lock_user_transform(self._widget_size())
            if self._emit_new_straight_mode_changed is not None:
                self._emit_new_straight_mode_changed(
                    self._creation_controller.straight_active
                )
        if update.curve_mode_changed:
            if self._creation_controller.curve_active:
                self._set_delete_section_active(False)
                self.cancel_split_section()
                self._transform_controller.lock_user_transform(self._widget_size())
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

    def _on_selection_changed(self, selection_value: object) -> None:
        if self._emit_selected_section_changed is not None:
            self._emit_selected_section_changed(selection_value)
        self._context.request_repaint()

    def get_section_set(self) -> tuple[list[SectionPreview], float | None]:
        track_length = (
            float(self._track_length) if self._track_length is not None else None
        )
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
        return (
            f"Track length: {total_length:.0f} DLONG (500ths) — {miles:.3f} miles"
        )

    # ------------------------------------------------------------------
    # Public controls
    # ------------------------------------------------------------------
    def set_trk_comparison(self, trk: TRKFile | None) -> None:
        self._trk_overlay.set_trk_comparison(trk)
        self._trk = trk

    def set_show_curve_markers(self, visible: bool) -> None:
        self._show_curve_markers = visible
        self._context.request_repaint()

    def set_show_axes(self, visible: bool) -> None:
        self._show_axes = visible
        self._context.request_repaint()

    def set_show_sg_fsects(self, visible: bool) -> None:
        self._show_sg_fsects = visible
        self._context.request_repaint()

    def set_show_xsect_dlat_line(self, visible: bool) -> None:
        self._show_xsect_dlat_line = visible
        self._context.request_repaint()

    def set_selected_xsect_index(self, index: int | None) -> None:
        self._selected_xsect_index = int(index) if index is not None else None
        self._context.request_repaint()

    def activate_set_start_finish_mode(self) -> None:
        """Backward-compatible alias for setting start/finish."""
        self.set_start_finish_at_selected_section()

    def select_next_section(self) -> None:
        if not self._selection.sections:
            return

        if self._selection.selected_section_index is None:
            self._selection.set_selected_section(0)
            return

        next_index = (self._selection.selected_section_index + 1) % len(
            self._selection.sections
        )
        self._selection.set_selected_section(next_index)

    def select_previous_section(self) -> None:
        if not self._selection.sections:
            return

        if self._selection.selected_section_index is None:
            self._selection.set_selected_section(len(self._selection.sections) - 1)
            return

        prev_index = (self._selection.selected_section_index - 1) % len(
            self._selection.sections
        )
        self._selection.set_selected_section(prev_index)

    def get_section_headings(self) -> list[selection.SectionHeadingData]:
        return self._selection.get_section_headings()

    def get_xsect_metadata(self) -> list[tuple[int, float]]:
        if self._sgfile is None:
            return []
        return [(idx, float(dlat)) for idx, dlat in enumerate(self._sgfile.xsect_dlats)]

    def set_xsect_definitions(self, entries: list[tuple[int | None, float]]) -> bool:
        try:
            self._document.set_xsect_definitions(entries)
        except (ValueError, IndexError):
            return False
        return True

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

    def get_section_xsect_values(
        self, section_id: int, xsect_index: int
    ) -> tuple[int | None, int | None]:
        sg_data = self._document.sg_data
        if (
            sg_data is None
            or section_id < 0
            or section_id >= len(sg_data.sects)
            or xsect_index < 0
            or xsect_index >= sg_data.num_xsects
        ):
            return None, None

        section = sg_data.sects[section_id]
        altitude = section.alt[xsect_index] if xsect_index < len(section.alt) else None
        grade = section.grade[xsect_index] if xsect_index < len(section.grade) else None
        return altitude, grade

    def get_section_xsect_altitudes(self, section_id: int) -> list[int | None]:
        sg_data = self._document.sg_data
        if (
            sg_data is None
            or section_id < 0
            or section_id >= len(sg_data.sects)
        ):
            return []

        section = sg_data.sects[section_id]
        num_xsects = sg_data.num_xsects
        altitudes: list[int | None] = []
        for idx in range(num_xsects):
            altitudes.append(section.alt[idx] if idx < len(section.alt) else None)
        return altitudes

    def set_section_xsect_altitude(
        self, section_id: int, xsect_index: int, altitude: float
    ) -> bool:
        try:
            self._document.set_section_xsect_altitude(
                section_id, xsect_index, altitude
            )
        except (ValueError, IndexError):
            return False
        return True

    def set_section_xsect_grade(
        self, section_id: int, xsect_index: int, grade: float
    ) -> bool:
        try:
            self._document.set_section_xsect_grade(section_id, xsect_index, grade)
        except (ValueError, IndexError):
            return False
        return True

    def copy_xsect_data_to_all(self, xsect_index: int) -> bool:
        try:
            self._document.copy_xsect_data_to_all(xsect_index)
        except (ValueError, IndexError):
            return False
        return True
