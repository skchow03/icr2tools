from __future__ import annotations

import math
import copy
from dataclasses import replace
from typing import TYPE_CHECKING, Callable

from PyQt5 import QtCore, QtGui

from sg_viewer.geometry.connect_curve_to_straight import (
    solve_curve_end_to_straight_start,
    solve_straight_end_to_curve_endpoint,
)
from sg_viewer.geometry.dlong import set_start_finish
from sg_viewer.geometry.picking import project_point_to_segment
from sg_viewer.geometry.sg_geometry import (
    assert_section_geometry_consistent,
    rebuild_centerline_from_sections,
    update_section_geometry,
)
from sg_viewer.models.preview_state_utils import is_disconnected_endpoint, is_invalid_id
from sg_viewer.preview.connection_detection import find_unconnected_node_target
from sg_viewer.preview.context import PreviewContext
from sg_viewer.preview.preview_mutations import (
    distance_to_polyline,
    project_point_along_heading,
    solve_curve_drag,
    translate_section,
    update_straight_endpoints,
)

from sg_viewer.geometry.topology import is_closed_loop
from sg_viewer.geometry.canonicalize import canonicalize_closed_loop


if TYPE_CHECKING:
    from sg_viewer.models.selection import SelectionManager
    from sg_viewer.models.sg_model import SectionPreview
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

        self._is_dragging_node = False
        self._active_node: tuple[int, str] | None = None
        self._connection_target: tuple[int, str] | None = None
        self._is_dragging_section = False
        self._active_section_index: int | None = None
        self._section_drag_start_mouse_screen: QtCore.QPointF | None = None
        self._section_drag_start_sections: list["SectionPreview"] | None = None
        self._active_chain_indices: list[int] | None = None
        self._set_start_finish_mode = False
        self._drag_state_active = False

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
        self._active_chain_indices = None
        self._set_start_finish_mode = False
        self._set_drag_state(False)
        self._context.end_drag_transform()

    def set_set_start_finish_mode(self, active: bool) -> None:
        self._set_start_finish_mode = active

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
        if drag_origin is not None:
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
                section_idx, endtype = hit
                sections = self._section_manager.sections
                if not is_closed_loop(sections):
                    self._show_status("Track must be closed to set start/finish")
                    self._set_start_finish_mode = False
                    return True

                if endtype == "end":
                    start_idx = sections[section_idx].next_id
                else:
                    start_idx = section_idx

                try:
                    sections = set_start_finish(sections, start_idx)
                except ValueError:
                    self._show_status("Track must be closed to set start/finish")
                    self._set_start_finish_mode = False
                    return True
                except RuntimeError:
                    self._show_status("Invalid loop topology; cannot set start/finish")
                    self._set_start_finish_mode = False
                    return True

                self._rebuild_after_start_finish(sections)
                self._show_status("Start/finish set to selected section (now section 0)")
                self._set_start_finish_mode = False
                return True

        if self._is_dragging_node:
            if self._connection_target is not None:
                if self._active_node is not None:
                    dragged_idx, dragged_end = self._active_node
                    target_idx, target_end = self._connection_target

                    dragged_section = self._section_manager.sections[dragged_idx]
                    target_section = self._section_manager.sections[target_idx]

                    if (
                        dragged_section.type_name == "curve"
                        and dragged_end == "end"
                        and target_section.type_name == "straight"
                        and target_end == "start"
                    ):
                        result = solve_curve_end_to_straight_start(
                            dragged_section,
                            target_section,
                        )

                        if result is None:
                            self._show_status("Curve → straight connection failed")
                            self._clear_drag_state()
                            return True

                        new_curve, new_straight = result
                        if self._sync_fsects_on_connection is not None:
                            self._sync_fsects_on_connection(
                                (dragged_idx, dragged_end),
                                (target_idx, target_end),
                            )
                        self._apply_curve_straight_connection(
                            curve_idx=dragged_idx,
                            curve_end=dragged_end,
                            straight_idx=target_idx,
                            straight_end=target_end,
                            curve=new_curve,
                            straight=new_straight,
                        )

                        self._show_status("Curve → straight connected")
                        self._clear_drag_state()
                        return True

                    if (
                        dragged_section.type_name == "straight"
                        and target_section.type_name == "curve"
                    ):
                        result = solve_straight_end_to_curve_endpoint(
                            dragged_section,
                            dragged_end,
                            target_section,
                            target_end,
                        )

                        if result is None:
                            self._show_status("Straight → curve connection failed")
                            self._clear_drag_state()
                            return True

                        new_straight, new_curve = result
                        if self._sync_fsects_on_connection is not None:
                            self._sync_fsects_on_connection(
                                (dragged_idx, dragged_end),
                                (target_idx, target_end),
                            )

                        self._apply_curve_straight_connection(
                            curve_idx=target_idx,
                            curve_end=target_end,
                            straight_idx=dragged_idx,
                            straight_end=dragged_end,
                            curve=new_curve,
                            straight=new_straight,
                        )

                        self._show_status("Straight → curve connected")
                        self._clear_drag_state()
                        return True

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

        if self._can_start_shared_straight_drag(node):
            self._start_node_drag(node, pos)
            return True

        if self._can_start_shared_curve_drag(node):
            self._start_node_drag(node, pos)
            return True

        if allow_disconnect:
            self._disconnect_node(node)
            return True

        return False

    def _disconnect_node(self, node: tuple[int, str]) -> None:
        sect_index, endtype = node
        sections = self._section_manager.sections
        updated_sections = self._editor.disconnect_neighboring_section(
            list(sections), sect_index, endtype
        )
        self._apply_section_updates(updated_sections)

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
        self._is_dragging_node = True
        self._set_drag_state(True)
        self._connection_target = None
        self._stop_panning()
        self._update_dragged_section(track_point)

    def _update_dragged_section(self, track_point: Point) -> None:
        sections = self._section_manager.sections
        if self._active_node is None or not sections:
            return

        if self._apply_constrained_shared_straight_drag(self._active_node, track_point):
            return

        if self._apply_constrained_shared_curve_drag(self._active_node, track_point):
            return

        sect_index, endtype = self._active_node
        if sect_index < 0 or sect_index >= len(sections):
            return

        sect = sections[sect_index]
        if not self._editor.can_drag_node(self._section_manager.sections, sect, endtype):
            return

        if self._apply_shared_node_drag_constraint(sections, sect_index, endtype, track_point):
            return

        start = sect.start
        end = sect.end
        disconnected_start = is_disconnected_endpoint(sections, sect, "start")
        disconnected_end = is_disconnected_endpoint(sections, sect, "end")
        if sect.type_name == "curve":
            if endtype == "start":
                start = track_point
            else:
                end = track_point
        else:
            if endtype == "start":
                if disconnected_start and not disconnected_end:
                    constrained_start = project_point_along_heading(
                        end, sect.end_heading, track_point
                    )
                    start = constrained_start or track_point
                else:
                    start = track_point
            else:
                if disconnected_end and not disconnected_start:
                    constrained_end = project_point_along_heading(
                        start, sect.start_heading, track_point
                    )
                    end = constrained_end or track_point
                else:
                    end = track_point

        if sect.type_name == "curve":
            updated_section = solve_curve_drag(sect, start, end)
        else:
            updated_section = update_straight_endpoints(sect, start, end)

        if updated_section is None:
            return

        sections = list(sections)
        sections[sect_index] = updated_section
        sections[sect_index] = update_section_geometry(sections[sect_index])
        self._apply_section_updates(sections, changed_indices=[sect_index])

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
        self._context.request_repaint()

    def _end_node_drag(self) -> None:
        if self._drag_state_active:
            self._set_sections(list(self._section_manager.sections))
        self._clear_drag_state()

    def _clear_drag_state(self) -> None:
        self._is_dragging_node = False
        self._active_node = None
        self._connection_target = None
        self._set_drag_state(False)
        self._context.end_drag_transform()

    def _connect_nodes(
        self, source: tuple[int, str], target: tuple[int, str]
    ) -> None:
        sections = list(self._section_manager.sections)

        if not sections:
            return

        src_index, src_end = source
        tgt_index, tgt_end = target

        if src_index == tgt_index:
            return

        if src_index < 0 or src_index >= len(sections):
            return
        if tgt_index < 0 or tgt_index >= len(sections):
            return

        src_section = sections[src_index]
        tgt_section = sections[tgt_index]

        if not is_disconnected_endpoint(sections, src_section, src_end):
            return
        if not is_disconnected_endpoint(sections, tgt_section, tgt_end):
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

        if self._sync_fsects_on_connection is not None:
            self._sync_fsects_on_connection(source, target)

        self._apply_section_updates(sections, changed_indices=[src_index, tgt_index])

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
            sections[chain_index] = update_section_geometry(updated_section)
            applied_dx = updated_section.start[0] - original_sections[chain_index].start[0]
            applied_dy = updated_section.start[1] - original_sections[chain_index].start[1]
            assert abs(applied_dx - dx) < epsilon and abs(applied_dy - dy) < epsilon

        self._apply_section_updates(sections, changed_indices=self._active_chain_indices)

    def _end_section_drag(self) -> None:
        if self._drag_state_active:
            self._set_sections(list(self._section_manager.sections))
        self._is_dragging_section = False
        self._active_section_index = None
        self._section_drag_start_mouse_screen = None
        self._section_drag_start_sections = None
        self._active_chain_indices = None
        self._set_drag_state(False)
        self._context.end_drag_transform()

    def _set_drag_state(self, active: bool) -> None:
        if self._drag_state_active == active:
            return
        self._drag_state_active = active
        if self._emit_drag_state_changed is not None:
            self._emit_drag_state_changed(active)

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def _apply_curve_straight_connection(
        self,
        *,
        curve_idx: int,
        curve_end: str,
        straight_idx: int,
        straight_end: str,
        curve: "SectionPreview",
        straight: "SectionPreview",
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
            old_sections,
            sections,
            start_idx=curve_idx,
            changed_indices=[curve_idx, straight_idx],
        )

    def _finalize_connection_updates(
        self,
        old_sections: list["SectionPreview"],
        updated_sections: list["SectionPreview"],
        *,
        start_idx: int,
        changed_indices: list[int],
    ) -> None:
        old_closed = is_closed_loop(old_sections)
        new_closed = is_closed_loop(updated_sections)

        sections = updated_sections

        if DEBUG_LOOP_DETECTION:
            print("=== LOOP DETECTION CHECK ===")
            print(f"Old closed: {old_closed}")
            print(f"New closed: {new_closed}")
            print(f"Sections: {len(sections)}")
            for i, s in enumerate(sections):
                print(f"  [{i}] prev={s.previous_id} next={s.next_id}")

        if not old_closed and new_closed:
            # Preserve Section 0 as the canonical start so the start/finish marker
            # always remains anchored to the beginning of the first section.
            canonical_start_idx = 0
            sections = canonicalize_closed_loop(
                sections,
                start_idx=canonical_start_idx,
            )

            self._set_sections(sections, changed_indices=changed_indices)

            self._show_status("Closed loop detected — track direction fixed")
        else:
            self._set_sections(sections, changed_indices=changed_indices)

        sections = self._section_manager.sections

        if DEBUG_LOOP_DETECTION and not new_closed:
            disconnected = []
            for i, s in enumerate(sections):
                if s.previous_id is None or s.next_id is None:
                    disconnected.append(i)

            if disconnected:
                print("Not closed — disconnected sections:", disconnected)

    def _apply_section_updates(
        self,
        sections: list["SectionPreview"],
        changed_indices: list[int] | None = None,
    ) -> None:
        if __debug__:
            for section in sections:
                assert_section_geometry_consistent(section)
        if self._drag_state_active:
            self._update_drag_preview(sections)
        else:
            self._set_sections(sections, changed_indices=changed_indices)

    def _shared_straight_pair(
        self, dragged_key: tuple[int, str]
    ) -> tuple[int, int, "SectionPreview", "SectionPreview"] | None:
        section_index, end_type = dragged_key
        sections = self._section_manager.sections

        if section_index < 0 or section_index >= len(sections):
            return None

        if end_type == "end":
            s1_idx = section_index
            s2_idx = sections[s1_idx].next_id
        elif end_type == "start":
            s2_idx = section_index
            s1_idx = sections[s2_idx].previous_id
        else:
            return None

        if is_invalid_id(sections, s1_idx) or is_invalid_id(sections, s2_idx):
            return None

        s1 = sections[s1_idx]
        s2 = sections[s2_idx]

        if s1.type_name != "straight" or s2.type_name != "straight":
            return None

        if s1.end != s2.start:
            return None

        return s1_idx, s2_idx, s1, s2

    def _shared_curve_pair(
        self, dragged_key: tuple[int, str]
    ) -> tuple[int, int, "SectionPreview", "SectionPreview", Point, float, float] | None:
        section_index, end_type = dragged_key
        sections = self._section_manager.sections

        if section_index < 0 or section_index >= len(sections):
            return None

        if end_type == "end":
            s1_idx = section_index
            s2_idx = sections[s1_idx].next_id
        elif end_type == "start":
            s2_idx = section_index
            s1_idx = sections[s2_idx].previous_id
        else:
            return None

        if is_invalid_id(sections, s1_idx) or is_invalid_id(sections, s2_idx):
            return None

        s1 = sections[s1_idx]
        s2 = sections[s2_idx]

        if s1.type_name != "curve" or s2.type_name != "curve":
            return None

        if not self._points_close(s1.end, s2.start):
            return None

        if s1.center is None or s2.center is None:
            return None

        if not self._points_close(s1.center, s2.center):
            return None

        if s1.radius is None or s2.radius is None:
            return None

        radius = abs(s1.radius)
        if radius <= 0:
            return None

        if abs(abs(s1.radius) - abs(s2.radius)) > 1e-6:
            return None

        orientation_1 = self._curve_orientation(s1)
        orientation_2 = self._curve_orientation(s2)
        if orientation_1 is None or orientation_2 is None:
            return None

        if orientation_1 * orientation_2 < 0:
            return None

        return s1_idx, s2_idx, s1, s2, s1.center, radius, orientation_1

    def _can_start_shared_straight_drag(self, node: tuple[int, str]) -> bool:
        shared_pair = self._shared_straight_pair(node)
        if shared_pair is None:
            return False

        sect_index, _ = node
        sections = self._section_manager.sections

        if sect_index < 0 or sect_index >= len(sections):
            return False

        selected_section = sections[sect_index]
        return selected_section.type_name == "straight"

    def _apply_constrained_shared_straight_drag(
        self, dragged_key: tuple[int, str], track_point: Point
    ) -> bool:
        shared_pair = self._shared_straight_pair(dragged_key)
        if shared_pair is None:
            return False

        s1_idx, s2_idx, s1, s2 = shared_pair
        sections = self._section_manager.sections

        A = s1.start
        C = s2.end

        P = project_point_to_segment(track_point, A, C)
        if P is None:
            return False

        MIN_LEN = 50.0
        total_len = math.hypot(C[0] - A[0], C[1] - A[1])
        if total_len <= 0:
            return False

        t = math.hypot(P[0] - A[0], P[1] - A[1]) / total_len
        min_t = MIN_LEN / total_len
        t = max(min_t, min(1.0 - min_t, t))

        Px = A[0] + t * (C[0] - A[0])
        Py = A[1] + t * (C[1] - A[1])
        P = (Px, Py)

        s1_length = math.hypot(P[0] - A[0], P[1] - A[1])
        s2_length = math.hypot(C[0] - P[0], C[1] - P[1])

        s1_new = replace(s1, end=P, length=s1_length)
        s2_new = replace(s2, start=P, length=s2_length)

        s1_new = update_section_geometry(s1_new)
        s2_new = update_section_geometry(s2_new)

        sections = list(sections)
        sections[s1_idx] = s1_new
        sections[s2_idx] = s2_new

        self._apply_section_updates(sections)
        self._context.request_repaint()
        return True

    def _can_start_shared_curve_drag(self, node: tuple[int, str]) -> bool:
        shared_pair = self._shared_curve_pair(node)
        if shared_pair is None:
            return False

        sect_index, _ = node
        sections = self._section_manager.sections

        if sect_index < 0 or sect_index >= len(sections):
            return False

        selected_section = sections[sect_index]
        return selected_section.type_name == "curve"

    def _apply_constrained_shared_curve_drag(
        self, dragged_key: tuple[int, str], track_point: Point
    ) -> bool:
        shared_pair = self._shared_curve_pair(dragged_key)
        if shared_pair is None:
            return False

        s1_idx, s2_idx, s1, s2, center, radius, orientation = shared_pair
        cx, cy = center

        start_vec = (s1.start[0] - cx, s1.start[1] - cy)
        end_vec = (s2.end[0] - cx, s2.end[1] - cy)

        start_angle = math.atan2(start_vec[1], start_vec[0])
        end_angle = math.atan2(end_vec[1], end_vec[0])
        total_span = self._directed_angle(start_angle, end_angle, orientation)
        if abs(total_span) <= 1e-9:
            return False

        target_vec = (track_point[0] - cx, track_point[1] - cy)
        target_mag = math.hypot(*target_vec)
        if target_mag <= 0:
            return False

        target_unit = (target_vec[0] / target_mag, target_vec[1] / target_mag)
        target_on_circle = (cx + target_unit[0] * radius, cy + target_unit[1] * radius)
        target_angle = math.atan2(target_on_circle[1] - cy, target_on_circle[0] - cx)
        target_span = self._directed_angle(start_angle, target_angle, orientation)

        fraction = target_span / total_span

        MIN_FRACTION = 0.02
        fraction = max(MIN_FRACTION, min(1.0 - MIN_FRACTION, fraction))
        constrained_span = total_span * fraction
        constrained_angle = start_angle + constrained_span
        constrained_point = (
            cx + math.cos(constrained_angle) * radius,
            cy + math.sin(constrained_angle) * radius,
        )

        s1_length = abs(constrained_span) * radius
        s2_length = abs(total_span - constrained_span) * radius

        def _tangent(vec: Point) -> tuple[float, float] | None:
            return self._curve_tangent(vec, orientation)

        start_heading = s1.start_heading or _tangent(start_vec)
        end_heading = s2.end_heading or _tangent(end_vec)
        shared_heading = _tangent((constrained_point[0] - cx, constrained_point[1] - cy))
        if shared_heading is None:
            return False

        updated_sections = list(self._section_manager.sections)

        updated_section_1 = replace(
            s1,
            end=constrained_point,
            length=s1_length,
            start_heading=start_heading,
            sang1=start_heading[0] if start_heading else None,
            sang2=start_heading[1] if start_heading else None,
            end_heading=shared_heading,
            eang1=shared_heading[0],
            eang2=shared_heading[1],
            center=center,
        )
        updated_section_2 = replace(
            s2,
            start=constrained_point,
            length=s2_length,
            start_heading=shared_heading,
            sang1=shared_heading[0],
            sang2=shared_heading[1],
            end_heading=end_heading,
            eang1=end_heading[0] if end_heading else None,
            eang2=end_heading[1] if end_heading else None,
            center=center,
        )

        updated_sections[s1_idx] = update_section_geometry(updated_section_1)
        updated_sections[s2_idx] = update_section_geometry(updated_section_2)

        self._apply_section_updates(updated_sections)
        self._context.request_repaint()
        return True

    def _apply_shared_node_drag_constraint(
        self,
        sections: list["SectionPreview"],
        sect_index: int,
        endtype: str,
        track_point: Point,
    ) -> bool:
        section_1_index: int | None
        section_2_index: int | None
        section_1: "SectionPreview" | None
        section_2: "SectionPreview" | None

        if endtype == "end":
            section_1_index = sect_index
            section_1 = sections[sect_index]
            next_idx = section_1.next_id
            section_2_index = None if is_invalid_id(sections, next_idx) else next_idx
            section_2 = None if section_2_index is None else sections[section_2_index]
        elif endtype == "start":
            section_2_index = sect_index
            section_2 = sections[sect_index]
            prev_idx = section_2.previous_id
            section_1_index = None if is_invalid_id(sections, prev_idx) else prev_idx
            section_1 = None if section_1_index is None else sections[section_1_index]
        else:
            return False

        if (
            section_1 is None
            or section_2 is None
            or section_1.type_name != "straight"
            or section_2.type_name != "straight"
        ):
            return False

        if section_1.end != section_2.start:
            return False

        def heading(a: Point, b: Point) -> tuple[float, float] | None:
            dx = b[0] - a[0]
            dy = b[1] - a[1]
            length = math.hypot(dx, dy)
            if length <= 0:
                return None
            return (dx / length, dy / length)

        heading_1 = heading(section_1.start, section_1.end)
        heading_2 = heading(section_2.start, section_2.end)
        if heading_1 is None or heading_2 is None:
            return False

        dot = heading_1[0] * heading_2[0] + heading_1[1] * heading_2[1]
        if dot < math.cos(math.radians(0.1)):
            return False

        ax, ay = section_1.start
        cx, cy = section_2.end
        vx = cx - ax
        vy = cy - ay
        length_sq = vx * vx + vy * vy
        if length_sq <= 0:
            return False

        px, py = track_point
        t = ((px - ax) * vx + (py - ay) * vy) / length_sq

        total_len = math.sqrt(length_sq)
        MIN_LEN = 50.0
        min_t = MIN_LEN / total_len
        t = max(min_t, min(1.0 - min_t, t))

        bx = ax + t * vx
        by = ay + t * vy
        constrained_point = (bx, by)

        updated_sections = list(sections)
        updated_section_1 = replace(section_1, end=constrained_point)
        updated_section_2 = replace(section_2, start=constrained_point)

        updated_sections[section_1_index] = update_section_geometry(updated_section_1)
        updated_sections[section_2_index] = update_section_geometry(updated_section_2)

        self._apply_section_updates(updated_sections)
        self._context.request_repaint()
        return True

    def _points_close(self, a: Point, b: Point, tol: float = 1e-6) -> bool:
        return math.hypot(a[0] - b[0], a[1] - b[1]) <= tol

    def _curve_orientation(self, section: "SectionPreview") -> float | None:
        if section.center is None:
            return None

        start_vec = (section.start[0] - section.center[0], section.start[1] - section.center[1])
        radius = math.hypot(*start_vec)
        if radius <= 0:
            return None

        heading = section.start_heading or section.end_heading
        if heading is not None:
            hx, hy = heading
            mag = math.hypot(hx, hy)
            if mag > 0:
                hx /= mag
                hy /= mag
                ccw_tangent = (-start_vec[1] / radius, start_vec[0] / radius)
                cw_tangent = (start_vec[1] / radius, -start_vec[0] / radius)
                ccw_dot = ccw_tangent[0] * hx + ccw_tangent[1] * hy
                cw_dot = cw_tangent[0] * hx + cw_tangent[1] * hy
                if abs(ccw_dot - cw_dot) > 1e-9:
                    return 1.0 if ccw_dot > cw_dot else -1.0

        if section.radius is not None and section.radius < 0:
            return -1.0

        end_vec = (section.end[0] - section.center[0], section.end[1] - section.center[1])
        cross = start_vec[0] * end_vec[1] - start_vec[1] * end_vec[0]
        if abs(cross) > 1e-9:
            return 1.0 if cross > 0 else -1.0

        return 1.0

    def _directed_angle(self, start_angle: float, end_angle: float, orientation: float) -> float:
        angle = end_angle - start_angle
        if orientation > 0:
            while angle <= 0:
                angle += 2 * math.pi
        else:
            while angle >= 0:
                angle -= 2 * math.pi
        return angle

    def _curve_tangent(self, vec: Point, orientation: float) -> tuple[float, float] | None:
        vx, vy = vec
        mag = math.hypot(vx, vy)
        if mag <= 0:
            return None
        return (-orientation * vy / mag, orientation * vx / mag)
