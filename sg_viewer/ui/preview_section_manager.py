from __future__ import annotations

from typing import Callable, Tuple

from track_viewer.geometry import CenterlineIndex

from sg_viewer.geometry.sg_geometry import (
    rebuild_centerline_from_sections,
    update_section_geometry,
)
from sg_viewer.models.preview_state_utils import (
    compute_section_signatures,
    section_signature,
)
from sg_viewer.models.sg_model import SectionPreview

Point = Tuple[float, float]


class PreviewSectionManager:
    def __init__(
        self,
        combine_bounds_with_background: Callable[
            [tuple[float, float, float, float]], tuple[float, float, float, float]
        ],
    ) -> None:
        self._combine_bounds_with_background = combine_bounds_with_background
        self.reset()

    def reset(self) -> None:
        self.sections: list[SectionPreview] = []
        self.section_signatures: list[tuple] = []
        self.section_endpoints: list[tuple[Point, Point]] = []
        self.centerline_polylines: list[list[Point]] = []
        self.sampled_centerline: list[Point] = []
        self.sampled_dlongs: list[float] = []
        self.sampled_bounds: tuple[float, float, float, float] | None = None
        self.centerline_index: CenterlineIndex | None = None

    def load_sections(
        self,
        *,
        sections: list[SectionPreview],
        section_endpoints: list[tuple[Point, Point]],
        sampled_centerline: list[Point],
        sampled_dlongs: list[float],
        sampled_bounds: tuple[float, float, float, float],
        centerline_index: CenterlineIndex,
    ) -> None:
        self.sections = sections
        self.section_signatures = compute_section_signatures(sections)
        self.section_endpoints = section_endpoints
        self.sampled_centerline = sampled_centerline
        self.sampled_dlongs = sampled_dlongs
        self.sampled_bounds = self._combine_bounds_with_background(sampled_bounds)
        self.centerline_index = centerline_index
        self.centerline_polylines = [sect.polyline for sect in self.sections]

    def set_sections(self, sections: list[SectionPreview]) -> bool:
        previous_signatures = self.section_signatures

        new_sections: list[SectionPreview] = []
        new_signatures: list[tuple] = []
        changed_indices: list[int] = []

        for idx, sect in enumerate(sections):
            signature = section_signature(sect)
            new_signatures.append(signature)
            prev_signature = (
                previous_signatures[idx] if idx < len(previous_signatures) else None
            )

            if (
                prev_signature is not None
                and prev_signature == signature
                and idx < len(self.sections)
            ):
                new_sections.append(self.sections[idx])
            else:
                new_sections.append(update_section_geometry(sect))
                changed_indices.append(idx)

        length_changed = len(sections) != len(self.sections)
        needs_rebuild = length_changed or bool(changed_indices)

        self.sections = new_sections
        self.section_signatures = new_signatures
        self.section_endpoints = [(sect.start, sect.end) for sect in self.sections]

        if needs_rebuild:
            points, dlongs, bounds, index = rebuild_centerline_from_sections(
                self.sections
            )
            self.centerline_polylines = [sect.polyline for sect in self.sections]
            self.sampled_centerline = points
            self.sampled_dlongs = dlongs
            self.sampled_bounds = self._combine_bounds_with_background(bounds)
            self.centerline_index = index

        return needs_rebuild

    def update_drag_preview(self, sections: list[SectionPreview]) -> bool:
        if len(sections) != len(self.sections):
            return False

        previous_signatures = self.section_signatures
        new_sections: list[SectionPreview] = []
        new_signatures: list[tuple] = []
        changed_indices: list[int] = []

        for idx, sect in enumerate(sections):
            signature = section_signature(sect)
            new_signatures.append(signature)
            prev_signature = (
                previous_signatures[idx] if idx < len(previous_signatures) else None
            )

            if (
                prev_signature is not None
                and prev_signature == signature
                and idx < len(self.sections)
            ):
                new_sections.append(self.sections[idx])
            else:
                new_sections.append(update_section_geometry(sect))
                changed_indices.append(idx)

        if not changed_indices:
            return False

        self.sections = new_sections
        self.section_signatures = new_signatures
        self.section_endpoints = [(sect.start, sect.end) for sect in self.sections]

        if len(self.centerline_polylines) != len(self.sections):
            self.centerline_polylines = [sect.polyline for sect in self.sections]
        else:
            for idx in changed_indices:
                self.centerline_polylines[idx] = self.sections[idx].polyline

        return True
