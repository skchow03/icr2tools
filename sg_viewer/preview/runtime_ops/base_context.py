from __future__ import annotations

import logging
from typing import Tuple

logger = logging.getLogger("sg_viewer.preview.runtime_ops_core")

Point = Tuple[float, float]
Transform = tuple[float, tuple[float, float]]

__all__ = ["Point", "Transform", "logger"]
