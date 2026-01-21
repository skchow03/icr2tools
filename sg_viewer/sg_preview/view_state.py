from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class SgPreviewViewState:
    selected_fsect_id: Optional[int] = None
    selected_surface_id: Optional[int] = None
    selected_boundary_id: Optional[int] = None
    show_surfaces: bool = True
    show_boundaries: bool = True
