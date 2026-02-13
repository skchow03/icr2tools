from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Literal

from .sg_model import SectionPreview

EndType = Literal["start", "end"]


def section_signature(section: SectionPreview) -> tuple:
    return (
        section.section_id,
        section.type_name,
        section.previous_id,
        section.next_id,
        section.start,
        section.end,
        section.start_dlong,
        section.length,
        section.center,
        section.sang1,
        section.sang2,
        section.eang1,
        section.eang2,
        section.radius,
    )


def compute_section_signatures(sections: Iterable[SectionPreview]) -> list[tuple]:
    return [section_signature(section) for section in sections]


def is_invalid_id(sections: Sequence[SectionPreview], value: int | None) -> bool:
    return value is None or value < 0 or value >= len(sections)


def is_disconnected_endpoint(
    sections: Sequence[SectionPreview], section: SectionPreview, endtype: EndType
) -> bool:
    if endtype == "start":
        return is_invalid_id(sections, section.previous_id)
    return is_invalid_id(sections, section.next_id)


def update_node_status(
    sections: Sequence[SectionPreview],
    node_status: dict[tuple[int, EndType], str] | None = None,
) -> dict[tuple[int, EndType], str]:
    status = node_status if node_status is not None else {}
    status.clear()

    if not sections:
        return status

    for index, section in enumerate(sections):
        start_disconnected = is_disconnected_endpoint(sections, section, "start")
        end_disconnected = is_disconnected_endpoint(sections, section, "end")

        status[(index, "start")] = "orange" if start_disconnected else "green"
        status[(index, "end")] = "orange" if end_disconnected else "green"

    return status
