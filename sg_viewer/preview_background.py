from __future__ import annotations

from pathlib import Path
from typing import Tuple

from PyQt5 import QtGui

from sg_viewer import preview_state

Point = Tuple[float, float]


class PreviewBackground:
    def __init__(self) -> None:
        self.image: QtGui.QImage | None = None
        self.image_path: Path | None = None
        self.scale_500ths_per_px: float = 1.0
        self.origin: Point = (0.0, 0.0)

    # ------------------------------------------------------------------
    # State management
    # ------------------------------------------------------------------
    def load_image(self, path: Path) -> None:
        image = QtGui.QImage(str(path))
        if image.isNull():
            raise ValueError(f"Unable to load image from {path}")

        self.image = image
        self.image_path = path

    def clear(self) -> None:
        self.image = None
        self.image_path = None
        self.scale_500ths_per_px = 1.0
        self.origin = (0.0, 0.0)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def bounds(self) -> tuple[float, float, float, float] | None:
        if self.image is None:
            return None

        scale = self.scale_500ths_per_px
        if scale <= 0:
            return None

        origin_x, origin_y = self.origin
        return (
            origin_x,
            origin_x + self.image.width() * scale,
            origin_y,
            origin_y + self.image.height() * scale,
        )

    def combine_bounds(self, bounds: tuple[float, float, float, float]) -> tuple[float, float, float, float]:
        background_bounds = self.bounds()
        if background_bounds is None:
            return bounds

        min_x = min(bounds[0], background_bounds[0])
        max_x = max(bounds[1], background_bounds[1])
        min_y = min(bounds[2], background_bounds[2])
        max_y = max(bounds[3], background_bounds[3])
        return (min_x, max_x, min_y, max_y)

    def fit_view(
        self, sampled_bounds: tuple[float, float, float, float] | None, widget_size: tuple[int, int]
    ) -> tuple[float, Point, tuple[float, float, float, float]] | None:
        background_bounds = self.bounds()
        if background_bounds is None:
            return None

        active_bounds = background_bounds
        if sampled_bounds:
            active_bounds = self.combine_bounds(sampled_bounds)

        fit_scale = preview_state.calculate_fit_scale(active_bounds, widget_size)
        if fit_scale is None:
            return None

        center = (
            (active_bounds[0] + active_bounds[1]) / 2,
            (active_bounds[2] + active_bounds[3]) / 2,
        )
        return fit_scale, center, active_bounds

