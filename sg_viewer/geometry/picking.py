# sg_viewer/geometry/picking.py

from typing import List, Optional, Dict, Tuple
import math


def dist2(a: Tuple[float, float], b: Tuple[float, float]) -> float:
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return dx * dx + dy * dy


def find_connection_target(
    dragged_node: Dict,
    candidate_nodes: List[Dict],
    snap_radius: float
) -> Optional[Dict]:
    """
    Detect whether a dragged unconnected node is close enough
    to another unconnected node to form a connection.

    Returns the closest valid target node, or None.
    """

    if dragged_node["connected"]:
        return None

    snap_r2 = snap_radius * snap_radius
    best = None
    best_d2 = snap_r2

    for node in candidate_nodes:
        if node is dragged_node:
            continue

        if node["connected"]:
            continue

        # Optional: disallow start->start or end->end
        # if node["kind"] == dragged_node["kind"]:
        #     continue

        d2 = dist2(dragged_node["position"], node["position"])
        if d2 <= best_d2:
            best = node
            best_d2 = d2

    return best


def project_point_to_segment(
    p: Tuple[float, float], a: Tuple[float, float], b: Tuple[float, float]
) -> Optional[Tuple[float, float]]:
    ax, ay = a
    bx, by = b
    px, py = p

    vx = bx - ax
    vy = by - ay
    denom = vx * vx + vy * vy
    if denom <= 0:
        return None

    t = ((px - ax) * vx + (py - ay) * vy) / denom
    t = max(0.0, min(1.0, t))

    return (ax + t * vx, ay + t * vy)
