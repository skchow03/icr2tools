from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

BoundaryKind = Literal["wall", "armco"]
BoundarySide = Literal["left", "right"]


@dataclass(frozen=True)
class BoundaryStyle:
    kind: BoundaryKind
    side: BoundarySide

    # world units (500ths)
    post_spacing: float = 12.0 * 500.0  # 12 feet
    post_length: float = 2.0 * 500.0  # 2 feet inward
