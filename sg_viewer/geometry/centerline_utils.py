from __future__ import annotations

from typing import Iterable

from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import getxyz
from sg_viewer.models.sg_model import Point


def compute_centerline_normal_and_tangent(
    trk: TRKFile, cline: Iterable[Point] | None, track_length: float, dlong: float
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]] | None:
    if cline is None or track_length <= 0:
        return None

    def _wrap(value: float) -> float:
        while value < 0:
            value += track_length
        while value >= track_length:
            value -= track_length
        return value

    base = _wrap(float(dlong))
    delta = max(50.0, track_length * 0.002)
    prev_dlong = _wrap(base - delta)
    next_dlong = _wrap(base + delta)

    px, py, _ = getxyz(trk, prev_dlong, 0, cline)
    nx, ny, _ = getxyz(trk, next_dlong, 0, cline)
    cx, cy, _ = getxyz(trk, base, 0, cline)

    vx = nx - px
    vy = ny - py
    length = (vx * vx + vy * vy) ** 0.5
    if length == 0:
        return None

    tangent = (vx / length, vy / length)
    normal = (-vy / length, vx / length)

    return (cx, cy), normal, tangent


def compute_start_finish_mapping_from_centerline(
    sampled_centerline: Iterable[Point],
) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]] | None:
    """Compute start/finish mapping from a sampled centreline polyline.

    This is a lightweight alternative to ``compute_centerline_normal_and_tangent``
    that uses the preview centreline rather than the TRK sampling logic.
    """
    iterator = iter(sampled_centerline)
    start = next(iterator, None)
    if start is None:
        return None

    for point in iterator:
        dx = point[0] - start[0]
        dy = point[1] - start[1]
        length = (dx * dx + dy * dy) ** 0.5
        if length > 0:
            tangent = (dx / length, dy / length)
            normal = (-tangent[1], tangent[0])
            return start, normal, tangent

    return None
