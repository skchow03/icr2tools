"""Selection helpers for the SG preview widget."""
from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

from sg_viewer.model.preview_state_utils import is_disconnected_endpoint
from sg_viewer.model.sg_model import SectionPreview
from sg_viewer.preview.geometry import heading_for_endpoint

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]


def build_node_positions(sections: Iterable[SectionPreview]) -> Dict[tuple[int, str], Point]:
    """Map section endpoints to world coordinates."""

    pos: Dict[tuple[int, str], Point] = {}
    for i, sect in enumerate(sections):
        pos[(i, "start")] = sect.start
        pos[(i, "end")] = sect.end
    return pos


def find_unconnected_node_hit(
    pos: tuple[float, float],
    sections: List[SectionPreview],
    transform: Transform | None,
    widget_height: float,
    radius_px: float,
) -> tuple[int, str, Point, tuple[float, float] | None] | None:
    """Return unconnected node hit details for a screen position.

    ``pos`` is a screen-space ``(x, y)`` tuple. ``transform`` maps world
    coordinates to screen via ``(scale, (ox, oy))``. The result is ``None`` when
    no disconnected endpoint is within ``radius_px`` pixels.
    """

    if transform is None:
        return None

    scale, offsets = transform
    ox, oy = offsets
    r2 = radius_px * radius_px

    for i, section in enumerate(sections):
        for endtype in ("start", "end"):
            if not is_disconnected_endpoint(sections, section, endtype):
                continue

            world_point = section.start if endtype == "start" else section.end
            px = ox + world_point[0] * scale
            py_world = oy + world_point[1] * scale
            py = widget_height - py_world

            dx = px - pos[0]
            dy = py - pos[1]
            if dx * dx + dy * dy <= r2:
                return i, endtype, world_point, heading_for_endpoint(section, endtype)

    return None
