from __future__ import annotations

from sg_viewer.geometry.centerline_utils import compute_start_finish_mapping_from_centerline
from sg_viewer.geometry.sg_geometry import (
    build_section_polyline,
    derive_heading_vectors,
    rebuild_centerline_from_sections,
)
from sg_viewer.model.sg_document import SGDocument
from sg_viewer.models.sg_model import SectionPreview


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
                # NOTE: section_id is an index, not a persistent identifier.
                self.boundary_posts[(sect.section_id, side)] = posts

        self._assert_section_id_invariant()
        self.dirty = False

    def _build_sections(self, sgfile) -> list[SectionPreview]:
        sections: list[SectionPreview] = []

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

            polyline = build_section_polyline(
                type_name,
                start,
                end,
                center,
                radius,
                (sang1, sang2) if sang1 is not None and sang2 is not None else None,
                (eang1, eang2) if eang1 is not None and eang2 is not None else None,
            )

            start_heading, end_heading = derive_heading_vectors(
                polyline, sang1, sang2, eang1, eang2
            )

            sections.append(
                SectionPreview(
                    section_id=idx,
                    type_name=type_name,
                    previous_id=int(getattr(sg_sect, "sec_prev", idx - 1)),
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

        for i, sect in enumerate(sections):
            object.__setattr__(sect, "section_id", i)

        assert all(
            i == sect.section_id
            for i, sect in enumerate(sections)
        ), "SectionPreview.section_id must equal list index"

        return sections

    def _assert_section_id_invariant(self) -> None:
        for i, sect in enumerate(self.sections):
            if sect.section_id != i:
                raise RuntimeError(
                    f"Section ID mismatch: index={i}, section_id={sect.section_id}"
                )
