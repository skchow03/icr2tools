from typing import Optional, Tuple

from sg_viewer.geometry.picking import find_connection_target
from sg_viewer.preview.selection import build_node_positions
from sg_viewer.models.preview_state_utils import is_disconnected_endpoint

Point = Tuple[float, float]


def find_unconnected_node_target(
    dragged_key: tuple[int, str],
    dragged_pos: Point,
    sections,
    snap_radius: float,
) -> Optional[tuple[int, str]]:

    node_positions = build_node_positions(sections)

    nodes = []
    dragged_node = None

    for key, pos in node_positions.items():
        section_index, endtype = key
        section = sections[section_index]
        connected = not is_disconnected_endpoint(sections, section, endtype)

        node = {
            "key": key,
            "position": pos,
            "connected": connected,
        }

        if key == dragged_key:
            node["position"] = dragged_pos
            dragged_node = node

            # Treat the dragged endpoint as temporarily disconnected so we can
            # still find a snap target even if the underlying connectivity
            # metadata has not been updated yet.
            node["connected"] = False

        nodes.append(node)

    if dragged_node is None:
        return None

    target = find_connection_target(
        dragged_node=dragged_node,
        candidate_nodes=nodes,
        snap_radius=snap_radius,
    )

    if target is None:
        return None

    if target["key"] == dragged_key:
        return None

    return target["key"]
