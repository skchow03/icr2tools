from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class TrackSection:
    start: tuple[float, float]
    end: tuple[float, float]

    def with_start_point(self, pos: tuple[float, float]) -> "TrackSection":
        return replace(self, start=pos)

    def with_end_point(self, pos: tuple[float, float]) -> "TrackSection":
        return replace(self, end=pos)


class TrackModel:
    """Minimal mutable track model used by interaction controller logic."""

    def __init__(self, sections: list[TrackSection]):
        self._sections = list(sections)

    def get_section(self, section_id: int) -> TrackSection:
        return self._sections[section_id]

    def replace_section(self, section_id: int, section: TrackSection) -> None:
        self._sections[section_id] = section

    def update_section_handle(self, section_id: int, handle: str, pos: tuple[float, float]):
        """
        Update the model for a section handle. Returns True if changed.
        """
        section = self.get_section(section_id)
        if handle == "start":
            section = section.with_start_point(pos)
        elif handle == "end":
            section = section.with_end_point(pos)
        else:
            raise ValueError(handle)

        self.replace_section(section_id, section)
