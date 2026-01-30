from __future__ import annotations

import math
from typing import Callable, Tuple

from track_viewer.geometry import CenterlineIndex, build_centerline_index

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
        self._centerline_points: list[Point] = []
        self._centerline_offsets: list[int] = []
        self._centerline_lengths: list[int] = []
        self._preview_sections: list[SectionPreview] | None = None
        self._preview_section_signatures: list[tuple] = []
        self._preview_section_endpoints: list[tuple[Point, Point]] | None = None
        self._preview_centerline_polylines: list[list[Point]] | None = None
        self.sampled_centerline: list[Point] = []
        self.sampled_dlongs: list[float] = []
        self.sampled_bounds: tuple[float, float, float, float] | None = None
        self.centerline_index: CenterlineIndex | None = None
        self._preview_mode = False

    def set_preview_mode(self, active: bool) -> None:
        self._preview_mode = active

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
        self._centerline_points = list(sampled_centerline)
        (
            self._centerline_offsets,
            self._centerline_lengths,
        ) = self._compute_centerline_offsets(self._centerline_polylines)
        self.clear_drag_preview()

    def set_sections(
        self,
        sections: list[SectionPreview],
        *,
        changed_indices: list[int] | None = None,
    ) -> bool:
        previous_signatures = self._section_signatures

        new_sections: list[SectionPreview] = []
        new_signatures: list[tuple] = []
        actual_changed_indices: list[int] = []

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
                actual_changed_indices.append(idx)

        if changed_indices:
            for idx in changed_indices:
                if 0 <= idx < len(sections) and idx not in actual_changed_indices:
                    new_sections[idx] = update_section_geometry(sections[idx])
                    actual_changed_indices.append(idx)

        actual_changed_indices = sorted(set(actual_changed_indices))

        length_changed = len(sections) != len(self._sections)
        needs_rebuild = length_changed or bool(actual_changed_indices)

        self._sections = new_sections
        self._section_signatures = new_signatures
        self._section_endpoints = [(sect.start, sect.end) for sect in self._sections]
        if self._preview_mode:
            return False

        self.clear_drag_preview()

        if needs_rebuild:
            incremental = None
            if not length_changed and actual_changed_indices:
                incremental = self._incremental_centerline_update(actual_changed_indices)

            if incremental is None:
                points, dlongs, bounds, index = rebuild_centerline_from_sections(
                    self._sections
                )
                offsets, lengths = self._compute_centerline_offsets(
                    [sect.polyline for sect in self._sections]
                )
                self._centerline_points = list(points)
                self._centerline_offsets = offsets
                self._centerline_lengths = lengths
            else:
                points, dlongs, bounds, index, offsets, lengths = incremental
                self._centerline_points = points
                self._centerline_offsets = offsets
                self._centerline_lengths = lengths

            if (
                self._centerline_polylines
                and len(self._centerline_polylines) == len(self._sections)
            ):
                for idx in actual_changed_indices:
                    if 0 <= idx < len(self._sections):
                        self._centerline_polylines[idx] = self._sections[idx].polyline
            else:
                self._centerline_polylines = [
                    sect.polyline for sect in self._sections
                ]
            self.sampled_centerline = points
            self.sampled_dlongs = dlongs
            self.sampled_bounds = (
                self._combine_bounds_with_background(bounds) if bounds else None
            )
            self.centerline_index = index

        return needs_rebuild

    def _compute_centerline_offsets(
        self, polylines: list[list[Point]]
    ) -> tuple[list[int], list[int]]:
        offsets: list[int] = []
        lengths: list[int] = []
        current = 0
        prev_last: Point | None = None

        for polyline in polylines:
            offsets.append(current)
            if polyline:
                if prev_last is not None and polyline[0] == prev_last:
                    length = max(len(polyline) - 1, 0)
                else:
                    length = len(polyline)
                current += length
                prev_last = polyline[-1]
            else:
                length = 0
            lengths.append(length)

        return offsets, lengths

    def _cache_valid(self, sections: list[SectionPreview]) -> bool:
        if len(self._centerline_offsets) != len(sections):
            return False
        if len(self._centerline_lengths) != len(sections):
            return False
        if sum(self._centerline_lengths) != len(self._centerline_points):
            return False
        return True

    def _section_contribution(
        self, polyline: list[Point], prev_last: Point | None
    ) -> list[Point]:
        if not polyline:
            return []
        if prev_last is not None and polyline[0] == prev_last:
            return list(polyline[1:])
        return list(polyline)

    def _incremental_centerline_update(
        self, changed_indices: list[int]
    ) -> tuple[
        list[Point],
        list[float],
        tuple[float, float, float, float] | None,
        CenterlineIndex | None,
        list[int],
        list[int],
    ] | None:
        if not self._cache_valid(self._sections):
            return None

        cached_points = self._centerline_points
        cached_offsets = self._centerline_offsets
        cached_lengths = self._centerline_lengths

        update_indices = {
            idx
            for idx in changed_indices
            if 0 <= idx < len(self._sections)
        }
        for idx in list(update_indices):
            if idx + 1 < len(self._sections):
                update_indices.add(idx + 1)

        if not update_indices:
            return None

        earliest_changed_offset = min(cached_offsets[idx] for idx in update_indices)

        new_points: list[Point] = []
        new_offsets: list[int] = []
        new_lengths: list[int] = []
        prev_last: Point | None = None

        for idx, section in enumerate(self._sections):
            new_offsets.append(len(new_points))
            if idx in update_indices:
                segment = self._section_contribution(section.polyline, prev_last)
            else:
                start = cached_offsets[idx]
                length = cached_lengths[idx]
                segment = cached_points[start : start + length]
            new_points.extend(segment)
            new_lengths.append(len(segment))
            if segment:
                prev_last = segment[-1]

        if len(new_points) < 2:
            return [], [], None, None, new_offsets, new_lengths

        prefix_len = 0
        if self.sampled_dlongs and cached_points and earliest_changed_offset > 0:
            prefix_len = min(
                earliest_changed_offset + 1,
                len(self.sampled_dlongs),
                len(new_points),
            )
            if cached_points[:prefix_len] != new_points[:prefix_len]:
                prefix_len = 0

        if prefix_len > 0:
            dlongs = list(self.sampled_dlongs[:prefix_len])
            distance = dlongs[-1]
            start_idx = prefix_len - 1
        else:
            dlongs = [0.0]
            distance = 0.0
            start_idx = 0

        for prev, cur in zip(new_points[start_idx:], new_points[start_idx + 1 :]):
            distance += math.hypot(cur[0] - prev[0], cur[1] - prev[1])
            dlongs.append(distance)

        bounds = (
            min(p[0] for p in new_points),
            max(p[0] for p in new_points),
            min(p[1] for p in new_points),
            max(p[1] for p in new_points),
        )

        centerline_index = build_centerline_index(new_points, bounds)

        return (
            new_points,
            dlongs,
            bounds,
            centerline_index,
            new_offsets,
            new_lengths,
        )

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
