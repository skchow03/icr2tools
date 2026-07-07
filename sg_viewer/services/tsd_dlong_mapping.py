from __future__ import annotations

import math
from bisect import bisect_left
from typing import Callable

AdjustedToSgRanges = tuple[list[tuple[float, float, float, float]], list[float]]


def build_adjusted_to_sg_ranges(
    sections: list[object],
    adjusted_section_range_500ths: Callable[[int], tuple[float, float] | None],
) -> AdjustedToSgRanges:
    section_ranges: list[tuple[float, float, float, float]] = []
    section_boundaries: list[float] = []
    for section_index, section in enumerate(sections):
        adjusted_range = adjusted_section_range_500ths(section_index)
        if adjusted_range is None:
            return [], []
        adjusted_start, adjusted_end = adjusted_range
        sg_start = float(section.start_dlong)
        sg_end = sg_start + float(section.length)
        section_ranges.append((float(adjusted_start), float(adjusted_end), sg_start, sg_end))
        section_boundaries.extend((float(adjusted_start), float(adjusted_end)))
    section_boundaries.sort()
    return section_ranges, section_boundaries


def find_adjusted_segment_index(normalized_dlong: float, section_ranges: list[tuple[float, float, float, float]], section_boundaries: list[float]) -> int | None:
    if not section_ranges or not section_boundaries:
        return None
    boundary_index = bisect_left(section_boundaries, normalized_dlong)
    candidate = max(0, min(len(section_ranges) - 1, (boundary_index - 1) // 2))
    adjusted_start, adjusted_end, _, _ = section_ranges[candidate]
    if adjusted_start <= normalized_dlong <= adjusted_end:
        return candidate
    if candidate + 1 < len(section_ranges):
        next_start, next_end, _, _ = section_ranges[candidate + 1]
        if next_start <= normalized_dlong <= next_end:
            return candidate + 1
    return None


def adjusted_dlong_to_sg_dlong(adjusted_dlong: int, adjusted_to_sg_ranges: AdjustedToSgRanges) -> int:
    section_ranges, section_boundaries = adjusted_to_sg_ranges
    if not section_ranges:
        return int(adjusted_dlong)
    total_adjusted_length = section_ranges[-1][1]
    if total_adjusted_length <= 0:
        return int(adjusted_dlong)
    normalized = float(adjusted_dlong) % total_adjusted_length
    segment_index = find_adjusted_segment_index(normalized, section_ranges, section_boundaries)
    if segment_index is None:
        return int(round(section_ranges[-1][3]))
    adjusted_start, adjusted_end, sg_start, sg_end = section_ranges[segment_index]
    adjusted_length = adjusted_end - adjusted_start
    if adjusted_length < 0:
        return int(round(section_ranges[-1][3]))
    if math.isclose(adjusted_length, 0.0):
        return int(round(sg_start))
    fraction = (normalized - adjusted_start) / adjusted_length
    return int(round(sg_start + fraction * (sg_end - sg_start)))
