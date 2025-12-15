from __future__ import annotations

import math
from dataclasses import replace
from typing import TYPE_CHECKING

from PyQt5 import QtCore, QtGui

from sg_viewer.geometry.curve_solver import _project_point_along_heading
from sg_viewer.geometry.sg_geometry import rebuild_centerline_from_sections, update_section_geometry
from sg_viewer.models.preview_state_utils import compute_section_signatures, is_disconnected_endpoint

if TYPE_CHECKING:
    from sg_viewer.ui.preview_widget import SGPreviewWidget
    from sg_viewer.ui.preview_state_controller import PreviewStateController
    from sg_viewer.models.selection import SelectionManager
    from sg_viewer.models.sg_model import SectionPreview


Point = tuple[float, float]


class PreviewInteraction:
    def __init__(
        self,
        widget: "SGPreviewWidget",
        controller: "PreviewStateController",
        selection: "SelectionManager",
    ) -> None:
        self._widget = widget
        self._controller = controller
        self._selection = selection

        self._is_dragging_node = False
        self._active_node: tuple[int, str] | None = None
        self._is_dragging_section = False
        self._active_section_index: int | None = None
        self._section_drag_origin: Point | None = None
        self._section_drag_start_end: tuple[Point, Point] | None = None
        self._section_drag_center: Point | None = None
        self._active_chain_indices: list[int] | None = None
        self._chain_drag_origins: dict[int, tuple[Point, Point, Point | None]] | None = None

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------
    @property
    def is_dragging_node(self) -> bool:
        return self._is_dragging_node

    @property
    def is_dragging_section(self) -> bool:
        return self._is_dragging_section

    def reset(self) -> None:
        self._is_dragging_node = False
        self._active_node = None
        self._is_dragging_section = False
        self._active_section_index = None
        self._section_drag_origin = None
        self._section_drag_start_end = None
        self._section_drag_center = None
        self._active_chain_indices = None
        self._chain_drag_origins = None

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
            self._update_drag_position(event.pos())
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

        if self._is_dragging_node:
            self._end_node_drag()
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
        widget_size = (self._widget.width(), self._widget.height())
        transform = self._controller.current_transform(widget_size)
        if transform is None:
            return None

        scale, offsets = transform
        ox, oy = offsets
        widget_height = self._widget.height()
        radius = self._widget._node_radius_px
        r2 = radius * radius

        def _sorted_indices(total: int, prefer: int | None) -> list[int]:
            indices = list(range(total))
            if prefer is None or prefer < 0 or prefer >= total:
                return indices
            indices.remove(prefer)
            indices.insert(0, prefer)
            return indices

        if not self._widget._sections:
            return None

        for i in _sorted_indices(len(self._widget._sections), preferred_index):
            for endtype in ("start", "end"):
                world_point = (
                    self._widget._sections[i].start
                    if endtype == "start"
                    else self._widget._sections[i].end
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
        if not self._widget._sections or index < 0 or index >= len(self._widget._sections):
            return None

        section = self._widget._sections[index]
        if not self._widget._can_drag_section_polyline(section, index):
            return None

        widget_size = (self._widget.width(), self._widget.height())
        transform = self._controller.current_transform(widget_size)
        if transform is None:
            return None

        track_point = self._controller.map_to_track(
            QtCore.QPointF(pos), widget_size, self._widget.height(), transform
        )
        if track_point is None:
            return None

        scale, _ = transform
        if scale <= 0:
            return None

        tolerance = 6 / scale
        if self._widget._distance_to_polyline(track_point, section.polyline) <= tolerance:
            return track_point
        return None

    # ------------------------------------------------------------------
    # Node dragging / disconnect
    # ------------------------------------------------------------------
    def _start_node_interaction(
        self, node: tuple[int, str], pos: QtCore.QPoint
    ) -> bool:
        sect_index, endtype = node
        if sect_index < 0 or sect_index >= len(self._widget._sections):
            return False

        sect = self._widget._sections[sect_index]
        if self._widget._can_drag_node(sect, endtype):
            self._start_node_drag(node, pos)
            return True

        updated_sections = self._widget._editor.disconnect_neighboring_section(
            list(self._widget._sections), sect_index, endtype
        )
        self._apply_section_updates(updated_sections)
        return True

    def _start_node_drag(self, node: tuple[int, str], pos: QtCore.QPoint) -> None:
        widget_size = (self._widget.width(), self._widget.height())
        transform = self._controller.current_transform(widget_size)
        track_point = self._controller.map_to_track(
            QtCore.QPointF(pos), widget_size, self._widget.height(), transform
        )
        if track_point is None:
            return
        self._active_node = node
        self._is_dragging_node = True
        self._widget._is_panning = False
        self._widget._press_pos = None
        self._widget._last_mouse_pos = None
        self._update_dragged_section(track_point)

    def _update_drag_position(self, pos: QtCore.QPoint) -> None:
        widget_size = (self._widget.width(), self._widget.height())
        transform = self._controller.current_transform(widget_size)
        track_point = self._controller.map_to_track(
            QtCore.QPointF(pos), widget_size, self._widget.height(), transform
        )
        if track_point is None or self._active_node is None:
            return
        self._update_dragged_section(track_point)

    def _update_dragged_section(self, track_point: Point) -> None:
        if self._active_node is None or not self._widget._sections:
            return

        sect_index, endtype = self._active_node
        if sect_index < 0 or sect_index >= len(self._widget._sections):
            return

        sect = self._widget._sections[sect_index]
        if not self._widget._can_drag_node(sect, endtype):
            return

        start = sect.start
        end = sect.end
        disconnected_start = is_disconnected_endpoint(self._widget._sections, sect, "start")
        disconnected_end = is_disconnected_endpoint(self._widget._sections, sect, "end")
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
            updated_section = self._widget._solve_curve_drag(sect, start, end)
        else:
            length = math.hypot(end[0] - start[0], end[1] - start[1])
            updated_section = replace(sect, start=start, end=end, length=length)

        if updated_section is None:
            return

        sections = list(self._widget._sections)
        sections[sect_index] = updated_section
        sections[sect_index] = update_section_geometry(sections[sect_index])
        self._apply_section_updates(sections)

    def _end_node_drag(self) -> None:
        self._is_dragging_node = False
        self._active_node = None

    # ------------------------------------------------------------------
    # Section dragging
    # ------------------------------------------------------------------
    def _start_section_drag(self, track_point: Point) -> None:
        if self._selection.selected_section_index is None:
            return
        index = self._selection.selected_section_index
        if index < 0 or index >= len(self._widget._sections):
            return
        sect = self._widget._sections[index]
        if not self._widget._can_drag_section_polyline(sect, index):
            return

        chain_indices = self._widget._get_drag_chain(index)
        if chain_indices is None:
            return

        self._active_section_index = index
        self._active_chain_indices = chain_indices
        self._section_drag_origin = track_point
        self._section_drag_start_end = (sect.start, sect.end)
        self._section_drag_center = sect.center
        self._chain_drag_origins = {
            i: (self._widget._sections[i].start, self._widget._sections[i].end, self._widget._sections[i].center)
            for i in chain_indices
        }
        self._is_dragging_section = True
        self._widget._is_panning = False
        self._widget._press_pos = None
        self._widget._last_mouse_pos = None

    def _update_section_drag_position(self, pos: QtCore.QPoint) -> None:
        widget_size = (self._widget.width(), self._widget.height())
        transform = self._controller.current_transform(widget_size)
        track_point = self._controller.map_to_track(
            QtCore.QPointF(pos), widget_size, self._widget.height(), transform
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
        if index < 0 or index >= len(self._widget._sections):
            return
        sect = self._widget._sections[index]
        if not self._widget._can_drag_section_polyline(sect, index):
            return

        dx = track_point[0] - self._section_drag_origin[0]
        dy = track_point[1] - self._section_drag_origin[1]

        sections = list(self._widget._sections)

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
        self._widget._sections = sections
        self._widget._section_endpoints = [(s.start, s.end) for s in sections]
        self._widget._section_signatures = compute_section_signatures(sections)

        points, dlongs, bounds, index = rebuild_centerline_from_sections(self._widget._sections)
        self._widget._centerline_polylines = [s.polyline for s in self._widget._sections]
        self._widget._sampled_centerline = points
        self._widget._sampled_dlongs = dlongs
        self._widget._sampled_bounds = bounds
        self._widget._centerline_index = index

        self._widget._selection.update_context(
            self._widget._sections,
            self._widget._track_length,
            self._widget._centerline_index,
            self._widget._sampled_dlongs,
        )
        self._widget._update_node_status()
        self._widget.update()

    def _project_point_along_heading(
        self, origin: Point, heading: tuple[float, float] | None, target: Point
    ) -> Point | None:
        return _project_point_along_heading(origin, heading, target)
