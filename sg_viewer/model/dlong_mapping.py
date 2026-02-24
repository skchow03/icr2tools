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
class _RangeEntry:
    start: float
    end: float
    section_index: int


@dataclass(frozen=True)
class DlongSectionIndex:
    """Indexed lookup for mapping dlong values to sections."""

    sections: Sequence[_SectionWithDlong]
    track_length: float
    _fast_starts: tuple[float, ...]
    _fast_ends: tuple[float, ...]
    _fast_section_indexes: tuple[int, ...]
    _ranges_by_start: tuple[_RangeEntry, ...]
    _range_starts: tuple[float, ...]
    _use_fast_path: bool

    @classmethod
    def build(
        cls,
        sections: Sequence[_SectionWithDlong],
        track_length: float | None = None,
    ) -> DlongSectionIndex | None:
        if not sections:
            return None

        resolved_length = _resolve_track_length(sections, track_length)
        if resolved_length <= 0:
            return None

        fast_starts: list[float] = []
        fast_ends: list[float] = []
        fast_indexes: list[int] = []
        ranges: list[_RangeEntry] = []
        fast_path_ok = True
        previous_end = -math.inf

        for idx, section in enumerate(sections):
            start = float(section.start_dlong)
            length = float(section.length)
            if length <= 0:
                continue

            normalized_start = start % resolved_length
            normalized_end = normalized_start + length

            if normalized_end <= resolved_length:
                ranges.append(_RangeEntry(normalized_start, normalized_end, idx))
            else:
                wrapped_end = normalized_end - resolved_length
                ranges.append(_RangeEntry(normalized_start, resolved_length, idx))
                ranges.append(_RangeEntry(0.0, wrapped_end, idx))

            if start < previous_end:
                fast_path_ok = False
            previous_end = start + length

            fast_starts.append(start)
            fast_ends.append(start + length)
            fast_indexes.append(idx)

        ordered_ranges = tuple(sorted(ranges, key=lambda r: (r.start, r.section_index)))

        return cls(
            sections=sections,
            track_length=resolved_length,
            _fast_starts=tuple(fast_starts),
            _fast_ends=tuple(fast_ends),
            _fast_section_indexes=tuple(fast_indexes),
            _ranges_by_start=ordered_ranges,
            _range_starts=tuple(entry.start for entry in ordered_ranges),
            _use_fast_path=fast_path_ok and bool(fast_starts),
        )

    def lookup(self, dlong: float) -> DlongSectionPosition:
        wrapped_dlong = float(dlong) % self.track_length

        if self._use_fast_path:
            candidate = bisect_right(self._fast_starts, wrapped_dlong)
            if candidate > 0:
                idx = candidate - 1
                if idx > 0 and math.isclose(wrapped_dlong, self._fast_starts[idx]):
                    prev_end = self._fast_ends[idx - 1]
                    if wrapped_dlong < prev_end or math.isclose(wrapped_dlong, prev_end):
                        return _build_position(self.sections, self._fast_section_indexes[idx - 1], wrapped_dlong, self.track_length)

                end = self._fast_ends[idx]
                if wrapped_dlong < end or math.isclose(wrapped_dlong, end):
                    return _build_position(self.sections, self._fast_section_indexes[idx], wrapped_dlong, self.track_length)

        candidate = bisect_right(self._range_starts, wrapped_dlong)
        matched: _RangeEntry | None = None
        for idx in range(candidate - 1, -1, -1):
            entry = self._ranges_by_start[idx]
            if wrapped_dlong < entry.start and not math.isclose(wrapped_dlong, entry.start):
                continue
            if wrapped_dlong < entry.end or math.isclose(wrapped_dlong, entry.end):
                if matched is None or entry.section_index < matched.section_index:
                    matched = entry
            else:
                break

        if matched is not None:
            return _build_position(self.sections, matched.section_index, wrapped_dlong, self.track_length)

        return DlongSectionPosition(section_index=len(self.sections) - 1, fraction=1.0)


def dlong_to_section_position(
    sections: Sequence[_SectionWithDlong],
    dlong: float,
    track_length: float | None = None,
) -> DlongSectionPosition | None:
    """Map absolute ``dlong`` to a section index and local fraction in [0, 1]."""
    index = DlongSectionIndex.build(sections, track_length)
    if index is None:
        return None
    return index.lookup(dlong)


def _resolve_track_length(sections: Sequence[_SectionWithDlong], track_length: float | None) -> float:
    if track_length is not None and track_length > 0:
        return float(track_length)

    starts = [float(section.start_dlong) for section in sections]
    lengths = [float(section.length) for section in sections]
    max_end = max((start + length for start, length in zip(starts, lengths)), default=0.0)

    total = max(max_end, sum(length for length in lengths if length > 0))
    return float(total)


def _build_position(
    sections: Sequence[_SectionWithDlong],
    section_index: int,
    wrapped_dlong: float,
    track_length: float,
) -> DlongSectionPosition:
    section = sections[section_index]
    start = float(section.start_dlong)
    length = float(section.length)
    if length <= 0:
        return DlongSectionPosition(section_index=section_index, fraction=1.0)

    fraction = (wrapped_dlong - start) / length
    if start + length > track_length and wrapped_dlong < start:
        fraction = (wrapped_dlong + track_length - start) / length
    return DlongSectionPosition(section_index=section_index, fraction=max(0.0, min(1.0, fraction)))
