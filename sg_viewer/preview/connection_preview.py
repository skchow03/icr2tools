# preview/connection_preview.py
#
# Connection previews are intentionally ephemeral. The sections returned from
# this module are for visualization only: do not store them in the
# authoritative section list or feed them into hit-testing.
from __future__ import annotations

from dataclasses import replace
from typing import List, Tuple

from sg_viewer.models.sg_model import SectionPreview, Point
from sg_viewer.models.preview_state_utils import heading_delta

EndpointKey = tuple[int, str]  # (section_index, "start"|"end")


def _get_endpoint_pos(section: SectionPreview, endtype: str) -> Point:
    return section.start if endtype == "start" else section.end


def _set_endpoint_pos(section: SectionPreview, endtype: str, p: Point) -> SectionPreview:
    return replace(section, start=p) if endtype == "start" else replace(section, end=p)


def build_connection_preview(
    sections: List[SectionPreview],
    a_key: EndpointKey,
    b_key: EndpointKey,
) -> tuple[List[SectionPreview], str]:
    a_idx, a_end = a_key
    b_idx, b_end = b_key
    if a_idx == b_idx:
        return ([], "")

    a = sections[a_idx]
    b = sections[b_idx]

    a_p0 = _get_endpoint_pos(a, a_end)
    b_p0 = _get_endpoint_pos(b, b_end)

    # Meet in the middle (simple, stable preview)
    mid: Point = ((a_p0[0] + b_p0[0]) * 0.5, (a_p0[1] + b_p0[1]) * 0.5)

    a2 = _set_endpoint_pos(a, a_end, mid)
    b2 = _set_endpoint_pos(b, b_end, mid)

    # Optional: report heading mismatch using the same helper used elsewhere
    a_heading = a2.start_heading if a_end == "start" else a2.end_heading
    b_heading = b2.start_heading if b_end == "start" else b2.end_heading
    hdelta = heading_delta(a_heading, b_heading)

    dx_a = mid[0] - a_p0[0]
    dy_a = mid[1] - a_p0[1]
    dx_b = mid[0] - b_p0[0]
    dy_b = mid[1] - b_p0[1]

    msg = (
        f"Preview connect: ({a_idx}:{a_end}) ↔ ({b_idx}:{b_end}) | "
        f"A Δ=({dx_a:.2f},{dy_a:.2f})  B Δ=({dx_b:.2f},{dy_b:.2f})"
    )
    if hdelta is not None:
        msg += f" | heading Δ={hdelta:.4f}°"

    return ([a2, b2], msg)
