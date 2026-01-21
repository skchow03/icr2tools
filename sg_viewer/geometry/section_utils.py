from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

T = TypeVar("T")


def previous_section_index(
    section_index: int,
    total: int,
    track_closed: bool,
) -> int | None:
    if total <= 0:
        return None
    if section_index > 0:
        return section_index - 1
    if track_closed and total > 1:
        return total - 1
    return None


def previous_section(
    sections: Sequence[T],
    section_index: int,
    track_closed: bool,
) -> T | None:
    prev_index = previous_section_index(section_index, len(sections), track_closed)
    if prev_index is None:
        return None
    return sections[prev_index]
