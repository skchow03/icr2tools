# sg_viewer/preview/hover_detection.py

from typing import Optional, Tuple

Point = Tuple[float, float]


def find_hovered_unconnected_node(
    mouse_pos: Point,
    context,
) -> Optional[tuple[int, str]]:
    """
    Returns (section_index, endtype) if the mouse is hovering
    near an unconnected endpoint, otherwise None.

    Distance thresholding is handled by context.find_unconnected_node.
    """

    hit = context.find_unconnected_node(mouse_pos)
    if hit is None:
        return None

    section_index, endtype, _pos, _heading = hit
    return section_index, endtype
