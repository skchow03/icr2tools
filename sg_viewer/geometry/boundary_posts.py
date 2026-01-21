from __future__ import annotations
import math
from typing import List, Tuple

Point = Tuple[float, float]
Segment = Tuple[Point, Point]


def _unit(vx: float, vy: float) -> tuple[float, float] | None:
    mag = math.hypot(vx, vy)
    if mag <= 1e-9:
        return None
    return vx / mag, vy / mag


def generate_boundary_posts(
    polyline: list[Point],
    *,
    side: str,
    spacing: float,
    length: float,
) -> List[Segment]:
    if len(polyline) < 2:
        return []

    posts: List[Segment] = []
    carry = 0.0

    for p0, p1 in zip(polyline, polyline[1:]):
        dx = p1[0] - p0[0]
        dy = p1[1] - p0[1]
        seg_len = math.hypot(dx, dy)
        if seg_len <= 1e-6:
            continue

        tdir = _unit(dx, dy)
        if tdir is None:
            continue

        # inward normal
        if side == "left":
            nx, ny = -tdir[1], tdir[0]
        else:
            nx, ny = tdir[1], -tdir[0]

        dist = carry
        while dist < seg_len:
            f = dist / seg_len
            x = p0[0] + dx * f
            y = p0[1] + dy * f
            posts.append(((x, y), (x + nx * length, y + ny * length)))
            dist += spacing

        carry = dist - seg_len

    return posts
