from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING, Callable

from PyQt5 import QtCore, QtGui

from sg_viewer.geometry.curve_solver import _project_point_along_heading
from sg_viewer.geometry.connect_curve_to_straight import (
    solve_curve_end_to_straight_start,
)
from sg_viewer.geometry.dlong import set_start_finish
from sg_viewer.geometry.sg_geometry import (
    assert_section_geometry_consistent,
    rebuild_centerline_from_sections,
    update_section_geometry,
)
from sg_viewer.models.preview_state_utils import is_disconnected_endpoint
from sg_viewer.preview.connection_detection import find_unconnected_node_target
from sg_viewer.preview.context import PreviewContext
from sg_viewer.preview.geometry import distance_to_polyline, solve_curve_drag

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
        set_sections: Callable[[list["SectionPreview"], float | None], None],
        rebuild_after_start_finish: Callable[[list["SectionPreview"]], None],
        node_radius_px: int,
        stop_panning: Callable[[], None],
        show_status: Callable[[str], None],
    ) -> None:
        self._context = context
        self._selection = selection
        self._section_manager = section_manager
        self._editor = editor
        self._set_sections = set_sections
        self._rebuild_after_start_finish = rebuild_after_start_finish
        self._node_radius_px = node_radius_px
        self._stop_panning = stop_panning
        self._show_status = show_status

        self._is_dragging_node = False
        self._active_node: tuple[int, str] | None = None
        self._connection_target: tuple[int, str] | None = None
        self._is_dragging_section = False
        self._active_section_index: int | None = None
        self._section_drag_origin: Point | None = None
        self._section_drag_start_end: tuple[Point, Point] | None = None
        self._section_drag_center: Point | None = None
        self._active_chain_indices: list[int] | None = None
        self._chain_drag_origins: dict[int, tuple[Point, Point, Point | None]] | None = None
        self._set_start_finish_mode = False

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

    def reset(self) -> None:
        self._is_dragging_node = False
        self._active_node = None
        self._connection_target = None
        self._is_dragging_section = False
        self._active_section_index = None
        self._section_drag_origin = None
        self._section_drag_start_end = None
        self._section_drag_center = None
        self._active_chain_indices = None
        self._chain_drag_origins = None
        self._set_start_finish_mode = False

    def set_set_start_finish_mode(self, active: bool) -> None:
        self._set_start_finish_mode = active

    # ------------------------------------------------------------------
    # Mouse interaction entry points
    # ------------------------------------------------------------------
    def handle_mouse_press(self, event: QtGui.QMouseEvent) -> bool:
        if event.button() != QtCore.Qt.LeftButton:
            return False

        selected_section = self._selection.selected_section_index
        hit = self._hit_test_node(event.pos(), selected_section)
        if hit is not None:
            if selected_section is None or selected_section != hit[0]:
                return False

            if self._start_node_interaction(hit, event.pos()):
                event.accept()
                return True
            return False

        drag_origin = self._hit_test_selected_section_line(event.pos())
        if drag_origin is not None:
            self._start_section_drag(drag_origin)
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
                        old_sections = list(self._section_manager.sections)
                        sections = list(self._section_manager.sections)

                        # Update connectivity
                        new_curve = replace(
                            new_curve,
                            next_id=target_idx,
                        )

                        new_straight = replace(
                            new_straight,
                            previous_id=dragged_idx,
                        )

                        sections[dragged_idx] = new_curve
                        sections[target_idx] = new_straight

                        self._set_sections(sections)


                        sections = self._section_manager.sections

                        old_closed = is_closed_loop(old_sections)
                        new_closed = is_closed_loop(sections)

                        if DEBUG_LOOP_DETECTION:
                            print("=== LOOP DETECTION CHECK ===")
                            print(f"Old closed: {old_closed}")
                            print(f"New closed: {new_closed}")
                            print(f"Sections: {len(sections)}")
                            for i, s in enumerate(sections):
                                print(
                                    f"  [{i}] prev={s.previous_id} next={s.next_id}"
                                )

                        if not old_closed and new_closed:

                            sections = canonicalize_closed_loop(
                                sections,
                                start_idx=dragged_idx,
                            )

                            self._set_sections(sections)

                            self._show_status("Closed loop detected — track direction fixed")

                        if DEBUG_LOOP_DETECTION and not new_closed:
                            disconnected = []
                            for i, s in enumerate(sections):
                                if s.previous_id is None or s.next_id is None:
                                    disconnected.append(i)

                            if disconnected:
                                print("Not closed — disconnected sections:", disconnected)



                        self._show_status("Curve → straight connected")
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
        self, node: tuple[int, str], pos: QtCore.QPoint
    ) -> bool:
        sect_index, endtype = node
        sections = self._section_manager.sections
        if sect_index < 0 or sect_index >= len(sections):
            return False

        sect = sections[sect_index]
        if self._editor.can_drag_node(self._section_manager.sections, sect, endtype):
            self._start_node_drag(node, pos)
            return True

        updated_sections = self._editor.disconnect_neighboring_section(
            list(sections), sect_index, endtype
        )
        self._apply_section_updates(updated_sections)
        return True

    def _start_node_drag(self, node: tuple[int, str], pos: QtCore.QPoint) -> None:
        widget_size = self._context.widget_size()
        transform = self._context.current_transform(widget_size)
        track_point = self._context.map_to_track(
            (pos.x(), pos.y()), widget_size, self._context.widget_height(), transform
        )
        if track_point is None:
            return
        self._active_node = node
        self._is_dragging_node = True
        self._connection_target = None
        self._stop_panning()
        self._update_dragged_section(track_point)

    def _update_dragged_section(self, track_point: Point) -> None:
        sections = self._section_manager.sections
        if self._active_node is None or not sections:
            return

        sect_index, endtype = self._active_node
        if sect_index < 0 or sect_index >= len(sections):
            return

        sect = sections[sect_index]
        if not self._editor.can_drag_node(self._section_manager.sections, sect, endtype):
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
                    constrained_start = self._project_point_along_heading(
                        end, sect.end_heading, track_point
                    )
                    start = constrained_start or track_point
                else:
                    start = track_point
            else:
                if disconnected_end and not disconnected_start:
                    constrained_end = self._project_point_along_heading(
                        start, sect.start_heading, track_point
                    )
                    end = constrained_end or track_point
                else:
                    end = track_point

        if sect.type_name == "curve":
            updated_section = solve_curve_drag(sect, start, end)
        else:
            length = math.hypot(end[0] - start[0], end[1] - start[1])
            updated_section = replace(sect, start=start, end=end, length=length)

        if updated_section is None:
            return

        sections = list(sections)
        sections[sect_index] = updated_section
        sections[sect_index] = update_section_geometry(sections[sect_index])
        self._apply_section_updates(sections)

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
        self._clear_drag_state()

    def _clear_drag_state(self) -> None:
        self._is_dragging_node = False
        self._active_node = None
        self._connection_target = None

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

        self._apply_section_updates(sections)

    # ------------------------------------------------------------------
    # Section dragging
    # ------------------------------------------------------------------
    def _start_section_drag(self, track_point: Point) -> None:
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

        self._active_section_index = index
        self._active_chain_indices = chain_indices
        self._section_drag_origin = track_point
        self._section_drag_start_end = (sect.start, sect.end)
        self._section_drag_center = sect.center
        self._chain_drag_origins = {
            i: (
                self._section_manager.sections[i].start,
                self._section_manager.sections[i].end,
                self._section_manager.sections[i].center,
            )
            for i in chain_indices
        }
        self._is_dragging_section = True
        self._stop_panning()

    def _update_section_drag_position(self, pos: QtCore.QPoint) -> None:
        widget_size = self._context.widget_size()
        transform = self._context.current_transform(widget_size)
        track_point = self._context.map_to_track(
            (pos.x(), pos.y()), widget_size, self._context.widget_height(), transform
        )
        if track_point is None:
            return
        self._update_section_drag(track_point)

    def _update_section_drag(self, track_point: Point) -> None:
        if (
            not self._is_dragging_section
            or self._active_section_index is None
            or self._section_drag_origin is None
            or self._active_chain_indices is None
            or self._chain_drag_origins is None
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

        dx = track_point[0] - self._section_drag_origin[0]
        dy = track_point[1] - self._section_drag_origin[1]

        sections = list(sections)

        for chain_index in self._active_chain_indices:
            if chain_index not in self._chain_drag_origins or chain_index < 0 or chain_index >= len(sections):
                continue

            start, end, center = self._chain_drag_origins[chain_index]
            translated_start = (start[0] + dx, start[1] + dy)
            translated_end = (end[0] + dx, end[1] + dy)

            translated_center = None
            if center is not None:
                cx, cy = center
                translated_center = (cx + dx, cy + dy)

            updated_section = replace(
                sections[chain_index],
                start=translated_start,
                end=translated_end,
                center=translated_center if translated_center is not None else sections[chain_index].center,
            )

            sections[chain_index] = update_section_geometry(updated_section)

        self._apply_section_updates(sections)

    def _end_section_drag(self) -> None:
        self._is_dragging_section = False
        self._active_section_index = None
        self._section_drag_origin = None
        self._section_drag_start_end = None
        self._section_drag_center = None
        self._active_chain_indices = None
        self._chain_drag_origins = None

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def _apply_section_updates(self, sections: list["SectionPreview"]) -> None:
        if __debug__:
            for section in sections:
                assert_section_geometry_consistent(section)
        self._set_sections(sections)

    def _project_point_along_heading(
        self, origin: Point, heading: tuple[float, float] | None, target: Point
    ) -> Point | None:
        return _project_point_along_heading(origin, heading, target)
