from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

Point = Tuple[float, float]


@dataclass(frozen=True)
class SgBoundaryGeom:
    id: int
    points: List[Point]
    is_closed: bool
    attrs: dict


@dataclass(frozen=True)
class SgSurfaceGeom:
    id: int
    outline: List[Point]
    holes: List[List[Point]]
    attrs: dict


@dataclass(frozen=True)
class SgFsectGeom:
    id: int
    surfaces: List[SgSurfaceGeom]
    boundaries: List[SgBoundaryGeom]
    attrs: dict


@dataclass(frozen=True)
class SgPreviewModel:
    fsects: List[SgFsectGeom]
    bounds: Optional[Tuple[float, float, float, float]]
