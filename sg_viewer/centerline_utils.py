from __future__ import annotations

from typing import Iterable

from icr2_core.trk.trk_classes import TRKFile
from icr2_core.trk.trk_utils import getxyz
from sg_viewer.sg_model import Point


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
