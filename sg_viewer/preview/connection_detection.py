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
        connected = not is_disconnected_endpoint(sections, key)

        node = {
            "key": key,
            "position": pos,
            "connected": connected,
        }

        if key == dragged_key:
            node["position"] = dragged_pos
            dragged_node = node

        nodes.append(node)

    if dragged_node is None:
        return None

    target = find_connection_target(
        dragged_node=dragged_node,
        candidate_nodes=nodes,
        snap_radius=snap_radius,
    )

    return target["key"] if target else None
