from __future__ import annotations

import math
from dataclasses import replace
from typing import Iterable

from sg_viewer.preview.creation_controller import (
    CurveCreationInteraction,
    StraightCreationInteraction,
)
from sg_viewer.models.preview_state_utils import is_disconnected_endpoint, is_invalid_id
from sg_viewer.ui.preview_state_controller import PreviewStateController
from sg_viewer.models.selection import SelectionManager
from sg_viewer.geometry.sg_geometry import (
    assert_section_geometry_consistent,
    update_section_geometry,
)
from sg_viewer.models.sg_model import SectionPreview

Point = tuple[float, float]


class PreviewEditor:
    """Encapsulates editing operations for the SG preview widget."""

    def __init__(
        self,
        controller: PreviewStateController,
        selection: SelectionManager,
        straight_creation: StraightCreationInteraction,
        curve_creation: CurveCreationInteraction,
    ) -> None:
        self._controller = controller
        self._selection = selection
        self._straight_creation = straight_creation
        self._curve_creation = curve_creation
        self._delete_section_active = False

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    @property
    def delete_section_active(self) -> bool:
        return self._delete_section_active

    def reset(self) -> None:
        self._delete_section_active = False

    def begin_delete_section(self, sections: Iterable[SectionPreview]) -> bool:
        if not list(sections):
            return False
        self._delete_section_active = True
        return True

    def cancel_delete_section(self) -> bool:
        if not self._delete_section_active:
            return False
        self._delete_section_active = False
        return True

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------
    def finalize_new_straight(
        self, sections: list[SectionPreview], track_length: float | None
    ) -> tuple[list[SectionPreview], float | None, int | None, str | None]:
        if (
            not self._straight_creation.active
            or self._straight_creation.start is None
            or self._straight_creation.end is None
        ):
            return sections, track_length, None, None

        start_point = self._straight_creation.start
        constrained_end = self._straight_creation.apply_heading_constraint(
            start_point, self._straight_creation.end
        )
        length = math.hypot(
            constrained_end[0] - start_point[0],
            constrained_end[1] - start_point[1],
        )
        next_start_dlong = self._next_section_start_dlong(sections)
        new_index = len(sections)

        new_section = SectionPreview(
            section_id=new_index,
            type_name="straight",
            previous_id=-1,
            next_id=-1,
            start=start_point,
            end=constrained_end,
            start_dlong=next_start_dlong,
            length=length,
            center=None,
            sang1=None,
            sang2=None,
            eang1=None,
            eang2=None,
            radius=None,
            start_heading=self._straight_creation.heading,
            end_heading=self._straight_creation.heading,
            polyline=[start_point, constrained_end],
        )

        updated_sections, new_section = self._connect_new_section(
            list(sections), new_section, self._straight_creation.connection
        )
        updated_sections.append(update_section_geometry(new_section))
        new_track_length = next_start_dlong + length
        if track_length is not None:
            track_length = max(track_length, new_track_length)
        else:
            track_length = new_track_length

        self._assert_sections_consistent(updated_sections)
        return (
            updated_sections,
            track_length,
            new_index,
            f"Added new straight #{new_index}.",
        )

    def finalize_new_curve(
        self, sections: list[SectionPreview], track_length: float | None
    ) -> tuple[list[SectionPreview], float | None, int | None, str | None]:
        if (
            not self._curve_creation.active
            or self._curve_creation.start is None
            or self._curve_creation.preview is None
        ):
            return sections, track_length, None, None

        new_section = self._curve_creation.preview
        new_index = len(sections)
        next_start_dlong = self._next_section_start_dlong(sections)
        new_section = replace(
            new_section, section_id=new_index, start_dlong=next_start_dlong
        )

        updated_sections, new_section = self._connect_new_section(
            list(sections), new_section, self._curve_creation.connection
        )
        updated_sections.append(update_section_geometry(new_section))
        new_track_length = next_start_dlong + new_section.length
        if track_length is not None:
            track_length = max(track_length, new_track_length)
        else:
            track_length = new_track_length

        self._assert_sections_consistent(updated_sections)
        return (
            updated_sections,
            track_length,
            new_index,
            f"Added new curve #{new_index}.",
        )

    def _connect_new_section(
        self,
        sections: list[SectionPreview],
        new_section: SectionPreview,
        connection: tuple[int, str] | None,
    ) -> tuple[list[SectionPreview], SectionPreview]:
        if connection is None:
            return sections, new_section

        neighbor_index, endtype = connection
        if neighbor_index < 0 or neighbor_index >= len(sections):
            return sections, new_section

        neighbor = sections[neighbor_index]
        if endtype == "end":
            new_section = replace(new_section, previous_id=neighbor_index)
            neighbor = replace(neighbor, next_id=new_section.section_id)
        else:
            new_section = replace(new_section, next_id=neighbor_index)
            neighbor = replace(neighbor, previous_id=new_section.section_id)

        sections[neighbor_index] = neighbor
        return sections, new_section

    # ------------------------------------------------------------------
    # Delete section
    # ------------------------------------------------------------------
    def delete_section(
        self, sections: list[SectionPreview], index: int
    ) -> tuple[list[SectionPreview], float | None, str]:
        if not sections or index < 0 or index >= len(sections):
            return sections, self._controller.track_length, ""

        removed_id = sections[index].section_id
        removed_targets = {removed_id, index}
        survivors = [sect for idx, sect in enumerate(sections) if idx != index]
        id_mapping = {sect.section_id: new_idx for new_idx, sect in enumerate(survivors)}

        new_sections: list[SectionPreview] = []
        cursor = 0.0
        for sect in survivors:
            new_prev = -1
            if sect.previous_id not in (None, -1) and sect.previous_id not in removed_targets:
                new_prev = id_mapping.get(sect.previous_id, -1)

            new_next = -1
            if sect.next_id not in (None, -1) and sect.next_id not in removed_targets:
                new_next = id_mapping.get(sect.next_id, -1)

            new_index = id_mapping.get(sect.section_id, -1)
            updated_section = replace(
                sect,
                section_id=new_index,
                previous_id=new_prev,
                next_id=new_next,
                start_dlong=cursor,
            )
            new_sections.append(update_section_geometry(updated_section))
            cursor += float(updated_section.length)

        self._delete_section_active = False
        self._assert_sections_consistent(new_sections)
        return new_sections, (cursor if new_sections else None), f"Deleted section #{index}."

    def split_straight_section(
        self, sections: list[SectionPreview], index: int, split_point: Point
    ) -> tuple[list[SectionPreview], float | None] | None:
        if not sections or index < 0 or index >= len(sections):
            return None

        sec = sections[index]
        if sec.type_name != "straight":
            return None

        ax, ay = sec.start
        bx, by = sec.end
        px, py = split_point

        vx = bx - ax
        vy = by - ay
        den = vx * vx + vy * vy
        if den <= 0:
            return None

        t = ((px - ax) * vx + (py - ay) * vy) / den

        MIN_T = 0.02
        if t <= MIN_T or t >= (1.0 - MIN_T):
            return None

        sx = ax + t * vx
        sy = ay + t * vy
        split = (sx, sy)

        def _adjust_id(value: int | None) -> int:
            if value is None or value < 0 or value >= len(sections):
                return -1
            return value + 1 if value > index else value

        first_length = math.hypot(split[0] - sec.start[0], split[1] - sec.start[1])
        second_length = math.hypot(sec.end[0] - split[0], sec.end[1] - split[1])

        first_prev = _adjust_id(sec.previous_id)
        second_next = _adjust_id(sec.next_id)

        s1 = replace(
            sec,
            end=split,
            length=first_length,
            previous_id=first_prev,
            next_id=index + 1,
        )
        s2 = replace(
            sec,
            start=split,
            length=second_length,
            previous_id=index,
            next_id=second_next,
        )

        new_sections: list[SectionPreview] = []
        for i, sect in enumerate(sections):
            if i == index:
                new_sections.append(s1)
                new_sections.append(s2)
                continue

            adjusted_prev = _adjust_id(sect.previous_id)
            adjusted_next = _adjust_id(sect.next_id)
            new_sections.append(
                replace(sect, previous_id=adjusted_prev, next_id=adjusted_next)
            )

        if 0 <= first_prev < len(new_sections):
            prev_section = new_sections[first_prev]
            new_sections[first_prev] = replace(prev_section, next_id=index)

        if 0 <= second_next < len(new_sections):
            next_section = new_sections[second_next]
            new_sections[second_next] = replace(next_section, previous_id=index + 1)

        dlong = 0.0
        for i, sect in enumerate(new_sections):
            updated_section = replace(sect, section_id=i, start_dlong=dlong)
            updated_section = update_section_geometry(updated_section)
            new_sections[i] = updated_section
            dlong += float(updated_section.length)

        self._assert_sections_consistent(new_sections)
        return new_sections, (dlong if new_sections else None)

    def _assert_sections_consistent(self, sections: list[SectionPreview]) -> None:
        if __debug__:
            for section in sections:
                assert_section_geometry_consistent(section)

    # ------------------------------------------------------------------
    # Drag helpers
    # ------------------------------------------------------------------
    def disconnect_neighboring_section(
        self, sections: list[SectionPreview], section_index: int, endtype: str
    ) -> list[SectionPreview]:
        if section_index < 0 or section_index >= len(sections):
            return sections

        sect = sections[section_index]
        if endtype == "start":
            prev_id = sect.previous_id
            sections[section_index] = replace(sect, previous_id=-1)
            if 0 <= prev_id < len(sections):
                prev_sect = sections[prev_id]
                sections[prev_id] = replace(prev_sect, next_id=-1)
        else:
            next_id = sect.next_id
            sections[section_index] = replace(sect, next_id=-1)
            if 0 <= next_id < len(sections):
                next_sect = sections[next_id]
                sections[next_id] = replace(next_sect, previous_id=-1)

        return sections

    def connected_neighbor_index(
        self, sections: list[SectionPreview], index: int, direction: str
    ) -> int | None:
        if index < 0 or index >= len(sections):
            return None

        section = sections[index]
        neighbor_index = section.previous_id if direction == "previous" else section.next_id
        if is_invalid_id(sections, neighbor_index):
            return None

        neighbor = sections[neighbor_index]
        if direction == "previous" and neighbor.next_id != index:
            return None
        if direction == "next" and neighbor.previous_id != index:
            return None

        return neighbor_index

    def get_drag_chain(
        self, sections: list[SectionPreview], index: int | None
    ) -> list[int] | None:
        if index is None or index < 0 or index >= len(sections):
            return None

        chain: list[int] = [index]
        visited = {index}

        prev_idx = self.connected_neighbor_index(sections, index, "previous")
        while prev_idx is not None and prev_idx not in visited:
            chain.insert(0, prev_idx)
            visited.add(prev_idx)
            prev_idx = self.connected_neighbor_index(sections, prev_idx, "previous")
        head_closed_loop = prev_idx == index

        next_idx = self.connected_neighbor_index(sections, index, "next")
        while next_idx is not None and next_idx not in visited:
            chain.append(next_idx)
            visited.add(next_idx)
            next_idx = self.connected_neighbor_index(sections, next_idx, "next")
        tail_closed_loop = next_idx == chain[0] or next_idx == index

        if not chain:
            return None

        head = sections[chain[0]]
        tail = sections[chain[-1]]
        head_open = is_invalid_id(sections, head.previous_id)
        tail_open = is_invalid_id(sections, tail.next_id)

        closed_loop = (
            not head_open
            and not tail_open
            and self.connected_neighbor_index(sections, chain[0], "previous") == chain[-1]
            and self.connected_neighbor_index(sections, chain[-1], "next") == chain[0]
            and (head_closed_loop or tail_closed_loop)
        )

        if not closed_loop and not (head_open and tail_open):
            return None

        return chain

    def can_drag_section_node(self, sections: list[SectionPreview], section: SectionPreview) -> bool:
        return (
            section.type_name == "straight"
            and is_invalid_id(sections, section.previous_id)
            and is_invalid_id(sections, section.next_id)
        )

    def can_drag_section_polyline(
        self,
        sections: list[SectionPreview],
        section: SectionPreview,
        index: int | None = None,
    ) -> bool:
        chain = self.get_drag_chain(sections, index) if index is not None else None
        if chain is not None:
            return True

        if section.type_name == "curve":
            return is_invalid_id(sections, section.previous_id) and is_invalid_id(
                sections, section.next_id
            )
        return self.can_drag_section_node(sections, section)

    def can_drag_node(
        self, sections: list[SectionPreview], section: SectionPreview, endtype: str
    ) -> bool:
        if section.type_name == "straight":
            return self.can_drag_section_node(sections, section) or self.is_disconnected_endpoint(
                sections, section, endtype
            )
        if section.type_name == "curve":
            return self.is_disconnected_endpoint(sections, section, endtype)
        return False

    def is_disconnected_endpoint(
        self, sections: list[SectionPreview], section: SectionPreview, endtype: str
    ) -> bool:
        return is_disconnected_endpoint(sections, section, endtype)

    def is_invalid_id(self, sections: list[SectionPreview], value: int | None) -> bool:
        return is_invalid_id(sections, value)

    def next_section_start_dlong(self, sections: list[SectionPreview]) -> float:
        return self._next_section_start_dlong(sections)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _next_section_start_dlong(self, sections: list[SectionPreview]) -> float:
        if not sections:
            return 0.0
        last = sections[-1]
        return float(last.start_dlong + last.length)
