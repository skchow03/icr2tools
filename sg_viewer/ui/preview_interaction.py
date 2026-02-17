from __future__ import annotations

import math
import copy
from typing import TYPE_CHECKING, Callable

from sg_viewer.model.edit_commands import ReplaceSectionsCommand
from sg_viewer.model.edit_manager import EditManager

from PyQt5 import QtCore, QtGui

from sg_viewer.model.preview_state_utils import is_invalid_id
from sg_viewer.preview.connection_detection import find_unconnected_node_target
from sg_viewer.preview.context import PreviewContext
from sg_viewer.preview.preview_mutations import (
    distance_to_polyline,
    translate_section,
)
from sg_viewer.runtime.preview_geometry_service import (
    ConnectNodesRequest,
    ConnectionSolveRequest,
    NodeDisconnectRequest,
    NodeDragRequest,
    PreviewGeometryService,
    StartFinishRequest,
)


if TYPE_CHECKING:
    from sg_viewer.model.selection import SelectionManager
    from sg_viewer.model.sg_model import SectionPreview
    from sg_viewer.ui.preview_editor import PreviewEditor
    from sg_viewer.ui.preview_section_manager import PreviewSectionManager


Point = tuple[float, float]
DEBUG_LOOP_DETECTION = True


class PreviewInteraction:
    def __init__(
        self,
        context: PreviewContext,
        selection: "SelectionManager",
        section_manager: "PreviewSectionManager",
        editor: "PreviewEditor",
        set_sections: Callable[..., None],
        update_drag_preview: Callable[[list["SectionPreview"]], None],
        rebuild_after_start_finish: Callable[[list["SectionPreview"]], None],
        node_radius_px: int,
        stop_panning: Callable[[], None],
        show_status: Callable[[str], None],
        emit_drag_state_changed: Callable[[bool], None] | None = None,
        sync_fsects_on_connection: Callable[
            [tuple[int, str], tuple[int, str]], None
        ]
        | None = None,
        apply_preview_to_sgfile: Callable[[], object] | None = None,
        recalculate_elevations: Callable[[list[int] | None], None] | None = None,
        edit_manager: EditManager | None = None,
        geometry_service: PreviewGeometryService | None = None,
    ) -> None:
        self._context = context
        self._selection = selection
        self._section_manager = section_manager
        self._editor = editor
        self._set_sections = set_sections
        self._update_drag_preview = update_drag_preview
        self._rebuild_after_start_finish = rebuild_after_start_finish
        self._node_radius_px = node_radius_px
        self._stop_panning = stop_panning
        self._show_status = show_status
        self._emit_drag_state_changed = emit_drag_state_changed
        self._sync_fsects_on_connection = sync_fsects_on_connection
        self._apply_preview_to_sgfile = apply_preview_to_sgfile
        self._recalculate_elevations = recalculate_elevations
        self._edit_manager = edit_manager or EditManager()
        self._geometry_service = geometry_service or PreviewGeometryService()

        self._is_dragging_node = False
        self._active_node: tuple[int, str] | None = None
        self._connection_target: tuple[int, str] | None = None
        self._is_dragging_section = False
        self._active_section_index: int | None = None
        self._section_drag_start_mouse_screen: QtCore.QPointF | None = None
        self._section_drag_start_sections: list["SectionPreview"] | None = None
        self._node_drag_start_sections: list["SectionPreview"] | None = None
        self._active_chain_indices: list[int] | None = None
        self._set_start_finish_mode = False
        self._drag_state_active = False
        self._last_dragged_indices: list[int] | None = None
        self._section_drag_enabled = True

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------
    @property
    def is_dragging_node(self) -> bool:
        return self._is_dragging_node

    @property
    def is_dragging_section(self) -> bool:
        return self._is_dragging_section

    @property
    def connection_target(self) -> tuple[int, str] | None:
        return self._connection_target

    @property
    def last_dragged_indices(self) -> tuple[int, ...] | None:
        if self._last_dragged_indices is None:
            return None
        return tuple(self._last_dragged_indices)

    def dragged_curve_heading(self) -> tuple["SectionPreview", Point] | None:
        if not self._is_dragging_node or self._active_node is None:
            return None

        section_index, endtype = self._active_node
        if endtype != "end":
            return None

        sections = self._section_manager.sections
        if section_index < 0 or section_index >= len(sections):
            return None

        section = sections[section_index]
        if section.type_name != "curve" or section.end_heading is None:
            return None

        return section, section.end

    def reset(self) -> None:
        self._is_dragging_node = False
        self._active_node = None
        self._connection_target = None
        self._is_dragging_section = False
        self._active_section_index = None
        self._section_drag_start_mouse_screen = None
        self._section_drag_start_sections = None
        self._node_drag_start_sections = None
        self._active_chain_indices = None
        self._set_start_finish_mode = False
        self._set_drag_state(False)
        self._section_manager.set_preview_mode(False)
        self._node_drag_start_sections = None
        self._context.end_drag_transform()
        self._last_dragged_indices = None

    def set_set_start_finish_mode(self, active: bool) -> None:
        self._set_start_finish_mode = active

    def set_section_drag_enabled(self, enabled: bool) -> None:
        self._section_drag_enabled = enabled
        if not enabled and self._is_dragging_section:
            self._end_section_drag()

    # ------------------------------------------------------------------
    # Mouse interaction entry points
    # ------------------------------------------------------------------
    def handle_mouse_press(self, event: QtGui.QMouseEvent) -> bool:
        selected_section = self._selection.selected_section_index

        if event.button() == QtCore.Qt.RightButton:
            hit = self._hit_test_node(event.pos(), selected_section)
            if hit is None:
                return False

            if selected_section is None or selected_section != hit[0]:
                return False

            self._disconnect_node(hit)
            event.accept()
            return True

        if event.button() != QtCore.Qt.LeftButton:
            return False

        hit = self._hit_test_node(event.pos(), selected_section)
        if hit is not None:
            if selected_section is None or selected_section != hit[0]:
                return False

            if self._start_node_interaction(hit, event.pos(), allow_disconnect=False):
                event.accept()
                return True
            return False

        drag_origin = self._hit_test_selected_section_line(event.pos())
        if drag_origin is not None and self._section_drag_enabled:
            self._start_section_drag(event.pos())
            event.accept()
            return True

        return False

    def handle_mouse_move(self, event: QtGui.QMouseEvent) -> bool:
        if self._is_dragging_node and self._active_node is not None:
            widget_size = self._context.widget_size()
            transform = self._context.current_transform(widget_size)
            track_point = self._context.map_to_track(
                (event.pos().x(), event.pos().y()),
                widget_size,
                self._context.widget_height(),
                transform,
            )
            if track_point is None:
                self._connection_target = None
                event.accept()
                return True

            self._update_connection_target(track_point, transform)
            self._update_dragged_section(track_point)
            event.accept()
            return True

        if self._is_dragging_section and self._active_section_index is not None:
            self._update_section_drag_position(event.pos())
            event.accept()
            return True

        return False

    def handle_mouse_release(self, event: QtGui.QMouseEvent) -> bool:
        if event.button() != QtCore.Qt.LeftButton:
            return False

        if self._set_start_finish_mode:
            hit = self._hit_test_node(event.pos(), None)
            if hit is not None:
                response = self._geometry_service.set_start_finish(
                    StartFinishRequest(sections=self._section_manager.sections, hit=hit)
                )
                if response.sections is not None:
                    self._rebuild_after_start_finish(response.sections)
                self._show_status(response.status_message)
                self._set_start_finish_mode = False
                return True

        if self._is_dragging_node:
            if self._connection_target is not None and self._active_node is not None:
                response = self._geometry_service.solve_connection(
                    ConnectionSolveRequest(
                        sections=self._section_manager.sections,
                        source=self._active_node,
                        target=self._connection_target,
                    )
                )
                if response.sections is not None:
                    if self._sync_fsects_on_connection is not None:
                        self._sync_fsects_on_connection(self._active_node, self._connection_target)
                    self._finalize_connection_updates(
                        old_sections=list(self._section_manager.sections),
                        updated_sections=response.sections,
                        changed_indices=response.changed_indices or [],
                    )
                if response.status_message is not None:
                    self._show_status(response.status_message)
                self._clear_drag_state()
                event.accept()
                return True

            active_node = self._active_node
            connection_target = self._connection_target
            self._end_node_drag()
            if active_node is not None and connection_target is not None:
                self._connect_nodes(active_node, connection_target)
            event.accept()
            return True
        if self._is_dragging_section:
            self._end_section_drag()
            event.accept()
            return True

        return False

    # ------------------------------------------------------------------
    # Hit testing
    # ------------------------------------------------------------------
    def _hit_test_node(
        self, pos: QtCore.QPoint, preferred_index: int | None
    ) -> tuple[int, str] | None:
        widget_size = self._context.widget_size()
        transform = self._context.current_transform(widget_size)
        if transform is None:
            return None

        scale, offsets = transform
        ox, oy = offsets
        widget_height = self._context.widget_height()
        radius = self._node_radius_px
        r2 = radius * radius

        def _sorted_indices(total: int, prefer: int | None) -> list[int]:
            indices = list(range(total))
            if prefer is None or prefer < 0 or prefer >= total:
                return indices
            indices.remove(prefer)
            indices.insert(0, prefer)
            return indices

        sections = self._section_manager.sections
        if not sections:
            return None

        for i in _sorted_indices(len(sections), preferred_index):
            for endtype in ("start", "end"):
                world_point = (
                    sections[i].start
                    if endtype == "start"
                    else sections[i].end
                )
                px = ox + world_point[0] * scale
                py_world = oy + world_point[1] * scale
                py = widget_height - py_world

                dx = px - pos.x()
                dy = py - pos.y()
                if dx * dx + dy * dy <= r2:
                    return (i, endtype)

        return None

    def _hit_test_selected_section_line(self, pos: QtCore.QPoint) -> Point | None:
        if self._selection.selected_section_index is None:
            return None

        index = self._selection.selected_section_index
        sections = self._section_manager.sections
        if not sections or index < 0 or index >= len(sections):
            return None

        section = sections[index]
        if not self._editor.can_drag_section_polyline(
            self._section_manager.sections, section, index
        ):
            return None

        widget_size = self._context.widget_size()
        transform = self._context.current_transform(widget_size)
        if transform is None:
            return None

        track_point = self._context.map_to_track(
            (pos.x(), pos.y()), widget_size, self._context.widget_height(), transform
        )
        if track_point is None:
            return None

        scale, _ = transform
        if scale <= 0:
            return None

        tolerance = 6 / scale
        if distance_to_polyline(track_point, section.polyline) <= tolerance:
            return track_point
        return None

    # ------------------------------------------------------------------
    # Node dragging / disconnect
    # ------------------------------------------------------------------
    def _start_node_interaction(
        self, node: tuple[int, str], pos: QtCore.QPoint, *, allow_disconnect: bool = True
    ) -> bool:
        sect_index, endtype = node
        sections = self._section_manager.sections
        if sect_index < 0 or sect_index >= len(sections):
            return False

        sect = sections[sect_index]
        if self._editor.can_drag_node(self._section_manager.sections, sect, endtype):
            self._start_node_drag(node, pos)
            return True

        if self._geometry_service.can_start_shared_node_drag(node, self._section_manager.sections):
            self._start_node_drag(node, pos)
            return True

        if allow_disconnect:
            self._disconnect_node(node)
            return True

        return False

    def _disconnect_node(self, node: tuple[int, str]) -> None:
        response = self._geometry_service.disconnect_node(
            NodeDisconnectRequest(sections=self._section_manager.sections, node=node)
        )
        if response.sections is None:
            return
        self._apply_section_updates(response.sections, changed_indices=response.changed_indices)
        if self._recalculate_elevations is not None:
            self._recalculate_elevations(response.changed_indices)

    def _start_node_drag(self, node: tuple[int, str], pos: QtCore.QPoint) -> None:
        widget_size = self._context.widget_size()
        transform = self._context.current_transform(widget_size)
        if transform is None:
            return
        self._context.begin_drag_transform(transform)
        track_point = self._context.map_to_track(
            (pos.x(), pos.y()), widget_size, self._context.widget_height(), transform
        )
        if track_point is None:
            self._context.end_drag_transform()
            return
        self._active_node = node
        self._node_drag_start_sections = copy.deepcopy(self._section_manager.sections)
        self._is_dragging_node = True
        self._set_drag_state(True)
        self._connection_target = None
        self._stop_panning()
        self._last_dragged_indices = [node[0]]
        self._update_dragged_section(track_point)

    def _update_dragged_section(self, track_point: Point) -> None:
        if self._active_node is None:
            return
        sections = self._section_manager.sections
        sect_index, endtype = self._active_node
        if sect_index < 0 or sect_index >= len(sections):
            return
        can_drag = self._editor.can_drag_node(sections, sections[sect_index], endtype)
        response = self._geometry_service.update_dragged_section(
            NodeDragRequest(
                sections=sections,
                active_node=self._active_node,
                track_point=track_point,
                can_drag_node=can_drag,
            )
        )
        if response.sections is None:
            return
        self._last_dragged_indices = response.last_dragged_indices
        self._apply_section_updates(response.sections, changed_indices=response.changed_indices)

    def _update_connection_target(
        self,
        track_point: Point,
        transform: tuple[float, tuple[float, float]] | None,
    ) -> None:
        if self._active_node is None:
            self._connection_target = None
            return

        if transform is None:
            self._connection_target = None
            return

        scale, _ = transform
        if scale <= 0:
            self._connection_target = None
            return

        sections = self._section_manager.sections
        if not sections:
            self._connection_target = None
            return

        snap_radius = self._node_radius_px / scale

        target = find_unconnected_node_target(
            dragged_key=self._active_node,
            dragged_pos=track_point,
            sections=sections,
            snap_radius=snap_radius,
        )

        if target == self._active_node:
            target = None

        self._connection_target = target
        if self._active_node is not None:
            if target is not None:
                self._last_dragged_indices = [self._active_node[0], target[0]]
            else:
                self._last_dragged_indices = [self._active_node[0]]
        self._context.request_repaint()

    def _end_node_drag(self) -> None:
        if self._drag_state_active:
            self._section_manager.set_preview_mode(False)
            before = self._node_drag_start_sections or list(self._section_manager.sections)
            self._commit_section_edit(before=before, after=list(self._section_manager.sections))
        self._clear_drag_state()

    def _clear_drag_state(self) -> None:
        self._is_dragging_node = False
        self._active_node = None
        self._connection_target = None
        self._set_drag_state(False)
        self._node_drag_start_sections = None
        self._context.end_drag_transform()

    def _connect_nodes(
        self, source: tuple[int, str], target: tuple[int, str]
    ) -> None:
        response = self._geometry_service.connect_nodes(
            ConnectNodesRequest(
                sections=self._section_manager.sections,
                source=source,
                target=target,
            )
        )
        if response.sections is None:
            return
        if self._sync_fsects_on_connection is not None:
            self._sync_fsects_on_connection(source, target)
        self._finalize_connection_updates(
            old_sections=list(self._section_manager.sections),
            updated_sections=response.sections,
            changed_indices=response.changed_indices or [],
        )

    # ------------------------------------------------------------------
    # Section dragging
    # ------------------------------------------------------------------
    def _start_section_drag(self, pos: QtCore.QPoint) -> None:
        if self._selection.selected_section_index is None:
            return
        index = self._selection.selected_section_index
        sections = self._section_manager.sections
        if index < 0 or index >= len(sections):
            return
        sect = sections[index]
        if not self._editor.can_drag_section_polyline(
            self._section_manager.sections, sect, index
        ):
            return

        chain_indices = self._editor.get_drag_chain(self._section_manager.sections, index)
        if chain_indices is None:
            return

        widget_size = self._context.widget_size()
        transform = self._context.current_transform(widget_size)
        if transform is None:
            return
        self._context.begin_drag_transform(transform)
        self._active_section_index = index
        self._active_chain_indices = chain_indices
        self._section_drag_start_mouse_screen = QtCore.QPointF(pos)
        self._section_drag_start_sections = copy.deepcopy(self._section_manager.sections)
        self._is_dragging_section = True
        self._set_drag_state(True)
        self._stop_panning()

    def _update_section_drag_position(self, pos: QtCore.QPoint) -> None:
        if (
            not self._is_dragging_section
            or self._active_section_index is None
            or self._active_chain_indices is None
            or self._section_drag_start_mouse_screen is None
            or self._section_drag_start_sections is None
        ):
            return

        index = self._active_section_index
        sections = self._section_manager.sections
        if index < 0 or index >= len(sections):
            return
        sect = sections[index]
        if not self._editor.can_drag_section_polyline(
            self._section_manager.sections, sect, index
        ):
            return

        widget_size = self._context.widget_size()
        transform = self._context.current_transform(widget_size)
        if transform is None:
            return

        screen_delta = QtCore.QPointF(pos) - self._section_drag_start_mouse_screen
        scale = transform[0]
        if scale == 0:
            return
        dx = screen_delta.x() / scale
        dy = -screen_delta.y() / scale
        epsilon = 1e-6

        original_sections = self._section_drag_start_sections
        sections = list(original_sections)

        for chain_index in self._active_chain_indices:
            if chain_index < 0 or chain_index >= len(sections):
                continue
            updated_section = translate_section(original_sections[chain_index], dx, dy)
            sections[chain_index] = self._geometry_service.refresh_section_geometry(updated_section)
            applied_dx = updated_section.start[0] - original_sections[chain_index].start[0]
            applied_dy = updated_section.start[1] - original_sections[chain_index].start[1]
            assert abs(applied_dx - dx) < epsilon and abs(applied_dy - dy) < epsilon

        self._apply_section_updates(sections, changed_indices=self._active_chain_indices)

    def _end_section_drag(self) -> None:
        if self._drag_state_active:
            self._section_manager.set_preview_mode(False)
            before = self._section_drag_start_sections or list(self._section_manager.sections)
            self._commit_section_edit(before=before, after=list(self._section_manager.sections))
        self._is_dragging_section = False
        self._active_section_index = None
        self._section_drag_start_mouse_screen = None
        self._section_drag_start_sections = None
        self._node_drag_start_sections = None
        self._active_chain_indices = None
        self._set_drag_state(False)
        self._context.end_drag_transform()

    def _set_drag_state(self, active: bool) -> None:
        if self._drag_state_active == active:
            return
        self._drag_state_active = active
        self._section_manager.set_preview_mode(active)
        if self._emit_drag_state_changed is not None:
            self._emit_drag_state_changed(active)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def _finalize_connection_updates(
        self,
        old_sections: list["SectionPreview"],
        updated_sections: list["SectionPreview"],
        changed_indices: list[int],
    ) -> None:
        if self._drag_state_active:
            self._section_manager.set_preview_mode(False)
            self._section_manager.clear_drag_preview()

        transition = self._geometry_service.apply_closure_transition(
            old_sections=old_sections,
            updated_sections=updated_sections,
            changed_indices=changed_indices,
        )
        self._commit_section_edit(
            before=old_sections,
            after=transition.sections,
            changed_indices=transition.changed_indices,
        )
        if transition.closed_loop_transition and self._apply_preview_to_sgfile is not None:
            self._apply_preview_to_sgfile()
        if transition.status_message is not None:
            self._show_status(transition.status_message)

    def _apply_section_updates(
        self,
        sections: list["SectionPreview"],
        changed_indices: list[int] | None = None,
    ) -> None:
        self._geometry_service.validate_sections(sections)
        if self._drag_state_active:
            self._update_drag_preview(sections)
        else:
            self._commit_section_edit(
                before=list(self._section_manager.sections),
                after=sections,
                changed_indices=changed_indices,
            )

    def _commit_section_edit(
        self,
        *,
        before: list["SectionPreview"],
        after: list["SectionPreview"],
        changed_indices: list[int] | None = None,
    ) -> None:
        command = ReplaceSectionsCommand(before=before, after=after)
        updated_sections = self._edit_manager.execute(command)
        self._set_sections(updated_sections, changed_indices=changed_indices)

    def undo(self) -> bool:
        """Undo the most recent committed section edit."""
        sections = self._edit_manager.undo()
        if sections is None:
            return False
        self._set_sections(sections)
        return True

    def redo(self) -> bool:
        """Redo the most recent undone section edit."""
        sections = self._edit_manager.redo()
        if sections is None:
            return False
        self._set_sections(sections)
        return True
