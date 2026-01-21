from __future__ import annotations

import logging

from sg_viewer.geometry.centerline_utils import compute_start_finish_mapping_from_centerline
from sg_viewer.geometry.sg_geometry import (
    DEBUG_CURVE_RENDER,
    build_section_polyline,
    compute_forward_anchor,
    derive_heading_vectors,
    rebuild_centerline_from_sections,
)
from sg_viewer.geometry.section_utils import previous_section_index
from sg_viewer.model.sg_document import SGDocument
from sg_viewer.models.sg_model import SectionPreview

logger = logging.getLogger(__name__)


class DerivedGeometry:
    def __init__(self, sg_document: SGDocument) -> None:
        self._document = sg_document
        self.dirty = True
        self.sections: list[SectionPreview] = []
        self.section_endpoints: list[tuple[tuple[float, float], tuple[float, float]]] = []
        self.sampled_centerline: list[tuple[float, float]] = []
        self.sampled_dlongs: list[float] = []
        self.sampled_bounds: tuple[float, float, float, float] | None = None
        self.centerline_index: object | None = None
        self.track_length: float = 0.0
        self.start_finish_mapping: tuple[tuple[float, float], tuple[float, float], tuple[float, float]] | None = None
        self.boundary_posts: dict[
            tuple[int, str],
            list[tuple[tuple[float, float], tuple[float, float]]],
        ] = {}

        self._document.geometry_changed.connect(self.mark_dirty)

    def mark_dirty(self) -> None:
        self.dirty = True

    def rebuild_if_needed(self) -> None:
        if not self.dirty:
            return

        sg_data = self._document.sg_data
        if sg_data is None or not sg_data.sects:
            self.sections = []
            self.section_endpoints = []
            self.sampled_centerline = []
            self.sampled_dlongs = []
            self.sampled_bounds = None
            self.centerline_index = None
            self.track_length = 0.0
            self.start_finish_mapping = None
            self.boundary_posts = {}
            self.dirty = False
            return

        self.sections = self._build_sections(sg_data)
        (
            self.sampled_centerline,
            self.sampled_dlongs,
            self.sampled_bounds,
            self.centerline_index,
        ) = rebuild_centerline_from_sections(self.sections)

        if self.sampled_dlongs:
            self.track_length = float(self.sampled_dlongs[-1])
        else:
            self.track_length = 0.0

        self.section_endpoints = [(sect.start, sect.end) for sect in self.sections]
        self.start_finish_mapping = compute_start_finish_mapping_from_centerline(
            self.sampled_centerline
        )

        from sg_viewer.geometry.boundary_posts import generate_boundary_posts

        self.boundary_posts.clear()
        for sect in self.sections:
            for side in ("left", "right"):
                posts = generate_boundary_posts(
                    sect.polyline,
                    side=side,
                    spacing=12.0 * 500.0,
                    length=2.0 * 500.0,
                )
                self.boundary_posts[(sect.section_id, side)] = posts

        self.dirty = False

    def _build_sections(self, sgfile) -> list[SectionPreview]:
        sections: list[SectionPreview] = []
        track_closed = _is_closed_loop(sgfile.sects)

        for idx, sg_sect in enumerate(sgfile.sects):
            start_dlong = float(sg_sect.start_dlong)
            length = float(sg_sect.length)

            start = (float(sg_sect.start_x), float(sg_sect.start_y))
            end = (
                float(getattr(sg_sect, "end_x", start[0])),
                float(getattr(sg_sect, "end_y", start[1])),
            )

            center = None
            radius = None
            sang1 = sang2 = eang1 = eang2 = None
            if getattr(sg_sect, "type", None) == 2:
                center = (float(sg_sect.center_x), float(sg_sect.center_y))
                radius = float(sg_sect.radius)
                sang1 = float(sg_sect.sang1)
                sang2 = float(sg_sect.sang2)
                eang1 = float(sg_sect.eang1)
                eang2 = float(sg_sect.eang2)

            type_name = "curve" if getattr(sg_sect, "type", None) == 2 else "straight"
            forward_anchor = None
            prev_index = previous_section_index(idx, len(sgfile.sects), track_closed)
            prev_section = sgfile.sects[prev_index] if prev_index is not None else None
            if type_name == "curve" and prev_section is not None:
                prev_start = (float(prev_section.start_x), float(prev_section.start_y))
                prev_end = (
                    float(getattr(prev_section, "end_x", prev_start[0])),
                    float(getattr(prev_section, "end_y", prev_start[1])),
                )
                prev_center = None
                prev_radius = None
                prev_type = "curve" if getattr(prev_section, "type", None) == 2 else "straight"
                if prev_type == "curve":
                    prev_center = (float(prev_section.center_x), float(prev_section.center_y))
                    prev_radius = float(prev_section.radius)
                forward_anchor = compute_forward_anchor(
                    prev_type, prev_start, prev_end, prev_center, prev_radius
                )
                if forward_anchor is not None and DEBUG_CURVE_RENDER:
                    logger.info(
                        "Anchored curve orientation using previous section",
                        extra={
                            "section_id": idx,
                            "previous_section_id": prev_index,
                            "previous_section_type": prev_type,
                        },
                    )

            polyline = build_section_polyline(
                type_name,
                start,
                end,
                center,
                radius,
                (sang1, sang2) if sang1 is not None and sang2 is not None else None,
                (eang1, eang2) if eang1 is not None and eang2 is not None else None,
                section_id=idx,
                forward_anchor=forward_anchor,
            )

            start_heading, end_heading = derive_heading_vectors(
                polyline, sang1, sang2, eang1, eang2
            )

            sections.append(
                SectionPreview(
                    section_id=idx,
                    type_name=type_name,
                    previous_id=int(
                        getattr(sg_sect, "sec_prev", prev_index if prev_index is not None else -1)
                    ),
                    next_id=int(getattr(sg_sect, "sec_next", idx + 1)),
                    start=start,
                    end=end,
                    start_dlong=start_dlong,
                    length=length,
                    center=center,
                    sang1=sang1,
                    sang2=sang2,
                    eang1=eang1,
                    eang2=eang2,
                    radius=radius,
                    start_heading=start_heading,
                    end_heading=end_heading,
                    polyline=polyline,
                )
            )

        return sections


def _is_closed_loop(sects) -> bool:
    n = len(sects)
    if n == 0:
        return False

    for sect in sects:
        prev_id = getattr(sect, "sec_prev", None)
        next_id = getattr(sect, "sec_next", None)
        if prev_id is None or next_id is None:
            return False
        prev_id = int(prev_id)
        next_id = int(next_id)
        if not (0 <= prev_id < n and 0 <= next_id < n):
            return False

    visited = set()
    idx = 0
    while idx not in visited:
        visited.add(idx)
        next_id = int(getattr(sects[idx], "sec_next", -1))
        if not (0 <= next_id < n):
            return False
        idx = next_id

    if idx != 0:
        return False
    if len(visited) != n:
        return False

    for j in visited:
        next_id = int(getattr(sects[j], "sec_next", -1))
        prev_id = int(getattr(sects[next_id], "sec_prev", -1))
        if prev_id != j:
            return False

    return True
