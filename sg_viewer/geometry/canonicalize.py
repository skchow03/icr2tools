from dataclasses import replace
from typing import List
import math

from sg_viewer.models.sg_model import SectionPreview
from sg_viewer.geometry.sg_geometry import update_section_geometry
from sg_viewer.geometry.sg_geometry import signed_radius_from_heading


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

        # Fix radius sign (important)
        if s.type_name == "curve" and s.start_heading is not None:
            signed_r = signed_radius_from_heading(
                s.start_heading,
                s.start,
                s.center,
                s.radius,
            )
            if signed_r != s.radius:
                s = replace(s, radius=signed_r)

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
        s = update_section_geometry(s)
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
            radius=-s.radius,
            sang=s.eang if hasattr(s, "eang") else s.sang,
            eang=s.sang if hasattr(s, "eang") else s.eang,
        )

    return s


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])
