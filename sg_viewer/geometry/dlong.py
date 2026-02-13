from dataclasses import replace
from typing import List

from sg_viewer.geometry.sg_geometry import update_section_geometry
from sg_viewer.geometry.topology import is_closed_loop
from sg_viewer.model.sg_model import SectionPreview


def set_start_finish(
    sections: List[SectionPreview],
    start_idx: int,
) -> List[SectionPreview]:
    """
    Reassign start_dlong so that `start_idx` is the start/finish (DLONG = 0).
    Requires a closed loop.
    """
    if not is_closed_loop(sections):
        raise ValueError("Track must be a closed loop to set start/finish")

    n = len(sections)

    # Walk traversal order starting at start_idx
    order = []
    i = start_idx
    visited = set()

    while i not in visited:
        visited.add(i)
        order.append(i)
        i = sections[i].next_id

    if len(order) != n:
        raise RuntimeError("Invalid loop topology")

    # Reassign start_dlongs and rewrite indices/connectivity
    new_sections: list[SectionPreview] = []
    cursor = 0.0

    for new_idx, old_idx in enumerate(order):
        s = sections[old_idx]
        s = replace(
            s,
            section_id=new_idx,
            previous_id=(new_idx - 1) % n,
            next_id=(new_idx + 1) % n,
            start_dlong=cursor,
        )
        s = update_section_geometry(s)
        new_sections.append(s)
        cursor += float(s.length)

    return new_sections
