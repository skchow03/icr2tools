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
        self._sections: list[SectionPreview] = []
        self._section_signatures: list[tuple] = []
        self._section_endpoints: list[tuple[Point, Point]] = []
        self._centerline_polylines: list[list[Point]] = []
        self._preview_sections: list[SectionPreview] | None = None
        self._preview_section_signatures: list[tuple] = []
        self._preview_section_endpoints: list[tuple[Point, Point]] | None = None
        self._preview_centerline_polylines: list[list[Point]] | None = None
        self.sampled_centerline: list[Point] = []
        self.sampled_dlongs: list[float] = []
        self.sampled_bounds: tuple[float, float, float, float] | None = None
        self.centerline_index: CenterlineIndex | None = None

    @property
    def sections(self) -> list[SectionPreview]:
        return (
            self._preview_sections
            if self._preview_sections is not None
            else self._sections
        )

    @property
    def section_endpoints(self) -> list[tuple[Point, Point]]:
        if self._preview_sections is not None:
            return self._preview_section_endpoints or []
        return self._section_endpoints

    @property
    def centerline_polylines(self) -> list[list[Point]]:
        if self._preview_sections is not None:
            return self._preview_centerline_polylines or []
        return self._centerline_polylines

    def clear_drag_preview(self) -> None:
        self._preview_sections = None
        self._preview_section_signatures = []
        self._preview_section_endpoints = None
        self._preview_centerline_polylines = None

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
        self._sections = sections
        self._section_signatures = compute_section_signatures(sections)
        self._section_endpoints = section_endpoints
        self.sampled_centerline = sampled_centerline
        self.sampled_dlongs = sampled_dlongs
        self.sampled_bounds = self._combine_bounds_with_background(sampled_bounds)
        self.centerline_index = centerline_index
        self._centerline_polylines = [sect.polyline for sect in self._sections]
        self.clear_drag_preview()

    def set_sections(self, sections: list[SectionPreview]) -> bool:
        previous_signatures = self._section_signatures

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
                and idx < len(self._sections)
            ):
                new_sections.append(self._sections[idx])
            else:
                new_sections.append(update_section_geometry(sect))
                changed_indices.append(idx)

        length_changed = len(sections) != len(self._sections)
        needs_rebuild = length_changed or bool(changed_indices)

        self._sections = new_sections
        self._section_signatures = new_signatures
        self._section_endpoints = [(sect.start, sect.end) for sect in self._sections]
        self.clear_drag_preview()

        if needs_rebuild:
            points, dlongs, bounds, index = rebuild_centerline_from_sections(
                self._sections
            )
            self._centerline_polylines = [sect.polyline for sect in self._sections]
            self.sampled_centerline = points
            self.sampled_dlongs = dlongs
            self.sampled_bounds = self._combine_bounds_with_background(bounds)
            self.centerline_index = index

        return needs_rebuild

    def update_drag_preview(self, sections: list[SectionPreview]) -> bool:
        if len(sections) != len(self.sections):
            return False

        base_sections = self.sections
        previous_signatures = (
            self._preview_section_signatures
            if self._preview_sections is not None
            else self._section_signatures
        )
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
                and idx < len(base_sections)
            ):
                new_sections.append(base_sections[idx])
            else:
                new_sections.append(update_section_geometry(sect))
                changed_indices.append(idx)

        if not changed_indices:
            return False

        self._preview_sections = new_sections
        self._preview_section_signatures = new_signatures
        self._preview_section_endpoints = [
            (sect.start, sect.end) for sect in self._preview_sections
        ]

        if (
            self._preview_centerline_polylines is None
            or len(self._preview_centerline_polylines)
            != len(self._preview_sections)
        ):
            self._preview_centerline_polylines = [
                sect.polyline for sect in self._preview_sections
            ]
        else:
            for idx in changed_indices:
                self._preview_centerline_polylines[idx] = (
                    self._preview_sections[idx].polyline
                )

        return True
