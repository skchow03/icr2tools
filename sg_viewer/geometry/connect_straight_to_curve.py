import math
from dataclasses import replace
from typing import Optional, Tuple

from sg_viewer.geometry.sg_geometry import update_section_geometry
from sg_viewer.models.sg_model import SectionPreview


def solve_straight_to_curve_free_end(
    straight: SectionPreview,
    curve: SectionPreview,
) -> Optional[Tuple[SectionPreview, SectionPreview]]:
    if straight.type_name != "straight":
        return None
    if curve.type_name != "curve":
        return None

    P = curve.start
    h = curve.start_heading
    if h is None:
        return None

    hx, hy = h
    mag = math.hypot(hx, hy)
    if mag <= 0:
        return None
    hx /= mag
    hy /= mag

    L = straight.length
    if L <= 0:
        return None

    new_end = P
    new_start = (
        P[0] - hx * L,
        P[1] - hy * L,
    )

    new_straight = replace(
        straight,
        start=new_start,
        end=new_end,
    )

    new_straight = update_section_geometry(new_straight)

    return new_straight, curve
