from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

Point = Tuple[float, float]


@dataclass(frozen=True)
class ViewTransform:
    scale: float
    offset: Point

    def world_to_screen(self, p: Point) -> Point:
        return (
            self.offset[0] + p[0] * self.scale,
            self.offset[1] - p[1] * self.scale,
        )

    def screen_to_world(self, p: Point) -> Point:
        if self.scale == 0:
            return (0.0, 0.0)
        return (
            (p[0] - self.offset[0]) / self.scale,
            (self.offset[1] - p[1]) / self.scale,
        )


def fit_to_bounds(bounds: tuple[float, float, float, float], viewport_size: Point) -> ViewTransform:
    min_x, max_x, min_y, max_y = bounds
    width = max_x - min_x
    height = max_y - min_y
    view_w, view_h = viewport_size

    if width <= 0 or height <= 0 or view_w <= 0 or view_h <= 0:
        return ViewTransform(scale=1.0, offset=(view_w * 0.5, view_h * 0.5))

    scale = min(view_w / width, view_h / height) * 0.95
    center_x = (min_x + max_x) * 0.5
    center_y = (min_y + max_y) * 0.5
    offset_x = view_w * 0.5 - center_x * scale
    offset_y = view_h * 0.5 + center_y * scale
    return ViewTransform(scale=scale, offset=(offset_x, offset_y))


def pan(transform: ViewTransform, dx: float, dy: float) -> ViewTransform:
    return ViewTransform(
        scale=transform.scale,
        offset=(transform.offset[0] + dx, transform.offset[1] + dy),
    )


def zoom(transform: ViewTransform, factor: float, anchor_point: Point) -> ViewTransform:
    if factor == 0:
        return transform
    new_scale = transform.scale * factor
    if new_scale == 0:
        return transform

    world_anchor = transform.screen_to_world(anchor_point)
    offset_x = anchor_point[0] - world_anchor[0] * new_scale
    offset_y = anchor_point[1] + world_anchor[1] * new_scale
    return ViewTransform(scale=new_scale, offset=(offset_x, offset_y))
