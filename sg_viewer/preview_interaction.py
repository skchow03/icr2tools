from __future__ import annotations

import math
import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from PyQt5 import QtCore, QtGui

from sg_viewer.curve_solver import (
    _project_point_along_heading,
    solve_curve_with_heading_constraint,
)
from sg_viewer.sg_geometry import rebuild_centerline_from_sections, update_section_geometry

if TYPE_CHECKING:
    from sg_viewer.preview_widget import SGPreviewWidget
    from sg_viewer.preview_state_controller import PreviewStateController
    from sg_viewer.selection import SelectionManager
    from sg_viewer.sg_model import SectionPreview


Point = tuple[float, float]


logger = logging.getLogger(__name__)


class PreviewInteraction:
    SNAP_HEADING_DISTANCE_TOLERANCE = 150.0

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

    def find_node_at_position(
        self, pos: QtCore.QPoint, preferred_index: int | None
    ) -> tuple[int, str] | None:
        """Public wrapper around _hit_test_node for external interaction logic."""

        return self._hit_test_node(pos, preferred_index)

    def _hit_test_selected_section_line(self, pos: QtCore.QPoint) -> Point | None:
        if self._selection.selected_section_index is None:
            return None

        index = self._selection.selected_section_index
        if not self._widget._sections or index < 0 or index >= len(self._widget._sections):
            return None

        section = self._widget._sections[index]
        if not self._widget._can_drag_section_polyline(section):
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

        if endtype == "start":
            prev_id = sect.previous_id
            sect = replace(sect, previous_id=-1)
            self._widget._sections[sect_index] = sect

            if 0 <= prev_id < len(self._widget._sections):
                prev_sect = self._widget._sections[prev_id]
                prev_sect = replace(prev_sect, next_id=-1)
                self._widget._sections[prev_id] = prev_sect
        else:
            next_id = sect.next_id
            sect = replace(sect, next_id=-1)
            self._widget._sections[sect_index] = sect

            if 0 <= next_id < len(self._widget._sections):
                next_sect = self._widget._sections[next_id]
                next_sect = replace(next_sect, previous_id=-1)
                self._widget._sections[next_id] = next_sect

        self._apply_section_updates(list(self._widget._sections))
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
        disconnected_start = self._widget._is_disconnected_endpoint(sect, "start")
        disconnected_end = self._widget._is_disconnected_endpoint(sect, "end")
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
        self._attempt_curve_to_straight_snap()
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
        if not self._widget._can_drag_section_polyline(sect):
            return

        self._active_section_index = index
        self._section_drag_origin = track_point
        self._section_drag_start_end = (sect.start, sect.end)
        self._section_drag_center = sect.center
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
            or self._section_drag_start_end is None
        ):
            return

        index = self._active_section_index
        if index < 0 or index >= len(self._widget._sections):
            return
        sect = self._widget._sections[index]
        if not self._widget._can_drag_section_polyline(sect):
            return

        dx = track_point[0] - self._section_drag_origin[0]
        dy = track_point[1] - self._section_drag_origin[1]
        start, end = self._section_drag_start_end

        translated_start = (start[0] + dx, start[1] + dy)
        translated_end = (end[0] + dx, end[1] + dy)

        translated_center = None
        if self._section_drag_center is not None:
            cx, cy = self._section_drag_center
            translated_center = (cx + dx, cy + dy)

        updated_section = replace(
            sect,
            start=translated_start,
            end=translated_end,
            center=translated_center if translated_center is not None else sect.center,
        )

        sections = list(self._widget._sections)
        sections[index] = update_section_geometry(updated_section)
        self._apply_section_updates(sections)

    def _end_section_drag(self) -> None:
        self._is_dragging_section = False
        self._active_section_index = None
        self._section_drag_origin = None
        self._section_drag_start_end = None
        self._section_drag_center = None

    # ------------------------------------------------------------------
    # Utilities
    # ------------------------------------------------------------------
    def _attempt_curve_to_straight_snap(self) -> None:
        if self._active_node is None:
            return

        sections = self._widget._sections
        if not sections:
            return

        sect_index, endtype = self._active_node
        if sect_index < 0 or sect_index >= len(sections):
            return

        curve = sections[sect_index]
        if curve.type_name != "curve" or not self._widget._is_disconnected_endpoint(curve, endtype):
            return

        moving_point = curve.start if endtype == "start" else curve.end

        best_solution: tuple[int, "SectionPreview", "SectionPreview", float] | None = None
        attempted_snap = False

        for idx, straight in enumerate(sections):
            if idx == sect_index or straight.type_name != "straight":
                continue

            if not self._widget._is_disconnected_endpoint(straight, "start"):
                continue

            attempted_snap = True
            logger.debug(
                "Attempting snap fit from curve node (%d, %s) at %s to straight node (%d, start) at %s",
                sect_index,
                endtype,
                moving_point,
                idx,
                straight.start,
            )

            heading = straight.start_heading
            if heading is None:
                continue

            hx, hy = heading
            heading_length = math.hypot(hx, hy)
            if heading_length <= 1e-9:
                continue

            heading_unit = (hx / heading_length, hy / heading_length)
            end_point = straight.end

            dx = moving_point[0] - end_point[0]
            dy = moving_point[1] - end_point[1]

            projection = dx * -heading_unit[0] + dy * -heading_unit[1]
            if projection <= 0:
                continue

            start_candidate = (
                end_point[0] - heading_unit[0] * projection,
                end_point[1] - heading_unit[1] * projection,
            )

            perpendicular_dist = math.hypot(
                moving_point[0] - start_candidate[0], moving_point[1] - start_candidate[1]
            )

            if perpendicular_dist > self.SNAP_HEADING_DISTANCE_TOLERANCE:
                continue

            curve_start = start_candidate if endtype == "start" else curve.start
            curve_end = start_candidate if endtype == "end" else curve.end

            solved_curve = solve_curve_with_heading_constraint(
                curve,
                curve_start,
                curve_end,
                heading_unit,
                heading_applies_to_start=endtype == "start",
                tolerance=self._widget.CURVE_SOLVE_TOLERANCE,
            )

            if solved_curve is None:
                continue

            updated_straight = replace(
                straight,
                start=start_candidate,
                length=projection,
                previous_id=sect_index,
            )

            solved_curve = replace(
                solved_curve,
                next_id=idx if endtype == "end" else solved_curve.next_id,
                previous_id=idx if endtype == "start" else solved_curve.previous_id,
            )

            score = perpendicular_dist
            if best_solution is None or score < best_solution[3]:
                best_solution = (idx, solved_curve, updated_straight, score)

        if not attempted_snap:
            logger.debug(
                "Snap fit skipped: no eligible straight section found for curve node (%d, %s) at %s",
                sect_index,
                endtype,
                moving_point,
            )
            return

        if best_solution is None:
            logger.debug(
                "Snap fit unsuccessful between curve node (%d, %s) at %s and any straight start node (tolerance %.1f)",
                sect_index,
                endtype,
                moving_point,
                self.SNAP_HEADING_DISTANCE_TOLERANCE,
            )
            return

        straight_index, solved_curve, updated_straight, _ = best_solution
        logger.debug(
            "Snap fit succeeded between curve node (%d, %s) at %s and straight node (%d, start) now at %s",
            sect_index,
            endtype,
            moving_point,
            straight_index,
            updated_straight.start,
        )
        sections = list(sections)
        sections[sect_index] = update_section_geometry(solved_curve)
        sections[straight_index] = update_section_geometry(updated_straight)
        self._apply_section_updates(sections)

    def attempt_manual_curve_to_straight_fit(
        self, curve_node: tuple[int, str], straight_node: tuple[int, str]
    ) -> tuple[bool, str]:
        """Attempt to snap a specific curve endpoint to a specific straight endpoint."""

        sections = self._widget._sections
        if not sections:
            return False, "No sections loaded to fit."

        curve_index, curve_endtype = curve_node
        straight_index, straight_endtype = straight_node

        if (
            curve_index < 0
            or curve_index >= len(sections)
            or straight_index < 0
            or straight_index >= len(sections)
        ):
            return False, "Invalid nodes selected for fitting."

        curve = sections[curve_index]
        straight = sections[straight_index]

        if curve.type_name != "curve":
            return False, "First node must belong to a curve section."
        if straight.type_name != "straight":
            return False, "Second node must belong to a straight section."

        if not self._widget._is_disconnected_endpoint(curve, curve_endtype):
            return False, "Curve node is already connected."
        if not self._widget._is_disconnected_endpoint(straight, straight_endtype):
            return False, "Straight node is already connected."

        moving_point = curve.start if curve_endtype == "start" else curve.end

        if straight_endtype == "start":
            heading = straight.start_heading
            anchor_point = straight.end
            heading_direction = -1.0
        else:
            heading = straight.end_heading or straight.start_heading
            anchor_point = straight.start
            heading_direction = 1.0

        if heading is None:
            return False, "Straight node is missing heading data for fitting."

        hx, hy = heading
        heading_length = math.hypot(hx, hy)
        if heading_length <= 1e-9:
            return False, "Straight heading is too small to use for fitting."

        heading_unit = (hx / heading_length, hy / heading_length)
        dx = moving_point[0] - anchor_point[0]
        dy = moving_point[1] - anchor_point[1]

        if heading_direction < 0:
            projection = dx * -heading_unit[0] + dy * -heading_unit[1]
            projected_point = (
                anchor_point[0] - heading_unit[0] * projection,
                anchor_point[1] - heading_unit[1] * projection,
            )
        else:
            projection = dx * heading_unit[0] + dy * heading_unit[1]
            projected_point = (
                anchor_point[0] + heading_unit[0] * projection,
                anchor_point[1] + heading_unit[1] * projection,
            )

        if projection <= 0:
            return False, "Selected nodes are not positioned for a valid fit."

        perpendicular_dist = math.hypot(
            moving_point[0] - projected_point[0], moving_point[1] - projected_point[1]
        )
        if perpendicular_dist > self.SNAP_HEADING_DISTANCE_TOLERANCE:
            return False, "Nodes are too far apart to fit based on heading tolerance."

        curve_start = projected_point if curve_endtype == "start" else curve.start
        curve_end = projected_point if curve_endtype == "end" else curve.end

        solved_curve = solve_curve_with_heading_constraint(
            curve,
            curve_start,
            curve_end,
            heading_unit,
            heading_applies_to_start=curve_endtype == "start",
            tolerance=self._widget.CURVE_SOLVE_TOLERANCE,
        )

        if solved_curve is None:
            return False, "Unable to solve curve with the provided nodes."

        straight_start = projected_point if straight_endtype == "start" else straight.start
        straight_end = straight.end if straight_endtype == "start" else projected_point

        updated_straight = replace(
            straight,
            start=straight_start,
            end=straight_end,
            length=projection,
            previous_id=curve_index if straight_endtype == "start" else straight.previous_id,
            next_id=curve_index if straight_endtype == "end" else straight.next_id,
        )

        solved_curve = replace(
            solved_curve,
            next_id=straight_index if curve_endtype == "end" else solved_curve.next_id,
            previous_id=straight_index
            if curve_endtype == "start"
            else solved_curve.previous_id,
        )

        logger.debug(
            "Manual snap fit succeeded: curve node (%d, %s) to straight node (%d, %s)",
            curve_index,
            curve_endtype,
            straight_index,
            straight_endtype,
        )

        new_sections = list(sections)
        new_sections[curve_index] = update_section_geometry(solved_curve)
        new_sections[straight_index] = update_section_geometry(updated_straight)
        self._apply_section_updates(new_sections)

        return True, "Fit applied successfully."

    def _apply_section_updates(self, sections: list["SectionPreview"]) -> None:
        self._widget._sections = sections
        self._widget._section_signatures = [self._widget._section_signature(s) for s in sections]
        self._widget._section_endpoints = [(s.start, s.end) for s in sections]

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
