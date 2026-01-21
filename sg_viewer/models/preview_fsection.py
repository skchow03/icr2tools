from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PreviewFSection:
    start_dlat: float
    end_dlat: float
    surface_type: int
    type2: int
