from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass
import math
from typing import Protocol, Sequence


class _SectionWithDlong(Protocol):
    start_dlong: float
    length: float


@dataclass(frozen=True)
class DlongSectionPosition:
    section_index: int
    fraction: float


@dataclass(frozen=True)
class DlongSectionInterval:
    start: float
    end: float
    section_index: int


@dataclass(frozen=True)
class DlongSectionLookup:
    intervals: tuple[DlongSectionInterval, ...]
    starts: tuple[float, ...]
    wrapping_interval_indexes: tuple[int, ...]


def build_dlong_section_lookup(
    sections: Sequence[_SectionWithDlong],
    track_length: float,
) -> DlongSectionLookup:
    intervals: list[DlongSectionInterval] = []
    starts: list[float] = []
    wrapping_interval_indexes: list[int] = []
    for section_index, section in enumerate(sections):
        length = float(section.length)
        if length <= 0:
            continue
        start = float(section.start_dlong)
        end = start + length
        interval_index = len(intervals)
        intervals.append(DlongSectionInterval(start=start, end=end, section_index=section_index))
        starts.append(start)
        if end > track_length:
            wrapping_interval_indexes.append(interval_index)

    return DlongSectionLookup(
        intervals=tuple(intervals),
        starts=tuple(starts),
        wrapping_interval_indexes=tuple(wrapping_interval_indexes),
    )


def dlong_to_section_position(
    sections: Sequence[_SectionWithDlong],
    dlong: float,
    track_length: float | None = None,
    lookup: DlongSectionLookup | None = None,
) -> DlongSectionPosition | None:
    """Map absolute ``dlong`` to a section index and local fraction in [0, 1]."""

    if not sections:
        return None

    resolved_length = _resolve_track_length(sections, track_length)
    if resolved_length <= 0:
        return None

    wrapped_dlong = dlong % resolved_length
    resolved_lookup = lookup or build_dlong_section_lookup(sections, resolved_length)

    position = _lookup_dlong_section_position(resolved_lookup, wrapped_dlong, resolved_length)
    if position is not None:
        return position

    return DlongSectionPosition(section_index=len(sections) - 1, fraction=1.0)


def _lookup_dlong_section_position(
    lookup: DlongSectionLookup,
    wrapped_dlong: float,
    track_length: float,
) -> DlongSectionPosition | None:
    if not lookup.intervals:
        return None

    interval_indexes: set[int] = set()
    candidate_index = bisect_right(lookup.starts, wrapped_dlong) - 1
    if 0 <= candidate_index < len(lookup.intervals):
        interval_indexes.add(candidate_index)
    if candidate_index - 1 >= 0:
        interval_indexes.add(candidate_index - 1)
    if candidate_index + 1 < len(lookup.intervals):
        interval_indexes.add(candidate_index + 1)
    interval_indexes.update(lookup.wrapping_interval_indexes)

    for interval_index in sorted(interval_indexes, key=lambda idx: lookup.intervals[idx].section_index):
        interval = lookup.intervals[interval_index]
        if not _dlong_in_section_range(wrapped_dlong, interval.start, interval.end, track_length):
            continue
        length = interval.end - interval.start
        if length <= 0:
            continue
        fraction = (wrapped_dlong - interval.start) / length
        if interval.end > track_length and wrapped_dlong < interval.start:
            fraction = (wrapped_dlong + track_length - interval.start) / length
        return DlongSectionPosition(
            section_index=interval.section_index,
            fraction=max(0.0, min(1.0, fraction)),
        )

    return None


def _resolve_track_length(sections: Sequence[_SectionWithDlong], track_length: float | None) -> float:
    if track_length is not None and track_length > 0:
        return float(track_length)

    starts = [float(section.start_dlong) for section in sections]
    lengths = [float(section.length) for section in sections]
    max_end = max((start + length for start, length in zip(starts, lengths)), default=0.0)

    total = max(max_end, sum(length for length in lengths if length > 0))
    return float(total)


def _dlong_in_section_range(dlong: float, start: float, end: float, track_length: float) -> bool:
    if end <= track_length:
        return start <= dlong < end or math.isclose(dlong, end)
    wrapped_end = end - track_length
    return dlong >= start or dlong < wrapped_end or math.isclose(dlong, wrapped_end)
