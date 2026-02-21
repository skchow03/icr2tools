from __future__ import annotations

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


def dlong_to_section_position(
    sections: Sequence[_SectionWithDlong],
    dlong: float,
    track_length: float | None = None,
) -> DlongSectionPosition | None:
    """Map absolute ``dlong`` to a section index and local fraction in [0, 1]."""

    if not sections:
        return None

    resolved_length = _resolve_track_length(sections, track_length)
    if resolved_length <= 0:
        return None

    wrapped_dlong = dlong % resolved_length

    for idx, section in enumerate(sections):
        start = float(section.start_dlong)
        length = float(section.length)
        if length <= 0:
            continue

        end = start + length
        if _dlong_in_section_range(wrapped_dlong, start, end, resolved_length):
            fraction = (wrapped_dlong - start) / length
            if end > resolved_length and wrapped_dlong < start:
                fraction = (wrapped_dlong + resolved_length - start) / length
            return DlongSectionPosition(section_index=idx, fraction=max(0.0, min(1.0, fraction)))

    return DlongSectionPosition(section_index=len(sections) - 1, fraction=1.0)


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
