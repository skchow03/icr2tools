from __future__ import annotations

import logging
import math
from dataclasses import replace
from pathlib import Path
from typing import Callable, List, Tuple

from PyQt5 import QtCore, QtGui

from icr2_core.trk.sg_classes import SGFile
from icr2_core.sg_elevation import sample_sg_elevation
from sg_viewer.model import preview_state, selection
from sg_viewer.preview.geometry import (
    CURVE_SOLVE_TOLERANCE as CURVE_SOLVE_TOLERANCE_DEFAULT,
)
from sg_viewer.preview.context import PreviewContext
from sg_viewer.preview.preview_defaults import create_empty_sgfile
from sg_viewer.preview.preview_mutations import project_point_to_polyline
from sg_viewer.preview.trk_overlay_controller import TrkOverlayController
from sg_viewer.preview.trackside_drag import quantize_trackside_drag_delta
from sg_viewer.preview.transform_controller import TransformController
from sg_viewer.preview.selection import build_node_positions, find_unconnected_node_hit
from sg_viewer.services.preview_background import PreviewBackground
from sg_viewer.services.trackside_objects import TracksideObject, normalize_rotation_point
from sg_viewer.model.preview_state import SgPreviewViewState
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
from sg_viewer.runtime.viewer_runtime_api import ViewerRuntimeApi
from sg_viewer.ui.preview_state_controller import PreviewStateController
from sg_viewer.services.tsd_io import TrackSurfaceDetailLine
from sg_viewer.ui.preview_section_manager import PreviewSectionManager
from sg_viewer.ui.preview_viewport import PreviewViewport
from sg_viewer.model.preview_state_utils import update_node_status
from sg_viewer.model.sg_model import PreviewData, SectionPreview
from sg_viewer.model.preview_fsection import PreviewFSection
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
        self._document.elevation_changed.connect(self._on_elevation_changed)
        self._document.elevations_bulk_changed.connect(self._on_elevations_bulk_changed)

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
        self._show_mrk_notches = False
        self._selected_mrk_wall: tuple[int, int, int] = (0, 0, 0)
        self._highlighted_mrk_walls: tuple[tuple[int, int, int, int, str], ...] = ()
        self._show_tsd_lines = False
        self._show_tsd_selected_section_only = False
        self._tsd_lines: tuple[TrackSurfaceDetailLine, ...] = ()
        self._tsd_lines_version = 0
        self._tsd_palette: tuple[QtGui.QColor, ...] = ()
        self._trackside_objects: tuple[TracksideObject, ...] = ()
        self._selected_trackside_object_index: int | None = None
        self._selected_trackside_object_indices: tuple[int, ...] = ()
        self._focused_trackside_object_index: int | None = None
        self._trackside_order_labels: tuple[tuple[int, int], ...] = ()
        self._show_trackside_objects = False
        self._trackside_object_drag_callback = None
        self._trackside_object_drag_end_callback = None
        self._trackside_map_click_callback = None
        self._trackside_box_select_callback = None
        self._trackside_box_select_enabled = False
        self._trackside_box_select_drag_start_screen: QtCore.QPointF | None = None
        self._trackside_box_select_drag_current_screen: QtCore.QPointF | None = None
        self._active_trackside_drag_index: int | None = None
        self._active_trackside_drag_origin: tuple[float, float] | None = None
        self._active_trackside_drag_remainder: tuple[float, float] = (0.0, 0.0)
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
        self._query_track_hover_point: Point | None = None
        self._query_track_overlay_message: str = ""
        self._ruler_start_point: Point | None = None
        self._ruler_end_point: Point | None = None
        self._ruler_label: str = ""


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
        self._show_crosshair = False
        self._show_background_image = True
        self._track_opacity = 1.0
        self._integrity_boundary_violation_points: tuple[Point, ...] = ()

        self._node_status = {}   # (index, "start"|"end") -> "green" or "orange"
        self._disconnected_nodes: set[tuple[int, str]] = set()
        self._node_radius_px = 6
        self._has_unsaved_changes = False
        self._show_status = show_status or self.set_status_text
        self._sg_version = 0
        self._last_load_warnings: list[str] = []
        self._elevation_bounds_cache: dict[tuple[int, int], tuple[float, float] | None] = {}
        self._elevation_xsect_bounds_cache: dict[
            tuple[int, int], dict[int, tuple[float, float] | None]
        ] = {}
        self._elevation_xsect_bounds_dirty: dict[tuple[int, int], set[int]] = {}
        self._elevation_profile_cache: dict[
            tuple[int, int],
            tuple[list[float], list[tuple[float, float]], list[tuple[int, int] | None]],
        ] = {}
        self._elevation_profile_alt_cache: dict[tuple[int, int, int], list[float]] = {}
        self._elevation_profile_dirty: dict[tuple[int, int, int], set[int]] = {}

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
            emit_drag_state_changed=self._emit_interaction_drag_changed,
            sync_fsects_on_connection=self._sync_fsects_on_connection,
            apply_preview_to_sgfile=self.sync_preview_to_sgfile_if_loaded,
            runtime_api=ViewerRuntimeApi(preview_context=self._context),
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
        self._request_interaction_repaint()
        event.accept()

    def _trackside_drag_hit_test(self, screen_pos: QtCore.QPointF) -> int | None:
        if not self._show_trackside_objects:
            return None
        move_enabled_indices = tuple(
            index
            for index in getattr(self, "_trackside_move_enabled_indices", ())
            if 0 <= index < len(self._trackside_objects)
        )
        if not move_enabled_indices:
            return None
        selected_indices = tuple(
            index
            for index in getattr(self, "_selected_trackside_object_indices", ())
            if index in move_enabled_indices
        )
        if not selected_indices:
            selected = self._selected_trackside_object_index
            if selected is not None and selected in move_enabled_indices:
                selected_indices = (selected,)
        candidate_indices = selected_indices or move_enabled_indices
        if not candidate_indices:
            return None
        transform = self.current_transform(self._widget_size())
        if transform is None:
            return None
        scale, offsets = transform
        hit_tolerance = 8.0
        for selected in candidate_indices:
            obj = self._trackside_objects[selected]
            yaw_radians = math.radians(float(obj.yaw) / 10.0)
            half_length = max(4.0 / max(scale, 1e-9), float(obj.bbox_length) * 0.5)
            half_width = max(4.0 / max(scale, 1e-9), float(obj.bbox_width) * 0.5)
            pivot_local_x, pivot_local_y = _rotation_pivot_local_offsets(
                normalize_rotation_point(str(getattr(obj, "rotation_point", "center"))),
                half_length,
                half_width,
            )
            center_x = float(obj.x) - (pivot_local_x * math.cos(yaw_radians) - pivot_local_y * math.sin(yaw_radians))
            center_y = float(obj.y) - (pivot_local_x * math.sin(yaw_radians) + pivot_local_y * math.cos(yaw_radians))
            sx = offsets[0] + center_x * scale
            sy = offsets[1] - center_y * scale
            dx = float(screen_pos.x()) - sx
            dy = float(screen_pos.y()) - sy
            cos_yaw = math.cos(-yaw_radians)
            sin_yaw = math.sin(-yaw_radians)
            local_x = dx * cos_yaw - dy * sin_yaw
            local_y = dx * sin_yaw + dy * cos_yaw
            near_length = half_length + (hit_tolerance / max(scale, 1e-9))
            near_width = half_width + (hit_tolerance / max(scale, 1e-9))
            if abs(local_x) <= near_length and abs(local_y) <= near_width:
                return selected
        return None

    def _drag_trackside_object_to(self, screen_pos: QtCore.QPointF) -> bool:
        index = self._active_trackside_drag_index
        callback = self._trackside_object_drag_callback
        if index is None or not callable(callback):
            return False
        transform = self.current_transform(self._widget_size())
        if transform is None:
            return False
        world_pos = self.map_to_track(
            (float(screen_pos.x()), float(screen_pos.y())),
            self._widget_size(),
            self._widget_height(),
            transform,
        )
        if world_pos is None:
            return False
        drag_origin = getattr(self, "_active_trackside_drag_origin", None)
        if drag_origin is None:
            return False
        delta_x, delta_y, remainder = quantize_trackside_drag_delta(
            world_pos[0] - drag_origin[0],
            world_pos[1] - drag_origin[1],
            getattr(self, "_active_trackside_drag_remainder", (0.0, 0.0)),
        )
        self._active_trackside_drag_origin = (world_pos[0], world_pos[1])
        self._active_trackside_drag_remainder = remainder
        if delta_x == 0 and delta_y == 0:
            return False
        callback(index, delta_x, delta_y)
        return True

    def _trackside_box_select_screen_rect(self) -> QtCore.QRectF | None:
        start = self._trackside_box_select_drag_start_screen
        current = self._trackside_box_select_drag_current_screen
        if start is None or current is None:
            return None
        return QtCore.QRectF(start, current).normalized()

    def on_mouse_press(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if event.button() == QtCore.Qt.LeftButton and self._trackside_box_select_enabled:
            self._trackside_box_select_drag_start_screen = QtCore.QPointF(event.localPos())
            self._trackside_box_select_drag_current_screen = QtCore.QPointF(event.localPos())
            event.accept()
            self._request_interaction_repaint()
            return

        if event.button() == QtCore.Qt.RightButton:
            hit_index = self._trackside_drag_hit_test(event.localPos())
            if hit_index is not None:
                transform = self.current_transform(self._widget_size())
                if transform is not None:
                    world_pos = self.map_to_track(
                        (float(event.localPos().x()), float(event.localPos().y())),
                        self._widget_size(),
                        self._widget_height(),
                        transform,
                    )
                    if world_pos is not None:
                        self._active_trackside_drag_index = hit_index
                        self._active_trackside_drag_origin = (world_pos[0], world_pos[1])
                        self._active_trackside_drag_remainder = (0.0, 0.0)
                        event.accept()
                        return

        if event.button() == QtCore.Qt.LeftButton:
            callback = getattr(self, "_trackside_map_click_callback", None)
            if callable(callback):
                transform = self.current_transform(self._widget_size())
                if transform is not None:
                    world_pos = self.map_to_track(
                        (float(event.localPos().x()), float(event.localPos().y())),
                        self._widget_size(),
                        self._widget_height(),
                        transform,
                    )
                    if world_pos is not None and bool(callback(int(round(world_pos[0])), int(round(world_pos[1])))):
                        event.accept()
                        self._request_interaction_repaint()
                        return

        if self._handle_creation_mouse_press(event):
            return

        inputs = self._interaction_inputs()
        if (
            self._track_interaction_enabled
            and not inputs.delete_section_active
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
        if self._trackside_box_select_drag_start_screen is not None:
            self._trackside_box_select_drag_current_screen = QtCore.QPointF(event.localPos())
            event.accept()
            self._request_interaction_repaint()
            return

        if self._active_trackside_drag_index is not None:
            moved = self._drag_trackside_object_to(event.localPos())
            event.accept()
            if moved:
                self._request_interaction_repaint()
            return

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

        if self._track_interaction_enabled and self._interaction.handle_mouse_move(event):
            self._request_interaction_repaint()
            return

        intent = self._interaction_state.on_mouse_move(
            event, inputs, self._creation_context()
        )
        self._apply_mouse_intent(intent, event)

    def on_mouse_release(self, event: QtGui.QMouseEvent) -> None:  # noqa: D401
        if self._trackside_box_select_drag_start_screen is not None and event.button() == QtCore.Qt.LeftButton:
            start_screen = self._trackside_box_select_drag_start_screen
            end_screen = QtCore.QPointF(event.localPos())
            self._trackside_box_select_drag_start_screen = None
            self._trackside_box_select_drag_current_screen = None
            callback = self._trackside_box_select_callback
            transform = self.current_transform(self._widget_size())
            if callable(callback) and transform is not None:
                start_world = self.map_to_track(
                    (float(start_screen.x()), float(start_screen.y())),
                    self._widget_size(),
                    self._widget_height(),
                    transform,
                )
                end_world = self.map_to_track(
                    (float(end_screen.x()), float(end_screen.y())),
                    self._widget_size(),
                    self._widget_height(),
                    transform,
                )
                if start_world is not None and end_world is not None:
                    callback(
                        int(round(min(start_world[0], end_world[0]))),
                        int(round(min(start_world[1], end_world[1]))),
                        int(round(max(start_world[0], end_world[0]))),
                        int(round(max(start_world[1], end_world[1]))),
                    )
            event.accept()
            self._request_interaction_repaint()
            return

        if self._active_trackside_drag_index is not None and event.button() == QtCore.Qt.RightButton:
            active_index = self._active_trackside_drag_index
            self._drag_trackside_object_to(event.localPos())
            self._active_trackside_drag_index = None
            self._active_trackside_drag_origin = None
            self._active_trackside_drag_remainder = (0.0, 0.0)
            drag_end_callback = getattr(self, "_trackside_object_drag_end_callback", None)
            if callable(drag_end_callback):
                drag_end_callback(active_index)
            event.accept()
            return

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
        dragged_indices = self._interaction.last_dragged_indices
        if self._track_interaction_enabled and self._interaction.handle_mouse_release(event):
            if was_dragging_node:
                affected_indices = (
                    list(dragged_indices) if dragged_indices is not None else None
                )
                self._recalculate_elevations_after_drag(affected_indices)
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

    @property
    def query_track_hover_point(self) -> Point | None:
        return self._query_track_hover_point

    def set_query_track_hover_point(self, point: Point | None) -> None:
        if point == self._query_track_hover_point:
            return
        self._query_track_hover_point = point
        self._context.request_repaint()

    @property
    def query_track_overlay_message(self) -> str:
        return self._query_track_overlay_message

    def set_query_track_overlay_message(self, message: str) -> None:
        normalized = str(message)
        if normalized == self._query_track_overlay_message:
            return
        self._query_track_overlay_message = normalized
        self._context.request_repaint()

    @property
    def ruler_start_point(self) -> Point | None:
        return self._ruler_start_point

    @property
    def ruler_end_point(self) -> Point | None:
        return self._ruler_end_point

    @property
    def ruler_label(self) -> str:
        return self._ruler_label

    def set_ruler_overlay(
        self,
        start_point: Point | None,
        end_point: Point | None,
        label: str,
    ) -> None:
        normalized_label = str(label)
        if (
            start_point == self._ruler_start_point
            and end_point == self._ruler_end_point
            and normalized_label == self._ruler_label
        ):
            return
        self._ruler_start_point = start_point
        self._ruler_end_point = end_point
        self._ruler_label = normalized_label
        self._context.request_repaint()


def _rotation_pivot_local_offsets(rotation_point: str, half_length: float, half_width: float) -> tuple[float, float]:
    if rotation_point == "top_left":
        return -half_length, half_width
    if rotation_point == "top_right":
        return half_length, half_width
    if rotation_point == "bottom_left":
        return -half_length, -half_width
    if rotation_point == "bottom_right":
        return half_length, -half_width
    return 0.0, 0.0
