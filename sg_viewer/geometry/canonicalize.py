from dataclasses import replace
from typing import List
import math

from sg_viewer.geometry.sg_geometry import (
    build_section_polyline,
    derive_heading_vectors,
    normalize_heading,
    round_heading,
)
from sg_viewer.models.sg_model import SectionPreview


def heading_is_normalized(section: SectionPreview) -> bool:
    return _heading_is_normalized(section.start_heading) and _heading_is_normalized(
        section.end_heading
    )


def polyline_is_consistent(section: SectionPreview) -> bool:
    if not section.polyline or len(section.polyline) < 2:
        return False
    return section.polyline[0] == section.start and section.polyline[-1] == section.end


def canonicalize_section(section: SectionPreview) -> SectionPreview:
    """
    Enforce all geometry invariants and return a normalized section.
    This function is the ONLY place geometry fixups are allowed.
    """

    start_heading = _resolve_heading(section.start_heading, section.sang1, section.sang2)
    end_heading = _resolve_heading(section.end_heading, section.eang1, section.eang2)

    center = section.center
    radius = section.radius if section.radius is not None else 0.0
    if section.type_name != "curve":
        center = None
        radius = 0.0
    if center is not None and radius <= 0:
        radius = math.hypot(section.start[0] - center[0], section.start[1] - center[1])
    radius = abs(radius)

    polyline = build_section_polyline(
        section.type_name,
        section.start,
        section.end,
        center,
        radius,
        start_heading,
        end_heading,
    )

    start_heading, end_heading = derive_heading_vectors(
        polyline, section.sang1, section.sang2, section.eang1, section.eang2
    )
    start_heading = _normalize_heading_vector(start_heading)
    end_heading = _normalize_heading_vector(end_heading)

    length = _polyline_length(polyline)

    canonical = replace(
        section,
        center=center,
        radius=radius,
        polyline=polyline,
        start_heading=start_heading,
        end_heading=end_heading,
        length=length,
    )

    assert canonical.radius == 0 or canonical.radius > 0
    assert heading_is_normalized(canonical)
    assert polyline_is_consistent(canonical)

    return canonical


def canonicalize_closed_loop(
    sections: List[SectionPreview],
    start_idx: int,
) -> List[SectionPreview]:
    """
    Canonicalize a closed loop of sections so that:
    - traversal direction is consistent
    - geometry agrees with traversal
    - indices are rewritten sequentially
    """

    # ------------------------
    # Step 1: walk the loop
    # ------------------------
    order = []
    seen = set()
    i = start_idx

    while i not in seen:
        seen.add(i)
        order.append(i)
        nxt = sections[i].next_id
        if nxt is None:
            raise RuntimeError("Loop is not closed")
        i = nxt

    if i != start_idx:
        raise RuntimeError("Graph is not a single simple loop")

    # ------------------------
    # Step 2: normalize direction
    # ------------------------
    # Choose canonical direction:
    # forward traversal means section.end connects to next.start
    # If the first section appears reversed, flip entire order
    s0 = sections[order[0]]
    s1 = sections[order[1]]

    dist_fwd = _dist(s0.end, s1.start)
    dist_rev = _dist(s0.start, s1.end)

    if dist_rev < dist_fwd:
        order.reverse()

    # ------------------------
    # Step 3: rebuild sections in traversal order
    # ------------------------
    new_sections: List[SectionPreview] = []

    n = len(order)

    for k, old_idx in enumerate(order):
        s = sections[old_idx]

        prev_idx = (k - 1) % n
        next_idx = (k + 1) % n

        prev_section = sections[order[prev_idx]]
        next_section = sections[order[next_idx]]

        # Determine if section is reversed relative to traversal
        forward_dist = _dist(s.end, next_section.start)
        backward_dist = _dist(s.start, next_section.end)

        reversed_section = backward_dist < forward_dist

        if reversed_section:
            s = _reverse_section(s)

        # Assign new connectivity (temporary indices)
        s = replace(
            s,
            previous_id=prev_idx,
            next_id=next_idx,
        )

        new_sections.append(s)

    # ------------------------
    # Step 4: reindex and fix geometry
    # ------------------------
    final_sections: List[SectionPreview] = []

    for idx, s in enumerate(new_sections):
        s = replace(
            s,
            previous_id=(idx - 1) % n,
            next_id=(idx + 1) % n,
        )
        final_sections.append(s)

    return final_sections


# ------------------------
# Helpers
# ------------------------

def _reverse_section(s: SectionPreview) -> SectionPreview:
    """
    Reverse direction of a section.
    """
    s = replace(
        s,
        start=s.end,
        end=s.start,
        polyline=list(reversed(s.polyline)) if s.polyline else None,
        previous_id=s.next_id,
        next_id=s.previous_id,
    )

    if s.type_name == "curve":
        s = replace(
            s,
            sang1=s.eang1,
            sang2=s.eang2,
            eang1=s.sang1,
            eang2=s.sang2,
        )

    return s


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _heading_is_normalized(heading: tuple[float, float] | None) -> bool:
    if heading is None:
        return True
    normalized = normalize_heading(heading)
    if normalized is None:
        return False
    return (
        math.isclose(normalized[0], heading[0], rel_tol=1e-5, abs_tol=1e-5)
        and math.isclose(normalized[1], heading[1], rel_tol=1e-5, abs_tol=1e-5)
    )


def _normalize_heading_vector(
    heading: tuple[float, float] | None,
) -> tuple[float, float] | None:
    if heading is None:
        return None
    return round_heading(heading)


def _resolve_heading(
    fallback: tuple[float, float] | None,
    component_x: float | None,
    component_y: float | None,
) -> tuple[float, float] | None:
    if component_x is not None and component_y is not None:
        return round_heading((component_x, component_y))
    return _normalize_heading_vector(fallback)


def _polyline_length(polyline: list[tuple[float, float]]) -> float:
    if len(polyline) < 2:
        return 0.0
    length = 0.0
    for start, end in zip(polyline, polyline[1:]):
        length += math.hypot(end[0] - start[0], end[1] - start[1])
    return length
