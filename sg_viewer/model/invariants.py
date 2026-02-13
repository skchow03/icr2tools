"""Invariant checks for editable SG preview sections."""

from __future__ import annotations

from math import isfinite
from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from sg_viewer.model.sg_model import SectionPreview


class InvariantError(ValueError):
    """Raised when the preview model violates a structural or geometric invariant."""


def assert_unique_section_ids(sections: Sequence["SectionPreview"]) -> None:
    """Assert section identifiers are unique and aligned to list positions.

    This invariant guarantees that each ``SectionPreview.section_id`` is unique,
    falls within the bounds of the list, and equals that section's list index.
    """

    seen_ids: set[int] = set()
    total = len(sections)
    for index, section in enumerate(sections):
        section_id = int(section.section_id)
        if section_id in seen_ids:
            raise InvariantError(f"Duplicate section_id detected: {section_id}.")
        seen_ids.add(section_id)

        if section_id < 0 or section_id >= total:
            raise InvariantError(
                f"section_id {section_id} is out of bounds for {total} sections."
            )

        if section_id != index:
            raise InvariantError(
                f"section_id/index mismatch at index {index}: section_id={section_id}."
            )


def assert_consistent_topology(sections: Sequence["SectionPreview"]) -> None:
    """Assert section connectivity references are valid and reciprocal.

    This invariant checks that ``previous_id``/``next_id`` are either ``-1`` or
    a valid section index, and that neighboring links are reciprocal:
    ``A.next_id == B.section_id`` implies ``B.previous_id == A.section_id`` and
    vice versa.
    """

    total = len(sections)
    if total == 0:
        return

    valid_ids = {-1, *range(total)}
    for section in sections:
        if section.previous_id not in valid_ids:
            raise InvariantError(
                f"Section {section.section_id} has invalid previous_id {section.previous_id}."
            )
        if section.next_id not in valid_ids:
            raise InvariantError(
                f"Section {section.section_id} has invalid next_id {section.next_id}."
            )

        if section.previous_id != -1:
            previous = sections[section.previous_id]
            if previous.next_id != section.section_id:
                raise InvariantError(
                    "Topology mismatch: "
                    f"section {section.section_id}.previous_id={section.previous_id}, "
                    f"but section {section.previous_id}.next_id={previous.next_id}."
                )

        if section.next_id != -1:
            nxt = sections[section.next_id]
            if nxt.previous_id != section.section_id:
                raise InvariantError(
                    "Topology mismatch: "
                    f"section {section.section_id}.next_id={section.next_id}, "
                    f"but section {section.next_id}.previous_id={nxt.previous_id}."
                )


def assert_geometry_valid(sections: Sequence["SectionPreview"]) -> None:
    """Assert section geometry values are finite and internally coherent.

    This invariant checks that start/end coordinates are finite numbers,
    section length is non-negative and finite, and section polylines (when
    present) start/end at the section endpoints.
    """

    for section in sections:
        start_x, start_y = section.start
        end_x, end_y = section.end
        if not all(isfinite(v) for v in (start_x, start_y, end_x, end_y)):
            raise InvariantError(
                f"Section {section.section_id} has non-finite endpoint coordinates."
            )

        if not isfinite(section.length) or section.length < 0.0:
            raise InvariantError(
                f"Section {section.section_id} has invalid length {section.length}."
            )

        if section.polyline:
            if section.polyline[0] != section.start:
                raise InvariantError(
                    f"Section {section.section_id} polyline does not start at section.start."
                )
            if section.polyline[-1] != section.end:
                raise InvariantError(
                    f"Section {section.section_id} polyline does not end at section.end."
                )


def validate_sections(sections: Sequence["SectionPreview"]) -> None:
    """Run all core section invariants."""

    assert_unique_section_ids(sections)
    assert_consistent_topology(sections)
    assert_geometry_valid(sections)

