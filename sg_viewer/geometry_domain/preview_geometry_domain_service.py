from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Literal

from sg_viewer.geometry.canonicalize import canonicalize_closed_loop
from sg_viewer.geometry.connect_curve_to_straight import (
    solve_curve_end_to_straight_start,
    solve_straight_end_to_curve_endpoint,
)
from sg_viewer.geometry.dlong import set_start_finish
from sg_viewer.geometry.picking import project_point_to_segment
from sg_viewer.geometry_core import curve_tangent, directed_angle, heading, is_perfectly_straight_chain, points_close
from sg_viewer.geometry.sg_geometry import assert_section_geometry_consistent, update_section_geometry
from sg_viewer.geometry.topology import is_closed_loop
from sg_viewer.model.preview_state_utils import is_disconnected_endpoint, is_invalid_id
from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.preview.connection_detection import find_unconnected_node_target
from sg_viewer.preview.preview_mutations import (
    project_point_along_heading,
    solve_curve_drag,
    update_straight_endpoints,
)

Point = tuple[float, float]
EndType = Literal["start", "end"]


@dataclass(frozen=True)
class ConnectNodesRequest:
    sections: list[SectionPreview]
    source: tuple[int, EndType]
    target: tuple[int, EndType]


@dataclass(frozen=True)
class NodeDisconnectRequest:
    sections: list[SectionPreview]
    node: tuple[int, EndType]


@dataclass(frozen=True)
class NodeDragRequest:
    sections: list[SectionPreview]
    active_node: tuple[int, EndType]
    track_point: Point
    can_drag_node: bool


@dataclass(frozen=True)
class SectionSnapshotResponse:
    sections: list[SectionPreview] | None
    changed_indices: list[int] | None = None
    last_dragged_indices: list[int] | None = None


@dataclass(frozen=True)
class ConnectionSolveRequest:
    sections: list[SectionPreview]
    source: tuple[int, EndType]
    target: tuple[int, EndType]


@dataclass(frozen=True)
class ConnectionSolveResponse:
    sections: list[SectionPreview] | None
    changed_indices: list[int] | None
    status_message: str | None


@dataclass(frozen=True)
class ClosureTransitionResponse:
    sections: list[SectionPreview]
    changed_indices: list[int] | None
    status_message: str | None = None
    closed_loop_transition: bool = False


@dataclass(frozen=True)
class StartFinishRequest:
    sections: list[SectionPreview]
    hit: tuple[int, EndType]


@dataclass(frozen=True)
class StartFinishResponse:
    sections: list[SectionPreview] | None
    status_message: str


class PreviewGeometryDomainService:
    def set_start_finish(self, request: StartFinishRequest) -> StartFinishResponse:
        section_idx, endtype = request.hit
        sections = request.sections
        if not is_closed_loop(sections):
            return StartFinishResponse(None, "Track must be closed to set start/finish")
        start_idx = sections[section_idx].next_id if endtype == "end" else section_idx
        try:
            return StartFinishResponse(set_start_finish(sections, start_idx), "Start/finish set to selected section (now section 0)")
        except ValueError:
            return StartFinishResponse(None, "Track must be closed to set start/finish")
        except RuntimeError:
            return StartFinishResponse(None, "Invalid loop topology; cannot set start/finish")

    def disconnect_node(self, request: NodeDisconnectRequest) -> SectionSnapshotResponse:
        sections = list(request.sections)
        section_index, endtype = request.node
        if section_index < 0 or section_index >= len(sections):
            return SectionSnapshotResponse(None)
        section = sections[section_index]
        if endtype == "start":
            neighbor = section.previous_id
            section = replace(section, previous_id=-1)
        else:
            neighbor = section.next_id
            section = replace(section, next_id=-1)
        sections[section_index] = update_section_geometry(section)
        changed = [section_index]
        if not is_invalid_id(sections, neighbor) and neighbor is not None:
            other = sections[neighbor]
            if endtype == "start" and other.next_id == section_index:
                other = replace(other, next_id=-1)
            elif endtype == "end" and other.previous_id == section_index:
                other = replace(other, previous_id=-1)
            sections[neighbor] = update_section_geometry(other)
            changed.append(neighbor)
        return SectionSnapshotResponse(sections=sections, changed_indices=changed)

    def connect_nodes(self, request: ConnectNodesRequest) -> SectionSnapshotResponse:
        sections = list(request.sections)
        if not sections:
            return SectionSnapshotResponse(None)
        src_index, src_end = request.source
        tgt_index, tgt_end = request.target
        if src_index == tgt_index or is_invalid_id(sections, src_index) or is_invalid_id(sections, tgt_index):
            return SectionSnapshotResponse(None)
        src_section = sections[src_index]
        tgt_section = sections[tgt_index]
        if not is_disconnected_endpoint(sections, src_section, src_end):
            return SectionSnapshotResponse(None)
        if not is_disconnected_endpoint(sections, tgt_section, tgt_end):
            return SectionSnapshotResponse(None)
        src_section = replace(src_section, previous_id=tgt_index) if src_end == "start" else replace(src_section, next_id=tgt_index)
        tgt_section = replace(tgt_section, previous_id=src_index) if tgt_end == "start" else replace(tgt_section, next_id=src_index)
        sections[src_index] = update_section_geometry(src_section)
        sections[tgt_index] = update_section_geometry(tgt_section)
        return SectionSnapshotResponse(sections=sections, changed_indices=[src_index, tgt_index])

    def solve_connection(self, request: ConnectionSolveRequest) -> ConnectionSolveResponse:
        sections = list(request.sections)
        dragged_idx, dragged_end = request.source
        target_idx, target_end = request.target
        dragged_section = sections[dragged_idx]
        target_section = sections[target_idx]

        if dragged_section.type_name == "curve" and dragged_end == "end" and target_section.type_name == "straight" and target_end == "start":
            result = solve_curve_end_to_straight_start(dragged_section, target_section)
            if result is None:
                return ConnectionSolveResponse(None, None, self.connection_failure_reason(dragged_section, dragged_end, target_section, target_end))
            new_curve, new_straight = result
            return self._apply_curve_straight_connection(sections, dragged_idx, dragged_end, target_idx, target_end, new_curve, new_straight, "Curve → straight connected")

        if dragged_section.type_name == "straight" and target_section.type_name == "curve":
            result = solve_straight_end_to_curve_endpoint(dragged_section, dragged_end, target_section, target_end)
            if result is None:
                return ConnectionSolveResponse(None, None, self.connection_failure_reason(dragged_section, dragged_end, target_section, target_end))
            new_straight, new_curve = result
            return self._apply_curve_straight_connection(sections, target_idx, target_end, dragged_idx, dragged_end, new_curve, new_straight, "Straight → curve connected")

        if dragged_section.type_name == "straight" and target_section.type_name == "straight":
            result = self._solve_straight_to_straight_connection(
                sections,
                dragged_idx,
                dragged_section,
                dragged_end,
                target_idx,
                target_section,
                target_end,
            )
            if result is None:
                return ConnectionSolveResponse(None, None, self.connection_failure_reason(dragged_section, dragged_end, target_section, target_end))
            new_dragged, new_target = result
            return self._apply_straight_straight_connection(
                sections,
                dragged_idx,
                dragged_end,
                target_idx,
                target_end,
                new_dragged,
                new_target,
                "Straight → straight connected",
            )

        return ConnectionSolveResponse(None, None, self.connection_failure_reason(dragged_section, dragged_end, target_section, target_end))

    def apply_closure_transition(self, old_sections: list[SectionPreview], updated_sections: list[SectionPreview], changed_indices: list[int] | None = None) -> ClosureTransitionResponse:
        old_closed = is_closed_loop(old_sections)
        new_closed = is_closed_loop(updated_sections)
        if not old_closed and new_closed:
            canonical = canonicalize_closed_loop(updated_sections, start_idx=0)
            return ClosureTransitionResponse(canonical, changed_indices, "Closed loop detected — track direction fixed", True)
        return ClosureTransitionResponse(updated_sections, changed_indices)

    def update_dragged_section(self, request: NodeDragRequest) -> SectionSnapshotResponse:
        sections = request.sections
        constrained_straight = self._apply_constrained_shared_straight_drag(request.active_node, request.track_point, sections)
        if constrained_straight is not None:
            return constrained_straight
        constrained_curve = self._apply_constrained_shared_curve_drag(request.active_node, request.track_point, sections)
        if constrained_curve is not None:
            return constrained_curve

        sect_index, endtype = request.active_node
        if sect_index < 0 or sect_index >= len(sections) or not request.can_drag_node:
            return SectionSnapshotResponse(None)
        constrained = self._apply_shared_node_drag_constraint(sections, sect_index, endtype, request.track_point)
        if constrained is not None:
            return constrained

        sect = sections[sect_index]
        start, end = sect.start, sect.end
        disconnected_start = is_disconnected_endpoint(sections, sect, "start")
        disconnected_end = is_disconnected_endpoint(sections, sect, "end")
        if sect.type_name == "curve":
            if endtype == "start":
                start = request.track_point
            else:
                end = request.track_point
        elif endtype == "start":
            start = project_point_along_heading(end, sect.end_heading, request.track_point) if disconnected_start and not disconnected_end else request.track_point
            start = start or request.track_point
        else:
            end = project_point_along_heading(start, sect.start_heading, request.track_point) if disconnected_end and not disconnected_start else request.track_point
            end = end or request.track_point

        updated = solve_curve_drag(sect, start, end) if sect.type_name == "curve" else update_straight_endpoints(sect, start, end)
        if updated is None:
            return SectionSnapshotResponse(None)
        result = list(sections)
        result[sect_index] = update_section_geometry(updated)
        return SectionSnapshotResponse(result, changed_indices=[sect_index], last_dragged_indices=[sect_index])


    def refresh_section_geometry(self, section: SectionPreview) -> SectionPreview:
        return update_section_geometry(section)

    def can_start_shared_node_drag(self, node: tuple[int, EndType], sections: list[SectionPreview]) -> bool:
        return self._shared_straight_pair(node, sections) is not None or self._shared_curve_pair(node, sections) is not None

    def find_connection_target(self, dragged_key: tuple[int, EndType], dragged_pos: Point, sections: list[SectionPreview], snap_radius: float) -> tuple[int, EndType] | None:
        return find_unconnected_node_target(
            dragged_key=dragged_key,
            dragged_pos=dragged_pos,
            sections=sections,
            snap_radius=snap_radius,
        )
    def validate_sections(self, sections: list[SectionPreview]) -> None:
        if __debug__:
            for section in sections:
                assert_section_geometry_consistent(section)

    def _apply_curve_straight_connection(self, sections: list[SectionPreview], curve_idx: int, curve_end: EndType, straight_idx: int, straight_end: EndType, curve: SectionPreview, straight: SectionPreview, msg: str) -> ConnectionSolveResponse:
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
        return ConnectionSolveResponse(sections, [curve_idx, straight_idx], msg)

    def _apply_straight_straight_connection(
        self,
        sections: list[SectionPreview],
        dragged_idx: int,
        dragged_end: EndType,
        target_idx: int,
        target_end: EndType,
        dragged: SectionPreview,
        target: SectionPreview,
        msg: str,
    ) -> ConnectionSolveResponse:
        if dragged_end == "start":
            dragged = replace(dragged, previous_id=target_idx)
        else:
            dragged = replace(dragged, next_id=target_idx)
        if target_end == "start":
            target = replace(target, previous_id=dragged_idx)
        else:
            target = replace(target, next_id=dragged_idx)
        sections[dragged_idx] = update_section_geometry(dragged)
        sections[target_idx] = update_section_geometry(target)
        return ConnectionSolveResponse(sections, [dragged_idx, target_idx], msg)

    def _solve_straight_to_straight_connection(
        self,
        sections: list[SectionPreview],
        dragged_idx: int,
        dragged: SectionPreview,
        dragged_end: EndType,
        target_idx: int,
        target: SectionPreview,
        target_end: EndType,
    ) -> tuple[SectionPreview, SectionPreview] | None:
        dragged_heading = self._endpoint_heading(dragged, dragged_end)
        target_heading = self._endpoint_heading(target, target_end)
        if dragged_heading is None:
            return None

        target_disconnected_both_ends = (
            is_disconnected_endpoint(sections, target, "start")
            and is_disconnected_endpoint(sections, target, "end")
        )
        if target_disconnected_both_ends:
            join_point = dragged.start if dragged_end == "start" else dragged.end
            segment_length = math.hypot(target.end[0] - target.start[0], target.end[1] - target.start[1])
            if segment_length <= 0:
                return None
            dx = dragged_heading[0] * segment_length
            dy = dragged_heading[1] * segment_length
            updated_target = (
                replace(target, start=join_point, end=(join_point[0] + dx, join_point[1] + dy))
                if target_end == "start"
                else replace(target, start=(join_point[0] - dx, join_point[1] - dy), end=join_point)
            )
            updated_dragged = dragged
            return updated_dragged, updated_target

        if target_heading is None:
            return None
        if dragged_heading != target_heading:
            return None

        join_point = target.start if target_end == "start" else target.end
        dragged_opposite = dragged.end if dragged_end == "start" else dragged.start
        target_opposite = target.end if target_end == "start" else target.start

        if not is_perfectly_straight_chain(dragged_opposite, join_point, target_opposite):
            return None

        updated_dragged = (
            replace(dragged, start=join_point) if dragged_end == "start" else replace(dragged, end=join_point)
        )
        updated_target = (
            replace(target, start=join_point) if target_end == "start" else replace(target, end=join_point)
        )
        return updated_dragged, updated_target

    def _apply_shared_node_drag_constraint(self, sections: list[SectionPreview], sect_index: int, endtype: EndType, track_point: Point) -> SectionSnapshotResponse | None:
        if endtype == "end":
            s1_idx = sect_index
            s2_idx = sections[sect_index].next_id
        else:
            s2_idx = sect_index
            s1_idx = sections[sect_index].previous_id
        if is_invalid_id(sections, s1_idx) or is_invalid_id(sections, s2_idx):
            return None
        s1 = sections[s1_idx]
        s2 = sections[s2_idx]
        if s1.type_name != "straight" or s2.type_name != "straight" or s1.end != s2.start:
            return None
        h1 = heading(s1.start, s1.end)
        h2 = heading(s2.start, s2.end)
        if h1 is None or h2 is None or h1[0] * h2[0] + h1[1] * h2[1] < math.cos(math.radians(0.1)):
            return None
        ax, ay = s1.start
        cx, cy = s2.end
        vx, vy = cx - ax, cy - ay
        length_sq = vx * vx + vy * vy
        if length_sq <= 0:
            return None
        px, py = track_point
        t = ((px - ax) * vx + (py - ay) * vy) / length_sq
        min_t = 50.0 / math.sqrt(length_sq)
        t = max(min_t, min(1.0 - min_t, t))
        point = (ax + t * vx, ay + t * vy)
        updated = list(sections)
        updated[s1_idx] = update_section_geometry(replace(s1, end=point))
        updated[s2_idx] = update_section_geometry(replace(s2, start=point))
        return SectionSnapshotResponse(updated, last_dragged_indices=[s1_idx, s2_idx])

    def _shared_straight_pair(self, dragged_key: tuple[int, EndType], sections: list[SectionPreview]):
        section_index, end_type = dragged_key
        if section_index < 0 or section_index >= len(sections):
            return None
        s1_idx, s2_idx = (section_index, sections[section_index].next_id) if end_type == "end" else (sections[section_index].previous_id, section_index)
        if is_invalid_id(sections, s1_idx) or is_invalid_id(sections, s2_idx):
            return None
        s1, s2 = sections[s1_idx], sections[s2_idx]
        if s1.type_name != "straight" or s2.type_name != "straight" or s1.end != s2.start:
            return None
        return s1_idx, s2_idx, s1, s2

    def _apply_constrained_shared_straight_drag(self, dragged_key: tuple[int, EndType], track_point: Point, sections: list[SectionPreview]) -> SectionSnapshotResponse | None:
        pair = self._shared_straight_pair(dragged_key, sections)
        if pair is None:
            return None
        s1_idx, s2_idx, s1, s2 = pair
        A, C = s1.start, s2.end
        P = project_point_to_segment(track_point, A, C)
        if P is None:
            return None
        total = math.hypot(C[0] - A[0], C[1] - A[1])
        if total <= 0:
            return None
        t = math.hypot(P[0] - A[0], P[1] - A[1]) / total
        min_t = 50.0 / total
        t = max(min_t, min(1.0 - min_t, t))
        p = (A[0] + t * (C[0] - A[0]), A[1] + t * (C[1] - A[1]))
        updated = list(sections)
        updated[s1_idx] = update_section_geometry(replace(s1, end=p, length=math.hypot(p[0]-A[0], p[1]-A[1])))
        updated[s2_idx] = update_section_geometry(replace(s2, start=p, length=math.hypot(C[0]-p[0], C[1]-p[1])))
        return SectionSnapshotResponse(updated, last_dragged_indices=[s1_idx, s2_idx])

    def _shared_curve_pair(self, dragged_key: tuple[int, EndType], sections: list[SectionPreview]):
        section_index, end_type = dragged_key
        if section_index < 0 or section_index >= len(sections):
            return None
        s1_idx, s2_idx = (section_index, sections[section_index].next_id) if end_type == "end" else (sections[section_index].previous_id, section_index)
        if is_invalid_id(sections, s1_idx) or is_invalid_id(sections, s2_idx):
            return None
        s1, s2 = sections[s1_idx], sections[s2_idx]
        if s1.type_name != "curve" or s2.type_name != "curve" or not points_close(s1.end, s2.start):
            return None
        if s1.center is None or s2.center is None or not points_close(s1.center, s2.center):
            return None
        if s1.radius is None or s2.radius is None or abs(s1.radius) <= 0 or abs(abs(s1.radius) - abs(s2.radius)) > 1e-6:
            return None
        o1 = self._curve_orientation(s1)
        o2 = self._curve_orientation(s2)
        if o1 is None or o2 is None or o1 * o2 < 0:
            return None
        return s1_idx, s2_idx, s1, s2, s1.center, abs(s1.radius), o1

    def _apply_constrained_shared_curve_drag(self, dragged_key: tuple[int, EndType], track_point: Point, sections: list[SectionPreview]) -> SectionSnapshotResponse | None:
        pair = self._shared_curve_pair(dragged_key, sections)
        if pair is None:
            return None
        s1_idx, s2_idx, s1, s2, center, radius, orientation = pair
        cx, cy = center
        sa = math.atan2(s1.start[1] - cy, s1.start[0] - cx)
        ea = math.atan2(s2.end[1] - cy, s2.end[0] - cx)
        total_span = directed_angle(sa, ea, orientation)
        if abs(total_span) <= 1e-9:
            return None
        ta = math.atan2(track_point[1] - cy, track_point[0] - cx)
        frac = directed_angle(sa, ta, orientation) / total_span
        frac = max(0.02, min(0.98, frac))
        span = total_span * frac
        ca = sa + span
        p = (cx + math.cos(ca) * radius, cy + math.sin(ca) * radius)
        shared_heading = curve_tangent((p[0] - cx, p[1] - cy), orientation)
        if shared_heading is None:
            return None
        start_heading = curve_tangent((s1.start[0] - cx, s1.start[1] - cy), orientation)
        end_heading = curve_tangent((s2.end[0] - cx, s2.end[1] - cy), orientation)
        updated = list(sections)
        updated[s1_idx] = update_section_geometry(replace(s1, end=p, length=abs(span) * radius, start_heading=start_heading, end_heading=shared_heading, sang1=start_heading[0] if start_heading else None, sang2=start_heading[1] if start_heading else None, eang1=shared_heading[0], eang2=shared_heading[1], center=center))
        updated[s2_idx] = update_section_geometry(replace(s2, start=p, length=abs(total_span-span) * radius, start_heading=shared_heading, end_heading=end_heading, sang1=shared_heading[0], sang2=shared_heading[1], eang1=end_heading[0] if end_heading else None, eang2=end_heading[1] if end_heading else None, center=center))
        return SectionSnapshotResponse(updated, last_dragged_indices=[s1_idx, s2_idx])

    def connection_failure_reason(self, dragged_section: SectionPreview, dragged_end: EndType, target_section: SectionPreview, target_end: EndType) -> str:
        if dragged_section.type_name == "straight" and target_section.type_name == "straight":
            return "Cannot connect straight → straight unless endpoint headings match and the connection is perfectly straight."
        if dragged_section.type_name == "curve" and target_section.type_name == "curve":
            return "Cannot connect curve → curve; drag a straight onto a curve or a curve end onto a straight."
        return "Unable to connect endpoints with current geometry."

    def _endpoint_heading(self, section: SectionPreview, end_type: EndType) -> tuple[float, float] | None:
        return section.start_heading if end_type == "start" else section.end_heading

    def _curve_orientation(self, section: SectionPreview) -> float | None:
        if section.center is None:
            return None
        start_vec = (section.start[0] - section.center[0], section.start[1] - section.center[1])
        end_vec = (section.end[0] - section.center[0], section.end[1] - section.center[1])
        cross = start_vec[0] * end_vec[1] - start_vec[1] * end_vec[0]
        return -1.0 if section.radius is not None and section.radius < 0 else (1.0 if cross >= 0 else -1.0)

