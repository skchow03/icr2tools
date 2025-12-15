"""Render-related helpers for the SG preview widget."""
from __future__ import annotations

from typing import Dict, Iterable, Tuple

Point = Tuple[float, float]


def split_nodes_by_status(
    node_positions: Dict[tuple[int, str], Point],
    node_status: Dict[tuple[int, str], str],
) -> tuple[Iterable[tuple[tuple[int, str], Point]], Iterable[tuple[tuple[int, str], Point]]]:
    """Separate node positions into green and orange sets based on status."""

    greens = []
    oranges = []
    for key, pos in node_positions.items():
        status = node_status.get(key, "green")
        if status == "orange":
            oranges.append((key, pos))
        else:
            greens.append((key, pos))
    return greens, oranges
