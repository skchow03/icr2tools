"""Helpers for track preview projection metadata."""
from __future__ import annotations

from typing import Any

from icr2_core.trk.trk_utils import getxyz


def track_elevation_at(
    model: Any, dlong: float | None, dlat: float | None
) -> float | None:
    """Return interpolated track elevation for a DLONG/DLAT position."""
    if dlong is None or dlat is None or not model.trk or not model.centerline:
        return None
    _, _, elevation = getxyz(model.trk, float(dlong), float(dlat), model.centerline)
    return elevation
